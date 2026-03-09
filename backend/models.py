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
    ai_key_enc: Optional[str] = Field(default=None)


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

    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None


class StudyExternalRef(SQLModel, table=True):
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
    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    study_id: int = Field(foreign_key="study.id", index=True)

    # Evidence scoring
    study_type: Optional[str] = Field(default=None, index=True)
    evidence_strength: Optional[int] = Field(default=None, ge=0, le=5)
    risk_of_bias: Optional[int] = Field(default=None, ge=0, le=5)
    sample_size: Optional[int] = Field(default=None, ge=0)

    # FIX: these 5 fields were missing — caused crash in metrics_service
    save_count: int = Field(default=0)
    folder_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    ai_runs: int = Field(default=0)
    last_accessed: Optional[datetime] = Field(default=None)

    notes: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AIResult(SQLModel, table=True):
    """
    FIX: This model was imported in routers/ai.py but never defined.
    Caused an ImportError on every startup — all /ai/* endpoints were dead.
    """
    id: Optional[int] = Field(default=None, primary_key=True)

    owner_username: str = Field(index=True)
    cache_key: str = Field(index=True)
    kind: str = Field(index=True)  # "summarize" | "ask"
    model_used: str = Field(default="byok")

    question: Optional[str] = None
    summary: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    study_id: int = Field(foreign_key="study.id", index=True)
    parent_id: Optional[int] = Field(default=None, index=True)

    author: str = Field(index=True)
    body: str

    created_at: datetime = Field(default_factory=datetime.utcnow)