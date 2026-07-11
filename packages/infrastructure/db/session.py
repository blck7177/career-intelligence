"""
SQLAlchemy engine + session factory.

Usage (in FastAPI dependency or Celery task):

    from packages.infrastructure.db.session import get_session

    with get_session() as session:
        session.add(...)
        session.commit()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://career:career@localhost:5432/career_openclaw",
)

_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "3"))
_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "5"))

engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-manager session. Commits on exit, rolls back on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
