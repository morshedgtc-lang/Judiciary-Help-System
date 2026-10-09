"""Shared pytest fixtures.

The environment is configured *before* any ``app`` module is imported, because
``app.database`` resolves ``DATABASE_URL`` at import time. Tests therefore run
against an isolated throwaway SQLite database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

_TMP_DIR = tempfile.mkdtemp(prefix="jh_tests_")
_DB_PATH = (Path(_TMP_DIR) / "test.db").as_posix()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("JUDICIARY_MIN_INTERVAL", "0")
os.environ.setdefault("SQL_ECHO", "false")
# Existing tests exercise the transport directly; the raw-HTTP cache is opt-in
# and covered by dedicated tests (test_http_cache.py).
os.environ.setdefault("JUDICIARY_HTTP_CACHE_ENABLED", "false")

from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: E402,F401  (registers models on Base)
from app.database import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    """A session against a clean cache table for each test."""
    session = SessionLocal()
    session.query(models.CaseQueryCache).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
