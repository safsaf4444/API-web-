from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, List

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
    JargonItem, PICOData, RewritesData, StatisticalData, WeightingItem,
)
from backend.services.ai_engine import run as engine_run
from backend.services.ai_service import strip_html
from backend.services.metrics_service import increment_ai_runs, write_clinical_data

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ai"])

# ── Evidence weighting (Phase 4) ──────────────────────────────────────────────

EVIDENCE_WEIGHTS = {
    "meta_analysis": 5.0, "systematic_review": 4.5, "rct": 4.0,
    "cohort": 3.0, "case_control": 2.5, "cross_sectional": 2.0,
    "review": 1.5, "case_report": 1.0, "editorial": 0.5, "other": 1.0,
}

def _compute_evidence_weight(study_type, year):
    base = EVIDENCE_WEIGHTS.get((study_type or "other").lower().replace(" ", "_"), 1.0)
    recency = False
    if year and (datetime.now(timezone.utc).year - year) <= 5:
        base *= 1.1
        recency = True
    return round(base, 2), recency

# ── Helpers ───────────────────────────────────────────────────────────────────

def _cache_key(kind, title, doi, pmid, pmcid, question=None):
    base = {
        "kind": kind,
        "title": (title or "").strip().lower(),
        "doi": (doi or "").strip().lower(),
        "pmid": (pmid or "").strip().lower(),
        "pmcid": (pmcid or "").strip().lower(),
        "question": (question or "").strip().lower(),
    }
    raw = "|".join([f"{k}={base[k]}" for k in sorted(base.keys())])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _synthesis_cache_key(study_ids):
    raw = "synthesis|" + ",".join(str(i) for i in sorted(study_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _subject_query_cache_key(query, source):
    raw = f"subject_query|{query.strip().lower()}|{source}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _get_byok_keys(user):
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

def _get_study_id_for_paper(session, owner, doi, pmid):
    if doi:
        s = session.exec(select(Study).where((Study.owner_username == owner) & (Study.doi == doi.strip()))).first()
        if s: return s.id
    if pmid:
        s = session.exec(select(Study).where((Study.owner_username == owner) & (Study.pmid == pmid.strip()))).first()
        if s: return s.id
    return None

def _wire_ai_runs(session, username, doi, pmid):
    try:
        study_id = _get_study_id_for_paper(session, username, doi, pmid)
        if study_id:
            increment_ai_runs(session, study_id, username)
    except Exception:
        pass

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
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "summarize"))).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AISummarizeResponse(text=cached.summary)
    system = "You are a careful medical evidence assistant. Write in clear plain English. Use short headings and bullet points. Do not invent results. If info is missing, say so."
    user_msg = f"Summarize this paper.\n\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)
    rec = AIResult(owner_username=current_user.username, cache_key=ck, kind="summarize", model_used=result.provider.value, summary=result.text)
    session.add(rec)
    session.commit()
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AISummarizeResponse(text=result.text)

# ── Summarize (streaming) ─────────────────────────────────────────────────────

@router.post("/ai/summarize/stream")
async def ai_summarize_stream(payload: AISummarizeRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    ck = _cache_key("summarize", payload.title, payload.doi, payload.pmid, payload.pmcid)
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "summarize"))).first()

    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        async def _cached_stream():
            text = cached.summary
            for i in range(0, len(text), 80):
                yield f"data: {json.dumps(text[i:i+80])}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_cached_stream(), media_type="text/event-stream")

    system = "You are a careful medical evidence assistant. Write in clear plain English. Use short headings and bullet points. Do not invent results. If info is missing, say so."
    user_msg = f"Summarize this paper.\n\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok = _get_byok_keys(current_user)
    full_text = []

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
    openai_key = byok.get("openai_key")
    anthropic_key = byok.get("anthropic_key")
    gemini_key = byok.get("gemini_key")
    groq_key = byok.get("groq_key")
    if openai_key:
        yield {"provider": "openai"}
        async for chunk in _openai_stream(openai_key, system, user_msg): yield chunk
        return
    if anthropic_key:
        yield {"provider": "anthropic"}
        async for chunk in _anthropic_stream(anthropic_key, system, user_msg): yield chunk
        return
    groq_free = os.getenv("GROQ_API_KEY", "").strip()
    active_groq = groq_key or groq_free
    if active_groq:
        yield {"provider": "groq"}
        async for chunk in _openai_stream(active_groq, system, user_msg, base_url="https://api.groq.com/openai/v1", model="llama-3.3-70b-versatile"): yield chunk
        return
    gemini_free = os.getenv("GEMINI_API_KEY", "").strip()
    active_gemini = gemini_key or gemini_free
    if active_gemini:
        yield {"provider": "gemini"}
        from backend.services.ai_engine import _call_gemini
        model = "gemini-1.5-pro" if gemini_key else "gemini-1.5-flash"
        text = await _call_gemini(active_gemini, system, user_msg, model=model)
        for i in range(0, len(text), 60): yield {"text": text[i:i+60]}
        return
    raise HTTPException(status_code=400, detail="No AI provider configured. Add a BYOK key or set GEMINI_API_KEY/GROQ_API_KEY.")


async def _openai_stream(api_key, system, user, base_url="https://api.openai.com/v1", model="gpt-4o-mini"):
    import httpx
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "temperature": 0.3, "stream": True,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
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
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content", "")
                    if delta: yield {"text": delta}
                except Exception: continue


async def _anthropic_stream(api_key, system, user):
    import httpx
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    payload = {"model": "claude-haiku-4-5", "max_tokens": 1024, "stream": True, "system": system,
               "messages": [{"role": "user", "content": user}]}
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
                except Exception: continue

# ── Ask ───────────────────────────────────────────────────────────────────────

@router.post("/ai/ask", response_model=AIAskResponse)
async def ai_ask(payload: AIAskRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    ck = _cache_key("ask", payload.title, payload.doi, payload.pmid, payload.pmcid, payload.question)
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "ask"))).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AIAskResponse(text=cached.summary)
    system = "You are a medical evidence assistant. Answer the user's question using ONLY the provided title/abstract context. If the abstract doesn't contain the answer, say what is missing and what to look for. Use concise bullet points when helpful."
    user_msg = f"Question: {payload.question}\n\nPaper:\nTitle: {payload.title}\nVenue: {payload.venue or 'n/a'}\nYear: {payload.year or 'n/a'}\nPMID: {payload.pmid or 'n/a'}\nPMCID: {payload.pmcid or 'n/a'}\nDOI: {payload.doi or 'n/a'}\n\nAbstract:\n{strip_html(payload.abstract or '')}"
    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)
    rec = AIResult(owner_username=current_user.username, cache_key=ck, kind="ask", model_used=result.provider.value, question=payload.question, summary=result.text)
    session.add(rec)
    session.commit()
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AIAskResponse(text=result.text)

# ── Phase 3: Clinical Intelligence ───────────────────────────────────────────

_CLINICAL_SYSTEM = """You are a senior clinical evidence appraiser.
Analyze the provided abstract and title. Return a valid JSON object with exactly these keys:
{
  "pico": {"population": str, "intervention": str, "comparator": str, "outcome": str, "primary_outcome": str_or_null},
  "stats": {"sample_size": int_or_null, "p_value": str_or_null, "effect_size": str_or_null, "confidence_interval": str_or_null, "nnt_nnh": str_or_null, "clinical_significance": str_or_null},
  "appraisal": {"evidence_strength": int_1_to_5, "evidence_explanation": str, "bias_risk": "Low"|"Moderate"|"High", "limitations": [str]},
  "key_claims": [str],
  "jargon": [{"term": str, "definition": str}],
  "rewrites": {"patient": str, "clinician": str, "student": str}
}
Rules:
- primary_outcome: the single primary endpoint/outcome if identifiable, else null
- clinical_significance: whether findings are clinically meaningful (separate from statistical p-values)
- evidence_explanation: 1-2 sentence reasoning for the evidence_strength score
- key_claims: 3-6 main claims or findings from the study, as concise bullet-point strings
- jargon: 3-8 technical terms used in the abstract with plain-English definitions
Return JSON only. No prose, no markdown fences, no keys outside this structure.
If a value cannot be determined from the abstract, use null."""


@router.post("/ai/clinical", response_model=AIClinicalResponse)
async def ai_clinical(payload: AIClinicalRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, payload.study_id)
    if not study: raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed")
    ck = _cache_key("clinical", payload.title, payload.doi, payload.pmid, payload.pmcid)
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "clinical"))).first()
    if cached and cached.patient_summary:
        return AIClinicalResponse(study_id=payload.study_id, pico=PICOData(**(json.loads(cached.question) if cached.question else {})), stats=StatisticalData(**(json.loads(cached.summary) if cached.summary else {})), appraisal=AppraisalData(), rewrites=RewritesData(patient=cached.patient_summary, clinician=cached.clinician_summary, student=cached.student_summary), cached=True)
    user_msg = f"Title: {payload.title}\nAbstract: {strip_html(payload.abstract or 'No abstract provided.')}"
    byok = _get_byok_keys(current_user)
    result = await engine_run(_CLINICAL_SYSTEM, user_msg, **byok)
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
    pico_raw = data.get("pico", {}) or {}
    stats_raw = data.get("stats", {}) or {}
    appraisal_raw = data.get("appraisal", {}) or {}
    rewrites_raw = data.get("rewrites", {}) or {}
    key_claims = data.get("key_claims") or []
    jargon_raw = data.get("jargon") or []
    try:
        write_clinical_data(session=session, study_id=payload.study_id, owner_username=current_user.username, pico_data=pico_raw, statistical_data=stats_raw, evidence_strength=appraisal_raw.get("evidence_strength"), risk_of_bias=appraisal_raw.get("bias_risk"))
    except Exception as e:
        logger.warning("write_clinical_data failed (non-fatal): %s", e)
    cache_data = {"pico": pico_raw, "stats": stats_raw, "appraisal": appraisal_raw, "key_claims": key_claims, "jargon": jargon_raw}
    try:
        rec = AIResult(owner_username=current_user.username, cache_key=ck, kind="clinical", model_used=result.provider.value, prompt_version="3.1", question=json.dumps(cache_data), summary=json.dumps(stats_raw), patient_summary=rewrites_raw.get("patient"), clinician_summary=rewrites_raw.get("clinician"), student_summary=rewrites_raw.get("student"))
        session.add(rec)
        session.commit()
    except Exception as e:
        logger.warning("AIResult cache write failed (non-fatal): %s", e)
    try:
        increment_ai_runs(session, payload.study_id, current_user.username)
    except Exception:
        pass
    jargon_items = [JargonItem(term=j.get("term", ""), definition=j.get("definition", "")) for j in jargon_raw if isinstance(j, dict)]
    return AIClinicalResponse(study_id=payload.study_id, pico=PICOData(population=pico_raw.get("population"), intervention=pico_raw.get("intervention"), comparator=pico_raw.get("comparator"), outcome=pico_raw.get("outcome"), primary_outcome=pico_raw.get("primary_outcome")), stats=StatisticalData(sample_size=stats_raw.get("sample_size"), p_value=str(stats_raw["p_value"]) if stats_raw.get("p_value") is not None else None, effect_size=stats_raw.get("effect_size"), confidence_interval=stats_raw.get("confidence_interval"), nnt_nnh=stats_raw.get("nnt_nnh"), clinical_significance=stats_raw.get("clinical_significance")), appraisal=AppraisalData(evidence_strength=appraisal_raw.get("evidence_strength"), evidence_explanation=appraisal_raw.get("evidence_explanation"), bias_risk=appraisal_raw.get("bias_risk"), limitations=appraisal_raw.get("limitations") or []), rewrites=RewritesData(patient=rewrites_raw.get("patient"), clinician=rewrites_raw.get("clinician"), student=rewrites_raw.get("student")), key_claims=key_claims, jargon=jargon_items, cached=False)


@router.get("/ai/clinical/{study_id}", response_model=AIClinicalResponse)
def get_clinical(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    study = session.get(Study, study_id)
    if not study: raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed")
    from backend.models import StudyMetrics
    m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()
    ck = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "clinical") & (AIResult.patient_summary != None))).first()  # noqa: E711
    if not m and not cached:
        raise HTTPException(status_code=404, detail="No clinical analysis found for this study. Run POST /ai/clinical first.")
    pico_raw = {}; stats_raw = {}; appraisal_raw = {}; key_claims = []; jargon_raw = []
    if cached:
        try:
            raw_q = json.loads(cached.question or "{}")
            if "pico" in raw_q:
                pico_raw = raw_q.get("pico", {}); stats_raw = raw_q.get("stats", {}); appraisal_raw = raw_q.get("appraisal", {}); key_claims = raw_q.get("key_claims", []); jargon_raw = raw_q.get("jargon", [])
            else:
                pico_raw = raw_q
            if not stats_raw: stats_raw = json.loads(cached.summary or "{}")
        except Exception: pass
    jargon_items = [JargonItem(term=j.get("term", ""), definition=j.get("definition", "")) for j in jargon_raw if isinstance(j, dict)]
    return AIClinicalResponse(study_id=study_id, pico=PICOData(population=pico_raw.get("population"), intervention=pico_raw.get("intervention"), comparator=pico_raw.get("comparator"), outcome=pico_raw.get("outcome"), primary_outcome=pico_raw.get("primary_outcome")), stats=StatisticalData(sample_size=stats_raw.get("sample_size"), p_value=stats_raw.get("p_value"), effect_size=stats_raw.get("effect_size"), confidence_interval=stats_raw.get("confidence_interval"), nnt_nnh=stats_raw.get("nnt_nnh"), clinical_significance=stats_raw.get("clinical_significance")), appraisal=AppraisalData(evidence_strength=appraisal_raw.get("evidence_strength") or (m.evidence_strength if m else None), evidence_explanation=appraisal_raw.get("evidence_explanation"), bias_risk=appraisal_raw.get("bias_risk") or (m.risk_of_bias if m else None), limitations=appraisal_raw.get("limitations") or []), rewrites=RewritesData(patient=cached.patient_summary if cached else None, clinician=cached.clinician_summary if cached else None, student=cached.student_summary if cached else None), key_claims=key_claims, jargon=jargon_items, cached=True)


@router.post("/ai/clinical/{study_id}/share")
def create_share_link(study_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    import uuid
    study = session.get(Study, study_id)
    if not study: raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed")
    ck = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
    cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "clinical"))).first()
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
    owner_studies = session.exec(select(Study).where(Study.owner_username == cached.owner_username)).all()
    title = "Untitled"; study_id = None
    for s in owner_studies:
        ck = _cache_key("clinical", s.title, s.doi, s.pmid, s.pmcid)
        if ck == cached.cache_key:
            title = s.title; study_id = s.id; break
    pico_raw = {}; stats_raw = {}; appraisal_raw = {}; key_claims = []; jargon_raw = []
    try:
        raw_q = json.loads(cached.question or "{}")
        if "pico" in raw_q:
            pico_raw = raw_q.get("pico", {}); stats_raw = raw_q.get("stats", {}); appraisal_raw = raw_q.get("appraisal", {}); key_claims = raw_q.get("key_claims", []); jargon_raw = raw_q.get("jargon", [])
        else:
            pico_raw = raw_q; stats_raw = json.loads(cached.summary or "{}")
    except Exception: pass
    m = None
    if study_id:
        m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()
    return {"title": title, "pico": pico_raw, "stats": stats_raw, "appraisal": {"evidence_strength": appraisal_raw.get("evidence_strength") or (m.evidence_strength if m else None), "evidence_explanation": appraisal_raw.get("evidence_explanation"), "bias_risk": appraisal_raw.get("bias_risk") or (m.risk_of_bias if m else None), "limitations": appraisal_raw.get("limitations") or []}, "rewrites": {"patient": cached.patient_summary, "clinician": cached.clinician_summary, "student": cached.student_summary}, "key_claims": key_claims, "jargon": jargon_raw, "is_retracted": False}

# ── Phase 4 helpers ───────────────────────────────────────────────────────────

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
- steel_man: the strongest possible counter-argument to the weighted_conclusion
- comparative_methodology: comparison of study designs, sample sizes, populations across papers
Return JSON only. No markdown fences."""


def _build_synthesis_context(studies, clinical_data):
    papers = []
    for i, study in enumerate(studies, 1):
        cd = clinical_data.get(study.id, {})
        pico = cd.get("pico", {})
        block = f"Paper {i}: {study.title}"
        if study.year: block += f" ({study.year})"
        if study.study_type: block += f" [{study.study_type.replace('_', ' ').title()}]"
        block += "\n"
        if study.abstract: block += f"Abstract: {strip_html(study.abstract)[:600]}\n"
        if pico.get("population"): block += f"Population: {pico['population']}\n"
        if pico.get("intervention"): block += f"Intervention: {pico['intervention']}\n"
        if pico.get("outcome"): block += f"Outcome: {pico['outcome']}\n"
        stats = cd.get("stats", {})
        if stats.get("effect_size"): block += f"Effect size: {stats['effect_size']}\n"
        if stats.get("p_value"): block += f"P-value: {stats['p_value']}\n"
        papers.append(block)
    return "\n---\n".join(papers)


def _build_weighting(studies):
    total = 0.0
    weights = []
    for s in studies:
        score, recency = _compute_evidence_weight(s.study_type, s.year)
        weights.append({"study_id": s.id, "study_title": s.title[:60] + ("…" if len(s.title) > 60 else ""), "study_type": s.study_type, "year": s.year, "base_score": EVIDENCE_WEIGHTS.get((s.study_type or "other").lower().replace(" ", "_"), 1.0), "recency_bonus": recency, "final_score": score, "weight_pct": 0.0})
        total += score
    if total > 0:
        for w in weights: w["weight_pct"] = round((w["final_score"] / total) * 100, 1)
    return weights


def _parse_synthesis_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _build_synthesis_response(rec, study_ids, cached):
    def _parse(field):
        try: return json.loads(field or "[]")
        except: return []
    consensus = [ConsensusPoint(finding=c.get("finding",""), supporting_studies=c.get("supporting_studies",[]), strength=c.get("strength")) for c in _parse(rec.consensus_points) if isinstance(c, dict)]
    contradictions = [ContradictionItem(issue=c.get("issue",""), side_a_studies=c.get("side_a_studies",[]), side_a_position=c.get("side_a_position",""), side_b_studies=c.get("side_b_studies",[]), side_b_position=c.get("side_b_position",""), likely_explanation=c.get("likely_explanation")) for c in _parse(rec.contradictions) if isinstance(c, dict)]
    weighting = [WeightingItem(study_title=w.get("study_title",""), study_type=w.get("study_type"), year=w.get("year"), base_score=w.get("base_score",1.0), recency_bonus=w.get("recency_bonus",False), final_score=w.get("final_score",1.0), weight_pct=w.get("weight_pct",0.0)) for w in _parse(rec.weighting_breakdown) if isinstance(w, dict)]
    gaps = _parse(rec.gap_analysis)
    return AISynthesisResponse(synthesis_id=rec.id or 0, study_ids=study_ids, paper_count=rec.paper_count, synthesis_narrative=rec.synthesis_narrative, consensus_points=consensus, contradictions=contradictions, gap_analysis=gaps if isinstance(gaps, list) else [], weighted_conclusion=rec.weighted_conclusion, steel_man=rec.steel_man, comparative_methodology=rec.comparative_methodology, weighting_breakdown=weighting, cached=cached, prompt_version=rec.prompt_version)

# ── Phase 4: Multi-Paper Synthesis endpoint ───────────────────────────────────

@router.post("/ai/synthesise", response_model=AISynthesisResponse)
async def ai_synthesise(payload: AISynthesisRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """Multi-paper evidence synthesis. Accepts 2-10 study IDs from the user's library."""
    if len(payload.study_ids) < 2: raise HTTPException(status_code=400, detail="At least 2 studies required.")
    if len(payload.study_ids) > 10: raise HTTPException(status_code=400, detail="Maximum 10 studies per synthesis.")
    studies = []
    for sid in payload.study_ids:
        study = session.get(Study, sid)
        if not study: raise HTTPException(status_code=404, detail=f"Study {sid} not found.")
        if study.owner_username != current_user.username: raise HTTPException(status_code=403, detail=f"Study {sid} not accessible.")
        studies.append(study)
    ck = _synthesis_cache_key(payload.study_ids)
    cached = session.exec(select(SynthesisResult).where((SynthesisResult.owner_username == current_user.username) & (SynthesisResult.cache_key == ck))).first()
    if cached and cached.synthesis_narrative:
        return _build_synthesis_response(cached, payload.study_ids, cached=True)
    clinical_data = {}
    for study in studies:
        study_ck = _cache_key("clinical", study.title, study.doi, study.pmid, study.pmcid)
        ai_rec = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == study_ck) & (AIResult.kind == "clinical"))).first()
        if ai_rec and ai_rec.question:
            try: clinical_data[study.id] = json.loads(ai_rec.question)
            except Exception: pass
    weighting = _build_weighting(studies)
    weight_ctx = "\n".join([f"  - {w['study_title']} ({w['study_type'] or 'unknown'}, {w['year'] or '?'}): weight {w['weight_pct']}%" for w in weighting])
    paper_ctx = _build_synthesis_context(studies, clinical_data)
    user_msg = f"Synthesise the following {len(studies)} research papers.\n\nEvidence weighting:\n{weight_ctx}\n\nPapers:\n{paper_ctx}"
    byok = _get_byok_keys(current_user)
    result = await engine_run(_SYNTHESIS_SYSTEM, user_msg, **byok)
    try:
        data = _parse_synthesis_json(result.text)
    except json.JSONDecodeError as exc:
        logger.error("Synthesis AI JSON parse failed: %s\nRaw: %s", exc, result.text[:500])
        raise HTTPException(status_code=502, detail="AI returned malformed JSON. Try again or use a BYOK key.")
    try:
        rec = SynthesisResult(owner_username=current_user.username, cache_key=ck, study_ids=json.dumps(sorted(payload.study_ids)), mode="multi_paper", synthesis_narrative=data.get("synthesis_narrative"), consensus_points=json.dumps(data.get("consensus_points") or []), contradictions=json.dumps(data.get("contradictions") or []), gap_analysis=json.dumps(data.get("gap_analysis") or []), weighted_conclusion=data.get("weighted_conclusion"), steel_man=data.get("steel_man"), comparative_methodology=data.get("comparative_methodology"), weighting_breakdown=json.dumps(weighting), prompt_version="4.0", model_used=result.provider.value, paper_count=len(studies))
        session.add(rec)
        session.commit()
        session.refresh(rec)
        return _build_synthesis_response(rec, payload.study_ids, cached=False)
    except Exception as e:
        logger.warning("SynthesisResult cache write failed (non-fatal): %s", e)
        # Return without DB ID
        dummy = SynthesisResult(id=0, owner_username=current_user.username, cache_key=ck, study_ids=json.dumps(sorted(payload.study_ids)), mode="multi_paper", synthesis_narrative=data.get("synthesis_narrative"), consensus_points=json.dumps(data.get("consensus_points") or []), contradictions=json.dumps(data.get("contradictions") or []), gap_analysis=json.dumps(data.get("gap_analysis") or []), weighted_conclusion=data.get("weighted_conclusion"), steel_man=data.get("steel_man"), comparative_methodology=data.get("comparative_methodology"), weighting_breakdown=json.dumps(weighting), prompt_version="4.0", model_used=result.provider.value, paper_count=len(studies))
        return _build_synthesis_response(dummy, payload.study_ids, cached=False)


@router.get("/ai/synthesise/{synthesis_id}", response_model=AISynthesisResponse)
def get_synthesis(synthesis_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    rec = session.get(SynthesisResult, synthesis_id)
    if not rec: raise HTTPException(status_code=404, detail="Synthesis not found.")
    if rec.owner_username != current_user.username: raise HTTPException(status_code=403, detail="Not allowed.")
    study_ids = json.loads(rec.study_ids or "[]")
    return _build_synthesis_response(rec, study_ids, cached=True)

# ── Phase 4: Subject Query ────────────────────────────────────────────────────

@router.post("/ai/subject-query", response_model=AISubjectQueryResponse)
async def ai_subject_query(payload: AISubjectQueryRequest, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """General subject query mode — auto-retrieves papers and synthesises them."""
    ck = _subject_query_cache_key(payload.query, payload.source)
    cached = session.exec(select(SynthesisResult).where((SynthesisResult.owner_username == current_user.username) & (SynthesisResult.cache_key == ck) & (SynthesisResult.mode == "subject_query"))).first()
    if cached and cached.synthesis_narrative:
        resp = _build_synthesis_response(cached, [], cached=True)
        return AISubjectQueryResponse(synthesis_id=resp.synthesis_id, query=payload.query, papers_found=cached.paper_count, synthesis_narrative=resp.synthesis_narrative, consensus_points=resp.consensus_points, contradictions=resp.contradictions, gap_analysis=resp.gap_analysis, weighted_conclusion=resp.weighted_conclusion, steel_man=resp.steel_man, papers_used=[], cached=True)
    src = (payload.source or "europepmc").strip().lower()
    papers_raw = []
    try:
        from backend.external_providers import get_provider
        provider = get_provider(src)
        retrieved, _, _ = await provider.search(q=payload.query, limit=payload.max_papers)
        papers_raw = retrieved
    except Exception as e:
        logger.warning("Subject query auto-retrieval failed: %s", e)
    if not papers_raw:
        raise HTTPException(status_code=404, detail="No papers found for this query. Try different keywords or a different source.")
    papers_with_abstracts = [p for p in papers_raw if p.abstract and len(p.abstract) > 60] or papers_raw
    papers_to_use = papers_with_abstracts[:payload.max_papers]
    paper_blocks = []
    papers_used = []
    for i, p in enumerate(papers_to_use, 1):
        st = getattr(p, "study_type", None) or "unknown"
        block = f"Paper {i}: {p.title}" + (f" ({p.year})" if p.year else "") + f"\nAbstract: {strip_html(p.abstract or '')[:500]}"
        paper_blocks.append(block)
        papers_used.append({"title": p.title, "year": p.year, "source": p.source, "study_type": st, "doi": p.doi})
    user_msg = f"Clinical question: {payload.query}\n\nSynthesise the following {len(papers_to_use)} retrieved papers:\n\n" + "\n---\n".join(paper_blocks)
    byok = _get_byok_keys(current_user)
    result = await engine_run(_SYNTHESIS_SYSTEM, user_msg, **byok)
    try:
        data = _parse_synthesis_json(result.text)
    except json.JSONDecodeError as exc:
        logger.error("Subject query AI JSON parse failed: %s\nRaw: %s", exc, result.text[:500])
        raise HTTPException(status_code=502, detail="AI returned malformed JSON. Try again.")
    synthesis_id = 0
    try:
        rec = SynthesisResult(owner_username=current_user.username, cache_key=ck, study_ids=json.dumps([]), mode="subject_query", query=payload.query, synthesis_narrative=data.get("synthesis_narrative"), consensus_points=json.dumps(data.get("consensus_points") or []), contradictions=json.dumps(data.get("contradictions") or []), gap_analysis=json.dumps(data.get("gap_analysis") or []), weighted_conclusion=data.get("weighted_conclusion"), steel_man=data.get("steel_man"), comparative_methodology=data.get("comparative_methodology"), weighting_breakdown=json.dumps([]), prompt_version="4.0", model_used=result.provider.value, paper_count=len(papers_to_use))
        session.add(rec)
        session.commit()
        session.refresh(rec)
        synthesis_id = rec.id
    except Exception as e:
        logger.warning("SynthesisResult (subject query) cache write failed: %s", e)
    consensus = [ConsensusPoint(finding=c.get("finding",""), supporting_studies=c.get("supporting_studies",[]), strength=c.get("strength")) for c in (data.get("consensus_points") or []) if isinstance(c, dict)]
    contradictions = [ContradictionItem(issue=c.get("issue",""), side_a_studies=c.get("side_a_studies",[]), side_a_position=c.get("side_a_position",""), side_b_studies=c.get("side_b_studies",[]), side_b_position=c.get("side_b_position",""), likely_explanation=c.get("likely_explanation")) for c in (data.get("contradictions") or []) if isinstance(c, dict)]
    return AISubjectQueryResponse(synthesis_id=synthesis_id or 0, query=payload.query, papers_found=len(papers_to_use), synthesis_narrative=data.get("synthesis_narrative"), consensus_points=consensus, contradictions=contradictions, gap_analysis=data.get("gap_analysis") or [], weighted_conclusion=data.get("weighted_conclusion"), steel_man=data.get("steel_man"), papers_used=papers_used, cached=False)

# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/ai/health")
async def ai_health():
    from backend.services.ai_engine import health_check
    checks = await health_check()
    return {"status": "ok", "router": "ai", "providers": checks}