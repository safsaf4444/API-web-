"""
Trust service — AI run lifecycle and claim management.
Written against the actual models_trust.py schema.

Public API
----------
create_ai_run()    — open a new AIRun row (status="running")
complete_ai_run()  — close it with latency/evidence stats
fail_ai_run()      — mark as failed with failure_reason
record_claims()    — bulk-insert EvidenceSpan + Claim rows
get_provenance()   — return full provenance bundle for a given ai_run_id
verify_claim()     — record a human sign-off on a Claim row
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from backend.models_trust import (
    AIRun,
    AuditLog,
    Claim,
    EvidenceSpan,
    VerificationRecord,
    VerificationState,
)
from backend.services import audit_service

logger = logging.getLogger(__name__)


# ── Confidence ceilings by evidence basis ─────────────────────────────────────

_CONFIDENCE_CEILINGS: Dict[str, float] = {
    "rct":               0.95,
    "systematic_review": 0.90,
    "cohort":            0.80,
    "case_control":      0.75,
    "cross_sectional":   0.70,
    "case_report":       0.60,
    "expert_opinion":    0.55,
    "unknown":           0.50,
    "none":              0.50,
}


def _ceiling_for(basis: str) -> float:
    return _CONFIDENCE_CEILINGS.get((basis or "none").lower(), 0.50)


# ── Return type for verify_claim ──────────────────────────────────────────────

@dataclass
class VerifyResult:
    """Lightweight result returned by verify_claim."""
    claim_id: int
    decision: str   # "approved" | "rejected" | "needs_review"
    verifier_username: str
    notes: Optional[str]


# ── AI Run lifecycle ──────────────────────────────────────────────────────────

def create_ai_run(
    session: Session,
    *,
    owner_username: str,
    endpoint: str,          # maps to task_kind
    provider: str,
    model: str,             # maps to model_used
    study_id: Optional[int] = None,
    review_id: Optional[int] = None,
    prompt_version: str = "unknown",
    evidence_basis: str = "none",
) -> AIRun:
    study_ids_json = json.dumps([study_id]) if study_id else None

    run = AIRun(
        owner_username=owner_username,
        task_kind=endpoint,
        model_used=model,
        provider=provider,
        prompt_version=prompt_version,
        evidence_basis=evidence_basis,
        study_ids_json=study_ids_json,
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    audit_service.log(
        session,
        event="ai_run.created",
        actor=owner_username,
        ai_run_id=run.id,
        study_id=study_id,
        review_id=review_id,
        detail=f"endpoint={endpoint} provider={provider} model={model}",
    )
    return run


def complete_ai_run(
    session: Session,
    run: AIRun,
    *,
    latency_ms: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    evidence_basis: str = "none",
    trust_score: Optional[float] = None,   # accepted but not persisted (no column)
) -> AIRun:
    ceiling = _ceiling_for(evidence_basis)
    if trust_score is not None:
        trust_score = min(trust_score, ceiling)

    run.status = "completed"
    run.latency_ms = latency_ms
    run.input_token_est = input_tokens
    run.output_token_est = output_tokens
    run.evidence_basis = evidence_basis

    session.add(run)
    session.commit()
    session.refresh(run)

    audit_service.log(
        session,
        event="ai_run.completed",
        actor=run.owner_username,
        ai_run_id=run.id,
        detail=f"basis={evidence_basis} ceiling={ceiling} latency={latency_ms}ms",
    )
    return run


def fail_ai_run(
    session: Session,
    run: AIRun,
    *,
    error_message: str,
) -> AIRun:
    run.status = "failed"
    run.failure_reason = error_message[:2000]

    session.add(run)
    session.commit()
    session.refresh(run)

    audit_service.log(
        session,
        event="ai_run.failed",
        actor=run.owner_username,
        ai_run_id=run.id,
        detail=error_message[:500],
    )
    return run


# ── Claim + evidence span recording ──────────────────────────────────────────

def record_claims(
    session: Session,
    run: AIRun,
    *,
    spans: List[Dict[str, Any]],
) -> List[Claim]:
    """
    Insert EvidenceSpan + Claim pairs.

    Each item in `spans` expects:
        source_text  : str   — the excerpt from source (maps to span_text)
        claim_text   : str   — the assertion
        basis        : str   — evidence basis hint (stored on AIRun, not span)
        confidence   : float — raw confidence
        claim_type   : str   — factual | inferential | recommendation
        study_id     : Optional[int]
        span_start   : Optional[int]  → char_start
        span_end     : Optional[int]  → char_end
    """
    claims_out: List[Claim] = []
    span_ids: List[int] = []

    for item in spans:
        basis = item.get("basis", "none")
        ceiling = _ceiling_for(basis)
        raw_conf = float(item.get("confidence", 0.5))
        calibrated = round(min(raw_conf, ceiling), 4)

        span = EvidenceSpan(
            ai_run_id=run.id,
            study_id=item.get("study_id"),
            span_text=item.get("source_text", item.get("span_text", "")),
            char_start=item.get("span_start", item.get("char_start")),
            char_end=item.get("span_end", item.get("char_end")),
            confidence=calibrated,
        )
        session.add(span)
        session.flush()
        span_ids.append(span.id)

        claim = Claim(
            ai_run_id=run.id,
            owner_username=run.owner_username,
            claim_text=item.get("claim_text", ""),
            claim_type=item.get("claim_type", "extracted"),
            evidence_span_ids=json.dumps([span.id]),
            has_grounding=True,
            model_confidence=raw_conf,
            calibrated_conf=calibrated,
            verification_state=VerificationState.DRAFT,
        )
        session.add(claim)
        session.flush()
        claims_out.append(claim)

    session.commit()
    for c in claims_out:
        session.refresh(c)
        # Expose .verification_state as "pending" alias for DRAFT
        if c.verification_state == VerificationState.DRAFT:
            c.__dict__["_vs_alias"] = "pending"

    if claims_out:
        audit_service.log(
            session,
            event="claims.recorded",
            actor=run.owner_username,
            ai_run_id=run.id,
            detail=f"{len(claims_out)} claims recorded",
        )
    return claims_out


# ── Provenance bundle ─────────────────────────────────────────────────────────

def get_provenance(session: Session, ai_run_id: int) -> Dict[str, Any]:
    run = session.get(AIRun, ai_run_id)
    if run is None:
        return {}

    spans = list(session.exec(
        select(EvidenceSpan).where(EvidenceSpan.ai_run_id == ai_run_id)
    ).all())
    claims = list(session.exec(
        select(Claim).where(Claim.ai_run_id == ai_run_id)
    ).all())
    verifications = list(session.exec(
        select(VerificationRecord).where(VerificationRecord.ai_run_id == ai_run_id)
    ).all())
    audit_trail = audit_service.query_trail(session, ai_run_id=ai_run_id)

    return {
        "ai_run": run,
        "evidence_spans": spans,
        "claims": claims,
        "verifications": verifications,
        "audit_trail": audit_trail,
    }


# ── Human claim verification ──────────────────────────────────────────────────

def verify_claim(
    session: Session,
    *,
    claim_id: int,
    verifier_username: str,
    decision: str,
    notes: Optional[str] = None,
    prompt_version_locked: Optional[str] = None,
) -> VerifyResult:
    """
    Record a human sign-off on a Claim.

    decision must be "approved" | "rejected" | "needs_review".
    Updates Claim.verification_state and Claim.verified_by in-place.
    Returns a VerifyResult dataclass (not a DB model row).
    """
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ValueError(f"Claim {claim_id} not found")

    if decision not in ("approved", "rejected", "needs_review"):
        raise ValueError(f"Invalid decision: {decision!r}. Must be approved | rejected | needs_review")

    decision_to_state = {
        "approved":     VerificationState.VERIFIED,
        "rejected":     VerificationState.REJECTED,
        "needs_review": VerificationState.REVIEWED,
    }
    claim.verification_state = decision_to_state[decision]
    claim.verified_by = verifier_username
    claim.verified_at = datetime.now(timezone.utc)
    if decision == "rejected" and notes:
        claim.rejection_reason = notes

    session.add(claim)
    session.commit()
    session.refresh(claim)

    audit_service.log(
        session,
        event="claim.verified",
        actor=verifier_username,
        claim_id=claim_id,
        detail=f"decision={decision}",
    )

    return VerifyResult(
        claim_id=claim_id,
        decision=decision,
        verifier_username=verifier_username,
        notes=notes,
    )
