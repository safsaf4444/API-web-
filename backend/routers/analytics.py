from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import Study, StudyMetrics, User

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _studies_for(session: Session, username: str, folder_id: Optional[int] = None):
    stmt = select(Study).where(Study.owner_username == username)
    if folder_id is not None:
        stmt = stmt.where(Study.folder_id == folder_id)
    return list(session.exec(stmt).all())


@router.get("/study-types")
def study_types(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    counts: Dict[str, int] = Counter(
        (s.study_type or "unknown") for s in studies
    )
    return [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


@router.get("/publication-years")
def publication_years(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    counts: Dict[int, int] = Counter(s.year for s in studies if s.year)
    return [{"year": k, "count": v} for k, v in sorted(counts.items())]


@router.get("/evidence-scatter")
def evidence_scatter(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    ids = [s.id for s in studies if s.id]
    if not ids:
        return []

    metrics_map: Dict[int, StudyMetrics] = {}
    for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all():
        metrics_map[m.study_id] = m

    out = []
    for s in studies:
        if not s.year or s.id not in metrics_map:
            continue
        m = metrics_map[s.id]
        if m.evidence_strength is None:
            continue
        out.append({
            "id": s.id,
            "x": s.year,
            "y": m.evidence_strength,
            "title": s.title,
            "study_type": s.study_type or "unknown",
        })
    return out


@router.get("/effect-sizes")
def effect_sizes(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    ids = [s.id for s in studies if s.id]
    if not ids:
        return []

    out = []
    for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all():
        stats = m.statistical_data or {}
        es = stats.get("effect_size")
        if es is not None:
            study = next((s for s in studies if s.id == m.study_id), None)
            out.append({
                "study_id": m.study_id,
                "title": study.title if study else f"Study {m.study_id}",
                "effect_size": es,
                "year": study.year if study else None,
            })
    return out


@router.get("/sample-sizes")
def sample_sizes(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    ids = [s.id for s in studies if s.id]
    if not ids:
        return []

    out = []
    for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all():
        if m.sample_size is not None:
            study = next((s for s in studies if s.id == m.study_id), None)
            out.append({
                "study_id": m.study_id,
                "title": study.title if study else f"Study {m.study_id}",
                "sample_size": m.sample_size,
            })
    return out


@router.get("/journals")
def top_journals(
    top_n: int = Query(default=20, ge=1, le=100),
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    counts: Dict[str, int] = Counter(
        s.venue for s in studies if s.venue and s.venue.strip()
    )
    top = counts.most_common(top_n)
    return [{"journal": k, "count": v} for k, v in top]


@router.get("/authors")
def top_authors(
    top_n: int = Query(default=20, ge=1, le=100),
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    author_counter: Counter = Counter()
    for s in studies:
        if not s.authors:
            continue
        for name in s.authors.split(","):
            name = name.strip()
            if name:
                author_counter[name] += 1
    top = author_counter.most_common(top_n)
    return [{"author": k, "count": v} for k, v in top]


@router.get("/bias-heatmap")
def bias_heatmap(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    ids = [s.id for s in studies if s.id]
    if not ids:
        return []

    metrics_map: Dict[int, StudyMetrics] = {
        m.study_id: m
        for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all()
    }

    out = []
    for s in studies:
        m = metrics_map.get(s.id)
        bias_score = m.extracted_bias_score if m and hasattr(m, "extracted_bias_score") else None
        # Use study-level bias if metrics not populated
        grade = m.pico_data or {} if m else {}
        out.append({
            "id": s.id,
            "title": s.title,
            "year": s.year,
            "study_type": s.study_type or "unknown",
            "risk_of_bias": m.risk_of_bias if m else None,
            "evidence_strength": m.evidence_strength if m else None,
            "sample_size": m.sample_size if m else None,
        })
    return out


@router.get("/usage-heatmap")
def usage_heatmap(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    metrics = session.exec(
        select(StudyMetrics).where(
            StudyMetrics.owner_username == user.username,
            StudyMetrics.last_accessed.isnot(None),
        )
    ).all()

    date_counts: Dict[str, int] = Counter()
    for m in metrics:
        if m.last_accessed:
            date_str = m.last_accessed.strftime("%Y-%m-%d")
            date_counts[date_str] += 1

    return [{"date": k, "count": v} for k, v in sorted(date_counts.items())]


@router.get("/evidence-leaderboard")
def evidence_leaderboard(
    top_n: int = Query(default=20, ge=1, le=100),
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    studies = _studies_for(session, user.username, folder_id)
    ids = [s.id for s in studies if s.id]
    if not ids:
        return []

    metrics_map = {
        m.study_id: m
        for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all()
    }

    rows = []
    for s in studies:
        m = metrics_map.get(s.id)
        rows.append({
            "id": s.id,
            "title": s.title,
            "year": s.year,
            "study_type": s.study_type or "unknown",
            "evidence_strength": m.evidence_strength if m else None,
            "sample_size": m.sample_size if m else None,
            "citation_count": s.citation_count,
            "doi": s.doi,
        })

    rows.sort(key=lambda r: (r["evidence_strength"] or 0, r["citation_count"] or 0), reverse=True)
    return rows[:top_n]


@router.get("/summary")
def analytics_summary(
    folder_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Single endpoint that returns all analytics in one call for dashboard init."""
    studies = _studies_for(session, user.username, folder_id)
    total   = len(studies)
    if total == 0:
        return {"total": 0, "study_types": [], "years": [], "journals": [], "authors": []}

    ids = [s.id for s in studies if s.id]
    metrics_map = {
        m.study_id: m
        for m in session.exec(select(StudyMetrics).where(StudyMetrics.study_id.in_(ids))).all()
    }

    study_types = Counter((s.study_type or "unknown") for s in studies)
    years       = Counter(s.year for s in studies if s.year)
    journals    = Counter(s.venue for s in studies if s.venue and s.venue.strip())
    authors_ctr: Counter = Counter()
    for s in studies:
        if s.authors:
            for a in s.authors.split(","):
                a = a.strip()
                if a:
                    authors_ctr[a] += 1

    scatter = []
    for s in studies:
        m = metrics_map.get(s.id)
        if s.year and m and m.evidence_strength is not None:
            scatter.append({"id": s.id, "x": s.year, "y": m.evidence_strength, "title": s.title, "study_type": s.study_type or "unknown"})

    return {
        "total": total,
        "study_types":  [{"label": k, "count": v} for k, v in study_types.most_common(15)],
        "years":        [{"year": k, "count": v} for k, v in sorted(years.items())],
        "journals":     [{"journal": k, "count": v} for k, v in journals.most_common(20)],
        "authors":      [{"author": k, "count": v} for k, v in authors_ctr.most_common(20)],
        "scatter":      scatter,
        "retracted":    sum(1 for s in studies if s.is_retracted),
        "open_access":  sum(1 for s in studies if getattr(s, "full_text_url", None)),
    }
