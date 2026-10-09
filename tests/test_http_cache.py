"""Tests for the raw-HTTP response cache (tier-1 memory + tier-2 SQLite)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models import HttpResponseCache
from app.services import scraper_service as S
from app.services.http_cache import (
    CachedResponse,
    HttpCache,
    build_cache_key,
    ttl_for,
)

NOW = dt.datetime(2026, 10, 8, 10, 0, 0)


@pytest.fixture()
def clean_http_cache(db_session: Session) -> Iterator[None]:
    db_session.query(HttpResponseCache).delete()
    db_session.commit()
    yield


def _scraper(client: httpx.Client, **kwargs: object) -> S.JudiciaryScraper:
    return S.JudiciaryScraper(
        min_interval=0.0, max_retries=0, client=client, http_cache=True, **kwargs
    )


def test_ttl_policy() -> None:
    assert ttl_for("https://x/api", {"path": "geo/districts"}, NOW) == dt.timedelta(days=30)
    assert ttl_for("https://x/api", {"path": "courts", "district_id": 9}, NOW) == dt.timedelta(
        days=30
    )
    assert ttl_for("https://x/causelist", {"date": "08-10-2026"}, NOW) == dt.timedelta(
        minutes=30
    )
    assert ttl_for("https://x/causelist", {"date": "01-01-2024"}, NOW) == dt.timedelta(days=30)
    assert ttl_for("https://x/causelist", {}, NOW) == dt.timedelta(minutes=30)
    assert ttl_for("https://x/caseinfo", {"id": "abc"}, NOW) == dt.timedelta(hours=24)
    assert ttl_for("https://x/other", {}, NOW) == dt.timedelta(hours=1)


def test_build_cache_key_is_deterministic() -> None:
    assert build_cache_key("https://x/api", {"b": 2, "a": 1}) == build_cache_key(
        "https://x/api", {"a": 1, "b": 2}
    )
    assert build_cache_key("https://x/api", {"a": 1}) != build_cache_key(
        "https://x/api", {"a": 2}
    )


def test_skip_when_disabled() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>ok</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    scraper = S.JudiciaryScraper(min_interval=0.0, client=client, http_cache=False)
    with scraper:
        scraper.fetch("/causelist", {"date": "01-01-2024"})
        scraper.fetch("/causelist", {"date": "01-01-2024"})
    assert len(calls) == 2


def test_second_identical_call_is_served_from_cache(
    db_session: Session, clean_http_cache: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>cached-data</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _scraper(client) as scraper:
        first = scraper.fetch("/causelist", {"date": "01-01-2024", "courtId": 930})
        second = scraper.fetch("/causelist", {"date": "01-01-2024", "courtId": 930})
    assert first == second == "<html>cached-data</html>"
    assert len(calls) == 1


def test_different_params_are_distinct_cache_keys(
    db_session: Session, clean_http_cache: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=request.url.params["date"])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _scraper(client) as scraper:
        scraper.fetch("/causelist", {"date": "01-01-2024"})
        scraper.fetch("/causelist", {"date": "02-01-2024"})
    assert len(calls) == 2


def test_stale_cache_served_when_transport_fails(
    db_session: Session, clean_http_cache: None
) -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>stale-body</html>")

    ok_client = httpx.Client(transport=httpx.MockTransport(ok_handler))
    with _scraper(ok_client) as scraper:
        scraper.fetch("/caseinfo", {"id": "abc"})

    def broken_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.NetworkError("connection reset")

    broken_client = httpx.Client(transport=httpx.MockTransport(broken_handler))
    with _scraper(broken_client) as scraper:
        stale = scraper.fetch("/caseinfo", {"id": "abc"})
    assert stale == "<html>stale-body</html>"


def test_non_200_or_empty_responses_not_cached(
    db_session: Session, clean_http_cache: None
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, text="down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _scraper(client) as scraper:
        with pytest.raises(S.ScraperError):
            scraper.fetch("/causelist", {"date": "01-01-2024"})
    assert len(calls) == 1


def test_http_cache_roundtrip(db_session: Session, clean_http_cache: None) -> None:
    cache = HttpCache(capacity=4)
    entry = CachedResponse(
        status_code=200,
        body="<html>abc</html>",
        content_type="text/html",
        expires_at=dt.datetime.utcnow() + dt.timedelta(days=1),
    )
    cache.put("k1", "https://x/causelist", {"date": "01-01-2024"}, entry)
    assert cache.get("k1") is not None
    assert cache.get("k1").body == "<html>abc</html>"
    assert cache.get("missing") is None
    cache.clear()
    assert cache.get("k1") is None