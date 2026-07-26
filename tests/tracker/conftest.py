"""Fixtures for application-tracker repository tests.

SQLite in-memory + real ORM (same strategy as tests/report/conftest.py).
FK enforcement is off so tests can create application rows without seeding
the full workspace/job graph — the repositories are what's under test here.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Base


@pytest.fixture()
def db_session():
    """In-memory SQLite session; schema built from the ORM models."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
