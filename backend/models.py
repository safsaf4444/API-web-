from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    ai_key_enc: Optional[str] = Field(default=None)  # encrypted OpenAI key (BYOK)


class Folder(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "name", name="uq_folder_owner_name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_username: str = Field(index=True)
    name: str = Field(index=True)


class Study(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "source", "source_id", name="uq_study_owner_source_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    folder_id: Optional[int] = Field(default=None, foreign_key="folder.id", index=True)

    source: str = Field(index=True)  # europepmc / semantic_scholar / openalex / crossref
    source_id: str = Field(index=True)  # provider record id

    title: str
    year: Optional[int] = Field(default=None, index=True)
    venue: Optional[str] = None
    authors: Optional[str] = None

    doi: Optional[str] = Field(default=None, index=True)
    url: Optional[str] = None

    abstract: Optional[str] = None
    pmid: Optional[str] = Field(default=None, index=True)
    pmcid: Optional[str] = Field(default=None, index=True)

    # v1 enrichment fields (safe for Phase 1 and Phase 2)
    notes: Optional[str] = None
    study_type: Optional[str] = None
    tags: Optional[str] = None

    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None


class StudyExternalRef(SQLModel, table=True):
    """
    Tracks additional external IDs for a saved Study so one saved paper can be linked to
    multiple providers (Europe PMC, OpenAlex, Crossref, Semantic Scholar, etc).

    This avoids duplicates while still preserving provenance + alternative IDs.
    """

    __table_args__ = (
        UniqueConstraint("owner_username", "source", "source_id", name="uq_studyext_owner_source_sourceid"),
        UniqueConstraint("study_id", "source", name="uq_studyext_study_source"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    study_id: int = Field(foreign_key="study.id", index=True)

    source: str = Field(index=True)
    source_id: str = Field(index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class StudyMetrics(SQLModel, table=True):
    """
    Optional evidence-scoring / quality assessment record.
    Kept minimal so Phase 1 boots cleanly.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    study_id: int = Field(foreign_key="study.id", index=True)

    # Core metrics (extend later)
    study_type: Optional[str] = Field(default=None, index=True)  # RCT / Meta-analysis / Observational / etc
    evidence_strength: Optional[int] = Field(default=None, ge=0, le=5)  # 0..5
    risk_of_bias: Optional[int] = Field(default=None, ge=0, le=5)  # 0..5
    sample_size: Optional[int] = Field(default=None, ge=0)

    notes: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    study_id: int = Field(foreign_key="study.id", index=True)
    parent_id: Optional[int] = Field(default=None, index=True)

    author: str = Field(index=True)
    body: str

    created_at: datetime = Field(default_factory=datetime.utcnow)