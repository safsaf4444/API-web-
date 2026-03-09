# tests/test_studies.py
"""
Studies CRUD: list, get, patch, delete, folder assignment, comments.
"""
from fastapi.testclient import TestClient

PAPER = {
    "source": "europepmc",
    "source_id": "PMC001",
    "title": "Test Paper Title",
    "year": 2023,
    "doi": "10.0000/test.paper",
    "abstract": "Test abstract content.",
    "pmid": "33333",
    "pmcid": "PMC001",
    "authors": ["Author A"],
    "venue": "Test Journal",
    "url": "https://europepmc.org/article/PMC/PMC001",
}


def _import(client, auth):
    return client.post("/external/import", json=PAPER, headers=auth).json()


class TestStudiesBasic:
    def test_list_empty(self, client: TestClient, auth: dict):
        r = client.get("/studies", headers=auth)
        assert r.status_code == 200
        assert r.json() == []

    def test_list_after_import(self, client: TestClient, auth: dict):
        _import(client, auth)
        studies = client.get("/studies", headers=auth).json()
        assert len(studies) == 1
        assert studies[0]["title"] == PAPER["title"]

    def test_get_by_id(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.get(f"/studies/{s['id']}", headers=auth)
        assert r.status_code == 200
        assert r.json()["id"] == s["id"]

    def test_get_not_found(self, client: TestClient, auth: dict):
        r = client.get("/studies/99999", headers=auth)
        assert r.status_code == 404

    def test_get_requires_auth(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.get(f"/studies/{s['id']}")
        assert r.status_code == 401

    def test_other_user_cannot_get(self, client: TestClient, auth: dict, auth2: dict):
        s = _import(client, auth)
        r = client.get(f"/studies/{s['id']}", headers=auth2)
        assert r.status_code == 403


class TestStudiesPatch:
    def test_patch_notes(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.patch(f"/studies/{s['id']}", json={"notes": "Important paper"}, headers=auth)
        assert r.status_code == 200
        assert r.json()["notes"] == "Important paper"

    def test_patch_folder(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        f = client.post("/folders", json={"name": "My Folder"}, headers=auth).json()
        r = client.patch(f"/studies/{s['id']}", json={"folder_id": f["id"]}, headers=auth)
        assert r.status_code == 200
        assert r.json()["folder_id"] == f["id"]

    def test_patch_invalid_folder(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.patch(f"/studies/{s['id']}", json={"folder_id": 99999}, headers=auth)
        assert r.status_code == 400

    def test_patch_other_user_folder_rejected(self, client: TestClient, auth: dict, auth2: dict):
        s = _import(client, auth)
        f2 = client.post("/folders", json={"name": "Other Folder"}, headers=auth2).json()
        r = client.patch(f"/studies/{s['id']}", json={"folder_id": f2["id"]}, headers=auth)
        assert r.status_code == 400


class TestStudiesDelete:
    def test_delete_study(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.delete(f"/studies/{s['id']}", headers=auth)
        assert r.status_code == 200
        assert client.get(f"/studies/{s['id']}", headers=auth).status_code == 404

    def test_delete_removes_comments(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        client.post(f"/studies/{s['id']}/comments", json={"body": "A comment"}, headers=auth)
        client.delete(f"/studies/{s['id']}", headers=auth)
        # Study gone → comment list should 404
        r = client.get(f"/studies/{s['id']}/comments", headers=auth)
        assert r.status_code == 404

    def test_delete_other_user_rejected(self, client: TestClient, auth: dict, auth2: dict):
        s = _import(client, auth)
        r = client.delete(f"/studies/{s['id']}", headers=auth2)
        assert r.status_code == 403


class TestStudiesSort:
    def test_sort_newest(self, client: TestClient, auth: dict):
        p1 = {**PAPER, "source_id": "s1", "doi": None, "year": 2020}
        p2 = {**PAPER, "source_id": "s2", "doi": None, "year": 2022}
        client.post("/external/import", json=p1, headers=auth)
        client.post("/external/import", json=p2, headers=auth)
        studies = client.get("/studies?sort=newest", headers=auth).json()
        assert studies[0]["source_id"] == "s2"

    def test_sort_oldest(self, client: TestClient, auth: dict):
        p1 = {**PAPER, "source_id": "s1", "doi": None, "year": 2020}
        p2 = {**PAPER, "source_id": "s2", "doi": None, "year": 2022}
        client.post("/external/import", json=p1, headers=auth)
        client.post("/external/import", json=p2, headers=auth)
        studies = client.get("/studies?sort=oldest", headers=auth).json()
        assert studies[0]["source_id"] == "s1"

    def test_search_by_title(self, client: TestClient, auth: dict):
        p1 = {**PAPER, "source_id": "x1", "doi": None, "title": "Creatine and Muscle"}
        p2 = {**PAPER, "source_id": "x2", "doi": None, "title": "Exercise and Heart Rate"}
        client.post("/external/import", json=p1, headers=auth)
        client.post("/external/import", json=p2, headers=auth)
        results = client.get("/studies?q=Creatine", headers=auth).json()
        assert len(results) == 1
        assert "Creatine" in results[0]["title"]


class TestComments:
    def test_add_comment(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        r = client.post(f"/studies/{s['id']}/comments",
                        json={"body": "Great paper"}, headers=auth)
        assert r.status_code == 200
        assert r.json()["body"] == "Great paper"
        assert r.json()["author"] == "testuser"

    def test_list_comments(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        client.post(f"/studies/{s['id']}/comments", json={"body": "First"}, headers=auth)
        client.post(f"/studies/{s['id']}/comments", json={"body": "Second"}, headers=auth)
        comments = client.get(f"/studies/{s['id']}/comments", headers=auth).json()
        assert len(comments) == 2

    def test_edit_comment(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        c = client.post(f"/studies/{s['id']}/comments",
                        json={"body": "Original"}, headers=auth).json()
        r = client.patch(f"/comments/{c['id']}", json={"body": "Edited"}, headers=auth)
        assert r.status_code == 200
        assert r.json()["body"] == "Edited"

    def test_delete_comment(self, client: TestClient, auth: dict):
        s = _import(client, auth)
        c = client.post(f"/studies/{s['id']}/comments",
                        json={"body": "To delete"}, headers=auth).json()
        r = client.delete(f"/comments/{c['id']}", headers=auth)
        assert r.status_code == 200
        comments = client.get(f"/studies/{s['id']}/comments", headers=auth).json()
        assert len(comments) == 0

    def test_other_user_cannot_comment(self, client: TestClient, auth: dict, auth2: dict):
        s = _import(client, auth)
        r = client.post(f"/studies/{s['id']}/comments",
                        json={"body": "Sneaky"}, headers=auth2)
        assert r.status_code == 403
