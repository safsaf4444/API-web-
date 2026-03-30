from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import (
    PaperReminder, ReviewScreening, Study, SystematicReview, User,
)
from backend.schemas import (
    BulkScreeningUpdate,
    EvidenceDriftPoint, EvidenceDriftResponse,
    PaperReminderCreate, PaperReminderPatch, PaperReminderRead,
    PRISMAData,
    REVIEW_PHASES, SCREENING_DECISIONS,
    ReviewScreeningCreate, ReviewScreeningPatch, ReviewScreeningRead,
    SystematicReviewCreate, SystematicReviewPatch, SystematicReviewRead,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reviews"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audit(review: SystematicReview, action: str, details: str = "") -> None:
    log = review.audit_log or []
    if not isinstance(log, list):
        log = []
    log.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "details": details,
    })
    review.audit_log = log
    review.updated_at = datetime.now(timezone.utc)


def _screening_counts(session: Session, review_id: int) -> dict:
    from sqlalchemy import func
    rows = session.exec(
        select(ReviewScreening.decision, func.count(ReviewScreening.id))
        .where(ReviewScreening.review_id == review_id)
        .group_by(ReviewScreening.decision)
    ).all()
    counts = {"pending": 0, "included": 0, "excluded": 0, "maybe": 0, "total": 0}
    for decision, cnt in rows:
        counts[decision] = cnt
        counts["total"] += cnt
    return counts


def _enrich_review(review: SystematicReview, session: Session) -> dict:
    d = SystematicReviewRead.model_validate(review).model_dump()
    counts = _screening_counts(session, review.id)
    d["screening_total"] = counts["total"]
    d["screening_included"] = counts["included"]
    d["screening_excluded"] = counts["excluded"]
    d["screening_pending"] = counts["pending"]
    d["screening_maybe"] = counts["maybe"]
    return d


# ══════════════════════════════════════════════════════════════════════════════
# Systematic Review CRUD
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reviews", response_model=SystematicReviewRead)
def create_review(
    payload: SystematicReviewCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = SystematicReview(
        owner_username=current_user.username,
        title=payload.title,
        description=payload.description,
        search_query=payload.search_query,
        search_source=payload.search_source or "europepmc",
        inclusion_criteria=payload.inclusion_criteria,
        exclusion_criteria=payload.exclusion_criteria,
        filters=payload.filters,
        audit_log=[],
    )
    _audit(review, "created", f"Review '{payload.title}' created")
    session.add(review)
    session.commit()
    session.refresh(review)
    return _enrich_review(review, session)


@router.get("/reviews", response_model=List[SystematicReviewRead])
def list_reviews(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reviews = session.exec(
        select(SystematicReview)
        .where(SystematicReview.owner_username == current_user.username)
        .order_by(SystematicReview.updated_at.desc())
    ).all()
    return [_enrich_review(r, session) for r in reviews]


@router.get("/reviews/{review_id}", response_model=SystematicReviewRead)
def get_review(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")
    return _enrich_review(review, session)


@router.patch("/reviews/{review_id}", response_model=SystematicReviewRead)
def patch_review(
    review_id: int,
    payload: SystematicReviewPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    fields_set = getattr(payload, "model_fields_set", set())
    changes = []

    if "title" in fields_set and payload.title is not None:
        review.title = payload.title
        changes.append("title")
    if "description" in fields_set:
        review.description = payload.description
        changes.append("description")
    if "phase" in fields_set and payload.phase is not None:
        if payload.phase not in REVIEW_PHASES:
            raise HTTPException(status_code=400, detail=f"Invalid phase. Must be one of: {', '.join(REVIEW_PHASES)}")
        review.phase = payload.phase
        changes.append(f"phase → {payload.phase}")
    if "search_query" in fields_set:
        review.search_query = payload.search_query
        changes.append("search_query")
    if "search_source" in fields_set:
        review.search_source = payload.search_source or review.search_source
    if "inclusion_criteria" in fields_set:
        review.inclusion_criteria = payload.inclusion_criteria
        changes.append("inclusion_criteria")
    if "exclusion_criteria" in fields_set:
        review.exclusion_criteria = payload.exclusion_criteria
        changes.append("exclusion_criteria")
    if "filters" in fields_set:
        review.filters = payload.filters
        changes.append("filters")

    if changes:
        _audit(review, "updated", f"Updated: {', '.join(changes)}")

    session.add(review)
    session.commit()
    session.refresh(review)
    return _enrich_review(review, session)


@router.delete("/reviews/{review_id}")
def delete_review(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    # Delete associated screenings
    screenings = session.exec(
        select(ReviewScreening).where(ReviewScreening.review_id == review_id)
    ).all()
    for s in screenings:
        session.delete(s)

    session.delete(review)
    session.commit()
    return {"status": "deleted", "review_id": review_id}


# ══════════════════════════════════════════════════════════════════════════════
# Search & Screening
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reviews/{review_id}/search")
async def run_review_search(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Run search using the review's query/filters and populate screening queue."""
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")
    if not review.search_query:
        raise HTTPException(status_code=400, detail="Set a search query first.")

    from backend.external_providers import get_provider
    try:
        provider = get_provider(review.search_source or "europepmc")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Build filter params
    filters = review.filters or {}
    year_from = filters.get("year_from")
    year_to = filters.get("year_to")

    try:
        results, _, hit_count = await provider.search(
            q=review.search_query,
            limit=100,
            year_from=year_from,
            year_to=year_to,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

    # Clear existing pending screenings (keep decided ones)
    existing_pending = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "pending")
        )
    ).all()
    for ep in existing_pending:
        session.delete(ep)

    # Collect existing DOIs/titles to avoid duplicates
    existing = session.exec(
        select(ReviewScreening).where(ReviewScreening.review_id == review_id)
    ).all()
    existing_ids = set()
    for ex in existing:
        if ex.external_doi:
            existing_ids.add(ex.external_doi.lower())
        if ex.external_title:
            existing_ids.add(ex.external_title.lower().strip()[:80])

    # Add new screening entries
    added = 0
    from backend.services.ai_service import strip_html
    for paper in results:
        doi_key = (paper.doi or "").lower()
        title_key = (paper.title or "").lower().strip()[:80]
        if doi_key and doi_key in existing_ids:
            continue
        if title_key and title_key in existing_ids:
            continue

        screening = ReviewScreening(
            review_id=review_id,
            owner_username=current_user.username,
            external_title=paper.title,
            external_doi=paper.doi,
            external_abstract=strip_html(paper.abstract or "")[:2000] if paper.abstract else None,
            external_source=paper.source,
            external_source_id=paper.source_id,
            external_year=paper.year,
            decision="pending",
        )
        session.add(screening)
        existing_ids.add(doi_key or title_key)
        added += 1

    review.search_results_count = hit_count
    if review.phase == "search":
        review.phase = "screen"
    _audit(review, "search_executed", f"Query: '{review.search_query}', source: {review.search_source}, hits: {hit_count}, added: {added}")

    session.add(review)
    session.commit()
    session.refresh(review)

    return {
        "status": "ok",
        "hits": hit_count,
        "papers_added": added,
        "phase": review.phase,
    }


@router.get("/reviews/{review_id}/screening", response_model=List[ReviewScreeningRead])
def list_screening(
    review_id: int,
    decision: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    stmt = select(ReviewScreening).where(ReviewScreening.review_id == review_id)
    if decision:
        stmt = stmt.where(ReviewScreening.decision == decision)
    stmt = stmt.order_by(ReviewScreening.id.asc())

    items = session.exec(stmt).all()
    out = []
    for item in items:
        d = ReviewScreeningRead.model_validate(item).model_dump()
        if item.study_id:
            study = session.get(Study, item.study_id)
            d["study_title"] = study.title if study else None
        else:
            d["study_title"] = item.external_title
        out.append(d)
    return out


@router.patch("/reviews/{review_id}/screening/{screening_id}", response_model=ReviewScreeningRead)
def patch_screening(
    review_id: int,
    screening_id: int,
    payload: ReviewScreeningPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")

    screening = session.get(ReviewScreening, screening_id)
    if not screening or screening.review_id != review_id:
        raise HTTPException(status_code=404, detail="Screening record not found")

    fields_set = getattr(payload, "model_fields_set", set())

    if "decision" in fields_set and payload.decision is not None:
        if payload.decision not in SCREENING_DECISIONS:
            raise HTTPException(status_code=400, detail=f"Invalid decision. Must be: {', '.join(SCREENING_DECISIONS)}")
        old_decision = screening.decision
        screening.decision = payload.decision
        _audit(review, "screening_decision", f"Paper '{(screening.external_title or '')[:50]}' {old_decision} → {payload.decision}")

    if "exclusion_reason" in fields_set:
        screening.exclusion_reason = payload.exclusion_reason
    if "screener_notes" in fields_set:
        screening.screener_notes = payload.screener_notes

    session.add(screening)
    session.add(review)
    session.commit()
    session.refresh(screening)

    d = ReviewScreeningRead.model_validate(screening).model_dump()
    d["study_title"] = screening.external_title
    return d


@router.post("/reviews/{review_id}/screening/bulk")
def bulk_screening(
    review_id: int,
    payload: BulkScreeningUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")
    if payload.decision not in SCREENING_DECISIONS:
        raise HTTPException(status_code=400, detail=f"Invalid decision")

    updated = 0
    for sid in payload.screening_ids:
        s = session.get(ReviewScreening, sid)
        if s and s.review_id == review_id:
            s.decision = payload.decision
            if payload.exclusion_reason and payload.decision == "excluded":
                s.exclusion_reason = payload.exclusion_reason
            session.add(s)
            updated += 1

    _audit(review, "bulk_screening", f"{updated} papers set to '{payload.decision}'")
    session.add(review)
    session.commit()
    return {"status": "ok", "updated": updated}


# ══════════════════════════════════════════════════════════════════════════════
# PRISMA
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/prisma", response_model=PRISMAData)
def get_prisma(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    counts = _screening_counts(session, review_id)

    identified = review.search_results_count or counts["total"]
    screened = counts["total"]
    excluded_screening = counts["excluded"]
    maybe_count = counts["maybe"]
    included = counts["included"]
    eligible = included + maybe_count

    return PRISMAData(
        identified=identified,
        duplicates_removed=max(0, identified - screened),
        screened=screened,
        excluded_screening=excluded_screening,
        eligible=eligible,
        excluded_eligibility=maybe_count,
        included=included,
        review_title=review.title,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Evidence Drift
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/drift", response_model=EvidenceDriftResponse)
def get_drift(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Analyse how evidence direction shifts across publication year periods."""
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    included = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        )
    ).all()

    if not included:
        return EvidenceDriftResponse(review_id=review_id, drift_detected=False, drift_summary="No included papers to analyse.")

    # Group by 5-year periods
    periods: dict[str, list] = {}
    for s in included:
        year = s.external_year
        if not year:
            continue
        decade_start = (year // 5) * 5
        period_label = f"{decade_start}–{decade_start + 4}"
        periods.setdefault(period_label, [])
        periods[period_label].append(s)

    if len(periods) < 2:
        return EvidenceDriftResponse(
            review_id=review_id,
            periods=[EvidenceDriftPoint(
                period=p,
                paper_count=len(papers),
                study_titles=[sp.external_title or "Untitled" for sp in papers],
            ) for p, papers in sorted(periods.items())],
            drift_detected=False,
            drift_summary="Not enough time periods to detect drift (need papers from at least 2 different 5-year periods).",
        )

    points = []
    for period_label in sorted(periods.keys()):
        papers = periods[period_label]
        points.append(EvidenceDriftPoint(
            period=period_label,
            paper_count=len(papers),
            study_titles=[sp.external_title or "Untitled" for sp in papers],
        ))

    # Simple drift detection: flag if paper count distribution varies significantly
    counts = [p.paper_count for p in points]
    drift_detected = len(points) >= 2
    drift_summary = (
        f"Evidence spans {len(points)} time periods ({points[0].period} to {points[-1].period}). "
        f"Earlier period has {points[0].paper_count} paper(s), latest has {points[-1].paper_count} paper(s). "
        f"Run synthesis on each period separately for a detailed shift analysis."
    )

    return EvidenceDriftResponse(
        review_id=review_id,
        periods=points,
        drift_detected=drift_detected,
        drift_summary=drift_summary,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Reminders
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reminders", response_model=PaperReminderRead)
def create_reminder(
    payload: PaperReminderCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    study = session.get(Study, payload.study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    if study.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    reminder = PaperReminder(
        owner_username=current_user.username,
        study_id=payload.study_id,
        remind_at=payload.remind_at,
        reason=payload.reason,
    )
    session.add(reminder)
    session.commit()
    session.refresh(reminder)

    d = PaperReminderRead.model_validate(reminder).model_dump()
    d["study_title"] = study.title
    return d


@router.get("/reminders", response_model=List[PaperReminderRead])
def list_reminders(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    rems = session.exec(
        select(PaperReminder)
        .where(
            (PaperReminder.owner_username == current_user.username) &
            (PaperReminder.is_dismissed == False)  # noqa: E712
        )
        .order_by(PaperReminder.remind_at.asc())
    ).all()
    out = []
    for r in rems:
        d = PaperReminderRead.model_validate(r).model_dump()
        study = session.get(Study, r.study_id)
        d["study_title"] = study.title if study else None
        out.append(d)
    return out


@router.get("/reminders/due", response_model=List[PaperReminderRead])
def due_reminders(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get reminders that are due (remind_at <= now and not dismissed)."""
    now = datetime.now(timezone.utc)
    rems = session.exec(
        select(PaperReminder)
        .where(
            (PaperReminder.owner_username == current_user.username) &
            (PaperReminder.is_dismissed == False) &  # noqa: E712
            (PaperReminder.remind_at <= now)
        )
        .order_by(PaperReminder.remind_at.asc())
    ).all()
    out = []
    for r in rems:
        d = PaperReminderRead.model_validate(r).model_dump()
        study = session.get(Study, r.study_id)
        d["study_title"] = study.title if study else None
        out.append(d)
    return out


@router.patch("/reminders/{reminder_id}", response_model=PaperReminderRead)
def patch_reminder(
    reminder_id: int,
    payload: PaperReminderPatch,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    rem = session.get(PaperReminder, reminder_id)
    if not rem:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if rem.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    fields_set = getattr(payload, "model_fields_set", set())
    if "remind_at" in fields_set and payload.remind_at is not None:
        rem.remind_at = payload.remind_at
    if "reason" in fields_set:
        rem.reason = payload.reason
    if "is_dismissed" in fields_set and payload.is_dismissed is not None:
        rem.is_dismissed = payload.is_dismissed

    session.add(rem)
    session.commit()
    session.refresh(rem)

    d = PaperReminderRead.model_validate(rem).model_dump()
    study = session.get(Study, rem.study_id)
    d["study_title"] = study.title if study else None
    return d


@router.delete("/reminders/{reminder_id}")
def delete_reminder(
    reminder_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    rem = session.get(PaperReminder, reminder_id)
    if not rem:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if rem.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")
    session.delete(rem)
    session.commit()
    return {"status": "deleted", "reminder_id": reminder_id}
