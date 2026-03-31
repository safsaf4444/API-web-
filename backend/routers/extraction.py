from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.models import (
    ExtractionRecord, ExtractionTemplate, ReviewScreening,
    Study, SystematicReview, User,
)
from backend.schemas import (
    BulkExtractionRequest, BulkExtractionResponse,
    ExtractionRecordCreate, ExtractionRecordRead,
    ExtractionTemplateCreate, ExtractionTemplateRead,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["extraction"])


# ══════════════════════════════════════════════════════════════════════════════
# Extraction Templates CRUD
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/extraction-templates", response_model=ExtractionTemplateRead)
def create_template(
    payload: ExtractionTemplateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tmpl = ExtractionTemplate(
        owner_username=current_user.username,
        name=payload.name,
        fields=[f.model_dump() for f in payload.fields] if payload.fields else [],
    )
    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return tmpl


@router.get("/extraction-templates", response_model=List[ExtractionTemplateRead])
def list_templates(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(ExtractionTemplate)
        .where(ExtractionTemplate.owner_username == current_user.username)
        .order_by(ExtractionTemplate.created_at.desc())
    ).all()


@router.delete("/extraction-templates/{template_id}")
def delete_template(
    template_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tmpl = session.get(ExtractionTemplate, template_id)
    if not tmpl or tmpl.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Template not found")
    session.delete(tmpl)
    session.commit()
    return {"status": "deleted"}


# ══════════════════════════════════════════════════════════════════════════════
# Extraction Records CRUD
# ══════════════════════════════════════════════════════════════════════════════

def _enrich_record(rec: ExtractionRecord, session: Session) -> dict:
    d = ExtractionRecordRead.model_validate(rec).model_dump()
    screening = session.get(ReviewScreening, rec.screening_id)
    d["paper_title"] = screening.external_title if screening else None
    return d


@router.post("/reviews/{review_id}/extract", response_model=ExtractionRecordRead)
def save_extraction(
    review_id: int,
    payload: ExtractionRecordCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")

    # Check screening belongs to this review
    screening = session.get(ReviewScreening, payload.screening_id)
    if not screening or screening.review_id != review_id:
        raise HTTPException(status_code=404, detail="Screening record not found")

    # Upsert: update if already exists
    existing = session.exec(
        select(ExtractionRecord).where(
            (ExtractionRecord.review_id == review_id) &
            (ExtractionRecord.screening_id == payload.screening_id) &
            (ExtractionRecord.owner_username == current_user.username)
        )
    ).first()

    if existing:
        existing.data = payload.data
        existing.template_id = payload.template_id
        existing.updated_at = datetime.now(timezone.utc)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return _enrich_record(existing, session)

    rec = ExtractionRecord(
        review_id=review_id,
        screening_id=payload.screening_id,
        template_id=payload.template_id,
        owner_username=current_user.username,
        data=payload.data,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return _enrich_record(rec, session)


@router.get("/reviews/{review_id}/extractions", response_model=List[ExtractionRecordRead])
def list_extractions(
    review_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")

    records = session.exec(
        select(ExtractionRecord)
        .where(
            (ExtractionRecord.review_id == review_id) &
            (ExtractionRecord.owner_username == current_user.username)
        )
        .order_by(ExtractionRecord.created_at.asc())
    ).all()

    return [_enrich_record(r, session) for r in records]


@router.post("/reviews/{review_id}/extract-bulk", response_model=BulkExtractionResponse)
async def bulk_extract(
    review_id: int,
    payload: BulkExtractionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """AI-powered bulk extraction across all included papers."""
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")

    from backend.routers.reviews import _get_byok_keys
    byok = _get_byok_keys(current_user)
    if not byok:
        raise HTTPException(status_code=400, detail="No AI API key configured.")

    # Get template fields
    field_names = payload.fields or []
    if payload.template_id:
        tmpl = session.get(ExtractionTemplate, payload.template_id)
        if tmpl and tmpl.fields:
            field_names = [f["name"] for f in tmpl.fields]

    if not field_names:
        field_names = ["dosage", "duration", "sample_size", "primary_outcome",
                       "effect_size", "adverse_events", "conclusion"]

    included = session.exec(
        select(ReviewScreening).where(
            (ReviewScreening.review_id == review_id) &
            (ReviewScreening.decision == "included")
        )
    ).all()

    if not included:
        raise HTTPException(status_code=400, detail="No included papers to extract from.")

    from backend.services.ai_engine import run as engine_run
    from backend.services.ai_service import strip_html

    extracted = 0
    failed = 0
    records = []

    fields_json = json.dumps(field_names)
    system = (
        f"You are a data extraction assistant for systematic reviews. "
        f"Extract the following fields from the paper abstract: {fields_json}. "
        f"Return a valid JSON object with exactly these field names as keys. "
        f"Use null for fields that cannot be determined from the abstract. "
        f"Be precise and concise. Return JSON only, no prose."
    )

    for s in included:
        title = s.external_title or "Untitled"
        abstract = strip_html(s.external_abstract or "")[:1500]
        if not abstract:
            failed += 1
            continue

        user_msg = f"Title: {title}\nAbstract: {abstract}"
        try:
            result = await engine_run(system, user_msg, **byok)
            text = result.text if hasattr(result, "text") else str(result)
            # Parse JSON from AI response
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)

            # Upsert record
            existing = session.exec(
                select(ExtractionRecord).where(
                    (ExtractionRecord.review_id == review_id) &
                    (ExtractionRecord.screening_id == s.id) &
                    (ExtractionRecord.owner_username == current_user.username)
                )
            ).first()

            if existing:
                existing.data = data
                existing.ai_extracted = True
                existing.template_id = payload.template_id
                existing.updated_at = datetime.now(timezone.utc)
                session.add(existing)
            else:
                rec = ExtractionRecord(
                    review_id=review_id,
                    screening_id=s.id,
                    template_id=payload.template_id,
                    owner_username=current_user.username,
                    data=data,
                    ai_extracted=True,
                )
                session.add(rec)

            extracted += 1
        except Exception as e:
            logger.warning("Bulk extraction failed for '%s': %s", title[:40], e)
            failed += 1

    session.commit()

    # Reload records
    all_records = session.exec(
        select(ExtractionRecord).where(
            (ExtractionRecord.review_id == review_id) &
            (ExtractionRecord.owner_username == current_user.username)
        )
    ).all()
    records = [_enrich_record(r, session) for r in all_records]

    return BulkExtractionResponse(
        review_id=review_id, extracted=extracted, failed=failed, records=records,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Export: CSV / XLSX
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reviews/{review_id}/extractions/export")
def export_extractions(
    review_id: int,
    format: str = Query(default="csv", regex="^(csv|xlsx)$"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    review = session.get(SystematicReview, review_id)
    if not review or review.owner_username != current_user.username:
        raise HTTPException(status_code=404, detail="Review not found")

    records = session.exec(
        select(ExtractionRecord).where(
            (ExtractionRecord.review_id == review_id) &
            (ExtractionRecord.owner_username == current_user.username)
        )
    ).all()

    if not records:
        raise HTTPException(status_code=404, detail="No extraction records to export.")

    # Collect all unique field names
    all_fields = set()
    for r in records:
        if r.data and isinstance(r.data, dict):
            all_fields.update(r.data.keys())
    field_list = sorted(all_fields)

    # Build rows
    rows = []
    for r in records:
        screening = session.get(ReviewScreening, r.screening_id)
        row = {
            "paper_title": screening.external_title if screening else "Unknown",
            "paper_year": screening.external_year if screening else None,
            "paper_doi": screening.external_doi if screening else None,
            "ai_extracted": r.ai_extracted,
        }
        data = r.data or {}
        for field in field_list:
            row[field] = data.get(field)
        rows.append(row)

    headers = ["paper_title", "paper_year", "paper_doi", "ai_extracted"] + field_list

    if format == "xlsx":
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Extractions"
            ws.append(headers)
            for row in rows:
                ws.append([str(row.get(h, "")) if row.get(h) is not None else "" for h in headers])

            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="extraction_{review_id}.xlsx"'},
            )
        except ImportError:
            raise HTTPException(status_code=500, detail="openpyxl not installed for XLSX export.")

    # CSV
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({h: str(row.get(h, "")) if row.get(h) is not None else "" for h in headers})

    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="extraction_{review_id}.csv"'},
    )
