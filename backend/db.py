from __future__ import annotations

import os
from sqlmodel import SQLModel, Session, create_engine

DB_URL = os.getenv("DATABASE_URL") or "sqlite:///./app.db"

connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DB_URL, echo=False, connect_args=connect_args)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
