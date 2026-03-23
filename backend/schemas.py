from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

from backend.models import ReadingStatus


# ---------- Auth ----------
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


# ---------- Folder ----------
class FolderCreate(BaseModel):
    name: str


class FolderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_username: str
    name: str


class FolderPatch(BaseModel):
    name: str


# ---------- Study ----------
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


# ---------- Comments ----------
class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    study_id: int
    parent_id: Optional[int] = None
    author: str
    body: str
    created_at: datetime


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: Optional[int] = None


class CommentPatch(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


# ---------- External ----------
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


# ---------- AI ----------
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


# ---------- Phase 3: Clinical Intelligence ----------
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


# ---------- Phase 4: Multi-Paper Synthesis ----------

class PaperContext(BaseModel):
    """Minimal paper data passed into a synthesis request."""
    study_id: int
    title: str
    abstract: Optional[str] = None
    year: Optional[int] = None
    study_type: Optional[str] = None
    evidence_strength: Optional[int] = None
    doi: Optional[str] = None


class AISynthesisRequest(BaseModel):
    study_ids: List[int] = Field(min_length=2, max_length=10)


class ConsensusPoint(BaseModel):
    finding: str
    supporting_studies: List[str] = []
    strength: Optional[str] = None  # "strong" | "moderate" | "weak"


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


# ---------- Phase 4: Subject Query (General Query Mode) ----------

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
    papers_used: List[dict] = []   # [{title, year, source, study_type}]
    cached: bool = False
    prompt_version: str = "4.0"