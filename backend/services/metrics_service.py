from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select

from backend.models import Study, StudyMetrics


def get_or_create_metrics(session: Session, study_id: int) -> StudyMetrics:
    m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()
    if m:
        return m
    m = StudyMetrics(study_id=study_id)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def touch_metrics(session: Session, study_id: int) -> None:
    m = get_or_create_metrics(session, study_id)
    m.last_accessed = datetime.utcnow()
    session.add(m)
    session.commit()


def sync_folder_count(session: Session, study: Study) -> None:
    """Derived: 1 if folder_id set else 0 (Phase 2 baseline)."""
    m = get_or_create_metrics(session, study.id)
    m.folder_count = 1 if study.folder_id is not None else 0
    session.add(m)
    session.commit()