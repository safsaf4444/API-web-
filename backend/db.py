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
    """Add any new columns that SQLModel.metadata.create_all won't handle on existing tables."""
    import logging
    logger = logging.getLogger("uvicorn")
    
    migrations = [
        # (table, column, type)
        ("airesult", "share_token", "VARCHAR"),
    ]
    
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                # PostgreSQL supports IF NOT EXISTS on ADD COLUMN
                if str(engine.url).startswith("postgresql"):
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {col_type}'
                        )
                    )
                    conn.commit()
                else:
                    # SQLite: check if column exists first
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