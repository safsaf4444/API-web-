from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from backend.ai_secure import decrypt_api_key, encrypt_api_key, mask_key
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import AIResult, Study, SynthesisResult, User
from backend.schemas import (
    AIAskRequest, AIAskResponse,
    AIClinicalRequest, AIClinicalResponse,
    AIKeySetRequest, AIKeyStatus,
    AISummarizeRequest, AISummarizeResponse,
    AISynthesisRequest, AISynthesisResponse,
    AISubjectQueryRequest, AISubjectQueryResponse,
    AppraisalData, ConsensusPoint, ContradictionItem,
    CrossPaperAskRequest, CrossPaperAskResponse,
    CitationRequest, CitationResponse, CitationItem,
    CITATION_FORMATS,
    GRADEData, JargonItem, PICOData, RewritesData, StatisticalData, WeightingItem,
    SynthesisListItem,
)
from backend.services.ai_engine import run as engine_run
from backend.services.ai_service import strip_html
from backend.services.metrics_service import increment_ai_runs, write_clinical_data

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ai"])

# ── Evidence weighting ────────────────────────────────────────────────────────

EVIDENCE_WEIGHTS = {
    "meta_analysis": 5.0, "systematic_review": 4.5, "rct": 4.0,
    "cohort": 3.0, "case_control": 2.5, "cross_sectional": 2.0,
    "review": 1.5, "case_report": 1.0, "editorial": 0.5, "other": 1.0,
}

# Cleanup fix: detect study type from abstract before defaulting to "other"
_STUDY_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("meta_analysis",     r"\bmeta.?analy"),
    ("systematic_review", r"\bsystematic\s+review\b"),
    ("rct",               r"\brandom(?:is|iz)ed\b|\brct\b|\brandomised\b"),
    ("cohort",            r"\bcohort\b"),
    ("case_control",      r"\bcase.control\b"),
    ("cross_sectional",   r"\bcross.sectional\b"),
    ("case_report",       r"\bcase\s+report\b"),
    ("review",            r"\breview\b"),
    ("editorial",         r"\beditorial\b"),
]

def _detect_study_type_from_abstract(abstract: str | None) -> str | None:
    if not abstract:
        return None
    text = abstract.lower()
    for study_type, pattern in _STUDY_TYPE_PATTERNS:
        if re.search(pattern, text):
            return study_type
    return None


def _compute_evidence_weight(study_type: str | None, year: int | None) -> tuple[float, bool]:
    base = EVIDENCE_WEIGHTS.get((study_type or "other").lower().replace(" ", "_"), 1.0)
    recency = False
    if year and (datetime.now(timezone.utc).year - year) <= 5:
        base *= 1.1
        recency = True
    return round(base, 2), recency


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cache_key(kind, title, doi, pmid, pmcid, question=None):
    base = {
        "kind":     kind,
        "title":    (title    or "").strip().lower(),
        "doi":      (doi      or "").strip().lower(),
        "pmid":     (pmid     or "").strip().lower(),
        "pmcid":    (pmcid    or "").strip().lower(),
        "question": (question or "").strip().lower(),
    }
    raw = "|".join([f"{k}={base[k]}" for k in sorted(base.keys())])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _synthesis_cache_key(study_ids: list[int]) -> str:
    raw = "synthesis|" + ",".join(str(i) for i in sorted(study_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _subject_query_cache_key(query: str, source: str) -> str:
    raw = f"subject_query|{query.strip().lower()}|{source}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_byok_keys(user: User) -> dict:
    if not user.ai_key_enc:
        return {}
    try:
        key = decrypt_api_key(user.ai_key_enc)
    except Exception:
        return {}
    if key.startswith("sk-ant-"): return {"anthropic_key": key}
    if key.startswith("AIza"):    return {"gemini_key": key}
    if key.startswith("gsk_"):    return {"groq_key": key}
    return {"openai_key": key}


def _get_study_id_for_paper(session: Session, owner: str, doi: str | None, pmid: str | None) -> int | None:
    if doi:
        s = session.exec(select(Study).where((Study.owner_username == owner) & (Study.doi == doi.strip()))).first()
        if s: return s.id
    if pmid:
        s = session.exec(select(Study).where((Study.owner_username == owner) & (Study.pmid == pmid.strip()))).first()
        if s: return s.id
    return None


def _wire_ai_runs(session: Session, username: str, doi: str | None, pmid: str | None) -> None:
    try:
        study_id = _get_study_id_for_paper(session, username, doi, pmid)
        if study_id:
            increment_ai_runs(session, study_id, username)
    except Exception:
        pass


def _parse_clinical_cache(cached: AIResult) -> tuple[dict, dict, dict, list, list, list, dict]:
    """
    Fully restore all clinical fields from a cached AIResult.
    Handles v3.0 (pico only), v3.1 (full cache_data), v3.2 (+ grade/offsets) formats.
    Returns (pico_raw, stats_raw, appraisal_raw, key_claims, jargon_raw, text_offsets, grade_raw).
    """
    pico_raw: dict = {}
    stats_raw: dict = {}
    appraisal_raw: dict = {}
    key_claims: list = []
    jargon_raw: list = []
    text_offsets: list = []
    grade_raw: dict = {}
    try:
        raw_q = json.loads(cached.question or "{}")
        if "pico" in raw_q:
            pico_raw      = raw_q.get("pico", {}) or {}
            stats_raw     = raw_q.get("stats", {}) or {}
            appraisal_raw = raw_q.get("appraisal", {}) or {}
            key_claims    = raw_q.get("key_claims", []) or []
            jargon_raw    = raw_q.get("jargon", []) or []
            grade_raw     = raw_q.get("grade", {}) or {}
        else:
            pico_raw = raw_q or {}
        if not stats_raw:
            stats_raw = json.loads(cached.summary or "{}") or {}
        # text_offsets stored in dedicated column (v3.2+)
        if cached.text_offsets:
            text_offsets = cached.text_offsets if isinstance(cached.text_offsets, list) else []
    except Exception:
        pass
    return pico_raw, stats_raw, appraisal_raw, key_claims, jargon_raw, text_offsets, grade_raw


# ── Citation formatter (no AI required) ──────────────────────────────────────

def _parse_authors(authors_raw: str | None) -> list[str]:
    if not authors_raw:
        return []
    return [a.strip() for a in authors_raw.split(",") if a.strip()]


def _author_last_first(name: str) -> str:
    """Smith John -> Smith, John"""
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return name


def _author_initials(name: str) -> str:
    """Smith John -> Smith J."""
    parts = name.strip().split()
    if len(parts) >= 2:
        last = parts[-1]
        initials = " ".join(p[0] + "." for p in parts[:-1] if p)
        return f"{last} {initials}"
    return name


def _format_citation(study: Study, fmt: str) -> str:
    title   = study.title or "Unknown Title"
    year    = str(study.year) if study.year else "n.d."
    venue   = study.venue or ""
    doi     = study.doi or ""
    doi_url = f"https://doi.org/{doi}" if doi else ""
    authors = _parse_authors(study.authors)

    if fmt == "harvard":
        if authors:
            parts    = [_author_last_first(a) for a in authors[:3]]
            auth_str = ", ".join(parts)
            if len(authors) > 3:
                auth_str += " et al."
        else:
            auth_str = "Anon."
        cite = f"{auth_str} ({year}) '{title}'"
        if venue:   cite += f", {venue}"
        if doi_url: cite += f". Available at: {doi_url}"
        return cite

    elif fmt == "apa":
        if authors:
            parts    = [_author_initials(a) for a in authors[:6]]
            auth_str = ", ".join(parts)
            if len(authors) > 6:
                auth_str += f", ... {_author_initials(authors[-1])}"
        else:
            auth_str = "Anonymous"
        cite = f"{auth_str} ({year}). {title}."
        if venue:   cite += f" {venue}."
        if doi_url: cite += f" {doi_url}"
        return cite

    elif fmt == "vancouver":
        if authors:
            parts    = [_author_initials(a) for a in authors[:6]]
            auth_str = ", ".join(parts)
            if len(authors) > 6:
                auth_str += " et al."
        else:
            auth_str = "Anonymous"
        cite = f"{auth_str}. {title}."
        if venue: cite += f" {venue}."
        cite += f" {year}"
        if doi_url: cite += f". doi: {doi_url}"
        return cite

    elif fmt == "chicago":
        if authors:
            first    = _author_last_first(authors[0])
            rest_str = ", ".join(authors[1:]) if len(authors) > 1 else ""
            auth_str = first + (f", {rest_str}" if rest_str else "")
        else:
            auth_str = "Anonymous"
        cite = f'{auth_str}. "{title}."'
        if venue:   cite += f" {venue}"
        cite += f" ({year})"
        if doi_url: cite += f". {doi_url}"
        return cite

    elif fmt == "mla":
        if authors:
            first    = _author_last_first(authors[0])
            rest_str = ", ".join(authors[1:]) if len(authors) > 1 else ""
            auth_str = first + (f", {rest_str}" if rest_str else "")
        else:
            auth_str = "Anonymous"
        cite = f'{auth_str}. "{title}."'
        if venue:   cite += f" {venue},"
        cite += f" {year}"
        if doi_url: cite += f", {doi_url}"
        return cite

    elif fmt == "bibtex":
        parsed_authors = _parse_authors(study.authors)
        key_base = (parsed_authors[0].split()[-1].lower() if parsed_authors else "anon")
        key_base = re.sub(r"[^a-z0-9]", "", key_base)
        bib_key  = f"{key_base}{year}"
        auth_bibtex = " and ".join(parsed_authors) if parsed_authors else "Anonymous"
        lines = [
            f"@article{{{bib_key},",
            f"  author  = {{{auth_bibtex}}},",
            f"  title   = {{{title}}},",
            f"  year    = {{{year}}},",
        ]
        if venue:       lines.append(f"  journal = {{{venue}}},")
        if doi:         lines.append(f"  doi     = {{{doi}}},")
        if study.pmid:  lines.append(f"  pmid    = {{{study.pmid}}},")
        lines.append("}")
        return "\n".join(lines)

    elif fmt == "nature":
        if authors:
            parts    = [_author_initials(a) for a in authors[:6]]
            auth_str = ", ".join(parts)
            if len(authors) > 6:
                auth_str += " et al."
        else:
            auth_str = "Anon."
        cite = f"{auth_str} {title}."
        if venue: cite += f" *{venue}*"
        cite += f" ({year})"
        if doi_url: cite += f". {doi_url}"
        return cite

    elif fmt == "ama":
        if authors:
            parts    = [_author_initials(a) for a in authors[:6]]
            auth_str = ", ".join(parts)
            if len(authors) > 6:
                auth_str += ", et al"
        else:
            auth_str = "Anonymous"
        cite = f"{auth_str}. {title}."
        if venue: cite += f" {venue}."
        cite += f" {year}"
        if doi: cite += f". doi:{doi}"
        return cite

    # Fallback plain text
    auth_str = ", ".join(authors) if authors else "Unknown"
    return f"{auth_str} ({year}). {title}. {venue}. {doi_url}".strip(". ")


# ── Key management ────────────────────────────────────────────────────────────

@router.get("/ai/key_status", response_model=AIKeyStatus)
def ai_key_status(current_user: User = Depends(get_current_user)):
    if not current_user.ai_key_enc:
        return AIKeyStatus(has_key=False, masked=None)
    try:
        key = decrypt_api_key(current_user.ai_key_enc)
        return AIKeyStatus(has_key=True, masked=mask_key(key))
    except Exception:
        return AIKeyStatus(has_key=False, masked=None)


@router.post("/ai/set_key")
def ai_set_key(payload: AIKeySetRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    k = (payload.api_key or "").strip()
    if not k or len(k) < 20:
        raise HTTPException(status_code=400, detail="Invalid API key format.")
    current_user.ai_key_enc = encrypt_api_key(k)
    session.add(current_user)
    session.commit()
    return {"status": "ok"}


@router.delete("/ai/clear_key")
def ai_clear_key(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    current_user.ai_key_enc = None
    session.add(current_user)
    session.commit()
    return {"status": "cleared"}


# ── Summarize (standard) ──────────────────────────────────────────────────────

@router.post("/ai/summarize", response_model=AISummarizeResponse)
async def ai_summarize(payload: AISummarizeRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    ck = _cache_key("summarize", payload.title, payload.doi, payload.pmid, payload.pmcid)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "summarize")
    )).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AISummarizeResponse(text=cached.summary)
    system   = "You are a careful medical evidence assistant. Write in clear plain English. Use short headings and bullet points. Do not invent results. If info is missing, say so."
    user_msg = f"Summarize this paper.\n\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok     = _get_byok_keys(current_user)
    result   = await engine_run(system, user_msg, **byok)
    rec      = AIResult(owner_username=current_user.username, cache_key=ck, kind="summarize", model_used=result.provider.value, summary=result.text)
    session.add(rec)
    session.commit()
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AISummarizeResponse(text=result.text)


# ── Summarize (streaming) ─────────────────────────────────────────────────────

@router.post("/ai/summarize/stream")
async def ai_summarize_stream(payload: AISummarizeRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    ck = _cache_key("summarize", payload.title, payload.doi, payload.pmid, payload.pmcid)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "summarize")
    )).first()

    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        async def _cached_stream():
            text = cached.summary
            for i in range(0, len(text), 80):
                yield f"data: {json.dumps(text[i:i+80])}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_cached_stream(), media_type="text/event-stream")

    system   = "You are a careful medical evidence assistant. Write in clear plain English. Use short headings and bullet points. Do not invent results. If info is missing, say so."
    user_msg = f"Summarize this paper.\n\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok     = _get_byok_keys(current_user)
    full_text: list = []

    async def _live_stream():
        nonlocal full_text
        provider_used = "unknown"
        try:
            chunks = _stream_from_provider(system, user_msg, byok)
            async for chunk in chunks:
                if chunk.get("provider"):
                    provider_used = chunk["provider"]
                    continue
                token = chunk.get("text", "")
                if token:
                    full_text.append(token)
                    yield f"data: {json.dumps(token)}\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'error': e.detail})}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            logger.error("Streaming error: %s", e)
            yield f"data: {json.dumps({'error': 'Stream failed. Please try again.'})}\n\n"
            yield "data: [DONE]\n\n"
            return
        assembled = "".join(full_text)
        if assembled:
            try:
                rec = AIResult(owner_username=current_user.username, cache_key=ck, kind="summarize", model_used=provider_used, summary=assembled)
                session.add(rec)
                session.commit()
                _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
            except Exception as e:
                logger.warning("Stream cache write failed: %s", e)
        yield "data: [DONE]\n\n"

    return StreamingResponse(_live_stream(), media_type="text/event-stream")


async def _stream_from_provider(system, user_msg, byok):
    import os
    openai_key    = byok.get("openai_key")
    anthropic_key = byok.get("anthropic_key")
    gemini_key    = byok.get("gemini_key")
    groq_key      = byok.get("groq_key")
    if openai_key:
        yield {"provider": "openai"}
        async for chunk in _openai_stream(openai_key, system, user_msg): yield chunk
        return
    if anthropic_key:
        yield {"provider": "anthropic"}
        async for chunk in _anthropic_stream(anthropic_key, system, user_msg): yield chunk
        return
    groq_free   = os.getenv("GROQ_API_KEY", "").strip()
    active_groq = groq_key or groq_free
    if active_groq:
        yield {"provider": "groq"}
        async for chunk in _openai_stream(active_groq, system, user_msg, base_url="https://api.groq.com/openai/v1", model="llama-3.3-70b-versatile"): yield chunk
        return
    gemini_free   = os.getenv("GEMINI_API_KEY", "").strip()
    active_gemini = gemini_key or gemini_free
    if active_gemini:
        yield {"provider": "gemini"}
        from backend.services.ai_engine import _call_gemini
        model = "gemini-1.5-pro" if gemini_key else "gemini-1.5-flash"
        text  = await _call_gemini(active_gemini, system, user_msg, model=model)
        for i in range(0, len(text), 60):
            yield {"text": text[i:i+60]}
        return
    raise HTTPException(status_code=400, detail="No AI provider configured. Add a BYOK key or set GEMINI_API_KEY/GROQ_API_KEY.")


async def _openai_stream(api_key, system, user, base_url="https://api.openai.com/v1", model="gpt-4o-mini"):
    import httpx
    url     = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model, "temperature": 0.3, "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code == 401: raise HTTPException(status_code=401, detail="API key rejected.")
            if r.status_code == 429: raise HTTPException(status_code=429, detail="Rate limit hit.")
            if r.status_code >= 400: raise HTTPException(status_code=400, detail=f"AI error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "): continue
                data = line[6:]
                if data.strip() == "[DONE]": break
                try:
                    obj   = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content", "")
                    if delta: yield {"text": delta}
                except Exception:
                    continue


async def _anthropic_stream(api_key, system, user):
    import httpx
    url     = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    payload = {
        "model": "claude-haiku-4-5", "max_tokens": 1024, "stream": True,
        "system": system, "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code == 401: raise HTTPException(status_code=401, detail="Anthropic key rejected.")
            if r.status_code == 429: raise HTTPException(status_code=429, detail="Anthropic rate limit hit.")
            if r.status_code >= 400: raise HTTPException(status_code=400, detail=f"Anthropic error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "): continue
                data = line[6:]
                try:
                    obj = json.loads(data)
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta", {}).get("text", "")
                        if delta: yield {"text": delta}
                except Exception:
                    continue


# ── Ask ───────────────────────────────────────────────────────────────────────

@router.post("/ai/ask", response_model=AIAskResponse)
async def ai_ask(payload: AIAskRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    ck = _cache_key("ask", payload.title, payload.doi, payload.pmid, payload.pmcid, payload.question)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "ask")
    )).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AIAskResponse(text=cached.summary)
    system   = "You are a medical evidence assistant. Answer the user's question using ONLY the provided title/abstract context. If the abstract doesn't contain the answer, say what is missing and what to look for. Use concise bullet points when helpful."
    user_msg = f"Question: {payload.question}\n\nPaper:\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok     = _get_byok_keys(current_user)
    result   = await engine_run(system, user_msg, **byok)
    rec      = AIResult(owner_username=current_user.username, cache_key=ck, kind="ask", model_used=result.provider.value, question=payload.question, summary=result.text)
    session.add(rec)
    session.commit()
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AIAskResponse(text=result.text)


# ── Phase 3: Clinical Intelligence ───────────────────────────────────────────

_CLINICAL_SYSTEM = """You are a senior clinical evidence appraiser.
Analyze the provided abstract and title. Return a valid JSON object with exactly these keys:
{
  "pico": {
    "population": str, "intervention": str, "comparator": str, "outcome": str, "primary_outcome": str_or_null,
    "offsets": {
      "population":    {"snippet": str, "start_char": int, "end_char": int},
      "intervention":  {"snippet": str, "start_char": int, "end_char": int},
      "comparator":    {"snippet": str, "start_char": int, "end_char": int},
      "outcome":       {"snippet": str, "start_char": int, "end_char": int}
    }
  },
  "stats": {
    "sample_size": int_or_null, "p_value": str_or_null, "effect_size": str_or_null,
    "confidence_interval": str_or_null, "nnt_nnh": str_or_null,
    "clinical_significance": str_or_null,
    "outcome_numeric": float_or_null
  },
  "appraisal": {
    "evidence_strength": int_1_to_5, "evidence_explanation": str,
    "bias_risk": "Low"|"Moderate"|"High", "bias_score": int_0_to_10, "limitations": [str]
  },
  "grade": {
    "imprecision": "not_serious"|"serious"|"very_serious",
    "inconsistency": "not_serious"|"serious"|"very_serious",
    "indirectness": "not_serious"|"serious"|"very_serious",
    "publication_bias": "undetected"|"suspected"|"unknown",
    "overall": "high"|"moderate"|"low"|"very_low"
  },
  "key_claims": [str],
  "jargon": [{"term": str, "definition": str}],
  "rewrites": {"patient": str, "clinician": str, "student": str}
}
Rules:
- offsets: character positions (0-indexed) in the ABSTRACT TEXT of the supporting evidence snippet for each PICO element. Use -1/-1 if not locatable in text.
- outcome_numeric: primary outcome as a float if extractable (OR, RR, mean diff, HbA1c value, etc.). Null if not numeric.
- bias_score: 0=no bias, 10=critical bias. Base on study design, blinding, randomisation, COI mentions.
- grade: GRADE evidence quality based on study design and reported statistics. Default to "high" for RCTs, "low" for observational, then downgrade for imprecision/inconsistency.
- primary_outcome: the single primary endpoint, else null.
- clinical_significance: whether findings are clinically meaningful beyond statistical significance.
- evidence_explanation: 1-2 sentence reasoning for the evidence_strength score.
- key_claims: 3-6 main findings as concise bullet strings.
- jargon: 3-8 technical terms with plain-English definitions.
Return JSON only. No prose, no markdown fences, no keys outside this structure.
If a value cannot be determined from the abstract, use null."""


@router.post("/ai/clinical", response_model=AIClinicalResponse)
async def ai_clinical(payload: AIClinicalRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, payload.study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    ck     = _cache_key("clinical", payload.title, payload.doi, payload.pmid, payload.pmcid)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "clinical")
    )).first()

    if cached and cached.patient_summary:
        pico_raw, stats_raw, appraisal_raw, key_claims, jargon_raw, text_offsets, grade_raw = _parse_clinical_cache(cached)
        jargon_items = [JargonItem(term=j.get("term", ""), definition=j.get("definition", "")) for j in jargon_raw if isinstance(j, dict)]
        grade = GRADEData(**grade_raw) if grade_raw else None
        return AIClinicalResponse(
            study_id=payload.study_id,
            pico=PICOData(population=pico_raw.get("population"), intervention=pico_raw.get("intervention"), comparator=pico_raw.get("comparator"), outcome=pico_raw.get("outcome"), primary_outcome=pico_raw.get("primary_outcome")),
            stats=StatisticalData(sample_size=stats_raw.get("sample_size"), p_value=stats_raw.get("p_value"), effect_size=stats_raw.get("effect_size"), confidence_interval=stats_raw.get("confidence_interval"), nnt_nnh=stats_raw.get("nnt_nnh"), clinical_significance=stats_raw.get("clinical_significance"), outcome_numeric=stats_raw.get("outcome_numeric")),
            appraisal=AppraisalData(evidence_strength=appraisal_raw.get("evidence_strength"), evidence_explanation=appraisal_raw.get("evidence_explanation"), bias_risk=appraisal_raw.get("bias_risk"), bias_score=appraisal_raw.get("bias_score"), limitations=appraisal_raw.get("limitations") or []),
            rewrites=RewritesData(patient=cached.patient_summary, clinician=cached.clinician_summary, student=cached.student_summary),
            key_claims=key_claims, jargon=jargon_items, grade=grade, text_offsets=text_offsets or None,
            cached=True, prompt_version=cached.prompt_version,
        )

    user_msg = f"Title: {payload.title}\nAbstract: {strip_html(payload.abstract or 'No abstract provided.')}"
    byok     = _get_byok_keys(current_user)
    result   = await engine_run(_CLINICAL_SYSTEM, user_msg, **byok)

    raw = result.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Clinical AI JSON parse failed: %s\nRaw: %s", exc, raw[:500])
        raise HTTPException(status_code=502, detail="AI returned malformed JSON. Try again or use a BYOK key for more reliable extraction.")

    pico_raw      = data.get("pico", {}) or {}
    stats_raw     = data.get("stats", {}) or {}
    appraisal_raw = data.get("appraisal", {}) or {}
    rewrites_raw  = data.get("rewrites", {}) or {}
    key_claims    = data.get("key_claims") or []
    jargon_raw    = data.get("jargon") or []
    grade_raw     = data.get("grade", {}) or {}

    # Build text_offsets list from pico.offsets
    pico_offsets_raw = pico_raw.get("offsets", {}) or {}
    text_offsets = []
    for field in ("population", "intervention", "comparator", "outcome"):
        off = pico_offsets_raw.get(field) or {}
        if off.get("snippet"):
            text_offsets.append({
                "field":      field,
                "snippet":    off.get("snippet", ""),
                "start_char": off.get("start_char", -1),
                "end_char":   off.get("end_char", -1),
            })

    try:
        write_clinical_data(session=session, study_id=payload.study_id, owner_username=current_user.username, pico_data=pico_raw, statistical_data=stats_raw, evidence_strength=appraisal_raw.get("evidence_strength"), risk_of_bias=appraisal_raw.get("bias_risk"))
    except Exception as e:
        logger.warning("write_clinical_data failed (non-fatal): %s", e)

    # Phase 4c: write structured extraction fields back to Study
    try:
        study.extracted_outcome_value = stats_raw.get("outcome_numeric")
        study.extracted_sample_size   = stats_raw.get("sample_size")
        study.extracted_bias_score    = appraisal_raw.get("bias_score")
        study.grade_criteria          = grade_raw if grade_raw else None
        session.add(study)
    except Exception as e:
        logger.warning("Study extraction write failed (non-fatal): %s", e)

    cache_data = {"pico": pico_raw, "stats": stats_raw, "appraisal": appraisal_raw, "key_claims": key_claims, "jargon": jargon_raw, "grade": grade_raw}
    try:
        rec = AIResult(owner_username=current_user.username, cache_key=ck, kind="clinical", model_used=result.provider.value, prompt_version="3.2", question=json.dumps(cache_data), summary=json.dumps(stats_raw), patient_summary=rewrites_raw.get("patient"), clinician_summary=rewrites_raw.get("clinician"), student_summary=rewrites_raw.get("student"), text_offsets=text_offsets if text_offsets else None)
        session.add(rec)
        session.commit()
    except Exception as e:
        logger.warning("AIResult cache write failed (non-fatal): %s", e)

    try:
        increment_ai_runs(session, payload.study_id, current_user.username)
    except Exception:
        pass

    grade = GRADEData(**grade_raw) if grade_raw else None
    jargon_items = [JargonItem(term=j.get("term", ""), definition=j.get("definition", "")) for j in jargon_raw if isinstance(j, dict)]
    return AIClinicalResponse(
        study_id=payload.study_id,
        pico=PICOData(population=pico_raw.get("population"), intervention=pico_raw.get("intervention"), comparator=pico_raw.get("comparator"), outcome=pico_raw.get("outcome"), primary_outcome=pico_raw.get("primary_outcome")),
        stats=StatisticalData(sample_size=stats_raw.get("sample_size"), p_value=str(stats_raw["p_value"]) if stats_raw.get("p_value") is not None else None, effect_size=stats_raw.get("effect_size"), confidence_interval=stats_raw.get("confidence_interval"), nnt_nnh=stats_raw.get("nnt_nnh"), clinical_significance=stats_raw.get("clinical_significance"), outcome_numeric=stats_raw.get("outcome_numeric")),
        appraisal=AppraisalData(evidence_strength=appraisal_raw.get("evidence_strength"), evidence_explanation=appraisal_raw.get("evidence_explanation"), bias_risk=appraisal_raw.get("bias_risk"), bias_score=appraisal_raw.get("bias_score"), limitations=appraisal_raw.get("limitations") or []),
        rewrites=RewritesData(patient=rewrites_raw.get("patient"), clinician=rewrites_raw.get("clinician"), student=rewrites_raw.get("student")),
        key_claims=key_claims, jargon=jargon_items, grade=grade, text_offsets=text_offsets or None, cached=False,
    )


@router.get("/ai/clinical/{study_id}", response_model=AIClinicalResponse)
def get_clinical(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, study_id)
    if not study: raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed")

    from backend.models import StudyMetrics
    m  = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()
    ck = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "clinical") &
        (AIResult.patient_summary != None)  # noqa: E711
    )).first()

    if not m and not cached:
        raise HTTPException(status_code=404, detail="No clinical analysis found for this study. Run POST /ai/clinical first.")

    pico_raw, stats_raw, appraisal_raw, key_claims, jargon_raw, text_offsets, grade_raw = _parse_clinical_cache(cached) if cached else ({}, {}, {}, [], [], [], {})
    jargon_items = [JargonItem(term=j.get("term", ""), definition=j.get("definition", "")) for j in jargon_raw if isinstance(j, dict)]
    grade = GRADEData(**grade_raw) if grade_raw else None

    return AIClinicalResponse(
        study_id=study_id,
        pico=PICOData(population=pico_raw.get("population"), intervention=pico_raw.get("intervention"), comparator=pico_raw.get("comparator"), outcome=pico_raw.get("outcome"), primary_outcome=pico_raw.get("primary_outcome")),
        stats=StatisticalData(sample_size=stats_raw.get("sample_size"), p_value=stats_raw.get("p_value"), effect_size=stats_raw.get("effect_size"), confidence_interval=stats_raw.get("confidence_interval"), nnt_nnh=stats_raw.get("nnt_nnh"), clinical_significance=stats_raw.get("clinical_significance"), outcome_numeric=stats_raw.get("outcome_numeric")),
        appraisal=AppraisalData(evidence_strength=appraisal_raw.get("evidence_strength") or (m.evidence_strength if m else None), evidence_explanation=appraisal_raw.get("evidence_explanation"), bias_risk=appraisal_raw.get("bias_risk") or (m.risk_of_bias if m else None), bias_score=appraisal_raw.get("bias_score"), limitations=appraisal_raw.get("limitations") or []),
        rewrites=RewritesData(patient=cached.patient_summary if cached else None, clinician=cached.clinician_summary if cached else None, student=cached.student_summary if cached else None),
        key_claims=key_claims, jargon=jargon_items, grade=grade, text_offsets=text_offsets or None,
        cached=True, prompt_version=cached.prompt_version if cached else None,
    )


@router.post("/ai/clinical/{study_id}/share")
def create_share_link(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    import uuid
    study = session.get(Study, study_id)
    if not study: raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed")
    ck     = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
    cached = session.exec(select(AIResult).where(
        (AIResult.owner_username == current_user.username) &
        (AIResult.cache_key == ck) &
        (AIResult.kind == "clinical")
    )).first()
    if not cached: raise HTTPException(status_code=404, detail="Run clinical analysis first before sharing.")
    if not cached.share_token:
        cached.share_token = uuid.uuid4().hex
        session.add(cached)
        session.commit()
        session.refresh(cached)
    return {"share_token": cached.share_token, "title": study.title}


@router.get("/ai/shared/{token}")
def get_shared_evidence(token: str, session: Session = Depends(get_session)):
    cached = session.exec(select(AIResult).where(AIResult.share_token == token)).first()
    if not cached: raise HTTPException(status_code=404, detail="Shared analysis not found or link expired.")

    from backend.models import StudyMetrics
    title    = "Untitled"
    study_id = None
    owner_studies = session.exec(select(Study).where(Study.owner_username == cached.owner_username).limit(500)).all()
    for s in owner_studies:
        if _cache_key("clinical", s.title, s.doi, s.pmid, s.pmcid) == cached.cache_key:
            title    = s.title
            study_id = s.id
            break

    pico_raw, stats_raw, appraisal_raw, key_claims, jargon_raw, text_offsets, grade_raw = _parse_clinical_cache(cached)
    m = None
    if study_id:
        m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()

    return {
        "title": title, "pico": pico_raw, "stats": stats_raw,
        "appraisal": {
            "evidence_strength":    appraisal_raw.get("evidence_strength") or (m.evidence_strength if m else None),
            "evidence_explanation": appraisal_raw.get("evidence_explanation"),
            "bias_risk":            appraisal_raw.get("bias_risk") or (m.risk_of_bias if m else None),
            "bias_score":           appraisal_raw.get("bias_score"),
            "limitations":          appraisal_raw.get("limitations") or [],
        },
        "grade":      grade_raw or None,
        "text_offsets": text_offsets or None,
        "rewrites":   {"patient": cached.patient_summary, "clinician": cached.clinician_summary, "student": cached.student_summary},
        "key_claims": key_claims,
        "jargon":     jargon_raw,
        "is_retracted": False,
    }


# ── Phase 4 helpers ───────────────────────────────────────────────────────────

# Strengthened steel-man: forces genuine counter-argument, not just limitations
_SYNTHESIS_SYSTEM = """You are a senior systematic review analyst with expertise in evidence-based medicine.
Synthesise the provided research papers and return a valid JSON object with exactly these keys:
{
  "synthesis_narrative": str,
  "consensus_points": [{"finding": str, "supporting_studies": [str], "strength": "strong"|"moderate"|"weak"}],
  "contradictions": [{"issue": str, "side_a_studies": [str], "side_a_position": str, "side_b_studies": [str], "side_b_position": str, "likely_explanation": str}],
  "gap_analysis": [str],
  "weighted_conclusion": str,
  "steel_man": str,
  "comparative_methodology": str
}
Definitions:
- synthesis_narrative: 2-3 paragraph overview of what these studies collectively show
- consensus_points: findings where 2+ studies agree. Use short paper titles/years as identifiers
- contradictions: where studies disagree — explain likely reason (population, methodology differences)
- gap_analysis: 3-5 specific evidence gaps (populations not studied, outcomes not measured, etc.)
- weighted_conclusion: conclusion that accounts for study quality (RCTs > cohorts > case reports)
- steel_man: construct the STRONGEST possible argument AGAINST the weighted_conclusion. Do NOT simply list limitations. Build a compelling opposing case using the available evidence — argue as an expert who genuinely believes the opposite conclusion and has good reasons for it.
- comparative_methodology: comparison of study designs, sample sizes, populations across papers
Return JSON only. No markdown fences."""


def _build_synthesis_context(studies: list, clinical_data: dict) -> str:
    papers = []
    for i, study in enumerate(studies, 1):
        cd   = clinical_data.get(study.id, {})
        pico = cd.get("pico", {})
        # Use detected study type if stored value is null
        effective_type = study.study_type or _detect_study_type_from_abstract(study.abstract)
        block = f"Paper {i}: {study.title}"
        if study.year:        block += f" ({study.year})"
        if effective_type:    block += f" [{effective_type.replace('_', ' ').title()}]"
        block += "\n"
        if study.abstract:           block += f"Abstract: {strip_html(study.abstract)[:600]}\n"
        if pico.get("population"):   block += f"Population: {pico['population']}\n"
        if pico.get("intervention"): block += f"Intervention: {pico['intervention']}\n"
        if pico.get("outcome"):      block += f"Outcome: {pico['outcome']}\n"
        stats = cd.get("stats", {})
        if stats.get("effect_size"): block += f"Effect size: {stats['effect_size']}\n"
        if stats.get("p_value"):     block += f"P-value: {stats['p_value']}\n"
        papers.append(block)
    return "\n---\n".join(papers)


def _build_weighting(studies: list) -> list:
    total   = 0.0
    weights = []
    for s in studies:
        # Use detected study type if stored value is null
        effective_type = s.study_type or _detect_study_type_from_abstract(s.abstract)
        score, recency = _compute_evidence_weight(effective_type, s.year)
        weights.append({
            "study_id":      s.id,
            "study_title":   s.title[:60] + ("..." if len(s.title) > 60 else ""),
            "study_type":    effective_type,
            "year":          s.year,
            "base_score":    EVIDENCE_WEIGHTS.get((effective_type or "other").lower().replace(" ", "_"), 1.0),
            "recency_bonus": recency,
            "final_score":   score,
            "weight_pct":    0.0,
        })
        total += score
    if total > 0:
        for w in weights:
            w["weight_pct"] = round((w["final_score"] / total) * 100, 1)
    return weights


def _parse_synthesis_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _build_synthesis_response(rec: SynthesisResult, study_ids: list, cached: bool) -> AISynthesisResponse:
    def _parse(field):
        try:
            return json.loads(field or "[]")
        except Exception:
            return []
    consensus      = [ConsensusPoint(finding=c.get("finding", ""), supporting_studies=c.get("supporting_studies", []), strength=c.get("strength")) for c in _parse(rec.consensus_points) if isinstance(c, dict)]
    contradictions = [ContradictionItem(issue=c.get("issue", ""), side_a_studies=c.get("side_a_studies", []), side_a_position=c.get("side_a_position", ""), side_b_studies=c.get("side_b_studies", []), side_b_position=c.get("side_b_position", ""), likely_explanation=c.get("likely_explanation")) for c in _parse(rec.contradictions) if isinstance(c, dict)]
    weighting      = [WeightingItem(study_title=w.get("study_title", ""), study_type=w.get("study_type"), year=w.get("year"), base_score=w.get("base_score", 1.0), recency_bonus=w.get("recency_bonus", False), final_score=w.get("final_score", 1.0), weight_pct=w.get("weight_pct", 0.0)) for w in _parse(rec.weighting_breakdown) if isinstance(w, dict)]
    gaps           = _parse(rec.gap_analysis)
    return AISynthesisResponse(
        synthesis_id=rec.id or 0, study_ids=study_ids, paper_count=rec.paper_count,
        synthesis_narrative=rec.synthesis_narrative, consensus_points=consensus,
        contradictions=contradictions, gap_analysis=gaps if isinstance(gaps, list) else [],
        weighted_conclusion=rec.weighted_conclusion, steel_man=rec.steel_man,
        comparative_methodology=rec.comparative_methodology, weighting_breakdown=weighting,
        cached=cached, prompt_version=rec.prompt_version,
    )


# ── Phase 4: Cross-Paper Analysis ────────────────────────────────────────────

@router.post("/ai/synthesise", response_model=AISynthesisResponse)
async def ai_synthesise(payload: AISynthesisRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """Cross-paper evidence analysis across 2-10 saved papers."""
    if len(payload.study_ids) < 2:  raise HTTPException(status_code=400, detail="At least 2 studies required.")
    if len(payload.study_ids) > 10: raise HTTPException(status_code=400, detail="Maximum 10 studies per analysis.")

    studies: list = []
    for sid in payload.study_ids:
        study = session.get(Study, sid)
        if not study: raise HTTPException(status_code=404, detail=f"Study {sid} not found.")
        if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail=f"Study {sid} not accessible.")
        studies.append(study)

    ck = _synthesis_cache_key(payload.study_ids)

    # force_rerun: delete existing cache entry before re-running
    if payload.force_rerun:
        existing = session.exec(select(SynthesisResult).where(
            (SynthesisResult.owner_username == current_user.username) &
            (SynthesisResult.cache_key == ck)
        )).first()
        if existing:
            session.delete(existing)
            session.commit()

    cached_rec = session.exec(select(SynthesisResult).where(
        (SynthesisResult.owner_username == current_user.username) &
        (SynthesisResult.cache_key == ck)
    )).first()
    if cached_rec and cached_rec.synthesis_narrative:
        return _build_synthesis_response(cached_rec, payload.study_ids, cached=True)

    # Gather existing clinical data for context enrichment
    clinical_data: dict = {}
    for study in studies:
        study_ck = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
        ai_rec   = session.exec(select(AIResult).where(
            (AIResult.owner_username == current_user.username) &
            (AIResult.cache_key == study_ck) &
            (AIResult.kind == "clinical")
        )).first()
        if ai_rec and ai_rec.question:
            try:
                clinical_data[study.id] = json.loads(ai_rec.question)
            except Exception:
                pass

    # Abstract quality filter: prefer papers with useful abstracts, keep at least 2
    usable = [s for s in studies if s.abstract and len(strip_html(s.abstract)) >= 40]
    if len(usable) < 2:
        usable = studies  # fallback

    weighting  = _build_weighting(usable)
    weight_ctx = "\n".join([f"  - {w['study_title']} ({w['study_type'] or 'unknown'}, {w['year'] or '?'}): weight {w['weight_pct']}%" for w in weighting])
    paper_ctx  = _build_synthesis_context(usable, clinical_data)
    user_msg   = f"Analyse the following {len(usable)} research papers.\n\nEvidence weighting:\n{weight_ctx}\n\nPapers:\n{paper_ctx}"

    byok   = _get_byok_keys(current_user)
    result = await engine_run(_SYNTHESIS_SYSTEM, user_msg, **byok)

    try:
        data = _parse_synthesis_json(result.text)
    except json.JSONDecodeError as exc:
        logger.error("Synthesis AI JSON parse failed: %s\nRaw: %s", exc, result.text[:500])
        raise HTTPException(status_code=502, detail="AI returned malformed JSON. Try again or use a BYOK key.")

    try:
        rec = SynthesisResult(
            owner_username=current_user.username, cache_key=ck,
            study_ids=json.dumps(sorted(payload.study_ids)), mode="multi_paper",
            synthesis_narrative=data.get("synthesis_narrative"),
            consensus_points=json.dumps(data.get("consensus_points") or []),
            contradictions=json.dumps(data.get("contradictions") or []),
            gap_analysis=json.dumps(data.get("gap_analysis") or []),
            weighted_conclusion=data.get("weighted_conclusion"),
            steel_man=data.get("steel_man"),
            comparative_methodology=data.get("comparative_methodology"),
            weighting_breakdown=json.dumps(weighting),
            prompt_version="4.1", model_used=result.provider.value, paper_count=len(usable),
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)
        return _build_synthesis_response(rec, payload.study_ids, cached=False)
    except Exception as e:
        logger.warning("SynthesisResult cache write failed (non-fatal): %s", e)
        dummy = SynthesisResult(
            id=0, owner_username=current_user.username, cache_key=ck,
            study_ids=json.dumps(sorted(payload.study_ids)), mode="multi_paper",
            synthesis_narrative=data.get("synthesis_narrative"),
            consensus_points=json.dumps(data.get("consensus_points") or []),
            contradictions=json.dumps(data.get("contradictions") or []),
            gap_analysis=json.dumps(data.get("gap_analysis") or []),
            weighted_conclusion=data.get("weighted_conclusion"),
            steel_man=data.get("steel_man"),
            comparative_methodology=data.get("comparative_methodology"),
            weighting_breakdown=json.dumps(weighting),
            prompt_version="4.1", model_used=result.provider.value, paper_count=len(usable),
        )
        return _build_synthesis_response(dummy, payload.study_ids, cached=False)


# IMPORTANT: /ai/synthesise/ask must be defined BEFORE /ai/synthesise/{synthesis_id}
# so FastAPI matches the static path first.

@router.post("/ai/synthesise/ask", response_model=CrossPaperAskResponse)
async def cross_paper_ask(payload: CrossPaperAskRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """
    Ask a question answered using only the content of the specified saved papers.
    This is distinct from subject-query (which searches fresh literature).
    Results are not cached — questions are free-form.
    """
    studies: list = []
    for sid in payload.study_ids:
        study = session.get(Study, sid)
        if not study: raise HTTPException(status_code=404, detail=f"Study {sid} not found.")
        if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail=f"Study {sid} not accessible.")
        studies.append(study)

    paper_ctx = "\n\n".join([
        f"Paper {i}: {s.title} ({s.year or 'n/a'})\nAbstract: {strip_html(s.abstract or 'No abstract.')[:400]}"
        for i, s in enumerate(studies, 1)
    ])

    system   = (
        "You are a clinical evidence assistant with access to both the provided paper abstracts "
        "AND your general medical knowledge.\n\n"
        "INSTRUCTIONS:\n"
        "1. First, check if the provided paper abstracts contain relevant information to answer the question.\n"
        "2. If YES: answer using the papers, citing which paper supports each point (e.g. \'Paper 1 found...\').\n"
        "3. If the papers only PARTIALLY answer the question: answer the paper-supported parts with citations, "
        "then continue with general medical knowledge for the rest, clearly marking the transition with: "
        "\'\u26a0\ufe0f The following is from general medical knowledge, not the selected papers:\'\n"
        "4. If the papers do NOT contain the answer: STILL answer the question using your general medical "
        "knowledge, but prefix your entire answer with: "
        "\'\u26a0\ufe0f Not found in selected papers — answering from general medical knowledge:\'\n\n"
        "NEVER refuse to answer. Always provide the most useful clinical response you can. Be concise and precise."
    )
    user_msg = f"Question: {payload.question}\n\nPapers to use as context:\n{paper_ctx}"

    byok   = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)

    return CrossPaperAskResponse(answer=result.text, study_ids=payload.study_ids, question=payload.question)


@router.get("/ai/synthesise/{synthesis_id}", response_model=AISynthesisResponse)
def get_synthesis(synthesis_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    rec = session.get(SynthesisResult, synthesis_id)
    if not rec: raise HTTPException(status_code=404, detail="Synthesis not found.")
    if rec.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed.")
    study_ids = json.loads(rec.study_ids or "[]")
    return _build_synthesis_response(rec, study_ids, cached=True)


# ── Phase 4: Literature Search & Synthesis (Subject Query) ───────────────────

@router.post("/ai/subject-query", response_model=AISubjectQueryResponse)
async def ai_subject_query(payload: AISubjectQueryRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """
    Literature search and synthesis mode.
    Searches FRESH literature from the specified source.
    Does NOT use the user's saved papers.
    """
    ck     = _subject_query_cache_key(payload.query, payload.source)
    cached = session.exec(select(SynthesisResult).where(
        (SynthesisResult.owner_username == current_user.username) &
        (SynthesisResult.cache_key == ck) &
        (SynthesisResult.mode == "subject_query")
    )).first()
    if cached and cached.synthesis_narrative:
        resp = _build_synthesis_response(cached, [], cached=True)
        return AISubjectQueryResponse(
            synthesis_id=resp.synthesis_id, query=payload.query, papers_found=cached.paper_count,
            synthesis_narrative=resp.synthesis_narrative, consensus_points=resp.consensus_points,
            contradictions=resp.contradictions, gap_analysis=resp.gap_analysis,
            weighted_conclusion=resp.weighted_conclusion, steel_man=resp.steel_man,
            papers_used=[], cached=True,
        )

    src        = (payload.source or "europepmc").strip().lower()
    papers_raw = []
    try:
        from backend.external_providers import get_provider
        provider   = get_provider(src)
        retrieved, _, _ = await provider.search(q=payload.query, limit=payload.max_papers)
        papers_raw = retrieved or []
    except HTTPException:
        raise  # re-raise FastAPI exceptions as-is
    except Exception as e:
        logger.warning("Subject query auto-retrieval failed for source '%s': %s", src, e)
        raise HTTPException(
            status_code=503,
            detail=f"Could not retrieve papers from {src}. Try a different source (e.g. OpenAlex) or rephrase your query.",
        )

    if not papers_raw:
        raise HTTPException(
            status_code=404,
            detail=f"No papers found for '{payload.query}' on {src}. Try different keywords or switch source.",
        )

    # Prefer papers with useful abstracts
    papers_with_abstracts = [p for p in papers_raw if p.abstract and len(p.abstract) > 60] or papers_raw
    papers_to_use = papers_with_abstracts[:payload.max_papers]

    paper_blocks: list = []
    papers_used:  list = []
    for i, p in enumerate(papers_to_use, 1):
        st    = getattr(p, "study_type", None) or _detect_study_type_from_abstract(getattr(p, "abstract", None)) or "unknown"
        block = f"Paper {i}: {p.title}" + (f" ({p.year})" if p.year else "") + f"\nAbstract: {strip_html(p.abstract or '')[:500]}"
        paper_blocks.append(block)
        papers_used.append({"title": p.title, "year": p.year, "source": p.source, "study_type": st, "doi": p.doi})

    user_msg = f"Clinical question: {payload.query}\n\nSynthesise the following {len(papers_to_use)} retrieved papers:\n\n" + "\n---\n".join(paper_blocks)
    byok     = _get_byok_keys(current_user)
    result   = await engine_run(_SYNTHESIS_SYSTEM, user_msg, **byok)

    try:
        data = _parse_synthesis_json(result.text)
    except json.JSONDecodeError as exc:
        logger.error("Subject query AI JSON parse failed: %s\nRaw: %s", exc, result.text[:500])
        raise HTTPException(status_code=502, detail="AI returned malformed JSON. Try again.")

    synthesis_id = 0
    try:
        rec = SynthesisResult(
            owner_username=current_user.username, cache_key=ck,
            study_ids=json.dumps([]), mode="subject_query", query=payload.query,
            synthesis_narrative=data.get("synthesis_narrative"),
            consensus_points=json.dumps(data.get("consensus_points") or []),
            contradictions=json.dumps(data.get("contradictions") or []),
            gap_analysis=json.dumps(data.get("gap_analysis") or []),
            weighted_conclusion=data.get("weighted_conclusion"),
            steel_man=data.get("steel_man"),
            comparative_methodology=data.get("comparative_methodology"),
            weighting_breakdown=json.dumps([]),
            prompt_version="4.1", model_used=result.provider.value, paper_count=len(papers_to_use),
        )
        session.add(rec)
        session.commit()
        session.refresh(rec)
        synthesis_id = rec.id
    except Exception as e:
        logger.warning("SynthesisResult (subject query) cache write failed: %s", e)

    consensus      = [ConsensusPoint(finding=c.get("finding", ""), supporting_studies=c.get("supporting_studies", []), strength=c.get("strength")) for c in (data.get("consensus_points") or []) if isinstance(c, dict)]
    contradictions = [ContradictionItem(issue=c.get("issue", ""), side_a_studies=c.get("side_a_studies", []), side_a_position=c.get("side_a_position", ""), side_b_studies=c.get("side_b_studies", []), side_b_position=c.get("side_b_position", ""), likely_explanation=c.get("likely_explanation")) for c in (data.get("contradictions") or []) if isinstance(c, dict)]

    return AISubjectQueryResponse(
        synthesis_id=synthesis_id or 0, query=payload.query, papers_found=len(papers_to_use),
        synthesis_narrative=data.get("synthesis_narrative"),
        consensus_points=consensus, contradictions=contradictions,
        gap_analysis=data.get("gap_analysis") or [],
        weighted_conclusion=data.get("weighted_conclusion"),
        steel_man=data.get("steel_man"),
        papers_used=papers_used, cached=False,
    )


# ── Phase 4 Cleanup: Citation Formatting ─────────────────────────────────────

@router.post("/ai/citations", response_model=CitationResponse)
def generate_citations(payload: CitationRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """
    Generate formatted citations for a list of saved studies.
    Supports: harvard, apa, vancouver, chicago, mla, bibtex.
    No AI required — uses stored metadata only.
    """
    fmt = payload.format.lower().strip()
    if fmt not in CITATION_FORMATS:
        raise HTTPException(status_code=400, detail=f"Format must be one of: {', '.join(CITATION_FORMATS)}")

    citations: list = []
    for sid in payload.study_ids:
        study = session.get(Study, sid)
        if not study:
            continue
        if study.owner_username != current_user.username:
            continue
        formatted = _format_citation(study, fmt)
        citations.append(CitationItem(study_id=study.id, title=study.title, formatted=formatted))

    return CitationResponse(citations=citations, format=fmt, count=len(citations))


# ── Synthesis history (persistent) ────────────────────────────────────────────

@router.get("/ai/syntheses", response_model=list[SynthesisListItem])
def list_syntheses(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """List all synthesis results for the current user (persistent history)."""
    recs = session.exec(
        select(SynthesisResult)
        .where(SynthesisResult.owner_username == current_user.username)
        .order_by(SynthesisResult.updated_at.desc())
    ).all()
    return [SynthesisListItem.model_validate(r) for r in recs]


@router.delete("/ai/syntheses/{synthesis_id}")
def delete_synthesis(synthesis_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    rec = session.get(SynthesisResult, synthesis_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Synthesis not found.")
    if rec.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed.")
    session.delete(rec)
    session.commit()
    return {"status": "deleted", "synthesis_id": synthesis_id}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/ai/health")
async def ai_health():
    from backend.services.ai_engine import health_check
    checks = await health_check()
    return {"status": "ok", "router": "ai", "providers": checks}