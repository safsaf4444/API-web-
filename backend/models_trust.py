"""
backend/models_trust.py
Trust & Validity System — Phase 1-8 database tables.

All tables are additive. Nothing in existing tables is removed.
Alembic picks these up because models.py imports this module at the bottom.

INVARIANT: AuditLog rows are NEVER updated or deleted.
           Enforce at the service layer — there is no ORM-level protection.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enums (string enums so they round-trip cleanly through JSON) ───────────────

class VerificationState(str, enum.Enum):
    DRAFT     = "draft"        # AI produced; no human has reviewed
    REVIEWED  = "reviewed"     # At least one reviewer has seen it
    VERIFIED  = "verified"     # Formally signed off — version-locked
    REJECTED  = "rejected"     # Reviewer explicitly rejected
    RETRACTED = "retracted"    # Post-publication retraction recorded


class ClaimType(str, enum.Enum):
    EXTRACTED   = "extracted"    # Copied verbatim / directly from source text
    INTERPRETED = "interpreted"  # AI inference from evidence
    SYNTHESISED = "synthesised"  # Cross-paper AI reasoning
    GENERATED   = "generated"    # AI output with no specific source grounding


class EvidenceBasis(str, enum.Enum):
    FULL_TEXT = "full_text"   # Full paper text was in context
    ABSTRACT  = "abstract"    # Only abstract available
    METADATA  = "metadata"    # Title/year/journal only
    NONE      = "none"        # Generated without any source text


class AuditEvent(str, enum.Enum):
    AI_RUN_STARTED         = "ai_run_started"
    AI_RUN_COMPLETED       = "ai_run_completed"
    AI_RUN_FAILED          = "ai_run_failed"
    CLAIM_CREATED          = "claim_created"
    CLAIM_VERIFIED         = "claim_verified"
    CLAIM_REJECTED         = "claim_rejected"
    VERIFICATION_CREATED   = "verification_created"
    VERIFICATION_SIGNED    = "verification_signed"
    VERIFICATION_REJECTED  = "verification_rejected"
    ADJUDICATION_OPENED    = "adjudication_opened"
    ADJUDICATION_CLOSED    = "adjudication_closed"
    EXPORT_BLOCKED         = "export_blocked"
    EXPORT_ALLOWED         = "export_allowed"
    PROMPT_VERSION_ACTIVATED = "prompt_version_activated"
    MODEL_VERSION_REGISTERED = "model_version_registered"
    FEATURE_FLAG_SET       = "feature_flag_set"
    SCREENING_DECISION     = "screening_decision"
    GUARDRAIL_TRIGGERED    = "guardrail_triggered"
    ALERT_RAISED           = "alert_raised"
    ALERT_RESOLVED         = "alert_resolved"
    ROLE_GRANTED           = "role_granted"
    ROLE_REVOKED           = "role_revoked"


class TrustAlertSeverity(str, enum.Enum):
    INFO     = "info"
    WARN     = "warn"
    CRITICAL = "critical"


class TrustAlertType(str, enum.Enum):
    NO_GROUNDING          = "no_grounding"
    MISSING_CITATION      = "missing_citation"
    IMPOSSIBLE_STAT       = "impossible_stat"
    HALLUCINATION_FLAG    = "hallucination_flag"
    CONFIDENCE_INFLATION  = "confidence_inflation"
    CONTRADICTORY_VALUES  = "contradictory_values"
    RETRACTED_SOURCE      = "retracted_source"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    THIN_CONTEXT          = "thin_context"
    PREDATORY_JOURNAL     = "predatory_journal"


# ── 1. AIRun — one row per call to engine_run() or engine_run_vision() ────────

class AIRun(SQLModel, table=True):
    __tablename__ = "ai_runs"

    id:              Optional[int] = Field(default=None, primary_key=True)
    owner_username:  str           = Field(index=True)
    task_kind:       str           # summarize | ask | clinical | synthesise | explain_figure | ...
    model_used:      str           # gemini-1.5-flash | gpt-4o-mini | ...
    provider:        str           # gemini_free | openai | anthropic | groq_free | ...
    prompt_version:  str           = Field(default="unknown")

    # Prompt fingerprints — content-addressed, never stored in plaintext here
    system_prompt_hash: str        = Field(default="")
    user_prompt_hash:   str        = Field(default="")

    # Token budget estimates (rough — no tiktoken dependency)
    input_token_est:  Optional[int] = None
    output_token_est: Optional[int] = None
    latency_ms:       Optional[int] = None

    # What source text was in the context window
    evidence_basis:   str           = Field(default=EvidenceBasis.NONE)
    context_chars:    Optional[int] = None   # chars of source text injected
    study_ids_json:   Optional[str] = None   # JSON list of int study IDs, e.g. "[1,2,3]"

    # Outcome
    status:         str           = Field(default="completed")  # completed | failed | partial
    failure_reason: Optional[str] = None

    # Snapshot of active feature flags at run time (JSON dict)
    flags_snapshot: Optional[str] = None

    created_at: datetime = Field(default_factory=_now)


# ── 2. PromptVersion — immutable registry of prompt templates ─────────────────

class PromptVersion(SQLModel, table=True):
    __tablename__ = "prompt_versions"

    id:           Optional[int] = Field(default=None, primary_key=True)
    task_kind:    str           = Field(index=True)   # summarize | clinical | synthesise | ...
    version:      str           = Field(index=True)   # semver: "4.1", "4.2"
    prompt_hash:  str           = Field(index=True)   # SHA-256 of system_prompt; unique per content
    system_prompt: str          # full text — immutable after creation

    notes:      Optional[str] = None   # change rationale
    is_active:  bool          = Field(default=False)  # only one active per task_kind
    created_by: str
    created_at: datetime = Field(default_factory=_now)


# ── 3. ModelVersion — model release registry ──────────────────────────────────

class ModelVersion(SQLModel, table=True):
    __tablename__ = "model_versions"

    id:              Optional[int] = Field(default=None, primary_key=True)
    provider:        str
    model_name:      str = Field(index=True)   # e.g. "gemini-1.5-flash"
    display_name:    str
    max_ctx_tokens:  int
    supports_json:   bool = Field(default=True)
    supports_vision: bool = Field(default=False)
    cost_tier:       str  = Field(default="free")   # free | byok | paid
    is_active:       bool = Field(default=True)

    deprecated_at:  Optional[datetime] = None
    notes:          Optional[str]      = None
    registered_by:  str
    registered_at:  datetime = Field(default_factory=_now)


# ── 4. EvidenceSpan — exact source text grounding a claim ─────────────────────

class EvidenceSpan(SQLModel, table=True):
    __tablename__ = "evidence_spans"

    id:          Optional[int] = Field(default=None, primary_key=True)
    ai_run_id:   int           = Field(foreign_key="ai_runs.id", index=True)
    study_id:    Optional[int] = Field(default=None, foreign_key="study.id", index=True)

    # Where in the source text
    source_section: Optional[str] = None  # abstract | methods | results | discussion | table | figure
    char_start:     Optional[int] = None  # offset within the text sent to the model
    char_end:       Optional[int] = None
    span_text:      str                   # the actual text excerpt

    table_ref:  Optional[str] = None   # "Table 2" if sourced from a table
    figure_ref: Optional[str] = None   # "Figure 1A" if sourced from a figure
    confidence: float         = Field(default=1.0)   # 0.0–1.0

    created_at: datetime = Field(default_factory=_now)


# ── 5. Claim — one assertable statement produced by an AI run ─────────────────

class Claim(SQLModel, table=True):
    __tablename__ = "claims"

    id:             Optional[int] = Field(default=None, primary_key=True)
    ai_run_id:      int           = Field(foreign_key="ai_runs.id", index=True)
    owner_username: str           = Field(index=True)

    claim_text:     str           # the assertion
    claim_type:     str           # ClaimType enum value
    field_name:     Optional[str] = None  # "sample_size" | "p_value" | "pico_population" | ...
    extracted_value: Optional[str] = None # structured value if numeric/categorical extraction

    # Grounding — JSON list of EvidenceSpan.id
    evidence_span_ids: Optional[str] = None
    has_grounding:     bool           = Field(default=False)  # True iff span_ids non-empty

    # Confidence
    model_confidence:  Optional[float] = None   # raw model estimate 0.0–1.0 if available
    calibrated_conf:   Optional[float] = None   # after calibration ceiling applied

    # Verification lifecycle
    verification_state: str           = Field(default=VerificationState.DRAFT, index=True)
    verified_by:        Optional[str] = None
    verified_at:        Optional[datetime] = None
    rejection_reason:   Optional[str] = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ── 6. VerificationRecord — sign-off trail for a complete AI output ───────────

class VerificationRecord(SQLModel, table=True):
    __tablename__ = "verification_records"

    id:          Optional[int] = Field(default=None, primary_key=True)
    ai_run_id:   int           = Field(foreign_key="ai_runs.id", index=True)

    # One of these will be set to identify WHAT is being verified
    ai_result_id:  Optional[int] = Field(default=None, foreign_key="airesult.id")
    synthesis_id:  Optional[int] = Field(default=None, foreign_key="synthesisresult.id")
    review_id:     Optional[int] = Field(default=None, foreign_key="systematicreview.id")

    state: str = Field(default=VerificationState.DRAFT, index=True)

    # Double-review support
    reviewer_1:      Optional[str]      = None
    reviewer_1_at:   Optional[datetime] = None
    reviewer_1_note: Optional[str]      = None
    reviewer_2:      Optional[str]      = None
    reviewer_2_at:   Optional[datetime] = None
    reviewer_2_note: Optional[str]      = None

    signed_off_by: Optional[str]      = None
    signed_off_at: Optional[datetime] = None

    # Version lock — set at sign-off, never changed afterward
    locked_prompt_version:  Optional[str] = None
    locked_model:           Optional[str] = None
    locked_study_ids_hash:  Optional[str] = None  # SHA-256 of sorted study IDs

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# ── 7. ReviewerAssignment — who is assigned to review what ────────────────────

class ReviewerAssignment(SQLModel, table=True):
    __tablename__ = "reviewer_assignments"

    id:               Optional[int] = Field(default=None, primary_key=True)
    verification_id:  int           = Field(foreign_key="verification_records.id", index=True)
    assigned_to:      str           = Field(index=True)  # username
    assigned_by:      str           # username or "system"
    role:             str           = Field(default="primary")  # primary | secondary | adjudicator

    due_at:       Optional[datetime] = None
    completed_at: Optional[datetime] = None
    decision:     Optional[str]      = None   # approve | reject | flag
    notes:        Optional[str]      = None

    created_at: datetime = Field(default_factory=_now)


# ── 8. Adjudication — resolves conflict between reviewers ─────────────────────

class Adjudication(SQLModel, table=True):
    __tablename__ = "adjudications"

    id:               Optional[int] = Field(default=None, primary_key=True)
    verification_id:  int           = Field(foreign_key="verification_records.id", index=True)
    opened_by:        str
    opened_at:        datetime      = Field(default_factory=_now)
    conflict_summary: str

    adjudicator:      Optional[str]      = None
    resolution:       Optional[str]      = None   # approve | reject
    resolution_note:  Optional[str]      = None
    resolved_at:      Optional[datetime] = None


# ── 9. AuditLog — append-only event stream ────────────────────────────────────
#
# INVARIANT: NEVER issue UPDATE or DELETE on this table.
#            Service layer enforces this — there is no DB-level constraint.
#            Any schema change must only add nullable columns.

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id:    Optional[int] = Field(default=None, primary_key=True)
    event: str           = Field(index=True)   # AuditEvent value
    actor: str           = Field(index=True)   # username or "system"

    # Target identifiers — at most one set per event
    study_id:         Optional[int] = Field(default=None, index=True)
    ai_run_id:        Optional[int] = Field(default=None, index=True)
    review_id:        Optional[int] = Field(default=None, index=True)
    claim_id:         Optional[int] = Field(default=None, index=True)
    verification_id:  Optional[int] = Field(default=None, index=True)

    # Structured event detail (JSON)
    detail: Optional[str] = None

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # Immutable — no updated_at column on purpose
    created_at: datetime = Field(default_factory=_now, index=True)


# ── 10. BenchmarkDataset — gold-standard annotation collection ────────────────

class BenchmarkDataset(SQLModel, table=True):
    __tablename__ = "benchmark_datasets"

    id:          Optional[int] = Field(default=None, primary_key=True)
    name:        str           = Field(unique=True)   # "pico_extraction_v1"
    task_kind:   str           = Field(index=True)    # pico | screening | statistics | bias
    description: Optional[str] = None
    source:      Optional[str] = None   # "cochrane_annotated" | "manual" | "published_sr"
    item_count:  int           = Field(default=0)
    is_active:   bool          = Field(default=True)
    created_at:  datetime      = Field(default_factory=_now)


class BenchmarkItem(SQLModel, table=True):
    __tablename__ = "benchmark_items"

    id:          Optional[int] = Field(default=None, primary_key=True)
    dataset_id:  int           = Field(foreign_key="benchmark_datasets.id", index=True)

    input_text:  str                    # abstract / excerpt fed to model
    input_meta:  Optional[str] = None   # JSON — {"title": ..., "year": ..., "study_type": ...}
    gold_output: str                    # JSON — task-specific ground-truth structured label

    annotated_by:       Optional[str] = None  # human annotator id or "imported"
    annotation_source:  Optional[str] = None  # "cochrane" | "manual" | "published_sr"
    difficulty:         Optional[str] = None  # easy | medium | hard
    notes:              Optional[str] = None

    created_at: datetime = Field(default_factory=_now)


# ── 11. EvalRun — one evaluation pass against a benchmark dataset ─────────────

class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"

    id:              Optional[int] = Field(default=None, primary_key=True)
    dataset_id:      int           = Field(foreign_key="benchmark_datasets.id", index=True)
    model_name:      str
    prompt_version:  str

    items_evaluated: int           = Field(default=0)
    # Aggregate metrics (populated when status=complete)
    precision:              Optional[float] = None
    recall:                 Optional[float] = None
    f1:                     Optional[float] = None
    hallucination_rate:     Optional[float] = None
    extraction_error_rate:  Optional[float] = None

    passed_threshold:  Optional[bool] = None
    threshold_used:    Optional[str]  = None   # JSON of thresholds applied

    baseline_eval_id:  Optional[int]  = None   # EvalRun.id for regression comparison
    regression_delta:  Optional[str]  = None   # JSON of per-metric deltas

    triggered_by:  str           = Field(default="manual")  # manual | ci | pre_deploy
    status:        str           = Field(default="pending")  # pending | running | complete | failed
    notes:         Optional[str] = None

    started_at:   datetime           = Field(default_factory=_now)
    completed_at: Optional[datetime] = None


class EvalMetric(SQLModel, table=True):
    """Per-item result for one EvalRun."""
    __tablename__ = "eval_metrics"

    id:                Optional[int] = Field(default=None, primary_key=True)
    eval_run_id:       int           = Field(foreign_key="eval_runs.id", index=True)
    benchmark_item_id: int           = Field(foreign_key="benchmark_items.id", index=True)

    model_output:   str            # JSON — raw model output for this item
    is_correct:     Optional[bool] = None
    partial_credit: Optional[float] = None   # 0.0–1.0
    error_type:     Optional[str]  = None    # hallucination | omission | wrong_value | format_error
    field_scores:   Optional[str]  = None    # JSON — per-field precision/recall
    notes:          Optional[str]  = None

    created_at: datetime = Field(default_factory=_now)


# ── 12. EvidenceWeightProfile ─────────────────────────────────────────────────

class EvidenceWeightProfile(SQLModel, table=True):
    __tablename__ = "evidence_weight_profiles"

    id:          Optional[int] = Field(default=None, primary_key=True)
    name:        str           = Field(unique=True)   # "default_v1"
    description: Optional[str] = None
    is_active:   bool          = Field(default=False)

    # JSON dicts
    weights:   str   # {"meta_analysis": 5.0, "rct": 4.0, ...}
    modifiers: str   # {"recency_bonus": {"years": 5, "factor": 1.1}, "retraction_penalty": -10.0}
    rules:     str   # {"require_n_rcts": 0, "block_editorial_only": false}

    created_by: str
    created_at: datetime = Field(default_factory=_now)


# ── 13. TrustAlert — flagged outputs requiring attention ──────────────────────

class TrustAlert(SQLModel, table=True):
    __tablename__ = "trust_alerts"

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    ai_run_id:      Optional[int] = Field(default=None, foreign_key="ai_runs.id", index=True)
    claim_id:       Optional[int] = Field(default=None, foreign_key="claims.id")

    severity:       str   # TrustAlertSeverity
    alert_type:     str   # TrustAlertType
    description:    str
    affected_field: Optional[str] = None

    is_resolved:     bool           = Field(default=False, index=True)
    resolved_by:     Optional[str]  = None
    resolved_at:     Optional[datetime] = None
    resolution_note: Optional[str]  = None

    created_at: datetime = Field(default_factory=_now)


# ── 14. FeatureFlag — runtime on/off switches for trust features ──────────────

class FeatureFlag(SQLModel, table=True):
    __tablename__ = "feature_flags"

    id:          Optional[int] = Field(default=None, primary_key=True)
    name:        str           = Field(unique=True, index=True)  # "trust.guardrails_enabled"
    is_enabled:  bool          = Field(default=False)
    description: Optional[str] = None
    set_by:      str           = Field(default="system")
    set_at:      datetime      = Field(default_factory=_now)

    # Optional: per-user override (NULL = applies globally)
    username: Optional[str] = Field(default=None, index=True)


# ── 15. UserRole — RBAC without modifying existing User table ─────────────────

class UserRole(SQLModel, table=True):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("username", "role", name="uq_user_role"),)

    id:         Optional[int] = Field(default=None, primary_key=True)
    username:   str           = Field(index=True)
    role:       str           = Field(index=True)  # researcher | reviewer | adjudicator | admin
    granted_by: str
    granted_at: datetime      = Field(default_factory=_now)
    revoked_at: Optional[datetime] = None   # NULL = currently active
