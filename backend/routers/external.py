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
from backend.external_providers import ProviderError, get_provider, list_sources, unpaywall_enrich_sync
from backend.models import Study, StudyExternalRef, User, ReadingStatus
from backend.schemas import (
    CitationEdge, CitationNetworkResponse, CitationNode,
    ExternalImportRequest, ExternalPaperOut, FullTextResponse, StudyRead,
)
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


# ── In-memory cache ────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    expires_at: float
    value: dict


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


# ── Retraction check (Europe PMC) ─────────────────────────────────────────────

async def _check_retraction_epmc(pmid: Optional[str], doi: Optional[str]) -> bool:
    """
    Check Europe PMC for retraction status.
    Returns True if the paper is retracted, False otherwise.
    Fails silently — never raises.
    """
    try:
        query = pmid or doi
        if not query:
            return False
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query}&format=json&resultType=core&pageSize=1"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url)
        if r.status_code != 200:
            return False
        data = r.json()
        results = data.get("resultList", {}).get("result", [])
        if not results:
            return False
        first = results[0]
        # Europe PMC returns `isRetracted` as "Y" / "N" or bool
        retracted = first.get("isRetracted", "N")
        if isinstance(retracted, bool):
            return retracted
        return str(retracted).strip().upper() == "Y"
    except Exception:
        return False


# ── Routes ─────────────────────────────────────────────────────────────────────

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

    cacheable = (src == "europepmc" and cursor == "*") or (
        src in ("semantic_scholar", "semanticscholar") and cursor == "0"
    )

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

    items = []
    for p in papers:
        # citation_count: Semantic Scholar returns this natively; Europe PMC/OpenAlex may not
        citation_count = getattr(p, "citation_count", None)

        # is_retracted: Europe PMC returns this field; others may not
        is_retracted = getattr(p, "is_retracted", False)

        items.append(
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
                citation_count=citation_count,
                is_retracted=is_retracted,
            )
        )

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

    # 1) Dedupe by DOI (cross-source)
    existing_by_doi = None
    if doi_clean:
        existing_by_doi = session.exec(
            select(Study).where((Study.owner_username == owner) & (Study.doi == doi_clean))
        ).first()

    if existing_by_doi:
        _ensure_external_ref(
            session=session,
            owner_username=owner,
            study_id=existing_by_doi.id,
            source=src,
            source_id=sid,
        )

        existing_by_doi.title    = _merge_str_keep_existing(existing_by_doi.title,    payload.title)
        existing_by_doi.abstract = _merge_str_keep_existing(existing_by_doi.abstract, payload.abstract)
        existing_by_doi.url      = _merge_str_keep_existing(existing_by_doi.url,      payload.url)
        existing_by_doi.pmid     = _merge_str_keep_existing(existing_by_doi.pmid,     payload.pmid)
        existing_by_doi.pmcid    = _merge_str_keep_existing(existing_by_doi.pmcid,    payload.pmcid)
        existing_by_doi.venue    = _merge_str_keep_existing(existing_by_doi.venue,    payload.venue)

        if existing_by_doi.year is None and payload.year is not None:
            existing_by_doi.year = payload.year

        if not (existing_by_doi.authors and str(existing_by_doi.authors).strip()) and payload.authors:
            existing_by_doi.authors = ", ".join([a for a in payload.authors if a])

        # Update citation count, retraction and new fields if provided
        if getattr(payload, "citation_count", None) is not None:
            existing_by_doi.citation_count = payload.citation_count
        if getattr(payload, "is_retracted", None) is not None:
            existing_by_doi.is_retracted = payload.is_retracted
        if getattr(payload, "publication_type", None):
            existing_by_doi.publication_type = payload.publication_type
        if getattr(payload, "full_text_url", None):
            existing_by_doi.full_text_url = payload.full_text_url

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
        _ensure_external_ref(session=session, owner_username=owner, study_id=existing.id, source=src, source_id=sid)
        session.commit()
        return existing

    authors_str = None
    if payload.authors:
        authors_str = ", ".join([a for a in payload.authors if a])

    study_type, tags = detect_study_type_and_tags(payload.title or "", payload.abstract)
    if not study_type:
        study_type = "Unknown"
        
    tags_str = ", ".join(tags) if tags else None

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
        reading_status=ReadingStatus.UNREAD,
        citation_count=getattr(payload, "citation_count", None),
        is_retracted=getattr(payload, "is_retracted", False) or False,
        publication_type=getattr(payload, "publication_type", None),
        full_text_url=getattr(payload, "full_text_url", None),
    )
    session.add(study)
    session.commit()
    session.refresh(study)

    _ensure_external_ref(session=session, owner_username=owner, study_id=study.id, source=src, source_id=sid)
    session.commit()
    session.refresh(study)

    # Enrich with Unpaywall open-access URL if we have a DOI and no full_text_url yet
    if doi_clean and not study.full_text_url:
        import os
        try:
            oa_url = unpaywall_enrich_sync(doi_clean, os.getenv("UNPAYWALL_EMAIL", "safa.dubai@gmail.com"))
            if oa_url:
                study.full_text_url = oa_url
                session.add(study)
                session.commit()
                session.refresh(study)
        except Exception:
            pass  # Unpaywall enrichment is best-effort

    return study


# ── Retraction check endpoint (on-demand) ─────────────────────────────────────

@router.get("/external/retraction_check")
async def retraction_check(
    pmid: Optional[str] = Query(default=None),
    doi:  Optional[str] = Query(default=None),
):
    """
    Check whether a paper is retracted via Europe PMC.
    Called on paper load to update retraction status without blocking search.
    """
    if not pmid and not doi:
        return {"is_retracted": False}
    retracted = await _check_retraction_epmc(pmid, doi)
    return {"is_retracted": retracted}


# ── Fulltext OA (Public) ───────────────────────────────────────────────────────

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


# ── Citation Web (OpenAlex) ───────────────────────────────────────────────────

_OA_HEADERS = {"User-Agent": "SerenMedical/1.0 (mailto:safa.dubai@gmail.com)"}
_OA_SELECT_FULL  = "id,title,publication_year,cited_by_count,doi,concepts,authorships,abstract_inverted_index,referenced_works,primary_location"
_OA_SELECT_LIGHT = "id,title,publication_year,cited_by_count,doi,concepts,authorships,primary_location"
_OA_SELECT_REFS  = "referenced_works"


async def _oa_get(client: httpx.AsyncClient, url: str) -> dict:
    try:
        resp = await client.get(url, headers=_OA_HEADERS, timeout=15.0)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"OpenAlex error: {e.response.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="OpenAlex request timed out.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAlex request failed: {e}")


def _oa_node(work: dict, node_type: str) -> CitationNode:
    import urllib.parse as _up
    wid     = (work.get("id") or "").strip()
    title   = (work.get("title") or "Untitled")[:120]
    year    = work.get("publication_year")
    ccount  = work.get("cited_by_count") or 0
    doi_raw = (work.get("doi") or "").replace("https://doi.org/", "").strip()

    concepts = work.get("concepts") or []
    field: Optional[str] = None
    if concepts and isinstance(concepts[0], dict):
        field = concepts[0].get("display_name")

    names = []
    for a in (work.get("authorships") or [])[:3]:
        if isinstance(a, dict):
            author = a.get("author") or {}
            name = (author.get("display_name") if isinstance(author, dict) else None)
            if name:
                names.append(name)
    authors_str = ", ".join(names) or None

    abstract_text: Optional[str] = None
    abstract_inv = work.get("abstract_inverted_index") or {}
    if abstract_inv and isinstance(abstract_inv, dict):
        try:
            all_pos = [p for positions in abstract_inv.values() for p in positions]
            if all_pos:
                word_arr = [""] * (max(all_pos) + 1)
                for word, positions in abstract_inv.items():
                    for pos in positions:
                        if 0 <= pos < len(word_arr):
                            word_arr[pos] = word
                abstract_text = " ".join(w for w in word_arr if w)[:300] or None
        except Exception:
            pass

    source_name: Optional[str] = None
    primary_loc = work.get("primary_location") or {}
    if isinstance(primary_loc, dict):
        src = primary_loc.get("source") or {}
        if isinstance(src, dict):
            source_name = src.get("display_name") or None

    return CitationNode(
        id=wid or doi_raw or f"unknown_{hash(title)}",
        label=title,
        year=year,
        citation_count=ccount,
        node_type=node_type,
        field=field,
        doi=doi_raw or None,
        abstract=abstract_text,
        authors=authors_str,
        source=source_name,
        is_key_paper=(ccount >= 100),
    )


@router.get("/external/citation-network", response_model=CitationNetworkResponse)
async def citation_network(
    doi: str = Query(..., description="Seed paper DOI"),
    depth: int = Query(default=1, ge=1, le=2),
):
    """
    Build a citation web for a DOI via OpenAlex.
    Returns ancestors (references), descendants (citing papers), and co-citations.
    No authentication required — public endpoint.
    """
    import asyncio
    import urllib.parse

    encoded_doi = urllib.parse.quote(doi.strip(), safe="")

    async with httpx.AsyncClient() as client:
        seed_data = await _oa_get(
            client,
            f"https://api.openalex.org/works/https://doi.org/{encoded_doi}?select={_OA_SELECT_FULL}",
        )
        if not seed_data or "id" not in seed_data:
            raise HTTPException(status_code=404, detail="Paper not found on OpenAlex. Check the DOI.")

        seed_id = seed_data["id"]
        nodes: list[CitationNode] = [_oa_node(seed_data, "seed")]
        edges: list[CitationEdge] = []
        seen: set[str] = {seed_id}

        ref_ids = [r for r in (seed_data.get("referenced_works") or []) if r][:40]
        anc_task = _oa_get(
            client,
            f"https://api.openalex.org/works?filter=openalex_id:{'|'.join(ref_ids)}&per-page=40&select={_OA_SELECT_LIGHT}",
        ) if ref_ids else None
        desc_task = _oa_get(
            client,
            f"https://api.openalex.org/works?filter=cites:{seed_id}&per-page=40&sort=cited_by_count:desc&select={_OA_SELECT_LIGHT}",
        )

        tasks = [t for t in [anc_task, desc_task] if t is not None]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        idx = 0
        if anc_task is not None:
            anc_result = results[idx]; idx += 1
            if isinstance(anc_result, dict):
                for work in (anc_result.get("results") or []):
                    wid = (work.get("id") or "").strip()
                    if wid and wid not in seen:
                        seen.add(wid)
                        nodes.append(_oa_node(work, "ancestor"))
                        edges.append(CitationEdge(source=seed_id, target=wid, edge_type="references"))

        desc_result = results[idx]
        if isinstance(desc_result, dict):
            for work in (desc_result.get("results") or []):
                wid = (work.get("id") or "").strip()
                if wid and wid not in seen:
                    seen.add(wid)
                    nodes.append(_oa_node(work, "descendant"))
                    edges.append(CitationEdge(source=wid, target=seed_id, edge_type="cites"))

        if depth >= 2:
            desc_ids = [e.source for e in edges if e.edge_type == "cites"]
            if desc_ids:
                ref_tasks = [
                    _oa_get(client, f"https://api.openalex.org/works/{urllib.parse.quote(did, safe='')}?select={_OA_SELECT_REFS}")
                    for did in desc_ids[:20]
                ]
                ref_results = await asyncio.gather(*ref_tasks, return_exceptions=True)
                ref_count: dict[str, int] = {}
                for res in ref_results:
                    if isinstance(res, dict):
                        for rid in (res.get("referenced_works") or [])[:20]:
                            if rid and rid != seed_id and rid not in seen:
                                ref_count[rid] = ref_count.get(rid, 0) + 1
                top_cocite = sorted(ref_count.items(), key=lambda x: x[1], reverse=True)[:10]
                if top_cocite:
                    co_ids = "|".join(r[0] for r in top_cocite)
                    co_data = await _oa_get(
                        client,
                        f"https://api.openalex.org/works?filter=openalex_id:{co_ids}&per-page=10&select={_OA_SELECT_LIGHT}",
                    )
                    for work in (co_data.get("results") or []):
                        wid = (work.get("id") or "").strip()
                        if wid and wid not in seen:
                            seen.add(wid)
                            nodes.append(_oa_node(work, "cocite"))
                            edges.append(CitationEdge(source=seed_id, target=wid, edge_type="co_citation"))

    years = [n.year for n in nodes if n.year is not None]
    return CitationNetworkResponse(
        seed_doi=doi,
        nodes=nodes,
        edges=edges,
        year_range=[min(years), max(years)] if len(years) >= 2 else [],
    )