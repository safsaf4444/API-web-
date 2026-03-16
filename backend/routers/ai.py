from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.ai_secure import decrypt_api_key, encrypt_api_key, mask_key
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import AIResult, User
from backend.schemas import (
    AIAskRequest,
    AIAskResponse,
    AIKeySetRequest,
    AIKeyStatus,
    AISummarizeRequest,
    AISummarizeResponse,
)
from backend.services.ai_engine import run as engine_run
from backend.services.ai_service import strip_html
from backend.services.metrics_service import increment_ai_runs

router = APIRouter(tags=["ai"])


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


def _get_study_id_for_paper(session: Session, owner: str, doi: str | None, pmid: str | None) -> int | None:
    """Try to find the saved study_id for metrics wiring."""
    from backend.models import Study
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
        # Still increment — user is viewing the result
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

    # ── Wire hook ──────────────────────────────────────────────
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)

    return AISummarizeResponse(text=result.text)


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

    # ── Wire hook ──────────────────────────────────────────────
    _wire_ai_runs(session, current_user.username, payload.doi, payload.pmid)

    return AIAskResponse(text=result.text)


def _wire_ai_runs(session: Session, username: str, doi: str | None, pmid: str | None) -> None:
    """Safely increment ai_runs — never raises."""
    try:
        study_id = _get_study_id_for_paper(session, username, doi, pmid)
        if study_id:
            increment_ai_runs(session, study_id, username)
    except Exception:
        pass


@router.get("/ai/health")
async def ai_health():
    from backend.services.ai_engine import health_check
    checks = await health_check()
    return {"status": "ok", "router": "ai", "providers": checks}