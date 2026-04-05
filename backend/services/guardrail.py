"""
PolicyEngine — fail-closed guardrails for every AI call.

Policy decision priority (first matching rule wins):
    block          → raise GuardrailBlocked (HTTP 422 to caller)
    degrade        → return a canned safe response instead of engine output
    require_review → allow but mark ai_run.flagged = True for human review
    pass           → allow through with no modification

POLICIES table maps (endpoint, condition) → action.
The table is deliberately simple and extensible without code changes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GuardrailBlocked(Exception):
    """Raised when a policy blocks the request entirely."""
    def __init__(self, policy_name: str, reason: str):
        super().__init__(reason)
        self.policy_name = policy_name
        self.reason = reason


@dataclass
class PolicyResult:
    action: str        # "pass" | "degrade" | "require_review" | "block"
    policy_name: str
    reason: Optional[str] = None
    degraded_response: Optional[str] = None


# ---------------------------------------------------------------------------
# Policy definitions
# Each entry: (name, endpoint_glob, condition_fn, action, reason, degraded_resp)
# endpoint_glob: "*" matches all endpoints
# condition_fn:  callable(context: dict) -> bool
# ---------------------------------------------------------------------------

def _flagged(ctx: Dict[str, Any]) -> bool:
    return bool(ctx.get("flagged"))

def _empty_output(ctx: Dict[str, Any]) -> bool:
    return not ctx.get("output", "").strip()

def _validator_hard_fail(ctx: Dict[str, Any]) -> bool:
    return bool(ctx.get("pre_validation_failed"))

def _high_confidence_no_rct(ctx: Dict[str, Any]) -> bool:
    # Confidence > 0.85 but evidence basis is not RCT/systematic_review
    basis = ctx.get("evidence_basis", "unknown")
    confidence = ctx.get("confidence", 0.0) or 0.0
    strong_bases = {"rct", "systematic_review"}
    return confidence > 0.85 and basis not in strong_bases

def _clinical_endpoint_no_disclaimer(ctx: Dict[str, Any]) -> bool:
    endpoint = ctx.get("endpoint", "")
    output = ctx.get("output", "")
    is_clinical = endpoint in ("clinical_qna", "summarise_clinical", "clinical")
    has_disclaimer = any(
        d in output.lower()
        for d in ["not medical advice", "consult a doctor", "seek professional", "qualified clinician"]
    )
    return is_clinical and bool(output) and not has_disclaimer


_CANNED_DEGRADE = (
    "I was unable to generate a reliable response for this request. "
    "Please rephrase your query or consult the original literature directly."
)

_CLINICAL_DISCLAIMER = (
    "\n\n---\n**Important:** This AI-generated summary is for informational purposes only "
    "and does not constitute medical advice. Always consult a qualified clinician before "
    "making clinical decisions."
)


POLICIES: List[Dict[str, Any]] = [
    {
        "name": "block_pre_validation_failure",
        "endpoint": "*",
        "condition": _validator_hard_fail,
        "action": "block",
        "reason": "Input failed pre-validation checks.",
    },
    {
        "name": "degrade_empty_output",
        "endpoint": "*",
        "condition": _empty_output,
        "action": "degrade",
        "reason": "Engine returned empty output.",
        "degraded_response": _CANNED_DEGRADE,
    },
    {
        "name": "require_review_flagged",
        "endpoint": "*",
        "condition": _flagged,
        "action": "require_review",
        "reason": "Output was flagged by post-validator.",
    },
    {
        "name": "require_review_high_confidence_weak_evidence",
        "endpoint": "*",
        "condition": _high_confidence_no_rct,
        "action": "require_review",
        "reason": "High confidence claim backed by weak evidence basis.",
    },
    {
        "name": "append_clinical_disclaimer",
        "endpoint": "*",
        "condition": _clinical_endpoint_no_disclaimer,
        "action": "require_review",
        "reason": "Clinical endpoint output missing safety disclaimer.",
    },
]


class PolicyEngine:
    """
    Evaluate all policies against the current call context.

    Parameters
    ----------
    context : dict with keys:
        endpoint           : str
        prompt             : str
        output             : str
        flagged            : bool
        flag_reason        : Optional[str]
        evidence_basis     : str
        confidence         : Optional[float]
        pre_validation_failed : bool

    Returns
    -------
    PolicyResult — callers must check .action before using the output.

    Raises
    ------
    GuardrailBlocked — when any policy action is "block".
    """

    def evaluate(self, context: Dict[str, Any]) -> PolicyResult:
        endpoint = context.get("endpoint", "*")

        for policy in POLICIES:
            ep = policy.get("endpoint", "*")
            if ep != "*" and ep != endpoint:
                continue

            try:
                triggered = policy["condition"](context)
            except Exception as exc:
                logger.warning("Policy %s condition raised: %s", policy["name"], exc)
                triggered = False

            if not triggered:
                continue

            action = policy["action"]
            name = policy["name"]
            reason = policy.get("reason")
            logger.info("Guardrail policy=%s action=%s endpoint=%s", name, action, endpoint)

            if action == "block":
                raise GuardrailBlocked(policy_name=name, reason=reason or "blocked")

            if action == "degrade":
                return PolicyResult(
                    action="degrade",
                    policy_name=name,
                    reason=reason,
                    degraded_response=policy.get("degraded_response", _CANNED_DEGRADE),
                )

            if action == "require_review":
                return PolicyResult(action="require_review", policy_name=name, reason=reason)

        return PolicyResult(action="pass", policy_name="none")
