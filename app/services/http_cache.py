"""Two-tier cache for raw portal HTTP responses.

Tier-1 is a bounded in-memory LRU; tier-2 is a persistent SQLite/Postgres table
(:class:`app.models.HttpResponseCache`) so cached pages survive restarts. The
portal is treated as a slow, rate-limited upstream: geo/court/office-unit
masters are effectively immutable (30-day TTL), past cause lists are baked
(30 days), today's cause list is refreshed every 30 minutes, and caseinfo pages
are considered stable for 24 hours. On any transport failure the last cached
copy is served as a stale fallback so repeated use tolerates portal outages.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import delete

from app.database import SessionLocal
from app.models import HttpResponseCache


@dataclass(slots=True)
class CachedResponse:
    """A shallow, serializable snapshot of a portal response."""

    status_code: int
    body: str
    content_type: str
    expires_at: datetime


_DEFAULT_TTL = timedelta(hours=1)
_MASTER_TTL = timedelta(days=30)
_CASEINFO_TTL = timedelta(hours=24)
_TODAY_CAUSELIST_TTL = timedelta(minutes=30)


def _path_of(url: str) -> str:
    """Return the portal path portion of ``url``."""
    if "://" in url:
        from urllib.parse import urlparse

        return urlparse(url).path
    return url.split("?", 1)[0]


def ttl_for(url: str, params: Mapping[str, Any] | None, now: datetime) -> timedelta:
    """Pick a route-aware TTL so genuinely-changing data stays fresh."""
    path = _path_of(url)
    params = dict(params or {})

    if path.endswith("/api"):
        api_path = str(params.get("path") or "")
        if any(kind in api_path for kind in ("geo/", "office/")) or api_path.startswith(
            "courts"
        ):
            return _MASTER_TTL
        return timedelta(hours=1)

    if path.endswith("/causelist"):
        date_str = str(params.get("date") or "")
        if not date_str or date_str == now.strftime("%d-%m-%Y"):
            return _TODAY_CAUSELIST_TTL
        return _MASTER_TTL

    if path.endswith("/caseinfo"):
        return _CASEINFO_TTL

    return _DEFAULT_TTL


def build_cache_key(url: str, params: Mapping[str, Any] | None) -> str:
    """Deterministic SHA-1 key over the URL and sorted query params."""
    payload = {
        "url": url,
        "params": {
            str(key): str(value) for key, value in sorted((params or {}).items())
        },
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class HttpCache:
    """Thread-safe two-tier cache using :class:`HttpResponseCache` storage."""

    def __init__(self, capacity: int = 256) -> None:
        self._capacity = max(1, int(capacity))
        self._memory: OrderedDict[str, CachedResponse] = OrderedDict()
        self._lock = threading.Lock()

    # -- tier 1 (memory) ---------------------------------------------------

    def _mem_get(self, key: str) -> CachedResponse | None:
        cached = self._memory.get(key)
        if cached is None:
            return None
        # Move to the back (most-recently used) on access.
        self._memory.move_to_end(key)
        return cached

    def _mem_put(self, key: str, entry: CachedResponse) -> None:
        self._memory[key] = entry
        self._memory.move_to_end(key)
        if len(self._memory) > self._capacity:
            self._memory.popitem(last=False)

    # -- query helpers -----------------------------------------------------

    def _entry_to_row(
        self, key: str, url: str, params: Mapping[str, Any] | None, entry: CachedResponse
    ) -> HttpResponseCache:
        return HttpResponseCache(
            key=key,
            url=url,
            params_json=(
                json.dumps({k: str(v) for k, v in params.items()})
                if params
                else None
            ),
            status_code=entry.status_code,
            content_type=entry.content_type,
            body=entry.body,
            expires_at=entry.expires_at,
        )

    def get(self, key: str) -> CachedResponse | None:
        """Return a cached entry, or ``None`` on miss."""
        with self._lock:
            entry = self._mem_get(key)
            if entry is not None:
                return entry
            with SessionLocal() as session:
                row = session.get(HttpResponseCache, key)
            if row is None:
                return None
            entry = CachedResponse(
                status_code=row.status_code,
                body=row.body,
                content_type=row.content_type or "",
                expires_at=row.expires_at or datetime.utcnow(),
            )
            self._mem_put(key, entry)
            return entry

    def put(
        self,
        key: str,
        url: str,
        params: Mapping[str, Any] | None,
        entry: CachedResponse,
    ) -> None:
        """Store a response in both tiers (upsert)."""
        with self._lock:
            self._mem_put(key, entry)
            with SessionLocal() as session:
                session.merge(self._entry_to_row(key, url, params, entry))
                session.commit()

    def clear(self) -> None:
        """Drop the memory tier and all persisted entries."""
        with self._lock:
            self._memory.clear()
            with SessionLocal() as session:
                session.execute(delete(HttpResponseCache))
                session.commit()