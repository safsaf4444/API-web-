from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import io
import tempfile
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from backend.ai_secure import decrypt_api_key
from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import (
    AIResult, PaperReminder, ReviewScreening, Study, SystematicReview, User,
)
from backend.schemas import (
    BiasCell, BiasHeatmapResponse,
    BulkScreeningUpdate,
    CitationEdge, CitationNetworkResponse, CitationNode,
    CumulativeStatPoint, CumulativeStatsResponse,
    EvidenceDriftPoint, EvidenceDriftResponse,
    KeyPaper, KeyPapersResponse,
    NetworkEdge, NetworkNode, NetworkResponse,
    PaperReminderCreate, PaperReminderPatch, PaperReminderRead,
    PRISMAData,
    REVIEW_PHASES, SCREENING_DECISIONS,
    ReviewAskRequest, ReviewAskResponse,
    ReviewScreeningCreate, ReviewScreeningPatch, ReviewScreeningRead,
    SupportingStudy, VerdictRequest, VerdictResponse,
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


def _get_byok_keys(user: User) -> dict:
    if not user.ai_key_enc:
        return {}
    try:
        key = decrypt_api_key(user.ai_key_enc)
    except Exception:
        return {}
    if key.startswith("sk-ant-"): return {"anthropic_key": key}
    if key.startswith("AIza"):    return {"gemini_key": key}
    if key.startswith("gsk_"):    return {"groq_key": key}
    return {"openai_key": key}


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
    if "evidence_notes" in fields_set:
        review.evidence_notes = payload.evidence_notes
        changes.append("evidence_notes")

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
async def get_drift(
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

    # Group by 5-year periods, enriching with Study extraction data
    periods: dict[str, list] = {}
    for s in included:
        year = s.external_year
        if not year:
            continue
        decade_start = (year // 5) * 5
        period_label = f"{decade_start}–{decade_start + 4}"
        periods.setdefault(period_label, [])
        study = session.get(Study, s.study_id) if s.study_id else None
        periods[period_label].append((s, study))

    if len(periods) < 2:
        return EvidenceDriftResponse(
            review_id=review_id,
            periods=[EvidenceDriftPoint(
                period=p,
                paper_count=len(papers),
                study_titles=[(sp.external_title or "Untitled") for sp, _ in papers],
            ) for p, papers in sorted(periods.items())],
            drift_detected=False,
            drift_summary="Not enough time periods to detect drift (need papers from at least 2 different 5-year periods).",
        )

    points = []
    for period_label in sorted(periods.keys()):
        paper_pairs = periods[period_label]
        outcome_vals = [st.extracted_outcome_value for _, st in paper_pairs if st and st.extracted_outcome_value is not None]
        bias_vals    = [st.extracted_bias_score    for _, st in paper_pairs if st and st.extracted_bias_score    is not None]
        avg_outcome  = round(sum(outcome_vals) / len(outcome_vals), 4) if outcome_vals else None
        avg_bias     = round(sum(bias_vals)    / len(bias_vals),    2) if bias_vals    else None
        points.append(EvidenceDriftPoint(
            period=period_label,
            paper_count=len(paper_pairs),
            avg_outcome_value=avg_outcome,
            avg_bias_score=avg_bias,
            study_titles=[(sp.external_title or "Untitled") for sp, _ in paper_pairs],
        ))

    drift_detected = len(points) >= 2
    first_outcome  = points[0].avg_outcome_value
    last_outcome   = points[-1].avg_outcome_value
    outcome_note   = ""
    if first_outcome is not None and last_outcome is not None:
        direction = "increasing" if last_outcome > first_outcome else "decreasing" if last_outcome < first_outcome else "stable"
        outcome_note = f" Mean outcome shifted from {first_outcome} to {last_outcome} ({direction})."
    drift_summary = (
        f"Evidence spans {len(points)} time periods ({points[0].period} to {points[-1].period}). "
        f"Earlier period has {points[0].paper_count} paper(s), latest has {points[-1].paper_count} paper(s).{outcome_note} "
        f"Run synthesis on each period separately for a detailed shift analysis."
    )

    # ── AI narrative (graceful fallback if no key) ────────────────────────────
    narrative: str | None = None
    byok = _get_byok_keys(current_user)
    if len(points) >= 2:
        try:
            from backend.services.ai_engine import run as engine_run
            pico_summary_lines = []
            for pt in points:
                titles_preview = ", ".join(pt.study_titles[:3])
                if len(pt.study_titles) > 3:
                    titles_preview += f" …+{len(pt.study_titles)-3} more"
                line = (
                    f"{pt.period}: {pt.paper_count} paper(s)"
                    + (f", avg outcome {pt.avg_outcome_value:.3f}" if pt.avg_outcome_value is not None else "")
                    + (f", avg bias {pt.avg_bias_score:.1f}/10" if pt.avg_bias_score is not None else "")
                    + f". Papers: {titles_preview}"
                )
                pico_summary_lines.append(line)
            pico_block = "\n".join(pico_summary_lines)
            system_prompt = (
                "You are a senior systematic review methodologist. "
                "Write a concise, evidence-based discovery narrative in exactly 3 paragraphs. "
                "Paragraph 1: describe the earliest evidence and its limitations. "
                "Paragraph 2: describe how the evidence evolved in the middle periods. "
                "Paragraph 3: summarise the most recent evidence and its clinical implications. "
                "Be analytical and cite time periods by name."
            )
            user_msg = (
                f"Systematic Review: {review.title}\n\n"
                f"Chronological evidence data by 5-year period:\n{pico_block}\n\n"
                "Write the 3-paragraph Discovery Narrative."
            )
            result = await engine_run(system_prompt, user_msg, **byok)
            narrative = result.text if hasattr(result, "text") else str(result)
        except Exception as _e:
            import logging
            logging.warning("Drift narrative AI call failed: %s", _e)

    return EvidenceDriftResponse(
        review_id=review_id,
        periods=points,
        drift_detected=drift_detected,
        drift_summary=drift_summary,
        narrative=narrative,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4c: Cumulative Stats (Living Forest Plot)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_ci_bounds(ci_str: str | None) -> tuple[float | None, float | None]:
    """Extract numeric CI bounds from strings like '0.5 to 1.2' or '95% CI: 0.3–0.8'."""
    if not ci_str:
        return None, None
    s = re.sub(r'(?:95%\s*CI:?\s*|\(|\))', '', ci_str, flags=re.I).strip()
    m = re.search(r'(-?\d+\.?\d*)\s*(?:to|[-–,])\s*(-?\d+\.?\d*)', s)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except ValueError:
            pass
    return None, None


@router.get("/reviews/{review_id}/cumulative-stats", response_model=CumulativeStatsResponse)
def get_cumulative_stats(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return included papers sorted by year with running pooled effect and cumulative sample size."""
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

    rows = []
    for s in included:
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        year = s.external_year or (study.year if study else None)
        title = (study.title if study else None) or s.external_title or "Untitled"
        source = s.external_source or (study.source if study else "unknown")

        outcome_val = study.extracted_outcome_value if study else None
        sample_size = study.extracted_sample_size if study else None
        bias_score  = study.extracted_bias_score  if study else None

        # Try to get CI from cached AIResult
        ci_lower, ci_upper = None, None
        if study:
            from sqlalchemy import and_
            import hashlib as _h
            raw = f"clinical|{(study.title or '').strip().lower()}|{(study.doi or '').strip().lower()}|{(study.pmid or '').strip().lower()}|{(study.pmcid or '').strip().lower()}|"
            ck = _h.sha256("|".join(f"{k}={v}" for k, v in sorted({"kind": "clinical", "title": (study.title or "").strip().lower(), "doi": (study.doi or "").strip().lower(), "pmid": (study.pmid or "").strip().lower(), "pmcid": (study.pmcid or "").strip().lower(), "question": ""}.items())).encode()).hexdigest()
            cached = session.exec(select(AIResult).where((AIResult.owner_username == current_user.username) & (AIResult.cache_key == ck) & (AIResult.kind == "clinical"))).first()
            if cached:
                try:
                    stats_raw = json.loads(cached.summary or "{}")
                    ci_lower, ci_upper = _parse_ci_bounds(stats_raw.get("confidence_interval"))
                except Exception:
                    pass

        rows.append({
            "year": year, "title": title, "source": source,
            "outcome_value": outcome_val, "sample_size": sample_size,
            "bias_score": bias_score, "ci_lower": ci_lower, "ci_upper": ci_upper,
        })

    # Sort by year (null years last)
    rows.sort(key=lambda r: (r["year"] is None, r["year"] or 9999))

    # Calculate cumulative running stats
    cum_n = 0
    cum_effect_sum = 0.0
    cum_effect_count = 0
    points = []
    for r in rows:
        if r["sample_size"]:
            cum_n += r["sample_size"]
        if r["outcome_value"] is not None:
            cum_effect_sum += r["outcome_value"]
            cum_effect_count += 1
        cum_effect = round(cum_effect_sum / cum_effect_count, 4) if cum_effect_count else None
        points.append(CumulativeStatPoint(
            year=r["year"], title=r["title"], source=r["source"],
            outcome_value=r["outcome_value"], sample_size=r["sample_size"],
            bias_score=r["bias_score"], ci_lower=r["ci_lower"], ci_upper=r["ci_upper"],
            cumulative_n=cum_n, cumulative_effect=cum_effect,
            has_data=r["outcome_value"] is not None,
        ))

    total_with_data = sum(1 for p in points if p.has_data)
    return CumulativeStatsResponse(
        review_id=review_id, points=points,
        total_included=len(points), total_with_data=total_with_data,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4c: Citation Network Graph
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/network", response_model=NetworkResponse)
def get_network(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return node/edge graph of included papers for Cytoscape citation network."""
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

    nodes = []
    # author_last → list of node_ids for edge building
    author_map: dict[str, list[str]] = {}
    # For chronological path: (year, node_id)
    year_order: list[tuple] = []

    from backend.services.ai_service import strip_html

    for s in included:
        node_id = str(s.id)
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        label  = (study.title if study else None) or s.external_title or "Untitled"
        year   = (study.year  if study else None) or s.external_year
        doi    = (study.doi   if study else None) or s.external_doi
        citation_count = study.citation_count if study else None
        study_type = (study.study_type if study else None)

        # Abstract snippet ≤200 chars for sidebar
        abstract_raw = (study.abstract if study else None) or s.external_abstract or ""
        abstract_snippet = strip_html(abstract_raw)[:200] or None

        # text_offsets from cached AIResult (if study exists)
        text_offsets = None
        if study:
            ck = hashlib.sha256("|".join(f"{k}={v}" for k, v in sorted({
                "kind": "clinical", "title": (study.title or "").strip().lower(),
                "doi": (study.doi or "").strip().lower(),
                "pmid": (study.pmid or "").strip().lower(),
                "pmcid": (study.pmcid or "").strip().lower(), "question": "",
            }.items())).encode()).hexdigest()
            cached = session.exec(
                select(AIResult).where(
                    (AIResult.owner_username == current_user.username) &
                    (AIResult.cache_key == ck) & (AIResult.kind == "clinical")
                )
            ).first()
            if cached and cached.text_offsets:
                text_offsets = cached.text_offsets

        nodes.append(NetworkNode(
            id=node_id, label=label[:60], year=year,
            citation_count=citation_count,
            source=s.external_source or (study.source if study else None),
            doi=doi, study_type=study_type,
            abstract_snippet=abstract_snippet,
            text_offsets=text_offsets,
        ))

        if year:
            year_order.append((year, node_id))

        # Index by first-author last name for edge building
        authors_str = study.authors if study else None
        if authors_str:
            first_author = authors_str.split(",")[0].strip().split()[-1].lower()
            if len(first_author) > 2:
                author_map.setdefault(first_author, []).append(node_id)

    # Build edges: papers sharing a first-author last name
    edges = []
    seen_pairs: set[frozenset] = set()
    for author, nids in author_map.items():
        if len(nids) < 2:
            continue
        for i in range(len(nids)):
            for j in range(i + 1, len(nids)):
                pair = frozenset([nids[i], nids[j]])
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    edges.append(NetworkEdge(source=nids[i], target=nids[j], reason="shared_author"))

    # Chronological discovery path: connect oldest → newest by year
    year_order_sorted = sorted(year_order, key=lambda t: t[0])
    for i in range(len(year_order_sorted) - 1):
        src = year_order_sorted[i][1]
        tgt = year_order_sorted[i + 1][1]
        pair = frozenset([src, tgt])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
        edges.append(NetworkEdge(source=src, target=tgt, reason="chronological_path", is_path=True))

    return NetworkResponse(review_id=review_id, nodes=nodes, edges=edges)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4c: Export Report
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/export-report")
def export_report(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate a Markdown report of the review and return it as a downloadable .md file."""
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    counts = _screening_counts(session, review_id)
    included_screenings = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        ).order_by(ReviewScreening.id.asc())
    ).all()

    lines: list[str] = []
    lines.append(f"# {review.title}")
    lines.append(f"\n**Phase:** {review.phase}  ")
    lines.append(f"**Search source:** {review.search_source}  ")
    lines.append(f"**Search query:** {review.search_query or '—'}  ")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append(f"**Author:** {current_user.username}\n")

    if review.description:
        lines.append(f"## Description\n\n{review.description}\n")

    # Criteria
    inc = (review.inclusion_criteria or {}).get("text", "")
    exc = (review.exclusion_criteria or {}).get("text", "")
    if inc or exc:
        lines.append("## Criteria\n")
        if inc:
            lines.append(f"**Inclusion:**\n\n{inc}\n")
        if exc:
            lines.append(f"**Exclusion:**\n\n{exc}\n")

    # PRISMA summary
    lines.append("## PRISMA Summary\n")
    lines.append(f"| Stage | Count |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Records identified | {review.search_results_count or counts['total']} |")
    lines.append(f"| Screened | {counts['total']} |")
    lines.append(f"| Included | {counts['included']} |")
    lines.append(f"| Excluded | {counts['excluded']} |")
    lines.append(f"| Pending / Maybe | {counts['pending'] + counts['maybe']} |\n")

    # Included papers
    if included_screenings:
        lines.append("## Included Papers\n")
        for i, s in enumerate(included_screenings, 1):
            study: Study | None = session.get(Study, s.study_id) if s.study_id else None
            title = (study.title if study else None) or s.external_title or "Untitled"
            year = (study.year if study else None) or s.external_year or "n/a"
            doi = (study.doi if study else None) or s.external_doi or ""
            doi_str = f"  DOI: {doi}" if doi else ""
            lines.append(f"{i}. **{title}** ({year}){doi_str}")
            if s.screener_notes:
                lines.append(f"   > Notes: {s.screener_notes}")
            if study and study.ai_summary:
                lines.append(f"   > AI Summary: {study.ai_summary[:300]}…")
        lines.append("")

    # Evidence notes
    if review.evidence_notes:
        lines.append("## Evidence Notes\n")
        lines.append(review.evidence_notes)
        lines.append("")

    # Audit summary
    audit = review.audit_log or []
    if audit:
        lines.append(f"## Audit Trail ({len(audit)} entries)\n")
        for entry in audit[-10:]:  # last 10
            ts = entry.get("timestamp", "")[:16].replace("T", " ")
            lines.append(f"- `{ts}` **{entry.get('action', '')}** {entry.get('details', '')}")
        lines.append("")

    markdown = "\n".join(lines)

    # Write to a temp file and return
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8",
        prefix=f"review_{review_id}_",
    )
    tmp.write(markdown)
    tmp.flush()
    tmp.close()

    safe_title = re.sub(r'[^\w\s-]', '', review.title)[:40].strip().replace(' ', '_')
    filename = f"review_{safe_title or review_id}.md"

    return FileResponse(
        path=tmp.name,
        media_type="text/markdown",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        background=None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4c: SR-Ask — query included papers only
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reviews/{review_id}/ask", response_model=ReviewAskResponse)
async def review_ask(
    review_id: int,
    payload: ReviewAskRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Answer a question using only the included papers of this systematic review."""
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    byok = _get_byok_keys(current_user)
    if not byok:
        raise HTTPException(status_code=400, detail="No AI API key configured. Add your key in Settings.")

    included = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        )
    ).all()

    if not included:
        raise HTTPException(status_code=400, detail="No included papers to query against. Include papers in the Screening tab first.")

    from backend.services.ai_service import strip_html
    from backend.services.ai_engine import run as engine_run

    paper_ctx_parts = []
    for i, s in enumerate(included, 1):
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        title = (study.title if study else None) or s.external_title or "Untitled"
        year = (study.year if study else None) or s.external_year or "n/a"
        abstract = (study.abstract if study else None) or s.external_abstract or "No abstract."
        abstract = strip_html(abstract)[:500]
        paper_ctx_parts.append(f"Paper {i} [{title} ({year})]:\n{abstract}")

    paper_ctx = "\n\n".join(paper_ctx_parts)

    system = (
        "You are a systematic review assistant. Answer questions based ONLY on the included papers provided. "
        "Cite papers by their title when referencing them (e.g., 'Paper 1 [title] found...'). "
        "If the papers do not contain enough information to answer, say so clearly. "
        "Be concise, precise, and clinically relevant."
    )
    user_msg = (
        f"Systematic Review: {review.title}\n"
        f"Included papers ({len(included)}):\n\n{paper_ctx}\n\n"
        f"Question: {payload.question}"
    )

    try:
        result = await engine_run(system, user_msg, **byok)
        answer = result.text if hasattr(result, "text") else str(result)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {e}")

    return ReviewAskResponse(
        answer=answer,
        review_id=review_id,
        question=payload.question,
        papers_used=len(included),
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


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: OpenAlex Citation Network
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/citation-network-openalex", response_model=CitationNetworkResponse)
async def openalex_citation_network(
    review_id: int,
    doi: str = Query(..., description="Seed paper DOI"),
    depth: int = Query(default=1, ge=1, le=2, description="1=direct only, 2=2-hop"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Build a full citation spider-web for a seed DOI using OpenAlex.
    Returns ancestors (references), descendants (citing papers), and co-citations.
    """
    import urllib.request
    import urllib.error
    import urllib.parse

    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    def _openalex_get(url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SerenMedical/1.0 (mailto:admin@seren.app)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            raise HTTPException(status_code=502, detail=f"OpenAlex error: {e.code}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"OpenAlex request failed: {e}")

    def _node_from_work(work: dict, node_type: str) -> CitationNode:
        wid      = work.get("id", "")
        title    = (work.get("title") or "Untitled")[:120]
        year     = work.get("publication_year")
        ccount   = work.get("cited_by_count", 0)
        doi_raw  = (work.get("doi") or "").replace("https://doi.org/", "")
        concepts = work.get("concepts") or []
        field    = concepts[0].get("display_name") if concepts else None
        authors_list = work.get("authorships") or []
        authors_str  = ", ".join(
            a.get("author", {}).get("display_name", "") for a in authors_list[:3]
        )
        abstract_inv = work.get("abstract_inverted_index") or {}
        abstract_text = ""
        if abstract_inv:
            max_pos = max((pos for positions in abstract_inv.values() for pos in positions), default=0)
            word_arr = [""] * (max_pos + 1)
            for word, positions in abstract_inv.items():
                for pos in positions:
                    if pos <= max_pos:
                        word_arr[pos] = word
            abstract_text = " ".join(w for w in word_arr if w)[:300]
        source_loc = work.get("primary_location") or {}
        source_name = (source_loc.get("source") or {}).get("display_name") or ""
        return CitationNode(
            id=wid or doi_raw,
            label=title,
            year=year,
            citation_count=ccount,
            node_type=node_type,
            field=field,
            doi=doi_raw or None,
            abstract=abstract_text or None,
            authors=authors_str or None,
            source=source_name or None,
            is_key_paper=(ccount >= 100),
        )

    # ── 1. Fetch seed paper ───────────────────────────────────────────────────
    encoded_doi = urllib.parse.quote(doi, safe="")
    seed_data = _openalex_get(
        f"https://api.openalex.org/works/https://doi.org/{encoded_doi}"
        f"?select=id,title,publication_year,cited_by_count,doi,concepts,authorships,abstract_inverted_index,referenced_works,primary_location"
    )
    if not seed_data or "id" not in seed_data:
        raise HTTPException(status_code=404, detail="Paper not found on OpenAlex. Check the DOI.")

    seed_id = seed_data["id"]
    nodes: list[CitationNode] = [_node_from_work(seed_data, "seed")]
    edges: list[CitationEdge] = []
    seen_ids: set[str] = {seed_id}

    # ── 2. Ancestors: papers this study references ────────────────────────────
    ref_ids = seed_data.get("referenced_works") or []
    # Batch fetch up to 40 references
    batch = ref_ids[:40]
    if batch:
        ids_param = "|".join(batch)
        ref_data = _openalex_get(
            f"https://api.openalex.org/works?filter=openalex_id:{ids_param}"
            f"&per-page=40&select=id,title,publication_year,cited_by_count,doi,concepts,authorships,primary_location"
        )
        for work in (ref_data.get("results") or []):
            wid = work.get("id", "")
            if wid and wid not in seen_ids:
                seen_ids.add(wid)
                nodes.append(_node_from_work(work, "ancestor"))
                edges.append(CitationEdge(source=seed_id, target=wid, edge_type="references"))

    # ── 3. Descendants: papers that cite this study ───────────────────────────
    cite_data = _openalex_get(
        f"https://api.openalex.org/works?filter=cites:{seed_id}"
        f"&per-page=40&sort=cited_by_count:desc"
        f"&select=id,title,publication_year,cited_by_count,doi,concepts,authorships,primary_location"
    )
    for work in (cite_data.get("results") or []):
        wid = work.get("id", "")
        if wid and wid not in seen_ids:
            seen_ids.add(wid)
            nodes.append(_node_from_work(work, "descendant"))
            edges.append(CitationEdge(source=wid, target=seed_id, edge_type="cites"))

    # ── 4. Co-citations: top-2 references shared by ≥2 descendants ───────────
    if depth >= 2:
        ref_count: dict[str, int] = {}
        for e in edges:
            if e.edge_type == "cites":
                # fetch that descendant's references (first 3 only, lightweight)
                desc_data = _openalex_get(
                    f"https://api.openalex.org/works/{urllib.parse.quote(e.source, safe='')}"
                    f"?select=referenced_works"
                )
                for rid in (desc_data.get("referenced_works") or [])[:20]:
                    if rid != seed_id and rid not in seen_ids:
                        ref_count[rid] = ref_count.get(rid, 0) + 1
        # Take top 10 co-cited papers
        top_cocite = sorted(ref_count.items(), key=lambda x: x[1], reverse=True)[:10]
        if top_cocite:
            co_ids = "|".join(r[0] for r in top_cocite)
            co_data = _openalex_get(
                f"https://api.openalex.org/works?filter=openalex_id:{co_ids}"
                f"&per-page=10&select=id,title,publication_year,cited_by_count,doi,concepts,authorships,primary_location"
            )
            for work in (co_data.get("results") or []):
                wid = work.get("id", "")
                if wid and wid not in seen_ids:
                    seen_ids.add(wid)
                    nodes.append(_node_from_work(work, "cocite"))
                    edges.append(CitationEdge(source=seed_id, target=wid, edge_type="co_citation"))

    # ── 5. Year range for timeline slider ────────────────────────────────────
    years = [n.year for n in nodes if n.year]
    year_range = [min(years), max(years)] if years else []

    return CitationNetworkResponse(
        seed_doi=doi,
        nodes=nodes,
        edges=edges,
        year_range=year_range,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: Key Papers (most influential included papers)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/key-papers", response_model=KeyPapersResponse)
def key_papers(
    review_id: int,
    top_n: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the top-N most-cited included papers in this review."""
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    from backend.services.ai_service import strip_html

    included = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        )
    ).all()

    papers = []
    for s in included:
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        title = (study.title if study else None) or s.external_title or "Untitled"
        year  = (study.year  if study else None) or s.external_year
        doi   = (study.doi   if study else None) or s.external_doi
        cc    = (study.citation_count if study else None) or 0
        abstract_raw = (study.abstract if study else None) or s.external_abstract or ""
        snippet = strip_html(abstract_raw)[:150] or None
        papers.append(KeyPaper(
            screening_id=s.id,
            title=title[:100],
            year=year,
            citation_count=cc,
            doi=doi,
            abstract_snippet=snippet,
            rank=0,
        ))

    papers.sort(key=lambda p: p.citation_count, reverse=True)
    for i, p in enumerate(papers[:top_n], 1):
        p.rank = i

    return KeyPapersResponse(review_id=review_id, papers=papers[:top_n])


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: Bias Heatmap
# ══════════════════════════════════════════════════════════════════════════════

_BIAS_DIMENSIONS = [
    "Selection Bias",
    "Performance Bias",
    "Detection Bias",
    "Attrition Bias",
    "Reporting Bias",
    "Sample Size",
]

@router.get("/reviews/{review_id}/bias-heatmap", response_model=BiasHeatmapResponse)
def bias_heatmap(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return a bias heatmap grid: studies × bias dimensions.
    Scores: 0 = low risk (green), 1 = some concerns (yellow), 2 = high risk (red).
    Pulls from cached AIResult bias_score + risk_of_bias fields where available.
    """
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

    study_names: list[str] = []
    cells: list[BiasCell] = []

    for s in included:
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        title = ((study.title if study else None) or s.external_title or "Untitled")[:50]
        study_names.append(title)

        # Try to read cached appraisal from AIResult
        bias_score_raw = study.extracted_bias_score if study else None  # 0-10
        sample_size    = study.extracted_sample_size if study else None

        # Try cached AI clinical appraisal for richer data
        appraisal_data: dict = {}
        if study:
            ck = hashlib.sha256("|".join(f"{k}={v}" for k, v in sorted({
                "kind": "clinical", "title": (study.title or "").strip().lower(),
                "doi": (study.doi or "").strip().lower(),
                "pmid": (study.pmid or "").strip().lower(),
                "pmcid": (study.pmcid or "").strip().lower(), "question": "",
            }.items())).encode()).hexdigest()
            cached = session.exec(
                select(AIResult).where(
                    (AIResult.owner_username == current_user.username) &
                    (AIResult.cache_key == ck) & (AIResult.kind == "clinical")
                )
            ).first()
            if cached and cached.synthesis_narrative:
                try:
                    appraisal_data = json.loads(cached.synthesis_narrative) if isinstance(cached.synthesis_narrative, str) else {}
                except Exception:
                    pass

        # Map overall bias_score (0-10) to 0/1/2 per dimension heuristically
        # If we have a detailed appraisal, use it; else derive from the scalar
        def _scalar_to_risk(val: Optional[float], invert: bool = False) -> int:
            """Convert a 0-10 or 0-5 scalar to 0/1/2 risk."""
            if val is None:
                return 1  # unknown = some concerns
            if invert:
                val = 10 - val
            if val <= 3:
                return 0
            if val <= 6:
                return 1
            return 2

        overall_risk = _scalar_to_risk(bias_score_raw)
        # Sample size: small (<30) = high risk, medium (30-100) = some, large (>100) = low
        if sample_size is None:
            ss_risk = 1
        elif sample_size < 30:
            ss_risk = 2
        elif sample_size < 100:
            ss_risk = 1
        else:
            ss_risk = 0

        dim_scores = {
            "Selection Bias":    appraisal_data.get("selection_bias_score", overall_risk),
            "Performance Bias":  appraisal_data.get("performance_bias_score", overall_risk),
            "Detection Bias":    appraisal_data.get("detection_bias_score", overall_risk),
            "Attrition Bias":    appraisal_data.get("attrition_bias_score", overall_risk),
            "Reporting Bias":    appraisal_data.get("reporting_bias_score", overall_risk),
            "Sample Size":       ss_risk,
        }

        for dim in _BIAS_DIMENSIONS:
            score = int(dim_scores.get(dim, 1))
            score = max(0, min(2, score))
            cells.append(BiasCell(study=title, dimension=dim, score=score))

    return BiasHeatmapResponse(
        review_id=review_id,
        studies=study_names,
        dimensions=_BIAS_DIMENSIONS,
        cells=cells,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: Verdict Synthesiser
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reviews/{review_id}/verdict", response_model=VerdictResponse)
async def synthesise_verdict(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a final research verdict (Supported / Mixed / Insufficient evidence)
    using an AI prompt over all included papers.
    """
    review = session.get(SystematicReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.owner_username != current_user.username:
        raise HTTPException(status_code=403, detail="Not allowed")

    byok = _get_byok_keys(current_user)
    if not byok:
        raise HTTPException(status_code=400, detail="No AI API key configured.")

    included = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        )
    ).all()

    if len(included) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 included papers to generate a verdict.")

    from backend.services.ai_service import strip_html
    from backend.services.ai_engine import run as engine_run

    paper_summaries = []
    for i, s in enumerate(included, 1):
        study: Study | None = session.get(Study, s.study_id) if s.study_id else None
        title    = (study.title if study else None) or s.external_title or "Untitled"
        year     = (study.year  if study else None) or s.external_year or "n/a"
        abstract = strip_html((study.abstract if study else None) or s.external_abstract or "")[:400]
        bias_s   = study.extracted_bias_score if study else None
        sample_s = study.extracted_sample_size if study else None
        outcome  = study.extracted_outcome_value if study else None

        meta = []
        if bias_s is not None: meta.append(f"bias_score={bias_s}/10")
        if sample_s:           meta.append(f"n={sample_s}")
        if outcome is not None: meta.append(f"outcome={outcome}")
        meta_str = f" [{', '.join(meta)}]" if meta else ""
        paper_summaries.append(f"Paper {i}: {title} ({year}){meta_str}\n{abstract}")

    paper_ctx = "\n\n".join(paper_summaries)
    system_prompt = (
        "You are a systematic review expert. Analyse the included papers and generate a final verdict.\n"
        "Return ONLY valid JSON with this exact structure:\n"
        "{\n"
        '  "verdict": "Supported" | "Mixed" | "Insufficient",\n'
        '  "confidence": "High" | "Moderate" | "Low",\n'
        '  "confidence_pct": <0-100>,\n'
        '  "summary": "<2-3 sentence plain-English conclusion>",\n'
        '  "key_supporting_studies": [\n'
        '    {"title": "...", "year": <int|null>, "finding": "...", "weight": "strong"|"moderate"|"weak"}\n'
        "  ],\n"
        '  "key_contradictions": ["<contradiction 1>", "..."],\n'
        '  "limitations": ["<limitation 1>", "..."],\n'
        '  "recommendation": "<clinical/research recommendation>"\n'
        "}"
    )
    user_msg = (
        f"Systematic Review: {review.title}\n"
        f"Review question / description: {review.description or review.search_query or '(not specified)'}\n\n"
        f"Included papers ({len(included)}):\n\n{paper_ctx}\n\n"
        "Generate the verdict JSON now."
    )

    try:
        result = await engine_run(system_prompt, user_msg, **byok)
        raw = result.text if hasattr(result, "text") else str(result)
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return a basic verdict if JSON parse fails
        data = {
            "verdict": "Mixed", "confidence": "Low", "confidence_pct": 30,
            "summary": "Unable to parse AI response. Please try again.",
            "key_supporting_studies": [], "key_contradictions": [],
            "limitations": ["AI response parsing failed"], "recommendation": "",
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {e}")

    supporting = [
        SupportingStudy(
            title=s.get("title", ""),
            year=s.get("year"),
            finding=s.get("finding", ""),
            weight=s.get("weight", "moderate"),
        )
        for s in (data.get("key_supporting_studies") or [])
    ]

    return VerdictResponse(
        review_id=review_id,
        verdict=data.get("verdict", "Mixed"),
        confidence=data.get("confidence", "Low"),
        confidence_pct=data.get("confidence_pct"),
        summary=data.get("summary", ""),
        key_supporting_studies=supporting,
        key_contradictions=data.get("key_contradictions") or [],
        limitations=data.get("limitations") or [],
        recommendation=data.get("recommendation", ""),
    )
