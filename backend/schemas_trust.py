"""
Pydantic / SQLModel DTOs for the Phase-6 Trust & Validity system.
All schemas are plain Pydantic models (table=False) so they are safe to
use in FastAPI request/response bodies.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── AIRun ────────────────────────────────────────────────────────────────────

class AIRunRead(BaseModel):
    id: int
    owner_username: str
    study_id: Optional[int]
    review_id: Optional[int]
    endpoint: str
    provider: str
    model: str
    prompt_version_id: Optional[int]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: Optional[int]
    status: str
    error_message: Optional[str]
    trust_score: Optional[float]
    confidence_ceiling: Optional[float]
    flagged: bool
    flag_reason: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── PromptVersion ─────────────────────────────────────────────────────────────

class PromptVersionCreate(BaseModel):
    endpoint: str
    version: str
    system_template: str
    user_template: str
    notes: Optional[str] = None

class PromptVersionRead(BaseModel):
    id: int
    endpoint: str
    version: str
    system_template: str
    user_template: str
    notes: Optional[str]
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


# ── EvidenceSpan ─────────────────────────────────────────────────────────────

class EvidenceSpanCreate(BaseModel):
    ai_run_id: int
    study_id: Optional[int] = None
    source_text: str
    claim_text: str
    basis: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    confidence: Optional[float] = None

class EvidenceSpanRead(BaseModel):
    id: int
    ai_run_id: int
    study_id: Optional[int]
    source_text: str
    claim_text: str
    basis: str
    span_start: Optional[int]
    span_end: Optional[int]
    confidence: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Claim ─────────────────────────────────────────────────────────────────────

class ClaimRead(BaseModel):
    id: int
    ai_run_id: int
    study_id: Optional[int]
    review_id: Optional[int]
    claim_type: str
    text: str
    evidence_span_id: Optional[int]
    confidence: Optional[float]
    verification_state: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── VerificationRecord ────────────────────────────────────────────────────────

class VerificationCreate(BaseModel):
    claim_id: int
    decision: str          # approved | rejected | needs_review
    notes: Optional[str] = None

class VerificationRead(BaseModel):
    id: int
    claim_id: int
    verifier_username: str
    decision: str
    notes: Optional[str]
    prompt_version_locked: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── AuditLog ─────────────────────────────────────────────────────────────────

class AuditLogRead(BaseModel):
    id: int
    event: str
    actor: str
    study_id: Optional[int]
    ai_run_id: Optional[int]
    review_id: Optional[int]
    claim_id: Optional[int]
    verification_id: Optional[int]
    detail: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class AuditLogQuery(BaseModel):
    actor: Optional[str] = None
    event: Optional[str] = None
    study_id: Optional[int] = None
    review_id: Optional[int] = None
    ai_run_id: Optional[int] = None
    limit: int = Field(default=50, le=500)
    offset: int = 0


# ── BenchmarkDataset ──────────────────────────────────────────────────────────

class BenchmarkDatasetCreate(BaseModel):
    name: str
    task_type: str
    description: Optional[str] = None

class BenchmarkDatasetRead(BaseModel):
    id: int
    name: str
    task_type: str
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class BenchmarkItemCreate(BaseModel):
    dataset_id: int
    input_text: str
    expected_output: str
    metadata_json: Optional[Dict[str, Any]] = None

class BenchmarkItemRead(BaseModel):
    id: int
    dataset_id: int
    input_text: str
    expected_output: str
    metadata_json: Optional[Dict[str, Any]]
    created_at: datetime

    class Config:
        from_attributes = True


# ── EvalRun ───────────────────────────────────────────────────────────────────

class EvalRunCreate(BaseModel):
    dataset_id: int
    provider: str
    model: str
    prompt_version_id: Optional[int] = None

class EvalRunRead(BaseModel):
    id: int
    dataset_id: int
    triggered_by: str
    provider: str
    model: str
    prompt_version_id: Optional[int]
    status: str
    error_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True

class EvalMetricRead(BaseModel):
    id: int
    eval_run_id: int
    metric_name: str
    metric_value: float
    threshold: Optional[float]
    passed: Optional[bool]

    class Config:
        from_attributes = True

class EvalRunDetail(EvalRunRead):
    metrics: List[EvalMetricRead] = []


# ── TrustAlert ────────────────────────────────────────────────────────────────

class TrustAlertRead(BaseModel):
    id: int
    owner_username: str
    ai_run_id: Optional[int]
    alert_type: str
    severity: str
    message: str
    is_dismissed: bool
    created_at: datetime

    class Config:
        from_attributes = True

class TrustAlertDismiss(BaseModel):
    alert_id: int


# ── FeatureFlag ───────────────────────────────────────────────────────────────

class FeatureFlagRead(BaseModel):
    id: int
    name: str
    is_enabled: bool
    description: Optional[str]
    updated_at: datetime

    class Config:
        from_attributes = True

class FeatureFlagSet(BaseModel):
    name: str
    is_enabled: bool
    description: Optional[str] = None


# ── UserRole ──────────────────────────────────────────────────────────────────

class UserRoleRead(BaseModel):
    id: int
    username: str
    role: str
    granted_by: str
    granted_at: datetime

    class Config:
        from_attributes = True

class UserRoleGrant(BaseModel):
    username: str
    role: str   # trust_reviewer | admin | eval_runner


# ── Provenance (composite response) ──────────────────────────────────────────

class ProvenanceResponse(BaseModel):
    ai_run: AIRunRead
    evidence_spans: List[EvidenceSpanRead]
    claims: List[ClaimRead]
    verifications: List[VerificationRead]
    audit_trail: List[AuditLogRead]


# ── Trust summary embedded in AI responses ────────────────────────────────────

class TrustSummary(BaseModel):
    ai_run_id: Optional[int]
    trust_score: Optional[float]
    confidence_ceiling: Optional[float]
    flagged: bool
    flag_reason: Optional[str]
    evidence_basis: Optional[str]
    claim_count: int
    provider: Optional[str]
    model: Optional[str]
