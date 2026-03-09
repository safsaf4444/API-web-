# tests/conftest.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from backend.app import app
from backend.db import get_session


@pytest.fixture(name="session")
def session_fixture():
    """Fresh in-memory SQLite DB per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """TestClient wired to in-memory DB, rate limiting disabled."""
    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session

    # Patch the rate limit setting so rapid test requests never get 429'd
    with patch("backend.core.rate_limit.settings") as mock_settings:
        mock_settings.rate_limit_enabled = False
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


def _login(client, username, email, password) -> dict:
    """Register (ignore if already exists) then login. Returns Bearer headers."""
    client.post("/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
    })
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed for {username}: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(name="auth")
def auth_fixture(client: TestClient):
    return _login(client, "testuser", "test@example.com", "password123")


@pytest.fixture(name="auth2")
def auth2_fixture(client: TestClient):
    """Second user — shares same client/session so both users exist in same DB."""
    return _login(client, "otheruser", "other@example.com", "password123")