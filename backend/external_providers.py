from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
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
    raw: Optional[Dict[str, Any]] = None


SearchResult = Tuple[List[ExternalPaper], Optional[str], int]


class Provider(Protocol):
    source_name: str
    async def search(self, q: str, limit: int = 10, cursor_mark: str = "*") -> SearchResult:
        ...


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

            # Retry on rate-limit and transient 5xx
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

    async def search(self, q: str, limit: int = 10, cursor_mark: str = "*") -> SearchResult:
        page_size = _clamp_limit(limit, 100)

        params = {
            "query": q,
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

            pmid = item.get("pmid")
            pmcid = item.get("pmcid")
            doi = item.get("doi")

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
                    raw=item,
                )
            )

        return out, next_cursor, int(hit_count)


class SemanticScholarProvider:
    source_name = "semantic_scholar"
    BASE = "https://api.semanticscholar.org/graph/v1"

    def __init__(self):
        self.api_key = (os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()

    async def search(self, q: str, limit: int = 10, cursor_mark: str = "0") -> SearchResult:
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
            "fields": "paperId,title,abstract,year,venue,authors,url,externalIds",
        }

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

            doi = ext.get("DOI")
            pmid = ext.get("PubMed")
            pmcid = ext.get("PubMedCentral")

            authors = None
            a_in = item.get("authors")
            if isinstance(a_in, list):
                authors = [a.get("name") for a in a_in if isinstance(a, dict) and a.get("name")]

            venue = item.get("venue")
            url = item.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}"
            abstract = item.get("abstract")
            year = _int_or_none(item.get("year"))

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
                    raw=item,
                )
            )

        next_cursor: Optional[str] = None
        if total > 0 and (offset + page_size) < total:
            next_cursor = str(offset + page_size)

        return out, next_cursor, int(total)


PROVIDERS: Dict[str, Provider] = {
    EuropePMCProvider.source_name: EuropePMCProvider(),
    SemanticScholarProvider.source_name: SemanticScholarProvider(),
}

ALIASES: Dict[str, str] = {
    "europe_pmc": "europepmc",
    "europepmc": "europepmc",
    "semantic": "semantic_scholar",
    "semantic_scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
}


def list_sources() -> List[str]:
    return sorted(PROVIDERS.keys())


def get_provider(source: str) -> Provider:
    key = _normalize_source(source)
    key = ALIASES.get(key, key)
    if key not in PROVIDERS:
        raise ValueError(f"Unknown source '{source}'. Available: {', '.join(list_sources())}")
    return PROVIDERS[key]
