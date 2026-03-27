from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.db import get_session
from backend.models import Highlight, NotebookPage, Study
from backend.routers.auth import get_current_user
from backend.schemas import (
    HighlightCreate, HighlightPatch, HighlightRead,
    NotebookPageCreate, NotebookPagePatch, NotebookPageRead,
)

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _enrich_page(page: NotebookPage, session: Session) -> NotebookPageRead:
    study_title = None
    if page.study_id:
        study = session.get(Study, page.study_id)
        if study:
            study_title = study.title
    data = NotebookPageRead.model_validate(page)
    data.study_title = study_title
    return data


# ── Notebook Pages ────────────────────────────────────────────────────────────

@router.get("", response_model=List[NotebookPageRead])
def list_pages(
    study_id: Optional[int] = None,
    q: Optional[str] = None,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """List all notebook pages for the current user, optionally filtered by study or search query."""
    stmt = select(NotebookPage).where(NotebookPage.owner_username == username)
    if study_id is not None:
        stmt = stmt.where(NotebookPage.study_id == study_id)
    if q:
        q_lower = q.lower()
        pages = [p for p in session.exec(stmt).all()
                 if q_lower in (p.title or "").lower() or q_lower in (p.content or "").lower()]
    else:
        pages = list(session.exec(stmt).all())

    # Pinned first, then by updated_at desc
    pages.sort(key=lambda p: (not p.is_pinned, -(p.updated_at.timestamp() if p.updated_at else 0)))
    return [_enrich_page(p, session) for p in pages]


@router.post("", response_model=NotebookPageRead, status_code=201)
def create_page(
    body: NotebookPageCreate,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Create a new notebook page (optionally linked to a study)."""
    if body.study_id is not None:
        study = session.get(Study, body.study_id)
        if not study or study.owner_username != username:
            raise HTTPException(404, "Study not found")

    page = NotebookPage(
        owner_username=username,
        study_id=body.study_id,
        title=body.title or "Untitled",
        content=body.content,
        color=body.color or "default",
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    return _enrich_page(page, session)


@router.get("/{page_id}", response_model=NotebookPageRead)
def get_page(
    page_id: int,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    page = session.get(NotebookPage, page_id)
    if not page or page.owner_username != username:
        raise HTTPException(404, "Page not found")
    return _enrich_page(page, session)


@router.patch("/{page_id}", response_model=NotebookPageRead)
def update_page(
    page_id: int,
    body: NotebookPagePatch,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    page = session.get(NotebookPage, page_id)
    if not page or page.owner_username != username:
        raise HTTPException(404, "Page not found")

    if body.title is not None:
        page.title = body.title
    if body.content is not None:
        page.content = body.content
    if body.color is not None:
        page.color = body.color
    if body.is_pinned is not None:
        page.is_pinned = body.is_pinned

    page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    session.commit()
    session.refresh(page)
    return _enrich_page(page, session)


@router.delete("/{page_id}", status_code=204)
def delete_page(
    page_id: int,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    page = session.get(NotebookPage, page_id)
    if not page or page.owner_username != username:
        raise HTTPException(404, "Page not found")
    session.delete(page)
    session.commit()


@router.post("/compile", response_model=dict)
def compile_pages(
    body: dict,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    """Compile selected pages into a single text export."""
    page_ids: list = body.get("page_ids", [])
    if not page_ids:
        raise HTTPException(400, "No page IDs provided")

    pages = []
    for pid in page_ids:
        p = session.get(NotebookPage, pid)
        if p and p.owner_username == username:
            pages.append(p)

    compiled = []
    for p in pages:
        study_title = ""
        if p.study_id:
            s = session.get(Study, p.study_id)
            if s:
                study_title = s.title
        header = f"# {p.title}"
        if study_title:
            header += f"\nSource: {study_title}"
        compiled.append(f"{header}\n\n{p.content or ''}")

    return {"text": "\n\n---\n\n".join(compiled), "page_count": len(compiled)}


# ── Highlights ────────────────────────────────────────────────────────────────

@router.get("/highlights/{study_id}", response_model=List[HighlightRead])
def list_highlights(
    study_id: int,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    stmt = select(Highlight).where(
        Highlight.owner_username == username,
        Highlight.study_id == study_id,
    )
    return list(session.exec(stmt).all())


@router.post("/highlights", response_model=HighlightRead, status_code=201)
def create_highlight(
    body: HighlightCreate,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    study = session.get(Study, body.study_id)
    if not study or study.owner_username != username:
        raise HTTPException(404, "Study not found")

    h = Highlight(
        owner_username=username,
        study_id=body.study_id,
        selected_text=body.selected_text,
        color=body.color or "yellow",
        annotation=body.annotation,
        section=body.section,
        char_start=body.char_start,
        char_end=body.char_end,
    )
    session.add(h)
    session.commit()
    session.refresh(h)
    return h


@router.patch("/highlights/{highlight_id}", response_model=HighlightRead)
def update_highlight(
    highlight_id: int,
    body: HighlightPatch,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    h = session.get(Highlight, highlight_id)
    if not h or h.owner_username != username:
        raise HTTPException(404, "Highlight not found")
    if body.annotation is not None:
        h.annotation = body.annotation
    if body.color is not None:
        h.color = body.color
    session.add(h)
    session.commit()
    session.refresh(h)
    return h


@router.delete("/highlights/{highlight_id}", status_code=204)
def delete_highlight(
    highlight_id: int,
    session: Session = Depends(get_session),
    username: str = Depends(get_current_user),
):
    h = session.get(Highlight, highlight_id)
    if not h or h.owner_username != username:
        raise HTTPException(404, "Highlight not found")
    session.delete(h)
    session.commit()