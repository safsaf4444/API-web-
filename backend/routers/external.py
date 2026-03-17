from __future__ import annotations

import html as html_lib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user
from backend.external_providers import ProviderError, get_provider, list_sources
from backend.models import Study, StudyExternalRef, User, ReadingStatus
from backend.schemas import ExternalImportRequest, ExternalPaperOut, FullTextResponse, StudyRead
from backend.services.study_analysis import detect_study_type_and_tags

router = APIRouter(tags=["external"])


def normalize_source(src: str) -> str:
    return (src or "").strip().lower().replace(" ", "_").replace("-", "_")


def _clean_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = str(doi).strip()
    d = re.sub(r"^doi:\s*", "", d, flags=re.I)
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.I)
    d = d.strip()
    return d or None


def _merge_str_keep_existing(existing: Optional[str], incoming: Optional[str]) -> Optional[str]:
    """Only fill empty existing values; never overwrite."""
    if existing and str(existing).strip():
        return existing
    if incoming and str(incoming).strip():
        return str(incoming).strip()
    return existing


def _ensure_external_ref(
    *,
    session: Session,
    owner_username: str,
    study_id: int,
    source: str,
    source_id: str,
) -> None:
    """
    Store the "also seen on" mapping.
    Safe to call repeatedly: it will no-op if already exists.
    """
    src = normalize_source(source)
    sid = (source_id or "").strip()
    if not src or not sid:
        return

    existing = session.exec(
        select(StudyExternalRef).where(
            (StudyExternalRef.owner_username == owner_username)
            & (StudyExternalRef.source == src)
            & (StudyExternalRef.source_id == sid)
        )
    ).first()
    if existing:
        # ensure it points at the right study (should, but keep safe)
        if existing.study_id != study_id:
            existing.study_id = study_id
            session.add(existing)
        return

    ref = StudyExternalRef(
        owner_username=owner_username,
        study_id=study_id,
        source=src,
        source_id=sid,
    )
    session.add(ref)


# -----------------------------
# Tiny in-memory cache (dev / single-process)
# -----------------------------
@dataclass
class _CacheEntry:
    expires_at: float
    value: dict


# include year_from/year_to in cache key
_EXTERNAL_SEARCH_CACHE: dict[Tuple[str, str, int, str, Optional[int], Optional[int]], _CacheEntry] = {}
_EXTERNAL_SEARCH_TTL_SECONDS = 600  # 10 minutes


def _cache_get(key: Tuple[str, str, int, str, Optional[int], Optional[int]]) -> Optional[dict]:
    ent = _EXTERNAL_SEARCH_CACHE.get(key)
    if not ent:
        return None
    if ent.expires_at < time.time():
        _EXTERNAL_SEARCH_CACHE.pop(key, None)
        return None
    return ent.value


def _cache_set(key: Tuple[str, str, int, str, Optional[int], Optional[int]], value: dict) -> None:
    _EXTERNAL_SEARCH_CACHE[key] = _CacheEntry(expires_at=time.time() + _EXTERNAL_SEARCH_TTL_SECONDS, value=value)


@router.get("/external/sources")
def external_sources():
    return {"sources": list_sources()}


@router.get("/external/search")
async def external_search(
    q: str = Query(..., min_length=2),
    source: str = Query("europepmc"),
    limit: int = Query(25, ge=1, le=100),
    cursor_mark: Optional[str] = Query(default=None),
    year_from: Optional[int] = Query(default=None, ge=1000, le=3000),
    year_to: Optional[int] = Query(default=None, ge=1000, le=3000),
):
    src = normalize_source(source)

    if cursor_mark is None or str(cursor_mark).strip() == "":
        cursor_mark = "0" if src in ("semantic_scholar", "semanticscholar") else "*"

    cursor = str(cursor_mark)

    # Cache only the common first pages (keeps UX snappy, reduces provider calls).
    cacheable = (src == "europepmc" and cursor == "*") or (
        src in ("semantic_scholar", "semanticscholar") and cursor == "0"
    )

    # include year bounds in cache key
    key = (src, q.strip().lower(), int(limit), cursor, year_from, year_to)
    if cacheable:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    try:
        provider = get_provider(src)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # pass year bounds to providers
        papers, next_cursor, hit_count = await provider.search(
            q=q,
            limit=limit,
            cursor_mark=cursor,
            year_from=year_from,
            year_to=year_to,
        )
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"External provider error: {type(e).__name__}: {e}")

    items = [
        ExternalPaperOut(
            source=p.source,
            source_id=p.source_id,
            title=p.title,
            year=p.year,
            authors=p.authors,
            venue=p.venue,
            doi=p.doi,
            url=p.url,
            abstract=p.abstract,
            pmid=p.pmid,
            pmcid=p.pmcid,
        )
        for p in papers
    ]

    out = {"items": items, "next_cursor_mark": next_cursor, "hit_count": hit_count}

    if cacheable:
        _cache_set(key, out)

    return out


@router.post("/external/import", response_model=StudyRead)
def external_import(
    payload: ExternalImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    owner = current_user.username
    src = normalize_source(payload.source)
    sid = (payload.source_id or "").strip()
    doi_clean = _clean_doi(payload.doi)

    # 1) Dedupe by DOI (cross-source), if DOI exists
    existing_by_doi = None
    if doi_clean:
        existing_by_doi = session.exec(
            select(Study).where((Study.owner_username == owner) & (Study.doi == doi_clean))
        ).first()

    if existing_by_doi:
        # Record that we also saw it on this provider
        _ensure_external_ref(
            session=session,
            owner_username=owner,
            study_id=existing_by_doi.id,
            source=src,
            source_id=sid,
        )

        # Fill missing fields (don’t overwrite)
        existing_by_doi.title = _merge_str_keep_existing(existing_by_doi.title, payload.title)
        existing_by_doi.abstract = _merge_str_keep_existing(existing_by_doi.abstract, payload.abstract)
        existing_by_doi.url = _merge_str_keep_existing(existing_by_doi.url, payload.url)
        existing_by_doi.pmid = _merge_str_keep_existing(existing_by_doi.pmid, payload.pmid)
        existing_by_doi.pmcid = _merge_str_keep_existing(existing_by_doi.pmcid, payload.pmcid)
        existing_by_doi.venue = _merge_str_keep_existing(existing_by_doi.venue, payload.venue)

        if existing_by_doi.year is None and payload.year is not None:
            existing_by_doi.year = payload.year

        if not (existing_by_doi.authors and str(existing_by_doi.authors).strip()) and payload.authors:
            existing_by_doi.authors = ", ".join([a for a in payload.authors if a])

        # Keep DOI cleaned
        existing_by_doi.doi = doi_clean

        session.add(existing_by_doi)
        session.commit()
        session.refresh(existing_by_doi)
        return existing_by_doi

    # 2) Fallback: same provider identity for this user
    existing = session.exec(
        select(Study).where((Study.owner_username == owner) & (Study.source == src) & (Study.source_id == sid))
    ).first()
    if existing:
        # Record that we also saw it on this provider (still useful)
        _ensure_external_ref(session=session, owner_username=owner, study_id=existing.id, source=src, source_id=sid)
        session.commit()
        return existing

    authors_str = None
    if payload.authors:
        authors_str = ", ".join([a for a in payload.authors if a])

    study_type, tags = detect_study_type_and_tags(payload.title or "", payload.abstract)
    tags_str = ", ".join(tags) if tags else None

    # PHASE 3: Explicitly set reading_status to unread for new imports
    study = Study(
        owner_username=owner,
        source=src,
        source_id=sid,
        title=payload.title,
        year=payload.year,
        venue=payload.venue,
        abstract=payload.abstract,
        doi=doi_clean,
        url=payload.url,
        authors=authors_str,
        pmid=payload.pmid,
        pmcid=payload.pmcid,
        study_type=study_type,
        tags=tags_str,
        reading_status=ReadingStatus.UNREAD
    )
    session.add(study)
    session.commit()
    session.refresh(study)

    # Record external ref for the newly-created study
    _ensure_external_ref(session=session, owner_username=owner, study_id=study.id, source=src, source_id=sid)
    session.commit()

    return study


# -----------------------------
# Fulltext OA (Public) - Europe PMC PMCID XML only
# -----------------------------

def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _xml_to_safe_html_paragraphs(xml_text: str, max_paragraphs: int = 250) -> str:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return ""

    paras: list[str] = []
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if _strip_ns(tag).lower() != "p":
            continue

        txt = "".join(el.itertext()).strip()
        txt = re.sub(r"\s+", " ", txt)

        if len(txt) >= 40:
            paras.append(txt)
            if len(paras) >= max_paragraphs:
                break

    if not paras:
        return ""

    return "\n".join([f"<p>{html_lib.escape(p)}</p>" for p in paras])


@router.get("/external/fulltext", response_model=FullTextResponse)
async def external_fulltext(source: str = Query("europepmc"), pmcid: Optional[str] = Query(default=None)):
    src = normalize_source(source)
    if src not in ("europepmc", "europe_pmc"):
        return FullTextResponse(available=False, kind="not_available", message="Only europepmc supported (v1).")

    if not pmcid:
        return FullTextResponse(available=False, kind="not_available", message="No PMCID available for this record.")

    pmcid = pmcid.strip()
    if not pmcid.upper().startswith("PMC"):
        return FullTextResponse(available=False, kind="not_available", message="Invalid PMCID.")

    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"Accept": "application/xml"})

        if r.status_code == 404:
            return FullTextResponse(
                available=False,
                kind="not_available",
                message="No OA full text found for this PMCID on Europe PMC.",
            )

        if r.status_code != 200 or not r.text:
            return FullTextResponse(
                available=False,
                kind="not_available",
                message=f"Full text not available via Europe PMC (HTTP {r.status_code}).",
            )

        html = _xml_to_safe_html_paragraphs(r.text)
        if not html:
            return FullTextResponse(
                available=True,
                kind="pmc_xml",
                message="Full text XML exists, but no readable paragraphs were extracted.",
                html=None,
            )

        return FullTextResponse(
            available=True,
            kind="pmc_xml",
            message=f"Open-access full text loaded from Europe PMC ({pmcid}).",
            html=html,
        )

    except Exception as e:
        return FullTextResponse(available=False, kind="error", message=f"{type(e).__name__}: {e}")