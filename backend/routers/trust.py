"""
Trust & Validity REST API endpoints.

All routes require authentication. Role-gated routes additionally require
the "trust_reviewer" or "admin" role (enforced via require_role dependency).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user, require_role
from backend.models import User
from backend.models_trust import (
    AIRun,
    AuditLog,
    Claim,
    EvidenceSpan,
    FeatureFlag,
    TrustAlert,
    UserRole,
    VerificationRecord,
)
from backend.schemas_trust import (
    AIRunRead,
    AuditLogQuery,
    AuditLogRead,
    ClaimRead,
    EvidenceSpanRead,
    FeatureFlagRead,
    FeatureFlagSet,
    ProvenanceResponse,
    TrustAlertDismiss,
    TrustAlertRead,
    UserRoleGrant,
    UserRoleRead,
    VerificationCreate,
    VerificationRead,
)
from backend.services import audit_service, trust_service
from backend.core.feature_flags import invalidate_flag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trust", tags=["trust"])


# ── AIRun ─────────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=List[AIRunRead])
def list_ai_runs(
    study_id: Optional[int] = Query(default=None),
    review_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(AIRun)
        .where(AIRun.owner_username == current_user.username)
        .order_by(AIRun.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if study_id is not None:
        stmt = stmt.where(AIRun.study_id == study_id)
    if review_id is not None:
        stmt = stmt.where(AIRun.review_id == review_id)
    return list(session.exec(stmt).all())


@router.get("/runs/{run_id}", response_model=AIRunRead)
def get_ai_run(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = session.get(AIRun, run_id)
    if not run or run.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="AIRun not found")
    return run


# ── Provenance bundle ─────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/provenance", response_model=ProvenanceResponse)
def get_provenance(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = session.get(AIRun, run_id)
    if not run or run.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="AIRun not found")

    bundle = trust_service.get_provenance(session, run_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Provenance not found")
    return bundle


# ── Evidence spans ────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/spans", response_model=List[EvidenceSpanRead])
def list_spans(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = session.get(AIRun, run_id)
    if not run or run.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="AIRun not found")
    return list(session.exec(select(EvidenceSpan).where(EvidenceSpan.ai_run_id == run_id)).all())


# ── Claims ────────────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/claims", response_model=List[ClaimRead])
def list_claims(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = session.get(AIRun, run_id)
    if not run or run.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="AIRun not found")
    return list(session.exec(select(Claim).where(Claim.ai_run_id == run_id)).all())


# ── Verification (human sign-off) ─────────────────────────────────────────────

@router.post("/claims/{claim_id}/verify", response_model=VerificationRead)
def verify_claim(
    claim_id: int,
    payload: VerificationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("trust_reviewer")),
):
    claim = session.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    try:
        rec = trust_service.verify_claim(
            session,
            claim_id=claim_id,
            verifier_username=current_user.username,
            decision=payload.decision,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return rec


@router.get("/claims/{claim_id}/verifications", response_model=List[VerificationRead])
def list_verifications(
    claim_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list(
        session.exec(select(VerificationRecord).where(VerificationRecord.claim_id == claim_id)).all()
    )


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.post("/audit/query", response_model=List[AuditLogRead])
def query_audit(
    query: AuditLogQuery,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("trust_reviewer")),
):
    return audit_service.query_trail(
        session,
        actor=query.actor,
        event=query.event,
        study_id=query.study_id,
        review_id=query.review_id,
        ai_run_id=query.ai_run_id,
        limit=query.limit,
        offset=query.offset,
    )


@router.get("/audit/my", response_model=List[AuditLogRead])
def my_audit_trail(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return audit_service.query_trail(
        session,
        actor=current_user.username,
        limit=limit,
        offset=offset,
    )


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts", response_model=List[TrustAlertRead])
def list_alerts(
    dismissed: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(TrustAlert)
        .where(TrustAlert.owner_username == current_user.username)
        .where(TrustAlert.is_dismissed == dismissed)
        .order_by(TrustAlert.id.desc())
    )
    return list(session.exec(stmt).all())


@router.post("/alerts/dismiss")
def dismiss_alert(
    payload: TrustAlertDismiss,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    alert = session.get(TrustAlert, payload.alert_id)
    if not alert or alert.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_dismissed = True
    session.add(alert)
    session.commit()
    return {"status": "dismissed"}


# ── Feature flags (admin only) ────────────────────────────────────────────────

@router.get("/flags", response_model=List[FeatureFlagRead])
def list_flags(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    return list(session.exec(select(FeatureFlag)).all())


@router.post("/flags", response_model=FeatureFlagRead)
def set_flag(
    payload: FeatureFlagSet,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    row = session.exec(select(FeatureFlag).where(FeatureFlag.name == payload.name)).first()
    if row is None:
        row = FeatureFlag(name=payload.name, is_enabled=payload.is_enabled)
        if payload.description:
            row.description = payload.description
    else:
        row.is_enabled = payload.is_enabled
        if payload.description is not None:
            row.description = payload.description

    session.add(row)
    session.commit()
    session.refresh(row)
    invalidate_flag(payload.name)

    audit_service.log(
        session,
        event="feature_flag.set",
        actor=current_user.username,
        detail=f"flag={payload.name} enabled={payload.is_enabled}",
    )
    return row


# ── User roles (admin only) ───────────────────────────────────────────────────

@router.get("/roles", response_model=List[UserRoleRead])
def list_roles(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    return list(session.exec(select(UserRole)).all())


@router.post("/roles", response_model=UserRoleRead)
def grant_role(
    payload: UserRoleGrant,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    existing = session.exec(
        select(UserRole)
        .where(UserRole.username == payload.username)
        .where(UserRole.role == payload.role)
    ).first()
    if existing:
        return existing

    role = UserRole(
        username=payload.username,
        role=payload.role,
        granted_by=current_user.username,
    )
    session.add(role)
    session.commit()
    session.refresh(role)

    audit_service.log(
        session,
        event="role.granted",
        actor=current_user.username,
        detail=f"username={payload.username} role={payload.role}",
    )
    return role


@router.delete("/roles/{role_id}")
def revoke_role(
    role_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    role = session.get(UserRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    session.delete(role)
    session.commit()
    audit_service.log(
        session,
        event="role.revoked",
        actor=current_user.username,
        detail=f"username={role.username} role={role.role}",
    )
    return {"status": "revoked"}
