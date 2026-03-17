from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.models import Study, StudyMetrics


def get_or_create_metrics(session: Session, study_id: int, owner_username: str) -> StudyMetrics:
    m = session.exec(
        select(StudyMetrics).where(StudyMetrics.study_id == study_id)
    ).first()
    if m:
        return m
    m = StudyMetrics(
        study_id=study_id,
        owner_username=owner_username,
        save_count=0,
        folder_count=0,
        comment_count=0,
        ai_runs=0,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def touch_metrics(session: Session, study_id: int, owner_username: str) -> None:
    """Update last_accessed timestamp. Call whenever a user opens a paper."""
    m = get_or_create_metrics(session, study_id, owner_username)
    m.last_accessed = datetime.now(timezone.utc)
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()


def increment_ai_runs(session: Session, study_id: int, owner_username: str) -> None:
    """Increment ai_runs counter. Call after every successful AI response."""
    m = get_or_create_metrics(session, study_id, owner_username)
    m.ai_runs = (m.ai_runs or 0) + 1
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()


def increment_comment_count(session: Session, study_id: int, owner_username: str) -> None:
    """Increment comment_count. Call after a comment is posted."""
    m = get_or_create_metrics(session, study_id, owner_username)
    m.comment_count = (m.comment_count or 0) + 1
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()


def sync_folder_count(session: Session, study: Study) -> None:
    """Derived: 1 if folder_id set else 0."""
    m = get_or_create_metrics(session, study.id, study.owner_username)
    m.folder_count = 1 if study.folder_id is not None else 0
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()


def on_study_saved(session: Session, study: Study) -> None:
    """Call once when a paper is first imported/saved."""
    m = get_or_create_metrics(session, study.id, study.owner_username)
    m.save_count = (m.save_count or 0) + 1
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()


# ── Phase 3: write clinical intelligence back to metrics row ──────────────────

def write_clinical_data(
    session: Session,
    study_id: int,
    owner_username: str,
    pico_data: dict,
    statistical_data: dict,
    evidence_strength: int | None,
    risk_of_bias: str | None,
) -> StudyMetrics:
    """
    Persist structured clinical extraction to the StudyMetrics row.
    Called by the /ai/clinical endpoint after a successful AI extraction.
    """
    m = get_or_create_metrics(session, study_id, owner_username)
    m.pico_data = pico_data
    m.statistical_data = statistical_data
    if evidence_strength is not None:
        m.evidence_strength = max(0, min(5, evidence_strength))
    if risk_of_bias is not None:
        m.risk_of_bias = risk_of_bias
    m.updated_at = datetime.now(timezone.utc)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m