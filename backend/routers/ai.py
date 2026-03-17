from __future__ import annotations

import hashlib
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from backend.ai_secure import decrypt_api_key, encrypt_api_key, mask_key
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import AIResult, Study, User
from backend.schemas import (
    AIAskRequest,
    AIAskResponse,
    AIClinicalRequest,
    AIClinicalResponse,
    AIKeySetRequest,
    AIKeyStatus,
    AISummarizeRequest,
    AISummarizeResponse,
    AppraisalData,
    PICOData,
    RewritesData,
    StatisticalData,
)
from backend.services.ai_engine import run as engine_run
from backend.services.ai_service import strip_html
from backend.services.metrics_service import increment_ai_runs, write_clinical_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])


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


def _get_byok_keys(user: User) -> dict:
    if not user.ai_key_enc:
        return {}
    try:
        key = decrypt_api_key(user.ai_key_enc)
    except Exception:
        return {}
    if key.startswith("sk-ant-"):
        return {"anthropic_key": key}
    if key.startswith("AIza"):
        return {"gemini_key": key}
    if key.startswith("gsk_"):
        return {"groq_key": key}
    return {"openai_key": key}


def _get_study_id_for_paper(
    session: Session, owner: str, doi: str | None, pmid: str | None
) -> int | None:
    if doi:
        s = session.exec(
            select(Study).where(
                (Study.owner_username == owner) & (Study.doi == doi.strip())
            )
        ).first()
        if s:
            return s.id
    if pmid:
        s = session.exec(
            select(Study).where(
                (Study.owner_username == owner) & (Study.pmid == pmid.strip())
            )
        ).first()
        if s:
            return s.id
    return None


def _wire_ai_runs(
    session: Session, username: str, doi: str | None, pmid: str | None
) -> None:
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
def ai_set_key(
    payload: AIKeySetRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    k = (payload.api_key or "").strip()
    if not k or len(k) < 20:
        raise HTTPException(status_code=400, detail="Invalid API key format.")
    current_user.ai_key_enc = encrypt_api_key(k)
    session.add(current_user)
    session.commit()
    return {"status": "ok"}


@router.delete("/ai/clear_key")
def ai_clear_key(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    current_user.ai_key_enc = None
    session.add(current_user)
    session.commit()
    return {"status": "cleared"}


# ── Summarize (standard) ──────────────────────────────────────────────────────

@router.post("/ai/summarize", response_model=AISummarizeResponse)
async def ai_summarize(
    payload: AISummarizeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ck = _cache_key("summarize", payload.title, payload.doi, payload.pmid, payload.pmcid)

    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "summarize")
        )
    ).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AISummarizeResponse(text=cached.summary)

    system = (
        "You are a careful medical evidence assistant. "
        "Write in clear plain English. Use short headings and bullet points. "
        "Do not invent results. If info is missing, say so."
    )
    user_msg = (
        f"Summarize this paper.\n\n"
        f"Title: {payload.title}\n"
        f"Venue: {payload.venue or 'n/a'}\n"
        f"Year: {payload.year or 'n/a'}\n"
        f"PMID: {payload.pmid or 'n/a'}\n"
        f"PMCID: {payload.pmcid or 'n/a'}\n"
        f"DOI: {payload.doi or 'n/a'}\n\n"
        f"Abstract:\n{strip_html(payload.abstract or '')}"
    )

    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)

    rec = AIResult(
        owner_username=current_user.username,
        cache_key=ck,
        kind="summarize",
        model_used=result.provider.value,
        summary=result.text,
    )
    session.add(rec)
    session.commit()

    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AISummarizeResponse(text=result.text)


# ── Summarize (streaming) ─────────────────────────────────────────────────────

@router.post("/ai/summarize/stream")
async def ai_summarize_stream(
    payload: AISummarizeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events stream of the summary.
    Frontend connects with EventSource or fetch+ReadableStream.
    Each chunk is: data: <token>\n\n
    Final message:  data: [DONE]\n\n
    """
    ck = _cache_key("summarize", payload.title, payload.doi, payload.pmid, payload.pmcid)

    # Serve cached result as a single fast chunk if available
    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "summarize")
        )
    ).first()

    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)

        async def _cached_stream() -> AsyncGenerator[str, None]:
            # Stream cached text in ~80-char chunks so the UI still animates
            text = cached.summary
            chunk_size = 80
            for i in range(0, len(text), chunk_size):
                yield f"data: {json.dumps(text[i:i+chunk_size])}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_cached_stream(), media_type="text/event-stream")

    system = (
        "You are a careful medical evidence assistant. "
        "Write in clear plain English. Use short headings and bullet points. "
        "Do not invent results. If info is missing, say so."
    )
    user_msg = (
        f"Summarize this paper.\n\n"
        f"Title: {payload.title}\n"
        f"Venue: {payload.venue or 'n/a'}\n"
        f"Year: {payload.year or 'n/a'}\n"
        f"PMID: {payload.pmid or 'n/a'}\n"
        f"PMCID: {payload.pmcid or 'n/a'}\n"
        f"DOI: {payload.doi or 'n/a'}\n\n"
        f"Abstract:\n{strip_html(payload.abstract or '')}"
    )

    byok = _get_byok_keys(current_user)
    full_text: list[str] = []

    async def _live_stream() -> AsyncGenerator[str, None]:
        nonlocal full_text
        provider_used = "unknown"

        try:
            chunks = await _stream_from_provider(system, user_msg, byok)
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

        # Persist to cache after stream completes
        assembled = "".join(full_text)
        if assembled:
            try:
                rec = AIResult(
                    owner_username=current_user.username,
                    cache_key=ck,
                    kind="summarize",
                    model_used=provider_used,
                    summary=assembled,
                )
                session.add(rec)
                session.commit()
                _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
            except Exception as e:
                logger.warning("Stream cache write failed (non-fatal): %s", e)

        yield "data: [DONE]\n\n"

    return StreamingResponse(_live_stream(), media_type="text/event-stream")


async def _stream_from_provider(
    system: str, user_msg: str, byok: dict
) -> AsyncGenerator[dict, None]:
    """
    Thin streaming layer. Tries BYOK first, then free-tier OpenAI-compatible
    providers. Each yielded dict is either {"text": str} or {"provider": str}.
    Falls back to non-streaming engine_run if provider doesn't support streaming.
    """
    import httpx
    import os

    openai_key = byok.get("openai_key")
    anthropic_key = byok.get("anthropic_key")
    gemini_key = byok.get("gemini_key")
    groq_key = byok.get("groq_key")

    # ── OpenAI streaming ──────────────────────────────────────────────────────
    if openai_key:
        yield {"provider": "openai"}
        async for chunk in _openai_stream(openai_key, system, user_msg):
            yield chunk
        return

    # ── Anthropic streaming ───────────────────────────────────────────────────
    if anthropic_key:
        yield {"provider": "anthropic"}
        async for chunk in _anthropic_stream(anthropic_key, system, user_msg):
            yield chunk
        return

    # ── Groq streaming (OpenAI-compatible) ───────────────────────────────────
    groq_free = os.getenv("GROQ_API_KEY", "").strip()
    active_groq = groq_key or groq_free
    if active_groq:
        yield {"provider": "groq"}
        async for chunk in _openai_stream(
            active_groq,
            system,
            user_msg,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
        ):
            yield chunk
        return

    # ── Gemini fallback (non-streaming, wrapped) ──────────────────────────────
    gemini_free = os.getenv("GEMINI_API_KEY", "").strip()
    active_gemini = gemini_key or gemini_free
    if active_gemini:
        yield {"provider": "gemini"}
        from backend.services.ai_engine import _call_gemini
        model = "gemini-1.5-pro" if gemini_key else "gemini-1.5-flash"
        text = await _call_gemini(active_gemini, system, user_msg, model=model)
        # Simulate streaming in ~60 char chunks
        for i in range(0, len(text), 60):
            yield {"text": text[i:i+60]}
        return

    raise HTTPException(
        status_code=400,
        detail="No AI provider configured. Add a BYOK key or set GEMINI_API_KEY/GROQ_API_KEY.",
    )


async def _openai_stream(
    api_key: str,
    system: str,
    user: str,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
) -> AsyncGenerator[dict, None]:
    import httpx
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": 0.3,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code == 401:
                raise HTTPException(status_code=401, detail="API key rejected.")
            if r.status_code == 429:
                raise HTTPException(status_code=429, detail="Rate limit hit.")
            if r.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"AI error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield {"text": delta}
                except Exception:
                    continue


async def _anthropic_stream(
    api_key: str, system: str, user: str
) -> AsyncGenerator[dict, None]:
    import httpx
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 1024,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code == 401:
                raise HTTPException(status_code=401, detail="Anthropic key rejected.")
            if r.status_code == 429:
                raise HTTPException(status_code=429, detail="Anthropic rate limit hit.")
            if r.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"Anthropic error {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                try:
                    obj = json.loads(data)
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta", {}).get("text", "")
                        if delta:
                            yield {"text": delta}
                except Exception:
                    continue


# ── Ask ───────────────────────────────────────────────────────────────────────

@router.post("/ai/ask", response_model=AIAskResponse)
async def ai_ask(
    payload: AIAskRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ck = _cache_key("ask", payload.title, payload.doi, payload.pmid, payload.pmcid, payload.question)

    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "ask")
        )
    ).first()
    if cached and cached.summary:
        _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
        return AIAskResponse(text=cached.summary)

    system = (
        "You are a medical evidence assistant. "
        "Answer the user's question using ONLY the provided title/abstract context. "
        "If the abstract doesn't contain the answer, say what is missing and what to look for. "
        "Use concise bullet points when helpful."
    )
    user_msg = (
        f"Question: {payload.question}\n\n"
        f"Paper:\n"
        f"Title: {payload.title}\n"
        f"Venue: {payload.venue or 'n/a'}\n"
        f"Year: {payload.year or 'n/a'}\n"
        f"PMID: {payload.pmid or 'n/a'}\n"
        f"PMCID: {payload.pmcid or 'n/a'}\n"
        f"DOI: {payload.doi or 'n/a'}\n\n"
        f"Abstract:\n{strip_html(payload.abstract or '')}"
    )

    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)

    rec = AIResult(
        owner_username=current_user.username,
        cache_key=ck,
        kind="ask",
        model_used=result.provider.value,
        question=payload.question,
        summary=result.text,
    )
    session.add(rec)
    session.commit()

    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)
    return AIAskResponse(text=result.text)


# ── Phase 3: Clinical Intelligence ───────────────────────────────────────────

_CLINICAL_SYSTEM = """You are a senior clinical evidence appraiser.
Analyze the provided abstract and title. Return a valid JSON object with exactly these keys:
{
  "pico": {"population": str, "intervention": str, "comparator": str, "outcome": str},
  "stats": {"sample_size": int_or_null, "p_value": str_or_null, "effect_size": str_or_null, "confidence_interval": str_or_null, "nnt_nnh": str_or_null},
  "appraisal": {"evidence_strength": int_1_to_5, "bias_risk": "Low"|"Moderate"|"High", "limitations": [str]},
  "rewrites": {"patient": str, "clinician": str, "student": str}
}
Return JSON only. No prose, no markdown fences, no keys outside this structure.
If a value cannot be determined from the abstract, use null."""


@router.post("/ai/clinical", response_model=AIClinicalResponse)
async def ai_clinical(
    payload: AIClinicalRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, payload.study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    ck = _cache_key("clinical", payload.title, payload.doi, payload.pmid, payload.pmcid)

    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "clinical")
        )
    ).first()

    if cached and cached.patient_summary:
        return AIClinicalResponse(
            study_id=payload.study_id,
            pico=PICOData(**(json.loads(cached.question) if cached.question else {})),
            stats=StatisticalData(**(json.loads(cached.summary) if cached.summary else {})),
            appraisal=AppraisalData(),
            rewrites=RewritesData(
                patient=cached.patient_summary,
                clinician=cached.clinician_summary,
                student=cached.student_summary,
            ),
            cached=True,
        )

    user_msg = (
        f"Title: {payload.title}\n"
        f"Abstract: {strip_html(payload.abstract or 'No abstract provided.')}"
    )

    byok = _get_byok_keys(current_user)
    result = await engine_run(_CLINICAL_SYSTEM, user_msg, **byok)

    raw = result.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Clinical AI JSON parse failed: %s\nRaw: %s", exc, raw[:500])
        raise HTTPException(
            status_code=502,
            detail="AI returned malformed JSON. Try again or use a BYOK key for more reliable extraction.",
        )

    pico_raw      = data.get("pico", {}) or {}
    stats_raw     = data.get("stats", {}) or {}
    appraisal_raw = data.get("appraisal", {}) or {}
    rewrites_raw  = data.get("rewrites", {}) or {}

    try:
        write_clinical_data(
            session=session,
            study_id=payload.study_id,
            owner_username=current_user.username,
            pico_data=pico_raw,
            statistical_data=stats_raw,
            evidence_strength=appraisal_raw.get("evidence_strength"),
            risk_of_bias=appraisal_raw.get("bias_risk"),
        )
    except Exception as e:
        logger.warning("write_clinical_data failed (non-fatal): %s", e)

    try:
        rec = AIResult(
            owner_username=current_user.username,
            cache_key=ck,
            kind="clinical",
            model_used=result.provider.value,
            prompt_version="3.0",
            question=json.dumps(pico_raw),
            summary=json.dumps(stats_raw),
            patient_summary=rewrites_raw.get("patient"),
            clinician_summary=rewrites_raw.get("clinician"),
            student_summary=rewrites_raw.get("student"),
        )
        session.add(rec)
        session.commit()
    except Exception as e:
        logger.warning("AIResult cache write failed (non-fatal): %s", e)

    try:
        increment_ai_runs(session, payload.study_id, current_user.username)
    except Exception:
        pass

    return AIClinicalResponse(
        study_id=payload.study_id,
        pico=PICOData(
            population=pico_raw.get("population"),
            intervention=pico_raw.get("intervention"),
            comparator=pico_raw.get("comparator"),
            outcome=pico_raw.get("outcome"),
        ),
        stats=StatisticalData(
            sample_size=stats_raw.get("sample_size"),
            p_value=str(stats_raw["p_value"]) if stats_raw.get("p_value") is not None else None,
            effect_size=stats_raw.get("effect_size"),
            confidence_interval=stats_raw.get("confidence_interval"),
            nnt_nnh=stats_raw.get("nnt_nnh"),
        ),
        appraisal=AppraisalData(
            evidence_strength=appraisal_raw.get("evidence_strength"),
            bias_risk=appraisal_raw.get("bias_risk"),
            limitations=appraisal_raw.get("limitations") or [],
        ),
        rewrites=RewritesData(
            patient=rewrites_raw.get("patient"),
            clinician=rewrites_raw.get("clinician"),
            student=rewrites_raw.get("student"),
        ),
        cached=False,
    )


# ── GET saved clinical data ───────────────────────────────────────────────────

@router.get("/ai/clinical/{study_id}", response_model=AIClinicalResponse)
def get_clinical(
    study_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve previously saved clinical intelligence for a study
    without re-running the AI. Returns 404 if not yet run.
    """
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    from backend.models import StudyMetrics
    m = session.exec(
        select(StudyMetrics).where(StudyMetrics.study_id == study_id)
    ).first()

    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.kind == "clinical")
            & (AIResult.patient_summary != None)  # noqa: E711
        )
    ).first()

    if not m and not cached:
        raise HTTPException(
            status_code=404,
            detail="No clinical analysis found for this study. Run POST /ai/clinical first.",
        )

    pico_raw  = {}
    stats_raw = {}

    if cached:
        try:
            pico_raw  = json.loads(cached.question or "{}")
            stats_raw = json.loads(cached.summary or "{}")
        except Exception:
            pass

    return AIClinicalResponse(
        study_id=study_id,
        pico=PICOData(
            population=pico_raw.get("population"),
            intervention=pico_raw.get("intervention"),
            comparator=pico_raw.get("comparator"),
            outcome=pico_raw.get("outcome"),
        ),
        stats=StatisticalData(
            sample_size=stats_raw.get("sample_size"),
            p_value=stats_raw.get("p_value"),
            effect_size=stats_raw.get("effect_size"),
            confidence_interval=stats_raw.get("confidence_interval"),
            nnt_nnh=stats_raw.get("nnt_nnh"),
        ),
        appraisal=AppraisalData(
            evidence_strength=m.evidence_strength if m else None,
            bias_risk=m.risk_of_bias if m else None,
        ),
        rewrites=RewritesData(
            patient=cached.patient_summary if cached else None,
            clinician=cached.clinician_summary if cached else None,
            student=cached.student_summary if cached else None,
        ),
        cached=True,
    )


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/ai/health")
async def ai_health():
    from backend.services.ai_engine import health_check
    checks = await health_check()
    return {"status": "ok", "router": "ai", "providers": checks}