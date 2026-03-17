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

    # PHASE 3 FIX: Forgiving string default, securely locked to lowercase.
    reading_status: Optional[str] = "unread" 
    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None


class StudyPatch(BaseModel):
    notes: Optional[str] = None
    folder_id: Optional[int] = None
    # Phase 3
    reading_status: Optional[ReadingStatus] = None


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


class StatisticalData(BaseModel):
    sample_size: Optional[int] = None
    p_value: Optional[str] = None
    effect_size: Optional[str] = None
    confidence_interval: Optional[str] = None
    nnt_nnh: Optional[str] = None


class AppraisalData(BaseModel):
    evidence_strength: Optional[int] = None
    bias_risk: Optional[str] = None
    limitations: Optional[List[str]] = None


class RewritesData(BaseModel):
    patient: Optional[str] = None
    clinician: Optional[str] = None
    student: Optional[str] = None


class AIClinicalResponse(BaseModel):
    study_id: int
    pico: PICOData
    stats: StatisticalData
    appraisal: AppraisalData
    rewrites: RewritesData
    cached: bool = False