"""
Shared pytest fixtures for trust test suite.

Importing both models modules ensures SQLModel.metadata contains ALL tables
before create_all() is called — otherwise FK references to study, systematicreview,
etc. would fail with "no such table" in the in-memory SQLite DB.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

# Must import ALL model modules so their table definitions are registered
# in SQLModel.metadata before create_all() runs.
import backend.models        # noqa: F401  — Study, Folder, User, etc.
import backend.models_trust  # noqa: F401  — AIRun, AuditLog, Claim, etc.


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    # This now knows about both main models and trust models
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
