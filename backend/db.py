from __future__ import annotations

import os
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Fix for Neon serverless + Vercel — disable SQLAlchemy connection pooling
# and let pgbouncer handle it instead
if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=1,
        max_overflow=0,
    )
else:
    # SQLite for local dev
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session