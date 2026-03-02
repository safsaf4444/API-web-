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

    source: str = Field(index=True)        # europepmc / semantic_scholar
    source_id: str = Field(index=True)     # provider record id

    title: str
    year: Optional[int] = Field(default=None, index=True)
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

    ai_summary: Optional[str] = None
    ai_summary_updated_at: Optional[datetime] = None


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    study_id: int = Field(foreign_key="study.id", index=True)
    parent_id: Optional[int] = Field(default=None, index=True)

    author: str = Field(index=True)
    body: str

    created_at: datetime = Field(default_factory=datetime.utcnow)
