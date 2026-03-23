from __future__ import annotations

import os
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(
        DATABASE_URL,
        poolclass=NullPool,
    )
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )


def _run_migrations():
    """Add any new columns/tables that SQLModel.metadata.create_all won't handle on existing tables."""
    import logging
    logger = logging.getLogger("uvicorn")

    column_migrations = [
        # (table, column, type)
        ("airesult", "share_token", "VARCHAR"),
        ("study", "citation_count", "INTEGER"),
        ("study", "is_retracted", "BOOLEAN DEFAULT FALSE"),
    ]

    with engine.connect() as conn:
        for table, column, col_type in column_migrations:
            try:
                if str(engine.url).startswith("postgresql"):
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                        )
                    )
                    conn.commit()
                else:
                    result = conn.execute(__import__("sqlalchemy").text(f"PRAGMA table_info({table})"))
                    cols = [row[1] for row in result]
                    if column not in cols:
                        conn.execute(
                            __import__("sqlalchemy").text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {col_type}')
                        )
                        conn.commit()
            except Exception as e:
                logger.warning(f"Migration {table}.{column}: {e}")


def init_db():
    SQLModel.metadata.create_all(engine)
    _run_migrations()


def get_session():
    with Session(engine) as session:
        yield session