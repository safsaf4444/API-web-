# tests/test_auth.py
"""
Auth tests: register, login, token, /me, edge cases.
"""
import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────
class TestRegister:
    def test_register_success(self, client: TestClient):
        r = client.post("/auth/register", json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "secret99",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "alice"
        assert data["email"] == "alice@example.com"
        assert "id" in data
        assert "hashed_password" not in data  # never leak hash

    def test_register_duplicate_username(self, client: TestClient):
        payload = {"username": "bob", "email": "bob@example.com", "password": "secret99"}
        client.post("/auth/register", json=payload)
        r = client.post("/auth/register", json={**payload, "email": "bob2@example.com"})
        assert r.status_code == 400

    def test_register_duplicate_email(self, client: TestClient):
        client.post("/auth/register", json={
            "username": "carol", "email": "carol@example.com", "password": "secret99"
        })
        r = client.post("/auth/register", json={
            "username": "carol2", "email": "carol@example.com", "password": "secret99"
        })
        assert r.status_code == 400

    def test_register_short_password(self, client: TestClient):
        r = client.post("/auth/register", json={
            "username": "dan", "email": "dan@example.com", "password": "abc"
        })
        assert r.status_code == 400

    def test_register_empty_password(self, client: TestClient):
        r = client.post("/auth/register", json={
            "username": "eve", "email": "eve@example.com", "password": ""
        })
        assert r.status_code == 400

    def test_register_email_stored_lowercase(self, client: TestClient):
        r = client.post("/auth/register", json={
            "username": "frank", "email": "FRANK@Example.COM", "password": "secret99"
        })
        assert r.status_code == 200
        assert r.json()["email"] == "frank@example.com"


# ─────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────
class TestLogin:
    def test_login_success(self, client: TestClient):
        client.post("/auth/register", json={
            "username": "grace", "email": "grace@example.com", "password": "mypassword"
        })
        r = client.post("/auth/login", json={
            "username": "grace", "password": "mypassword"
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert len(data["access_token"]) > 20

    def test_login_wrong_password(self, client: TestClient):
        client.post("/auth/register", json={
            "username": "heidi", "email": "heidi@example.com", "password": "correct"
        })
        r = client.post("/auth/login", json={"username": "heidi", "password": "wrong"})
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client: TestClient):
        r = client.post("/auth/login", json={"username": "nobody", "password": "pass"})
        assert r.status_code == 401

    def test_login_returns_bearer_usable_token(self, client: TestClient, auth: dict):
        """Token from auth fixture actually works on /me."""
        r = client.get("/me", headers=auth)
        assert r.status_code == 200
        assert r.json()["username"] == "testuser"


# ─────────────────────────────────────────
# /ME
# ─────────────────────────────────────────
class TestMe:
    def test_me_no_token(self, client: TestClient):
        r = client.get("/me")
        assert r.status_code == 401

    def test_me_bad_token(self, client: TestClient):
        r = client.get("/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert r.status_code == 401

    def test_me_returns_correct_user(self, client: TestClient, auth: dict):
        r = client.get("/me", headers=auth)
        assert r.status_code == 200
        data = r.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_me_does_not_leak_password(self, client: TestClient, auth: dict):
        r = client.get("/me", headers=auth)
        body = r.text
        assert "hashed_password" not in body
        assert "password" not in body


# ─────────────────────────────────────────
# TOKEN STATUS
# ─────────────────────────────────────────
class TestTokenStatus:
    def test_token_status_valid(self, client: TestClient, auth: dict):
        token = auth["Authorization"].split()[1]
        r = client.get(f"/auth/token_status?token={token}")
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["sub"] == "testuser"
        assert data["seconds_left"] > 0

    def test_token_status_invalid(self, client: TestClient):
        r = client.get("/auth/token_status?token=garbage.token.value")
        assert r.status_code == 200
        assert r.json()["valid"] is False

    def test_token_status_no_token(self, client: TestClient):
        r = client.get("/auth/token_status")
        assert r.status_code == 401

    def test_token_status_via_header(self, client: TestClient, auth: dict):
        r = client.get("/auth/token_status", headers=auth)
        assert r.status_code == 200
        assert r.json()["valid"] is True


# ─────────────────────────────────────────
# PASSWORD HASHING (unit level)
# ─────────────────────────────────────────
class TestPasswordHashing:
    def test_hash_and_verify(self):
        from backend.auth import hash_password, verify_password
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_wrong_password_fails(self):
        from backend.auth import hash_password, verify_password
        h = hash_password("correct")
        assert verify_password("wrong", h) is False

    def test_hash_is_not_plaintext(self):
        from backend.auth import hash_password
        h = hash_password("secret")
        assert "secret" not in h

    def test_two_hashes_differ(self):
        from backend.auth import hash_password
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2  # PBKDF2 uses a random salt so identical passwords produce different hashes

    def test_empty_password_raises(self):
        from backend.auth import hash_password
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            hash_password("")
        assert exc.value.status_code == 400

    def test_short_password_raises(self):
        from backend.auth import hash_password
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            hash_password("abc")
        assert exc.value.status_code == 400


# ─────────────────────────────────────────
# JWT (unit level)
# ─────────────────────────────────────────
class TestJWT:
    def test_create_and_decode(self):
        from backend.auth import create_access_token, decode_token
        token = create_access_token("alice")
        subject = decode_token(token)
        assert subject == "alice"

    def test_tampered_token_rejected(self):
        from backend.auth import create_access_token, decode_token
        from fastapi import HTTPException
        token = create_access_token("alice")
        tampered = token[:-4] + "XXXX"
        with pytest.raises(HTTPException) as exc:
            decode_token(tampered)
        assert exc.value.status_code == 401

    def test_garbage_token_rejected(self):
        from backend.auth import decode_token
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            decode_token("not.a.jwt")
        assert exc.value.status_code == 401