# tests/test_providers.py
"""
Provider unit tests — no real HTTP calls.
Uses pytest-httpx (or monkeypatching) to mock responses.
Tests: DOI normalisation, EuropePMC parsing, Semantic Scholar parsing,
year filtering logic, ProviderError handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────
# DOI NORMALISATION (pure unit)
# ─────────────────────────────────────────
class TestDoiNormalisation:
    """Tests the _clean_doi helper used in external.py."""

    def _clean(self, doi):
        from backend.routers.external import _clean_doi
        return _clean_doi(doi)

    def test_bare_doi_unchanged(self):
        assert self._clean("10.1234/test.001") == "10.1234/test.001"

    def test_strips_https_doi_prefix(self):
        assert self._clean("https://doi.org/10.1234/test.001") == "10.1234/test.001"

    def test_strips_http_doi_prefix(self):
        assert self._clean("http://doi.org/10.1234/test.001") == "10.1234/test.001"

    def test_strips_dx_doi_prefix(self):
        assert self._clean("https://dx.doi.org/10.1234/test.001") == "10.1234/test.001"

    def test_strips_doi_colon_prefix(self):
        assert self._clean("doi:10.1234/test.001") == "10.1234/test.001"

    def test_strips_doi_colon_space_prefix(self):
        assert self._clean("doi: 10.1234/test.001") == "10.1234/test.001"

    def test_none_returns_none(self):
        assert self._clean(None) is None

    def test_empty_string_returns_none(self):
        assert self._clean("") is None

    def test_whitespace_only_returns_none(self):
        assert self._clean("   ") is None

    def test_strips_surrounding_whitespace(self):
        assert self._clean("  10.1234/test.001  ") == "10.1234/test.001"


# ─────────────────────────────────────────
# PROVIDER REGISTRY
# ─────────────────────────────────────────
class TestProviderRegistry:
    def test_get_europepmc(self):
        from backend.external_providers import get_provider
        p = get_provider("europepmc")
        assert p.source_name == "europepmc"

    def test_get_semantic_scholar(self):
        from backend.external_providers import get_provider
        p = get_provider("semantic_scholar")
        assert p.source_name == "semantic_scholar"

    def test_get_openalex(self):
        from backend.external_providers import get_provider
        p = get_provider("openalex")
        assert p.source_name == "openalex"

    def test_unknown_provider_raises(self):
        from backend.external_providers import get_provider
        with pytest.raises(ValueError):
            get_provider("not_a_real_provider")

    def test_list_sources_contains_expected(self):
        from backend.external_providers import list_sources
        sources = list_sources()
        assert "europepmc" in sources
        assert "semantic_scholar" in sources


# ─────────────────────────────────────────
# EUROPE PMC — mock HTTP
# ─────────────────────────────────────────
MOCK_EPMC_RESPONSE = {
    "hitCount": 1,
    "nextCursorMark": "*",
    "resultList": {
        "result": [
            {
                "id": "PMC123",
                "title": "Exercise and Cardiac Health",
                "pubYear": "2022",
                "doi": "10.1234/test.001",
                "pmid": "11111",
                "pmcid": "PMC123",
                "authorString": "Smith J, Jones A",
                "journalTitle": "Journal of Cardiology",
                "abstractText": "This is a test abstract about cardiac health.",
            }
        ]
    },
}


class TestEuropePMCProvider:
    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        from backend.external_providers import EuropePMCProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_EPMC_RESPONSE

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = EuropePMCProvider()
            papers, cursor, count = await provider.search("cardiac exercise")

        assert len(papers) == 1
        p = papers[0]
        assert p.title == "Exercise and Cardiac Health"
        assert p.doi == "10.1234/test.001"
        assert p.pmcid == "PMC123"
        assert p.pmid == "11111"
        assert p.year == 2022
        assert p.source == "europepmc"
        assert "Smith J" in p.authors

    @pytest.mark.asyncio
    async def test_search_empty_results(self):
        from backend.external_providers import EuropePMCProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hitCount": 0,
            "nextCursorMark": None,
            "resultList": {"result": []},
        }

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = EuropePMCProvider()
            papers, cursor, count = await provider.search("xyzunlikelykeyword")

        assert papers == []
        assert count == 0

    @pytest.mark.asyncio
    async def test_search_429_raises_provider_error(self):
        from backend.external_providers import EuropePMCProvider, ProviderError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = EuropePMCProvider()
            with pytest.raises(ProviderError) as exc:
                await provider.search("test")
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_search_500_raises_provider_error(self):
        from backend.external_providers import EuropePMCProvider, ProviderError

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "internal error"
        mock_response.headers = {}

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = EuropePMCProvider()
            with pytest.raises(ProviderError):
                await provider.search("test")

    @pytest.mark.asyncio
    async def test_network_error_raises_provider_error(self):
        from backend.external_providers import EuropePMCProvider, ProviderError
        import httpx

        with patch(
            "backend.external_providers._request_with_retries",
            new=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        ):
            provider = EuropePMCProvider()
            with pytest.raises(ProviderError):
                await provider.search("test")

    @pytest.mark.asyncio
    async def test_skips_entries_with_no_title(self):
        from backend.external_providers import EuropePMCProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hitCount": 2,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {"id": "A1", "title": ""},           # no title — skip
                    {"id": "A2", "title": "Valid Paper", "pubYear": "2020"},
                ]
            },
        }

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = EuropePMCProvider()
            papers, _, _ = await provider.search("test")

        assert len(papers) == 1
        assert papers[0].title == "Valid Paper"


# ─────────────────────────────────────────
# SEMANTIC SCHOLAR — mock HTTP
# ─────────────────────────────────────────
MOCK_SS_RESPONSE = {
    "total": 1,
    "data": [
        {
            "paperId": "ss-abc-999",
            "title": "Creatine Supplementation in Athletes",
            "abstract": "Study about creatine.",
            "year": 2021,
            "venue": "Sports Medicine",
            "url": "https://semanticscholar.org/paper/ss-abc-999",
            "authors": [{"name": "Brown K"}, {"name": "White L"}],
            "externalIds": {
                "DOI": "10.9999/creatine.02",
                "PubMed": "22222",
                "PubMedCentral": "PMC999",
            },
        }
    ],
}


class TestSemanticScholarProvider:
    @pytest.mark.asyncio
    async def test_search_returns_papers(self):
        from backend.external_providers import SemanticScholarProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = MOCK_SS_RESPONSE

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = SemanticScholarProvider()
            papers, cursor, count = await provider.search("creatine athletes")

        assert len(papers) == 1
        p = papers[0]
        assert p.title == "Creatine Supplementation in Athletes"
        assert p.doi == "10.9999/creatine.02"
        assert p.source == "semantic_scholar"
        assert p.source_id == "ss-abc-999"
        assert "Brown K" in p.authors

    @pytest.mark.asyncio
    async def test_search_429_raises_provider_error(self):
        from backend.external_providers import SemanticScholarProvider, ProviderError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = SemanticScholarProvider()
            with pytest.raises(ProviderError) as exc:
                await provider.search("test")
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_pagination_cursor(self):
        from backend.external_providers import SemanticScholarProvider

        # total=30, page_size=10, offset=0 → next cursor = "10"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 30,
            "data": [{"paperId": f"id{i}", "title": f"Paper {i}"} for i in range(10)],
        }

        with patch("backend.external_providers._request_with_retries", new=AsyncMock(return_value=mock_response)):
            provider = SemanticScholarProvider()
            papers, cursor, count = await provider.search("test", limit=10, cursor_mark="0")

        assert cursor == "10"
        assert count == 30


# ─────────────────────────────────────────
# YEAR BOUNDS HELPER (pure unit)
# ─────────────────────────────────────────
class TestYearBounds:
    def _bounds(self, yf, yt):
        from backend.external_providers import _year_bounds
        return _year_bounds(yf, yt)

    def test_both_none(self):
        assert self._bounds(None, None) == (None, None)

    def test_normal_range(self):
        assert self._bounds(2010, 2020) == (2010, 2020)

    def test_reversed_swapped(self):
        yf, yt = self._bounds(2020, 2010)
        assert yf == 2010
        assert yt == 2020

    def test_invalid_year_ignored(self):
        yf, yt = self._bounds(999, 2020)
        assert yf is None
        assert yt == 2020

    def test_only_from(self):
        yf, yt = self._bounds(2018, None)
        assert yf == 2018
        assert yt is None


# ─────────────────────────────────────────
# EXTERNAL SEARCH ENDPOINT
# ─────────────────────────────────────────
class TestExternalSearchEndpoint:
    def test_sources_endpoint(self, client):
        r = client.get("/external/sources")
        assert r.status_code == 200
        sources = r.json()["sources"]
        assert "europepmc" in sources

    def test_search_requires_q(self, client):
        r = client.get("/external/search?source=europepmc")
        assert r.status_code == 422  # missing required param

    def test_search_q_too_short(self, client):
        r = client.get("/external/search?q=a&source=europepmc")
        assert r.status_code == 422

    def test_search_invalid_source(self, client):
        r = client.get("/external/search?q=cancer&source=fakeprovider")
        assert r.status_code == 400
