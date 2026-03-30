from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from backend.models import ReadingStatus


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str

class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str


# ── Folder ────────────────────────────────────────────────────────────────────

class FolderCreate(BaseModel):
    name: str

class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    name: str

class FolderPatch(BaseModel):
    name: str


# ── Study ─────────────────────────────────────────────────────────────────────

class StudyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    folder_id: Optional[int] = None
    source: str
    source_id: str
    title: str
    year: Optional[int] = None
    venue: Optional[str] = None
    authors: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    notes: Optional[str] = None
    study_type: Optional[str] = None
    tags: Optional[str] = None
    reading_status: Optional[str] = "unread"
    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None
    comment_count: int = 0
    citation_count: Optional[int] = None
    is_retracted: bool = False

class StudyPatch(BaseModel):
    notes: Optional[str] = None
    folder_id: Optional[int] = None
    reading_status: Optional[str] = None


# ── Comments (paper threads) ──────────────────────────────────────────────────

class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    study_id: int
    parent_id: Optional[int] = None
    author: str
    body: str
    upvotes: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    replies: List["CommentRead"] = []       # nested for reddit-style rendering

class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: Optional[int] = None

class CommentPatch(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

CommentRead.model_rebuild()


# ── External ──────────────────────────────────────────────────────────────────

class ExternalPaperOut(BaseModel):
    source: str
    source_id: str
    title: str
    year: Optional[int] = None
    authors: Optional[List[str]] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    citation_count: Optional[int] = None
    is_retracted: bool = False

class ExternalImportRequest(BaseModel):
    source: str
    source_id: str
    title: str
    year: Optional[int] = None
    authors: Optional[List[str]] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    citation_count: Optional[int] = None
    is_retracted: bool = False

class FullTextResponse(BaseModel):
    available: bool
    kind: str
    message: str
    html: Optional[str] = None


# ── AI ────────────────────────────────────────────────────────────────────────

class AIKeySetRequest(BaseModel):
    api_key: str

class AIKeyStatus(BaseModel):
    has_key: bool
    masked: Optional[str] = None

class AISummarizeRequest(BaseModel):
    title: str
    abstract: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None

class AISummarizeResponse(BaseModel):
    text: str

class AIAskRequest(BaseModel):
    question: str
    title: str
    abstract: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    doi: Optional[str] = None

class AIAskResponse(BaseModel):
    text: str


# ── Phase 3: Clinical Intelligence ───────────────────────────────────────────

class AIClinicalRequest(BaseModel):
    study_id: int
    title: str
    abstract: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None

class PICOData(BaseModel):
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcome: Optional[str] = None
    primary_outcome: Optional[str] = None

class StatisticalData(BaseModel):
    sample_size: Optional[int] = None
    p_value: Optional[str] = None
    effect_size: Optional[str] = None
    confidence_interval: Optional[str] = None
    nnt_nnh: Optional[str] = None
    clinical_significance: Optional[str] = None

class AppraisalData(BaseModel):
    evidence_strength: Optional[int] = None
    evidence_explanation: Optional[str] = None
    bias_risk: Optional[str] = None
    limitations: Optional[List[str]] = None

class RewritesData(BaseModel):
    patient: Optional[str] = None
    clinician: Optional[str] = None
    student: Optional[str] = None

class JargonItem(BaseModel):
    term: str
    definition: str

class AIClinicalResponse(BaseModel):
    study_id: int
    pico: PICOData
    stats: StatisticalData
    appraisal: AppraisalData
    rewrites: RewritesData
    key_claims: Optional[List[str]] = None
    jargon: Optional[List[JargonItem]] = None
    cached: bool = False
    prompt_version: Optional[str] = None


# ── Phase 4: Multi-Paper Synthesis ───────────────────────────────────────────

class PaperContext(BaseModel):
    study_id: int
    title: str
    abstract: Optional[str] = None
    year: Optional[int] = None
    study_type: Optional[str] = None
    evidence_strength: Optional[int] = None
    doi: Optional[str] = None

class AISynthesisRequest(BaseModel):
    study_ids: List[int] = Field(min_length=2, max_length=10)
    force_rerun: bool = False

class ConsensusPoint(BaseModel):
    finding: str
    supporting_studies: List[str] = []
    strength: Optional[str] = None

class ContradictionItem(BaseModel):
    issue: str
    side_a_studies: List[str] = []
    side_a_position: str = ""
    side_b_studies: List[str] = []
    side_b_position: str = ""
    likely_explanation: Optional[str] = None

class WeightingItem(BaseModel):
    study_title: str
    study_type: Optional[str] = None
    year: Optional[int] = None
    base_score: float
    recency_bonus: bool = False
    final_score: float
    weight_pct: float

class AISynthesisResponse(BaseModel):
    synthesis_id: int
    study_ids: List[int]
    paper_count: int
    synthesis_narrative: Optional[str] = None
    consensus_points: List[ConsensusPoint] = []
    contradictions: List[ContradictionItem] = []
    gap_analysis: List[str] = []
    weighted_conclusion: Optional[str] = None
    steel_man: Optional[str] = None
    comparative_methodology: Optional[str] = None
    weighting_breakdown: List[WeightingItem] = []
    cached: bool = False
    prompt_version: str = "4.0"

class AISubjectQueryRequest(BaseModel):
    query: str = Field(min_length=5, max_length=500)
    max_papers: int = Field(default=5, ge=2, le=10)
    source: str = Field(default="europepmc")

class AISubjectQueryResponse(BaseModel):
    synthesis_id: int
    query: str
    papers_found: int
    synthesis_narrative: Optional[str] = None
    consensus_points: List[ConsensusPoint] = []
    contradictions: List[ContradictionItem] = []
    gap_analysis: List[str] = []
    weighted_conclusion: Optional[str] = None
    steel_man: Optional[str] = None
    papers_used: List[dict] = []
    cached: bool = False
    prompt_version: str = "4.0"

class CrossPaperAskRequest(BaseModel):
    study_ids: List[int] = Field(min_length=1, max_length=10)
    question: str = Field(min_length=3, max_length=500)

class CrossPaperAskResponse(BaseModel):
    answer: str
    study_ids: List[int]
    question: str

CITATION_FORMATS = ["harvard", "apa", "vancouver", "chicago", "mla", "bibtex", "nature", "ama"]

class CitationRequest(BaseModel):
    study_ids: List[int] = Field(min_length=1, max_length=50)
    format: str = Field(default="harvard")

class CitationItem(BaseModel):
    study_id: int
    title: str
    formatted: str

class CitationResponse(BaseModel):
    citations: List[CitationItem]
    format: str
    count: int


# ── Phase 4: Synthesis History ───────────────────────────────────────────────

class SynthesisListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    mode: str
    query: Optional[str] = None
    paper_count: int
    prompt_version: str
    model_used: str
    created_at: datetime
    updated_at: datetime


# ── Phase 4: Systematic Review Tooling ───────────────────────────────────────

REVIEW_PHASES = ["search", "screen", "extract", "synthesise", "complete"]
SCREENING_DECISIONS = ["pending", "included", "excluded", "maybe"]

class SystematicReviewCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    search_query: Optional[str] = None
    search_source: str = Field(default="europepmc")
    inclusion_criteria: Optional[Dict[str, Any]] = None
    exclusion_criteria: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None

class SystematicReviewPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    phase: Optional[str] = None
    search_query: Optional[str] = None
    search_source: Optional[str] = None
    inclusion_criteria: Optional[Dict[str, Any]] = None
    exclusion_criteria: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None

class SystematicReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    title: str
    description: Optional[str] = None
    phase: str
    search_query: Optional[str] = None
    search_source: str
    search_results_count: int
    inclusion_criteria: Optional[Dict[str, Any]] = None
    exclusion_criteria: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None
    audit_log: Optional[Any] = None
    synthesis_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # summary counts (populated by router)
    screening_total: int = 0
    screening_included: int = 0
    screening_excluded: int = 0
    screening_pending: int = 0
    screening_maybe: int = 0

class ReviewScreeningCreate(BaseModel):
    study_id: Optional[int] = None
    external_title: Optional[str] = None
    external_doi: Optional[str] = None
    external_abstract: Optional[str] = None
    external_source: Optional[str] = None
    external_source_id: Optional[str] = None
    external_year: Optional[int] = None
    decision: str = Field(default="pending")
    screener_notes: Optional[str] = None

class ReviewScreeningPatch(BaseModel):
    decision: Optional[str] = None
    exclusion_reason: Optional[str] = None
    screener_notes: Optional[str] = None

class ReviewScreeningRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    review_id: int
    study_id: Optional[int] = None
    external_title: Optional[str] = None
    external_doi: Optional[str] = None
    external_abstract: Optional[str] = None
    external_source: Optional[str] = None
    external_source_id: Optional[str] = None
    external_year: Optional[int] = None
    decision: str
    exclusion_reason: Optional[str] = None
    screener_notes: Optional[str] = None
    created_at: datetime
    # denormalised for UI
    study_title: Optional[str] = None

class BulkScreeningUpdate(BaseModel):
    screening_ids: List[int] = Field(min_length=1, max_length=200)
    decision: str
    exclusion_reason: Optional[str] = None

class PRISMAData(BaseModel):
    identified: int = 0
    duplicates_removed: int = 0
    screened: int = 0
    excluded_screening: int = 0
    eligible: int = 0
    excluded_eligibility: int = 0
    included: int = 0
    review_title: str = ""

class EvidenceDriftPoint(BaseModel):
    period: str
    paper_count: int
    avg_effect_direction: Optional[str] = None
    consensus_summary: Optional[str] = None
    study_titles: List[str] = []

class EvidenceDriftResponse(BaseModel):
    review_id: int
    periods: List[EvidenceDriftPoint] = []
    drift_detected: bool = False
    drift_summary: Optional[str] = None

class PaperReminderCreate(BaseModel):
    study_id: int
    remind_at: datetime
    reason: Optional[str] = Field(default=None, max_length=500)

class PaperReminderPatch(BaseModel):
    remind_at: Optional[datetime] = None
    reason: Optional[str] = None
    is_dismissed: Optional[bool] = None

class PaperReminderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    study_id: int
    remind_at: datetime
    reason: Optional[str] = None
    is_dismissed: bool
    created_at: datetime
    # denormalised
    study_title: Optional[str] = None


# ── Notebook ──────────────────────────────────────────────────────────────────

class NotebookPageCreate(BaseModel):
    title: str = Field(default="Untitled", max_length=200)
    content: Optional[str] = None
    study_id: Optional[int] = None
    color: str = Field(default="default")

class NotebookPagePatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    content: Optional[str] = None
    color: Optional[str] = None
    is_pinned: Optional[bool] = None

class NotebookPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    study_id: Optional[int] = None
    title: str
    content: Optional[str] = None
    color: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime
    # denormalised for UI
    study_title: Optional[str] = None

class HighlightCreate(BaseModel):
    study_id: int
    selected_text: str = Field(min_length=1, max_length=2000)
    color: str = Field(default="yellow")
    annotation: Optional[str] = Field(default=None, max_length=1000)
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

class HighlightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    study_id: int
    selected_text: str
    color: str
    annotation: Optional[str] = None
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    created_at: datetime

class HighlightPatch(BaseModel):
    annotation: Optional[str] = Field(default=None, max_length=1000)
    color: Optional[str] = None


# ── Community ─────────────────────────────────────────────────────────────────

POST_TYPES = ["question", "discussion", "case_study", "resource"]

COMMUNITY_TAGS = [
    "Cardiology", "Oncology", "Neurology", "Respiratory", "Endocrinology",
    "Infectious Disease", "Surgery", "Pharmacology", "Paediatrics",
    "Mental Health", "Methods", "Statistics", "Evidence-Based Medicine", "General",
]

class CommunityPostCreate(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    body: str = Field(min_length=10, max_length=10000)
    post_type: str = Field(default="discussion")
    tags: Optional[str] = None
    study_id: Optional[int] = None
    is_anonymous: bool = False

    @field_validator('study_id', mode='before')
    @classmethod
    def parse_study_id(cls, v):
        if v == "" or v == "null":
            return None
        return v

class CommunityPostPatch(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    body: Optional[str] = Field(default=None, max_length=10000)
    tags: Optional[str] = None

class CommunityPostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    author: Optional[str] = None
    is_anonymous: bool
    title: str
    body: str
    post_type: str
    tags: Optional[str] = None
    study_id: Optional[int] = None
    upvotes: int
    reply_count: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    # client extras
    user_upvoted: bool = False
    user_bookmarked: bool = False
    study_title: Optional[str] = None

class CommunityReplyCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_reply_id: Optional[int] = None
    is_anonymous: bool = False

class CommunityReplyPatch(BaseModel):
    body: str = Field(min_length=1, max_length=5000)

class CommunityReplyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    post_id: int
    parent_reply_id: Optional[int] = None
    author: Optional[str] = None
    is_anonymous: bool
    body: str
    upvotes: int
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    user_upvoted: bool = False
    user_bookmarked: bool = False
    replies: List["CommunityReplyRead"] = []

CommunityReplyRead.model_rebuild()

class BookmarkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_username: str
    target_id: int
    target_type: str
    created_at: datetime


# ── Landing / Metrics ─────────────────────────────────────────────────────────

class TrendingTopic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    topic: str
    count: int
    change: str = "stable"  # "up" | "down" | "stable"

class PaperOfDay(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    title: str
    year: Optional[int] = None
    study_type: Optional[str] = None
    summary: str
    doi: Optional[str] = None
    source: str

class LandingStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    papers_analysed: int
    syntheses_run: int
    community_posts: int
    researchers: int