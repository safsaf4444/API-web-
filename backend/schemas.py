from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


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
    id: int
    username: str
    email: str


# ---------- Folder ----------
class FolderCreate(BaseModel):
    name: str


class FolderRead(BaseModel):
    id: int
    owner_username: str
    name: str


# ---------- Study ----------
class StudyRead(BaseModel):
    id: int
    owner_username: str
    folder_id: Optional[int]

    source: str
    source_id: str
    title: str
    year: Optional[int]
    venue: Optional[str]
    authors: Optional[str]
    doi: Optional[str]
    url: Optional[str]
    abstract: Optional[str]
    pmid: Optional[str]
    pmcid: Optional[str]

    notes: Optional[str]
    study_type: Optional[str]
    tags: Optional[str]

    ai_summary: Optional[str]
    ai_summary_updated_at: Optional[datetime]


class StudyPatch(BaseModel):
    notes: Optional[str] = None
    folder_id: Optional[int] = None


# ---------- Comments ----------
class CommentRead(BaseModel):
    id: int
    study_id: int
    parent_id: Optional[int] = None
    author: str
    body: str
    created_at: Optional[str] = None


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
