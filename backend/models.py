from __future__ import annotations
import enum
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import UniqueConstraint, Column, JSON
from sqlmodel import Field, SQLModel


# ── Enums ─────────────────────────────────────────────────────────────────────

class ReadingStatus(str, enum.Enum):
    UNREAD  = "unread"
    READING = "reading"
    DONE    = "done"
    FLAGGED = "flagged"


# ── User Management ───────────────────────────────────────────────────────────

class User(SQLModel, table=True):
    id:               Optional[int] = Field(default=None, primary_key=True)
    username:         str            = Field(index=True, unique=True)
    email:            str            = Field(index=True, unique=True)
    hashed_password:  str
    ai_key_enc:       Optional[str]  = Field(default=None)
    is_verified:      bool           = Field(default=False)


# ── Organisation ──────────────────────────────────────────────────────────────

class Folder(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "name", name="uq_folder_owner_name"),)

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    name:           str           = Field(index=True)


# ── Core Research Data ────────────────────────────────────────────────────────

class Study(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "source", "source_id", name="uq_study_owner_source_id"),)

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    folder_id:      Optional[int] = Field(default=None, foreign_key="folder.id", index=True)

    source:    str           = Field(index=True)
    source_id: str           = Field(index=True)
    title:     str
    year:      Optional[int] = Field(default=None, index=True)
    venue:     Optional[str] = None
    authors:   Optional[str] = None

    doi:   Optional[str] = Field(default=None, index=True)
    url:   Optional[str] = None

    abstract: Optional[str] = None
    pmid:     Optional[str] = Field(default=None, index=True)
    pmcid:    Optional[str] = Field(default=None, index=True)

    notes:      Optional[str] = None
    study_type: Optional[str] = None
    tags:       Optional[str] = None

    reading_status:         str            = Field(default="unread", index=True)
    ai_summary:             Optional[str]  = None
    ai_summary_updated_at:  Optional[datetime] = None

    citation_count: Optional[int] = Field(default=None)
    is_retracted:   bool          = Field(default=False)


class StudyExternalRef(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("owner_username", "source", "source_id", name="uq_studyext_owner_source_sourceid"),
        UniqueConstraint("study_id", "source", name="uq_studyext_study_source"),
    )

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    study_id:       int           = Field(foreign_key="study.id", index=True)
    source:         str           = Field(index=True)
    source_id:      str           = Field(index=True)
    created_at:     datetime      = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)


# ── Evidence & Intelligence ───────────────────────────────────────────────────

class StudyMetrics(SQLModel, table=True):
    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    study_id:       int           = Field(foreign_key="study.id", index=True)

    study_type:        Optional[str] = Field(default=None, index=True)
    evidence_strength: Optional[int] = Field(default=None, ge=0, le=5)
    risk_of_bias:      Optional[str] = Field(default=None)
    sample_size:       Optional[int] = Field(default=None, ge=0)

    pico_data:        Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    statistical_data: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    save_count:    int = Field(default=0)
    folder_count:  int = Field(default=0)
    comment_count: int = Field(default=0)
    ai_runs:       int = Field(default=0)

    notes:         Optional[str]     = None
    updated_at:    datetime          = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: Optional[datetime] = Field(default=None)


class AIResult(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_username", "cache_key", "kind", name="uq_airesult_owner_key_kind"),)

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    cache_key:      str           = Field(index=True)
    kind:           str           = Field(index=True)

    model_used:     str          = Field(default="byok")
    prompt_version: str          = Field(default="3.0")
    question:       Optional[str] = None
    summary:        Optional[str] = None

    patient_summary:   Optional[str] = None
    clinician_summary: Optional[str] = None
    student_summary:   Optional[str] = None

    share_token: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Phase 4: Multi-Paper Synthesis ───────────────────────────────────────────

class SynthesisResult(SQLModel, table=True):
    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    cache_key:      str           = Field(index=True)
    study_ids:      str           = Field(default="[]")

    mode:  str           = Field(default="multi_paper", index=True)
    query: Optional[str] = None

    synthesis_narrative:   Optional[str] = None
    consensus_points:      Optional[str] = None
    contradictions:        Optional[str] = None
    gap_analysis:          Optional[str] = None
    weighted_conclusion:   Optional[str] = None
    steel_man:             Optional[str] = None
    comparative_methodology: Optional[str] = None
    weighting_breakdown:   Optional[str] = None

    prompt_version: str = Field(default="4.0")
    model_used:     str = Field(default="unknown")
    paper_count:    int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Social: Comments (paper threads) ─────────────────────────────────────────

class Comment(SQLModel, table=True):
    id:        Optional[int] = Field(default=None, primary_key=True)
    study_id:  int           = Field(foreign_key="study.id", index=True)
    parent_id: Optional[int] = Field(default=None, index=True)

    author: str = Field(index=True)
    body:   str

    upvotes: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommentUpvote(SQLModel, table=True):
    """Tracks which users have upvoted which comments (prevents double-upvote)."""
    __table_args__ = (UniqueConstraint("username", "comment_id", name="uq_comment_upvote"),)

    id:         Optional[int] = Field(default=None, primary_key=True)
    username:   str           = Field(index=True)
    comment_id: int           = Field(foreign_key="comment.id", index=True)
    created_at: datetime      = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Notebook ──────────────────────────────────────────────────────────────────

class NotebookPage(SQLModel, table=True):
    """A page in a user's notebook. May be linked to a study or standalone."""
    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    study_id:       Optional[int] = Field(default=None, foreign_key="study.id", index=True)

    title:   str           = Field(default="Untitled")
    content: Optional[str] = None          # rich text / markdown
    color:   str           = Field(default="default")   # default, yellow, green, blue, pink

    is_pinned: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Highlight(SQLModel, table=True):
    """A text highlight made on a paper's abstract or full text."""
    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    study_id:       int           = Field(foreign_key="study.id", index=True)

    selected_text: str           # the highlighted text
    color:         str           = Field(default="yellow")   # yellow, green, blue, pink
    annotation:    Optional[str] = None    # optional note attached to highlight
    section:       Optional[str] = None    # "abstract" | "fulltext"
    char_start:    Optional[int] = None    # character offset in source text
    char_end:      Optional[int] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Community ─────────────────────────────────────────────────────────────────

class CommunityPost(SQLModel, table=True):
    id:           Optional[int] = Field(default=None, primary_key=True)
    author:       Optional[str] = Field(default=None, index=True)  # None = anonymous
    is_anonymous: bool          = Field(default=False)

    title:     str
    body:      str
    post_type: str           = Field(default="discussion", index=True)
    # post_type: "question" | "discussion" | "case_study" | "resource"
    tags:      Optional[str] = None        # comma-separated clinical topic tags

    study_id: Optional[int] = Field(default=None, foreign_key="study.id")  # linked Seren paper

    upvotes:     int  = Field(default=0)
    reply_count: int  = Field(default=0)
    is_deleted:  bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommunityReply(SQLModel, table=True):
    id:             Optional[int] = Field(default=None, primary_key=True)
    post_id:        int           = Field(foreign_key="communitypost.id", index=True)
    parent_reply_id: Optional[int] = Field(default=None, index=True)  # nested replies

    author:       Optional[str] = Field(default=None, index=True)
    is_anonymous: bool          = Field(default=False)
    body:         str

    upvotes:    int  = Field(default=0)
    is_deleted: bool = Field(default=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommunityUpvote(SQLModel, table=True):
    """Prevents double-upvoting on posts or replies."""
    __table_args__ = (UniqueConstraint("username", "target_id", "target_type", name="uq_community_upvote"),)

    id:          Optional[int] = Field(default=None, primary_key=True)
    username:    str           = Field(index=True)
    target_id:   int
    target_type: str           # "post" | "reply"
    created_at:  datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))


class Bookmark(SQLModel, table=True):
    """User bookmarks on community posts or replies."""
    __table_args__ = (UniqueConstraint("owner_username", "target_id", "target_type", name="uq_bookmark"),)

    id:             Optional[int] = Field(default=None, primary_key=True)
    owner_username: str           = Field(index=True)
    target_id:      int
    target_type:    str           # "post" | "reply"
    created_at:     datetime     = Field(default_factory=lambda: datetime.now(timezone.utc))