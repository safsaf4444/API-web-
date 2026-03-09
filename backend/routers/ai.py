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

router = APIRouter(tags=["ai"])


def _cache_key(
    kind: str,
    title: str,
    doi: str | None,
    pmid: str | None,
    pmcid: str | None,
    question: str | None = None,
) -> str:
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
    """
    Decrypt and return whatever BYOK key the user has stored.
    Returns a dict ready to unpack into engine_run().
    If no key stored, returns empty dict — engine falls through to free tier.
    """
    if not user.ai_key_enc:
        return {}
    try:
        key = decrypt_api_key(user.ai_key_enc)
    except Exception:
        return {}

    # Detect key type by prefix
    if key.startswith("sk-ant-"):
        return {"anthropic_key": key}
    if key.startswith("AIza"):
        return {"gemini_key": key}
    if key.startswith("gsk_"):
        return {"groq_key": key}
    # Default: treat as OpenAI
    return {"openai_key": key}


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

    # Check cache first
    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "summarize")
        )
    ).first()
    if cached and cached.summary:
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

    # Route through engine — BYOK if set, free tier if not
    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)

    # Cache the result
    rec = AIResult(
        owner_username=current_user.username,
        cache_key=ck,
        kind="summarize",
        model_used=result.provider.value,
        summary=result.text,
    )
    session.add(rec)
    session.commit()

    return AISummarizeResponse(text=result.text)


@router.post("/ai/ask", response_model=AIAskResponse)
async def ai_ask(
    payload: AIAskRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ck = _cache_key("ask", payload.title, payload.doi, payload.pmid, payload.pmcid, payload.question)

    # Check cache first
    cached = session.exec(
        select(AIResult).where(
            (AIResult.owner_username == current_user.username)
            & (AIResult.cache_key == ck)
            & (AIResult.kind == "ask")
        )
    ).first()
    if cached and cached.summary:
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

    # Route through engine — BYOK if set, free tier if not
    byok = _get_byok_keys(current_user)
    result = await engine_run(system, user_msg, **byok)

    # Cache the result
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

    return AIAskResponse(text=result.text)


@router.get("/ai/health")
async def ai_health():
    from backend.services.ai_engine import health_check
    checks = await health_check()
    return {"status": "ok", "router": "ai", "providers": checks}