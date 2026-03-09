# tests/test_dedup.py
"""
Import deduplication tests.
Covers: DOI-first dedup, same-provider dedup, cross-source same DOI,
field merging (keep-existing), StudyExternalRef tracking.
"""
from fastapi.testclient import TestClient


PAPER_A = {
    "source": "europepmc",
    "source_id": "PMC123",
    "title": "Effects of Exercise on Cardiac Muscle",
    "year": 2022,
    "doi": "10.1234/test.001",
    "abstract": "This study examines exercise effects.",
    "pmid": "11111",
    "pmcid": "PMC123",
    "authors": ["Smith J", "Jones A"],
    "venue": "Journal of Cardiology",
    "url": "https://europepmc.org/article/PMC/PMC123",
}

PAPER_A_SAME_DOI_DIFF_SOURCE = {
    "source": "semantic_scholar",
    "source_id": "ss-abc-999",
    "title": "Effects of Exercise on Cardiac Muscle",
    "year": 2022,
    "doi": "10.1234/test.001",   # same DOI — should dedup
    "abstract": "A different abstract that should NOT overwrite.",
    "pmid": None,
    "pmcid": None,
    "authors": ["Smith J"],
    "venue": None,
    "url": "https://semanticscholar.org/paper/ss-abc-999",
}

PAPER_B = {
    "source": "europepmc",
    "source_id": "PMC999",
    "title": "Creatine and Muscle Recovery",
    "year": 2021,
    "doi": "10.9999/creatine.02",
    "abstract": "Creatine study abstract.",
    "pmid": "22222",
    "pmcid": "PMC999",
    "authors": ["Brown K"],
    "venue": "Sports Medicine",
    "url": "https://europepmc.org/article/PMC/PMC999",
}


class TestImportBasic:
    def test_import_creates_study(self, client: TestClient, auth: dict):
        r = client.post("/external/import", json=PAPER_A, headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == PAPER_A["title"]
        assert data["doi"] == "10.1234/test.001"
        assert data["source"] == "europepmc"

    def test_import_assigns_owner(self, client: TestClient, auth: dict):
        r = client.post("/external/import", json=PAPER_A, headers=auth)
        assert r.status_code == 200
        assert r.json()["owner_username"] == "testuser"

    def test_import_requires_auth(self, client: TestClient):
        r = client.post("/external/import", json=PAPER_A)
        assert r.status_code == 401

    def test_import_second_paper_distinct(self, client: TestClient, auth: dict):
        client.post("/external/import", json=PAPER_A, headers=auth)
        r = client.post("/external/import", json=PAPER_B, headers=auth)
        assert r.status_code == 200
        assert r.json()["source_id"] == "PMC999"

        studies = client.get("/studies", headers=auth).json()
        assert len(studies) == 2


class TestDOIDedup:
    def test_doi_dedup_returns_same_id(self, client: TestClient, auth: dict):
        """Importing same DOI from two sources returns the same study id."""
        r1 = client.post("/external/import", json=PAPER_A, headers=auth)
        assert r1.status_code == 200
        id1 = r1.json()["id"]

        r2 = client.post("/external/import", json=PAPER_A_SAME_DOI_DIFF_SOURCE, headers=auth)
        assert r2.status_code == 200
        id2 = r2.json()["id"]

        assert id1 == id2

    def test_doi_dedup_no_duplicate_in_library(self, client: TestClient, auth: dict):
        client.post("/external/import", json=PAPER_A, headers=auth)
        client.post("/external/import", json=PAPER_A_SAME_DOI_DIFF_SOURCE, headers=auth)

        studies = client.get("/studies", headers=auth).json()
        assert len(studies) == 1

    def test_doi_dedup_preserves_original_abstract(self, client: TestClient, auth: dict):
        """First import's abstract should be kept (keep-existing merge)."""
        r1 = client.post("/external/import", json=PAPER_A, headers=auth)
        original_abstract = r1.json()["abstract"]

        r2 = client.post("/external/import", json=PAPER_A_SAME_DOI_DIFF_SOURCE, headers=auth)
        assert r2.json()["abstract"] == original_abstract

    def test_doi_dedup_fills_missing_fields(self, client: TestClient, auth: dict):
        """If first import is missing a field, second import fills it in."""
        paper_no_venue = {**PAPER_A, "venue": None, "doi": "10.1234/test.fill"}
        paper_with_venue = {**PAPER_A_SAME_DOI_DIFF_SOURCE, "doi": "10.1234/test.fill", "venue": "New Venue"}

        r1 = client.post("/external/import", json=paper_no_venue, headers=auth)
        assert r1.json()["venue"] is None

        r2 = client.post("/external/import", json=paper_with_venue, headers=auth)
        assert r2.json()["venue"] == "New Venue"

    def test_doi_normalised_before_dedup(self, client: TestClient, auth: dict):
        """DOIs with https://doi.org/ prefix should match bare DOIs."""
        paper_bare = {**PAPER_A, "doi": "10.1234/norm.001"}
        paper_url  = {**PAPER_A_SAME_DOI_DIFF_SOURCE, "doi": "https://doi.org/10.1234/norm.001"}

        r1 = client.post("/external/import", json=paper_bare, headers=auth)
        r2 = client.post("/external/import", json=paper_url, headers=auth)
        assert r1.json()["id"] == r2.json()["id"]

        studies = client.get("/studies", headers=auth).json()
        assert len(studies) == 1


class TestSameProviderDedup:
    def test_same_source_same_id_deduped(self, client: TestClient, auth: dict):
        """Same source + source_id for same user = no duplicate."""
        r1 = client.post("/external/import", json={**PAPER_A, "doi": None}, headers=auth)
        r2 = client.post("/external/import", json={**PAPER_A, "doi": None}, headers=auth)
        assert r1.json()["id"] == r2.json()["id"]

        studies = client.get("/studies", headers=auth).json()
        assert len(studies) == 1


class TestUserIsolation:
    def test_two_users_same_doi_independent(self, client: TestClient, auth: dict, auth2: dict):
        """Same DOI imported by two different users = two separate studies."""
        r1 = client.post("/external/import", json=PAPER_A, headers=auth)
        r2 = client.post("/external/import", json=PAPER_A, headers=auth2)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["id"] != r2.json()["id"]

    def test_user_cannot_see_other_user_study(self, client: TestClient, auth: dict, auth2: dict):
        r = client.post("/external/import", json=PAPER_A, headers=auth)
        study_id = r.json()["id"]

        r2 = client.get(f"/studies/{study_id}", headers=auth2)
        assert r2.status_code == 403
