from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx


@dataclass
class ExternalPaper:
    source: str
    source_id: str
    title: str
    year: Optional[int] = None
    authors: Optional[List[str]] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    citation_count: Optional[int] = None
    is_retracted: bool = False
    raw: Optional[Dict[str, Any]] = None


SearchResult = Tuple[List[ExternalPaper], Optional[str], int]


class Provider(Protocol):
    source_name: str

    async def search(
        self,
        q: str,
        limit: int = 10,
        cursor_mark: str = "*",
        *,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> SearchResult:
        ...


from backend.doi import normalize_doi as _clean_doi


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _normalize_source(source: str) -> str:
    s = (source or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def _clamp_limit(limit: int, max_allowed: int = 100) -> int:
    try:
        n = int(limit)
    except Exception:
        n = 10
    return max(1, min(n, max_allowed))


def _int_or_none(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _year_bounds(year_from: Optional[int], year_to: Optional[int]) -> Tuple[Optional[int], Optional[int]]:
    yf = _int_or_none(year_from)
    yt = _int_or_none(year_to)
    if yf is not None and (yf < 1000 or yf > 3000):
        yf = None
    if yt is not None and (yt < 1000 or yt > 3000):
        yt = None
    if yf is not None and yt is not None and yf > yt:
        yf, yt = yt, yf
    return yf, yt


async def _request_with_retries(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 20.0,
    max_retries: int = 3,
    retry_base_sleep: float = 0.8,
) -> httpx.Response:
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                r = await client.request(method, url, params=params, headers=headers)

            if r.status_code in (429,) or (500 <= r.status_code <= 599):
                if attempt < max_retries:
                    ra = r.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        await asyncio.sleep(float(ra))
                    else:
                        await asyncio.sleep(retry_base_sleep * (2 ** attempt))
                    continue
            return r

        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt < max_retries:
                await asyncio.sleep(retry_base_sleep * (2 ** attempt))
                continue
            raise

    raise RuntimeError("Retry loop failed unexpectedly")


class EuropePMCProvider:
    source_name = "europepmc"

    async def search(
        self,
        q: str,
        limit: int = 10,
        cursor_mark: str = "*",
        *,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> SearchResult:
        page_size = _clamp_limit(limit, 100)

        yf, yt = _year_bounds(year_from, year_to)
        query = q
        if yf is not None or yt is not None:
            yf2 = yf if yf is not None else 1000
            yt2 = yt if yt is not None else 3000
            query = f"({q}) AND PUB_YEAR:[{yf2} TO {yt2}]"

        params = {
            "query": query,
            "format": "json",
            "pageSize": str(page_size),
            "resultType": "core",
            "cursorMark": cursor_mark or "*",
        }

        headers = {
            "Accept": "application/json",
            "User-Agent": "MedicalEvidenceApp/1.0 (EuropePMC)",
        }

        try:
            r = await _request_with_retries(
                "GET",
                "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params=params,
                headers=headers,
                timeout=20.0,
                max_retries=2,
            )
        except Exception as e:
            raise ProviderError(f"Europe PMC error: {type(e).__name__}: {e}", status_code=502)

        if r.status_code == 429:
            raise ProviderError("Europe PMC rate-limited (429). Try again soon.", status_code=429)
        if r.status_code >= 400:
            raise ProviderError(f"Europe PMC HTTP {r.status_code}. {(r.text or '')[:200]}", status_code=502)

        try:
            data = r.json() or {}
        except Exception:
            raise ProviderError("Europe PMC returned non-JSON response.", status_code=502)

        results = (data.get("resultList") or {}).get("result") or []
        next_cursor = data.get("nextCursorMark")
        hit_count = _int_or_none(data.get("hitCount")) or 0

        out: List[ExternalPaper] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue

            pmid  = item.get("pmid")
            pmcid = item.get("pmcid")
            doi   = item.get("doi")

            source_id = item.get("id") or pmid or pmcid or doi
            if not source_id:
                continue

            year = _int_or_none(item.get("pubYear"))

            author_str = item.get("authorString")
            authors = None
            if isinstance(author_str, str) and author_str.strip():
                authors = [a.strip() for a in author_str.split(",") if a.strip()]

            journal = item.get("journalTitle") or (item.get("journalInfo", {}) or {}).get("journal", {}).get("title")

            url = None
            if pmid:
                url = f"https://europepmc.org/article/MED/{pmid}"
            elif pmcid:
                url = f"https://europepmc.org/article/PMC/{pmcid}"
            elif doi:
                url = f"https://doi.org/{doi}"

            abstract = item.get("abstractText")

            # Retraction: Europe PMC returns "Y" / "N" string
            retracted_raw = item.get("isRetracted", "N")
            is_retracted = str(retracted_raw).strip().upper() == "Y"

            # Citation count: Europe PMC returns citedByCount
            citation_count = _int_or_none(item.get("citedByCount"))

            out.append(
                ExternalPaper(
                    source=self.source_name,
                    source_id=str(source_id),
                    title=title,
                    year=year,
                    authors=authors,
                    venue=journal,
                    doi=str(doi) if doi else None,
                    url=url,
                    abstract=abstract,
                    pmid=str(pmid) if pmid else None,
                    pmcid=str(pmcid) if pmcid else None,
                    citation_count=citation_count,
                    is_retracted=is_retracted,
                    raw=item,
                )
            )

        return out, next_cursor, int(hit_count)


class SemanticScholarProvider:
    source_name = "semantic_scholar"
    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self):
        self.api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()

    async def search(
        self,
        q: str,
        limit: int = 10,
        cursor_mark: str = "0",
        *,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> SearchResult:
        page_size = _clamp_limit(limit, 100)

        offset = 0
        try:
            if cursor_mark is not None and str(cursor_mark).strip() != "":
                offset = max(0, int(str(cursor_mark)))
        except Exception:
            offset = 0

        params = {
            "query": q,
            "limit": page_size,
            "offset": offset,
            # Added citationCount to fields
            "fields": "paperId,title,abstract,year,venue,authors,url,externalIds,citationCount,isOpenAccess",
        }

        yf, yt = _year_bounds(year_from, year_to)
        if yf is not None or yt is not None:
            if yf is not None and yt is not None:
                params["year"] = f"{yf}-{yt}"
            elif yf is not None:
                params["year"] = f"{yf}-"
            else:
                params["year"] = f"-{yt}"

        headers = {
            "Accept": "application/json",
            "User-Agent": "MedicalEvidenceApp/1.0 (SemanticScholar)",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            r = await _request_with_retries(
                "GET",
                f"{self.BASE}/paper/search",
                params=params,
                headers=headers,
                timeout=25.0,
                max_retries=3,
            )
        except Exception as e:
            raise ProviderError(f"Semantic Scholar error: {type(e).__name__}: {e}", status_code=502)

        if r.status_code == 429:
            raise ProviderError(
                "Semantic Scholar rate-limited (429). Add SEMANTIC_SCHOLAR_API_KEY or try again later.",
                status_code=429,
            )
        if r.status_code == 401:
            raise ProviderError("Semantic Scholar auth failed (401). Check SEMANTIC_SCHOLAR_API_KEY.", status_code=502)
        if r.status_code == 403:
            raise ProviderError("Semantic Scholar blocked the request (403).", status_code=502)
        if r.status_code >= 400:
            raise ProviderError(f"Semantic Scholar HTTP {r.status_code}. {(r.text or '')[:250]}", status_code=502)

        try:
            data = r.json() or {}
        except Exception:
            raise ProviderError("Semantic Scholar returned non-JSON response.", status_code=502)

        total = _int_or_none(data.get("total")) or 0
        raw_results = data.get("data") or []
        if not isinstance(raw_results, list):
            raw_results = []

        out: List[ExternalPaper] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue

            title = (item.get("title") or "").strip()
            paper_id = item.get("paperId")
            if not paper_id or not title:
                continue

            ext = item.get("externalIds") or {}
            if not isinstance(ext, dict):
                ext = {}

            doi   = ext.get("DOI")
            pmid  = ext.get("PubMed")
            pmcid = ext.get("PubMedCentral")

            authors = None
            a_in = item.get("authors")
            if isinstance(a_in, list):
                authors = [a.get("name") for a in a_in if isinstance(a, dict) and a.get("name")]

            venue    = item.get("venue")
            url      = item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"
            abstract = item.get("abstract")
            year     = _int_or_none(item.get("year"))

            # Citation count: Semantic Scholar returns citationCount directly
            citation_count = _int_or_none(item.get("citationCount"))

            out.append(
                ExternalPaper(
                    source=self.source_name,
                    source_id=str(paper_id),
                    title=title,
                    year=year,
                    authors=authors,
                    venue=venue,
                    doi=str(doi) if doi else None,
                    url=url,
                    abstract=abstract,
                    pmid=str(pmid) if pmid else None,
                    pmcid=str(pmcid) if pmcid else None,
                    citation_count=citation_count,
                    is_retracted=False,  # Semantic Scholar doesn't expose retraction status
                    raw=item,
                )
            )

        next_cursor: Optional[str] = None
        if total > 0 and (offset + page_size) < total:
            next_cursor = str(offset + page_size)

        return out, next_cursor, int(total)


class OpenAlexProvider:
    source_name = "openalex"
    BASE = "https://api.openalex.org"

    async def search(
        self,
        q: str,
        limit: int = 10,
        cursor_mark: str = "*",
        *,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> SearchResult:
        page_size = _clamp_limit(limit, 200)
        cursor = (cursor_mark or "*").strip() or "*"

        params = {
            "search": q,
            "per_page": str(page_size),
            "cursor": cursor,
        }

        yf, yt = _year_bounds(year_from, year_to)
        filters: List[str] = []
        if yf is not None:
            filters.append(f"from_publication_date:{yf}-01-01")
        if yt is not None:
            filters.append(f"to_publication_date:{yt}-12-31")
        if filters:
            params["filter"] = ",".join(filters)

        headers = {
            "Accept": "application/json",
            "User-Agent": "MedicalEvidenceApp/1.0 (OpenAlex)",
        }

        try:
            r = await _request_with_retries(
                "GET",
                f"{self.BASE}/works",
                params=params,
                headers=headers,
                timeout=25.0,
                max_retries=3,
            )
        except Exception as e:
            raise ProviderError(f"OpenAlex error: {type(e).__name__}: {e}", status_code=502)

        if r.status_code == 429:
            raise ProviderError("OpenAlex rate-limited (429). Try again soon.", status_code=429)
        if r.status_code >= 400:
            raise ProviderError(f"OpenAlex HTTP {r.status_code}. {(r.text or '')[:250]}", status_code=502)

        try:
            data = r.json() or {}
        except Exception:
            raise ProviderError("OpenAlex returned non-JSON response.", status_code=502)

        results  = data.get("results") or []
        meta     = data.get("meta") or {}
        hit_count = _int_or_none(meta.get("count")) or 0
        next_cursor = None
        if isinstance(meta, dict) and meta.get("next_cursor"):
            next_cursor = str(meta.get("next_cursor"))

        out: List[ExternalPaper] = []
        if not isinstance(results, list):
            results = []

        for item in results:
            if not isinstance(item, dict):
                continue
            title   = (item.get("title") or "").strip()
            work_id = item.get("id")
            if not title or not work_id:
                continue

            year = _int_or_none(item.get("publication_year"))

            authors = None
            al = item.get("authorships")
            if isinstance(al, list):
                names: List[str] = []
                for a in al:
                    if not isinstance(a, dict):
                        continue
                    au = a.get("author") or {}
                    if isinstance(au, dict) and au.get("display_name"):
                        names.append(str(au.get("display_name")))
                if names:
                    authors = names

            venue = None
            host = item.get("host_venue") or {}
            if isinstance(host, dict):
                venue = host.get("display_name")

            doi = None
            ids = item.get("ids") or {}
            if isinstance(ids, dict):
                doi = ids.get("doi")
            doi = _clean_doi(doi)

            url = None
            if doi:
                url = f"https://doi.org/{doi}"
            elif item.get("id"):
                url = str(item.get("id"))

            abstract = None
            aii = item.get("abstract_inverted_index")
            if isinstance(aii, dict) and aii:
                try:
                    positions: Dict[int, str] = {}
                    for token, poss in aii.items():
                        if not isinstance(poss, list):
                            continue
                        for p in poss:
                            if isinstance(p, int):
                                positions[p] = str(token)
                    if positions:
                        abstract = " ".join(positions[i] for i in sorted(positions.keys()))
                except Exception:
                    abstract = None

            # OpenAlex returns cited_by_count
            citation_count = _int_or_none(item.get("cited_by_count"))

            out.append(
                ExternalPaper(
                    source=self.source_name,
                    source_id=str(work_id),
                    title=title,
                    year=year,
                    authors=authors,
                    venue=str(venue) if venue else None,
                    doi=doi,
                    url=url,
                    abstract=abstract,
                    citation_count=citation_count,
                    is_retracted=False,
                    raw=item,
                )
            )

        return out, next_cursor, int(hit_count)


class CrossrefProvider:
    source_name = "crossref"
    BASE = "https://api.crossref.org"

    async def search(
        self,
        q: str,
        limit: int = 10,
        cursor_mark: str = "*",
        *,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> SearchResult:
        page_size = _clamp_limit(limit, 100)
        offset = 0
        try:
            if cursor_mark is not None and str(cursor_mark).strip() != "":
                offset = max(0, int(str(cursor_mark)))
        except Exception:
            offset = 0

        params = {
            "query": q,
            "rows": str(page_size),
            "offset": str(offset),
            "select": "DOI,title,author,issued,container-title,URL,abstract",
        }

        yf, yt = _year_bounds(year_from, year_to)
        filt_parts: List[str] = []
        if yf is not None:
            filt_parts.append(f"from-pub-date:{yf}-01-01")
        if yt is not None:
            filt_parts.append(f"until-pub-date:{yt}-12-31")
        if filt_parts:
            params["filter"] = ",".join(filt_parts)

        headers = {
            "Accept": "application/json",
            "User-Agent": "MedicalEvidenceApp/1.0 (Crossref)",
        }

        try:
            r = await _request_with_retries(
                "GET",
                f"{self.BASE}/works",
                params=params,
                headers=headers,
                timeout=25.0,
                max_retries=3,
            )
        except Exception as e:
            raise ProviderError(f"Crossref error: {type(e).__name__}: {e}", status_code=502)

        if r.status_code == 429:
            raise ProviderError("Crossref rate-limited (429). Try again soon.", status_code=429)
        if r.status_code >= 400:
            raise ProviderError(f"Crossref HTTP {r.status_code}. {(r.text or '')[:250]}", status_code=502)

        try:
            data = r.json() or {}
        except Exception:
            raise ProviderError("Crossref returned non-JSON response.", status_code=502)

        msg   = data.get("message") or {}
        items = msg.get("items") or []
        total = _int_or_none(msg.get("total-results")) or 0

        out: List[ExternalPaper] = []
        if not isinstance(items, list):
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            doi = _clean_doi(item.get("DOI"))
            title_list = item.get("title")
            title = None
            if isinstance(title_list, list) and title_list:
                title = str(title_list[0]).strip()
            elif isinstance(title_list, str):
                title = title_list.strip()
            if not title:
                continue

            source_id = doi or item.get("URL") or title

            year = None
            issued = item.get("issued") or {}
            if isinstance(issued, dict):
                dp = issued.get("date-parts")
                if isinstance(dp, list) and dp and isinstance(dp[0], list) and dp[0]:
                    year = _int_or_none(dp[0][0])

            venue = None
            ct = item.get("container-title")
            if isinstance(ct, list) and ct:
                venue = str(ct[0])

            authors = None
            au = item.get("author")
            if isinstance(au, list):
                names: List[str] = []
                for a in au:
                    if not isinstance(a, dict):
                        continue
                    given  = (a.get("given") or "").strip()
                    family = (a.get("family") or "").strip()
                    nm = (given + " " + family).strip()
                    if nm:
                        names.append(nm)
                if names:
                    authors = names

            url = None
            if doi:
                url = f"https://doi.org/{doi}"
            elif item.get("URL"):
                url = str(item.get("URL"))

            abstract = item.get("abstract")

            out.append(
                ExternalPaper(
                    source=self.source_name,
                    source_id=str(source_id),
                    title=title,
                    year=year,
                    authors=authors,
                    venue=venue,
                    doi=doi,
                    url=url,
                    abstract=str(abstract) if isinstance(abstract, str) and abstract.strip() else None,
                    citation_count=None,  # Crossref doesn't expose citation counts
                    is_retracted=False,
                    raw=item,
                )
            )

        next_cursor: Optional[str] = None
        if total > 0 and (offset + page_size) < total:
            next_cursor = str(offset + page_size)

        return out, next_cursor, int(total)


PROVIDERS: Dict[str, Provider] = {
    EuropePMCProvider.source_name:    EuropePMCProvider(),
    SemanticScholarProvider.source_name: SemanticScholarProvider(),
    OpenAlexProvider.source_name:     OpenAlexProvider(),
    CrossrefProvider.source_name:     CrossrefProvider(),
}

ALIASES: Dict[str, str] = {
    "europe_pmc":     "europepmc",
    "europepmc":      "europepmc",
    "semantic":       "semantic_scholar",
    "semantic_scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "open_alex":      "openalex",
    "openalex":       "openalex",
    "cross_ref":      "crossref",
    "crossref":       "crossref",
}


def list_sources() -> List[str]:
    return sorted(PROVIDERS.keys())


def get_provider(source: str) -> Provider:
    key = _normalize_source(source)
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        raise ValueError(f"Unknown source '{source}'. Available: {', '.join(list_sources())}")
    return PROVIDERS[key]