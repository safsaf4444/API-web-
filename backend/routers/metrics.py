from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import Study, StudyMetrics, User

router = APIRouter(tags=["metrics"])


def score(m: StudyMetrics) -> float:
    return (
        (m.save_count * 2.0)
        + (m.folder_count * 1.5)
        + (m.comment_count * 1.0)
        + (m.ai_runs * 1.2)
    )


@router.get("/metrics/trending")
def trending(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    # Phase 2 baseline: trending is per-user library.
    studies = session.exec(select(Study).where(Study.owner_username == current_user.username)).all()

    rows = []
    for s in studies:
        m = session.exec(select(StudyMetrics).where(StudyMetrics.study_id == s.id)).first()
        if not m:
            continue
        rows.append(
            {
                "study_id": s.id,
                "title": s.title,
                "source": s.source,
                "year": s.year,
                "score": score(m),
                "metrics": {
                    "save_count": m.save_count,
                    "folder_count": m.folder_count,
                    "comment_count": m.comment_count,
                    "ai_runs": m.ai_runs,
                    "last_accessed": m.last_accessed,
                },
            }
        )

    rows.sort(key=lambda x: x["score"], reverse=True)
    return {"items": rows[:limit]}