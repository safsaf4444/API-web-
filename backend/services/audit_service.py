"""
Append-only audit log writer.

INVARIANT: AuditLog rows are NEVER updated or deleted.
           This module enforces that invariant — never expose update/delete.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from backend.models_trust import AuditLog

logger = logging.getLogger(__name__)


def log(
    session: Session,
    *,
    event: str,
    actor: str,
    study_id: Optional[int] = None,
    ai_run_id: Optional[int] = None,
    review_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    verification_id: Optional[int] = None,
    detail: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditLog:
    """Write one immutable audit entry. Commits immediately.

    Parameters
    ----------
    session : open SQLModel session (caller owns the session lifecycle)
    event   : short dot-separated identifier, e.g. "ai_run.completed"
    actor   : username or "system"
    """
    entry = AuditLog(
        event=event,
        actor=actor,
        study_id=study_id,
        ai_run_id=ai_run_id,
        review_id=review_id,
        claim_id=claim_id,
        verification_id=verification_id,
        detail=detail,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    try:
        session.add(entry)
        session.commit()
        session.refresh(entry)
    except Exception as exc:
        logger.error("audit_service.log FAILED — event=%s actor=%s: %s", event, actor, exc)
        # Do NOT re-raise: audit failure must never crash the calling request.
    return entry


def query_trail(
    session: Session,
    *,
    actor: Optional[str] = None,
    event: Optional[str] = None,
    study_id: Optional[int] = None,
    review_id: Optional[int] = None,
    ai_run_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    """Return audit entries matching the given filters, newest-first."""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit)
    if actor is not None:
        stmt = stmt.where(AuditLog.actor == actor)
    if event is not None:
        stmt = stmt.where(AuditLog.event == event)
    if study_id is not None:
        stmt = stmt.where(AuditLog.study_id == study_id)
    if review_id is not None:
        stmt = stmt.where(AuditLog.review_id == review_id)
    if ai_run_id is not None:
        stmt = stmt.where(AuditLog.ai_run_id == ai_run_id)
    return list(session.exec(stmt).all())
