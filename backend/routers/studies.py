from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import Comment, Folder, ReadingStatus, Study, StudyMetrics, User
from backend.schemas import StudyRead, StudyPatch

try:
    from backend.services.metrics_service import sync_folder_count, touch_metrics
except Exception:  # pragma: no cover
    sync_folder_count = None
    touch_metrics = None

logger = logging.getLogger(__name__)

router = APIRouter(tags=["studies"])


@router.get("/studies", response_model=List[StudyRead])
def list_studies(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    q: Optional[str] = Query(default=None, description="Search title + abstract"),
    sort: str = Query(default="newest", description="newest|oldest|year_desc|year_asc|title_asc|title_desc"),
    folder_id: Optional[int] = Query(default=None),
    reading_status: Optional[ReadingStatus] = Query(default=None, description="Filter by reading status"),
):
    stmt = select(Study).where(Study.owner_username == current_user.username)

    if folder_id is not None:
        stmt = stmt.where(Study.folder_id == folder_id)

    if reading_status is not None:
        stmt = stmt.where(Study.reading_status == reading_status)

    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Study.title.ilike(needle), Study.abstract.ilike(needle)))

    # --- Existing Sorting Logic ---
    sort_key = (sort or "newest").strip().lower()
    if sort_key == "oldest":
        stmt = stmt.order_by(Study.id.asc())
    elif sort_key == "year_desc":
        stmt = stmt.order_by(Study.year.desc().nullslast(), Study.id.desc())
    elif sort_key == "year_asc":
        stmt = stmt.order_by(Study.year.asc().nullsfirst(), Study.id.desc())
    elif sort_key == "title_asc":
        stmt = stmt.order_by(Study.title.asc(), Study.id.desc())
    elif sort_key == "title_desc":
        stmt = stmt.order_by(Study.title.desc(), Study.id.desc())
    else:
        stmt = stmt.order_by(Study.id.desc())

    # --- Safe Data Fix for Phase 3 ---
    # Fetch results first
    results = session.exec(stmt).all()
    
    # If any existing studies have no status (old data), default them to 'unread'
    # so the Enum validation doesn't crash the response.
    for study in results:
        if not study.reading_status:
            study.reading_status = ReadingStatus.UNREAD
            
    return results


@router.get("/studies/{study_id}", response_model=StudyRead)
def get_study(
    study_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    if touch_metrics is not None:
        try:
            touch_metrics(session, study.id, study.owner_username)
        except Exception as e:
            logger.warning("touch_metrics failed (non-fatal) for study_id=%s: %s", study.id, e)

    return study


@router.patch("/studies/{study_id}", response_model=StudyRead)
def patch_study(
    study_id: int,
    payload: StudyPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    fields_set = getattr(payload, "model_fields_set", set())

    if "notes" in fields_set:
        study.notes = payload.notes

    if "folder_id" in fields_set:
        if payload.folder_id is None:
            study.folder_id = None
        else:
            f = session.get(Folder, payload.folder_id)
            if not f or f.owner_username != current_user.username:
                raise HTTPException(status_code=400, detail="Invalid folder_id")
            study.folder_id = payload.folder_id

    # Phase 3: reading status
    if "reading_status" in fields_set and payload.reading_status is not None:
        study.reading_status = payload.reading_status

    session.add(study)
    session.commit()
    session.refresh(study)

    if sync_folder_count is not None:
        try:
            sync_folder_count(session, study)
        except Exception as e:
            logger.warning("sync_folder_count failed (non-fatal) for study_id=%s: %s", study.id, e)

    return study


@router.delete("/studies/{study_id}")
def delete_study(
    study_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    comments = session.exec(select(Comment).where(Comment.study_id == study_id)).all()
    for c in comments:
        session.delete(c)

    try:
        m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == study_id)).first()
        if m:
            session.delete(m)
    except Exception as e:
        logger.warning("StudyMetrics delete cleanup failed (non-fatal) for study_id=%s: %s", study_id, e)

    session.delete(study)
    session.commit()
    return {"status": "deleted", "study_id": study_id}