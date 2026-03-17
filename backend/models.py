from __future__ import annotations
import enum
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import UniqueConstraint, Column, JSON
from sqlmodel import Field, SQLModel

# --- Phase 3 Enums ---
class ReadingStatus(str, enum.Enum):
    """Tracks the user's progress through a paper[cite: 178, 180]."""
    UNREAD = "unread"
    READING = "reading"
    DONE = "done"
    FLAGGED = "flagged"

# --- User Management ---
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    ai_key_enc: Optional[str] = Field(default=None)
    is_verified: bool = Field(default=False)  # From Phase 2.5 [cite: 63]

# --- Organization ---
class Folder(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "name", name="uq_folder_owner_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_username: str = Field(index=True)
    name: str = Field(index=True)

# --- Core Research Data ---
class Study(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "source", "source_id", name="uq_study_owner_source_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    folder_id: Optional[int] = Field(default=None, foreign_key="folder.id", index=True)

    source: str = Field(index=True)
    source_id: str = Field(index=True)

    title: str
    year: Optional[int] = Field(default=None, index=True)
    venue: Optional[str] = None
    authors: Optional[str] = None

    doi: Optional[str] = Field(default=None, index=True)
    url: Optional[str] = None

    abstract: Optional[str] = None
    pmid: Optional[str] = Field(default=None, index=True)
    pmcid: Optional[str] = Field(default=None, index=True)

    notes: Optional[str] = None
    study_type: Optional[str] = None
    tags: Optional[str] = None

    # PHASE 3 UPGRADES
    reading_status: ReadingStatus = Field(default=ReadingStatus.UNREAD, index=True) # [cite: 178]
    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None

class StudyExternalRef(SQLModel, table=True):
    """Links one saved paper to multiple providers[cite: 383]."""
    __table_args__ = (
        UniqueConstraint("owner_username", "source", "source_id", name="uq_studyext_owner_source_sourceid"),
        UniqueConstraint("study_id", "source", name="uq_studyext_study_source"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_username: str = Field(index=True)
    study_id: int = Field(foreign_key="study.id", index=True)

    source: str = Field(index=True)
    source_id: str = Field(index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

# --- Evidence & Intelligence ---
class StudyMetrics(SQLModel, table=True):
    """Usage + high-fidelity clinical data[cite: 90, 91, 134]."""
    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    study_id: int = Field(foreign_key="study.id", index=True)

    # Evidence quality (Phase 3 Structured Data) [cite: 85, 98]
    study_type: Optional[str] = Field(default=None, index=True)
    evidence_strength: Optional[int] = Field(default=None, ge=0, le=5) 
    risk_of_bias: Optional[str] = Field(default=None) # e.g., "Low", "Moderate", "High"
    sample_size: Optional[int] = Field(default=None, ge=0)
    
    # PICO & Stats JSON Storage [cite: 76, 77, 89, 90]
    # Includes: Population, Intervention, Comparator, Outcome, NNT/NNH, CIs
    pico_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    statistical_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    # Usage counters (Dormant hooks to be wired) [cite: 45, 47]
    save_count: int = Field(default=0)
    folder_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    ai_runs: int = Field(default=0)

    notes: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: Optional[datetime] = Field(default=None)

class AIResult(SQLModel, table=True):
    """Cache for specialized AI extractions and translations[cite: 109, 119, 128]."""
    __table_args__ = (UniqueConstraint("owner_username", "cache_key", "kind", name="uq_airesult_owner_key_kind"),)

    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    cache_key: str = Field(index=True)
    kind: str = Field(index=True) # "summarize" | "pico" | "bias" | "translate"

    model_used: str = Field(default="byok")
    prompt_version: str = Field(default="3.0") # [cite: 109]
    question: Optional[str] = None
    summary: Optional[str] = None 
    
    # Research Translation Rewrites [cite: 128, 129]
    patient_summary: Optional[str] = None
    clinician_summary: Optional[str] = None
    student_summary: Optional[str] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# --- Social ---
class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    study_id: int = Field(foreign_key="study.id", index=True)
    parent_id: Optional[int] = Field(default=None, index=True)

    author: str = Field(index=True)
    body: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))