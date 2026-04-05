"""
run_with_trust() — drop-in wrapper around engine_run that adds the full
Trust & Validity pipeline:

  1. Pre-validate inputs
  2. Open AIRun row
  3. Call engine (engine_run / engine_run_vision)
  4. Post-validate output
  5. Run PolicyEngine
  6. Complete / fail AIRun
  7. Return enriched response dict with trust metadata

Feature-flag guarded: if "trust_guardrails" flag is OFF the wrapper is a
transparent pass-through that still records the AIRun (if "audit_log" is on).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session

from backend.core.feature_flags import (
    FLAG_AUDIT_LOG,
    FLAG_AUTO_ALERTS,
    FLAG_CLAIM_EXTRACTION,
    FLAG_TRUST_GUARDRAILS,
    flag_enabled,
)
from backend.models_trust import TrustAlert
from backend.services import audit_service, trust_service
from backend.services.guardrail import GuardrailBlocked, PolicyEngine
from backend.services.validator import PostValidator, PreValidator, ValidationError

logger = logging.getLogger(__name__)

_pre_validator = PreValidator()
_post_validator = PostValidator()
_policy_engine = PolicyEngine()


def run_with_trust(
    session: Session,
    *,
    owner_username: str,
    endpoint: str,
    provider: str,
    model: str,
    prompt: str,
    engine_fn: Callable[..., str],
    engine_kwargs: Dict[str, Any],
    study_id: Optional[int] = None,
    review_id: Optional[int] = None,
    evidence_basis: str = "unknown",
    prompt_version_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Wrap an engine call with trust pipeline.

    Parameters
    ----------
    engine_fn      : the actual engine function (engine_run or engine_run_vision)
    engine_kwargs  : kwargs forwarded verbatim to engine_fn
    evidence_basis : hint about the evidence strength ("rct", "cohort", …)

    Returns
    -------
    {
        "output":       str,          # final text (possibly degraded)
        "ai_run_id":    int | None,
        "trust_score":  float | None,
        "confidence_ceiling": float | None,
        "flagged":      bool,
        "flag_reason":  str | None,
        "warnings":     [str],
        "policy_action": str,         # "pass" | "degrade" | "require_review"
    }
    """
    guardrails_on = flag_enabled(session, FLAG_TRUST_GUARDRAILS)
    audit_on      = flag_enabled(session, FLAG_AUDIT_LOG)

    warnings: List[str] = []
    pre_failed = False

    # ── 1. Pre-validation ───────────────────────────────────────────────────
    if guardrails_on:
        try:
            pre_warnings = _pre_validator.validate(
                endpoint=endpoint,
                prompt=prompt,
                context={"study_id": study_id, "evidence_basis": evidence_basis},
            )
            warnings.extend(pre_warnings)
        except ValidationError as exc:
            pre_failed = True
            warnings.append(f"Pre-validation failed: {exc.message}")
            logger.warning("Pre-validation blocked endpoint=%s: %s", endpoint, exc.message)

    # ── 2. Open AIRun row ───────────────────────────────────────────────────
    ai_run = None
    if audit_on or guardrails_on:
        try:
            ai_run = trust_service.create_ai_run(
                session,
                owner_username=owner_username,
                endpoint=endpoint,
                provider=provider,
                model=model,
                study_id=study_id,
                review_id=review_id,
                prompt_version_id=prompt_version_id,
            )
        except Exception as exc:
            logger.error("create_ai_run failed (non-fatal): %s", exc)

    ai_run_id = ai_run.id if ai_run else None

    # ── 3. Block on pre-validation failure ──────────────────────────────────
    if pre_failed and guardrails_on:
        if ai_run:
            trust_service.fail_ai_run(session, ai_run, error_message="pre_validation_failed")
        return _error_response(ai_run_id, "pre_validation_failed", warnings)

    # ── 4. Call engine ───────────────────────────────────────────────────────
    output: str = ""
    latency_ms: Optional[int] = None
    engine_error: Optional[str] = None

    t0 = time.monotonic()
    try:
        output = engine_fn(**engine_kwargs)
    except Exception as exc:
        engine_error = str(exc)
        logger.error("Engine call failed endpoint=%s: %s", endpoint, exc)
    finally:
        latency_ms = int((time.monotonic() - t0) * 1000)

    if engine_error:
        if ai_run:
            trust_service.fail_ai_run(session, ai_run, error_message=engine_error)
        return _error_response(ai_run_id, engine_error, warnings)

    # ── 5. Post-validation ──────────────────────────────────────────────────
    flagged = False
    flag_reason: Optional[str] = None
    policy_action = "pass"

    if guardrails_on:
        post = _post_validator.validate(output=output, endpoint=endpoint)
        warnings.extend(post["warnings"])
        flagged = post["flagged"]
        flag_reason = post["flag_reason"]

        # ── 6. PolicyEngine ─────────────────────────────────────────────────
        ctx = {
            "endpoint": endpoint,
            "prompt": prompt,
            "output": output,
            "flagged": flagged,
            "flag_reason": flag_reason,
            "evidence_basis": evidence_basis,
            "confidence": None,
            "pre_validation_failed": pre_failed,
        }
        try:
            policy_result = _policy_engine.evaluate(ctx)
            policy_action = policy_result.action
            if policy_result.reason:
                warnings.append(f"Policy [{policy_result.policy_name}]: {policy_result.reason}")
            if policy_action == "degrade" and policy_result.degraded_response:
                output = policy_result.degraded_response
            if policy_action in ("degrade", "require_review"):
                flagged = True
                flag_reason = flag_reason or policy_result.reason
        except GuardrailBlocked as exc:
            if ai_run:
                trust_service.fail_ai_run(session, ai_run, error_message=f"blocked:{exc.reason}")
            return _error_response(ai_run_id, f"Blocked by policy '{exc.policy_name}': {exc.reason}", warnings)

    # ── 7. Complete AIRun ────────────────────────────────────────────────────
    trust_score: Optional[float] = None
    confidence_ceiling: Optional[float] = None

    if ai_run:
        try:
            trust_score = _compute_trust_score(output, flagged, evidence_basis)
            completed = trust_service.complete_ai_run(
                session,
                ai_run,
                latency_ms=latency_ms,
                trust_score=trust_score,
                evidence_basis=evidence_basis,
            )
            trust_score = completed.trust_score
            confidence_ceiling = completed.confidence_ceiling

            # Persist flagged state
            if flagged:
                ai_run.flagged = True
                ai_run.flag_reason = flag_reason
                session.add(ai_run)
                session.commit()
        except Exception as exc:
            logger.error("complete_ai_run failed (non-fatal): %s", exc)

    # ── 8. Auto-alert if flagged ─────────────────────────────────────────────
    if flagged and ai_run_id and flag_enabled(session, FLAG_AUTO_ALERTS):
        try:
            alert = TrustAlert(
                owner_username=owner_username,
                ai_run_id=ai_run_id,
                alert_type="output_flagged",
                severity="medium",
                message=flag_reason or "Output flagged by post-validator or policy engine.",
            )
            session.add(alert)
            session.commit()
        except Exception as exc:
            logger.warning("TrustAlert creation failed (non-fatal): %s", exc)

    return {
        "output": output,
        "ai_run_id": ai_run_id,
        "trust_score": trust_score,
        "confidence_ceiling": confidence_ceiling,
        "flagged": flagged,
        "flag_reason": flag_reason,
        "warnings": warnings,
        "policy_action": policy_action,
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _compute_trust_score(output: str, flagged: bool, evidence_basis: str) -> float:
    """Very simple heuristic trust score — replace with ML model later."""
    base = 0.75
    if flagged:
        base -= 0.25
    basis_bonus = {
        "rct": 0.15,
        "systematic_review": 0.12,
        "cohort": 0.05,
    }
    base += basis_bonus.get(evidence_basis.lower(), 0.0)
    return round(max(0.0, min(1.0, base)), 3)


def _error_response(ai_run_id: Optional[int], reason: str, warnings: List[str]) -> Dict[str, Any]:
    return {
        "output": "",
        "ai_run_id": ai_run_id,
        "trust_score": None,
        "confidence_ceiling": None,
        "flagged": True,
        "flag_reason": reason,
        "warnings": warnings,
        "policy_action": "block",
    }
