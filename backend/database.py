"""SQLAlchemy 2.x engine + session factory.

Macro-level architecture note: rosters are loaded into RAM at sim time and
results are flushed back via a single ``executemany`` per day. Keep the SQLite
connection lightweight; we do *not* hold sessions open during simulation.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    # SQLite-specific: allow access from multiple threads (FastAPI workers)
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for per-request DB sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create all tables. Imports the models module to register them on Base.metadata."""
    # Local import to avoid circular dependency at module load.
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_all() -> None:
    """Drop all tables — used by the seed script for a clean slate."""
    from backend import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
