"""
Feature flag runtime checks with 60-second TTL cache.

All trust-system flags default to OFF (fail-closed). The feature flag table
is seeded by the Alembic migration; rows can be updated via the admin API.

Usage:
    from backend.core.feature_flags import flag_enabled
    if flag_enabled(session, "trust_guardrails"):
        ...
"""
from __future__ import annotations

import time
from typing import Optional

from sqlmodel import Session, select

# ---------------------------------------------------------------------------
# Cache: {flag_name: (is_enabled, expires_at_epoch)}
# ---------------------------------------------------------------------------
_CACHE: dict[str, tuple[bool, float]] = {}
_TTL = 60.0  # seconds


def flag_enabled(session: Session, name: str) -> bool:
    """Return True if the named feature flag is enabled.

    Uses an in-process TTL cache to avoid a DB hit on every request.
    Falls back to False (fail-closed) if the flag doesn't exist.
    """
    now = time.monotonic()
    cached = _CACHE.get(name)
    if cached is not None and now < cached[1]:
        return cached[0]

    # Lazy import to avoid circular-import issues at module load time
    from backend.models_trust import FeatureFlag

    row = session.exec(select(FeatureFlag).where(FeatureFlag.name == name)).first()
    value = row.is_enabled if row is not None else False
    _CACHE[name] = (value, now + _TTL)
    return value


def invalidate_flag(name: str) -> None:
    """Evict a single flag from the cache (call after DB update)."""
    _CACHE.pop(name, None)


def invalidate_all() -> None:
    """Evict every flag from the cache."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Canonical flag names — use these constants to avoid typos
# ---------------------------------------------------------------------------
FLAG_TRUST_GUARDRAILS      = "trust_guardrails"
FLAG_CLAIM_EXTRACTION      = "claim_extraction"
FLAG_EVIDENCE_SPANS        = "evidence_spans"
FLAG_CONFIDENCE_CEILINGS   = "confidence_ceilings"
FLAG_AUDIT_LOG             = "audit_log"
FLAG_AUTO_ALERTS           = "auto_alerts"
FLAG_EVAL_RUNNER           = "eval_runner"
FLAG_REQUIRE_VERIFICATION  = "require_verification"
