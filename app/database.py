"""Database engine, session factory, and declarative base.

SQLAlchemy 2.0 style. Defaults to a local SQLite file for development; set the
``DATABASE_URL`` environment variable to point at PostgreSQL (or any other
SQLAlchemy-supported backend) in production, e.g.::

    DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/judiciary
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_SQLITE_URL = "sqlite:///./judiciary_help.db"


def _resolve_database_url() -> str:
    """Return the configured database URL, normalising common cloud schemes."""
    url = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL).strip()
    # Railway/Heroku hand out ``postgres://``; SQLAlchemy 2.x needs a driver.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL: str = _resolve_database_url()

# SQLite needs this flag so the connection can cross threads (FastAPI workers).
_connect_args: dict[str, object] = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,  # recycle dead connections
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # keep attributes usable after commit in responses
)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables for the current metadata.

    Convenience for local development and tests. Production schema changes
    should go through Alembic migrations instead.
    """
    from app import models  # noqa: F401  (import registers models on Base)

    Base.metadata.create_all(bind=engine)
