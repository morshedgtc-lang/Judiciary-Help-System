"""Tests for the scraper transport layer (offline, via httpx mock transport)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services import scraper_service as S


def _mock_client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_block_detection() -> None:
    assert S._looks_blocked(403, "x", {}) is True
    assert S._looks_blocked(200, "<title>Just a moment...</title>", {}) is True
    assert S._looks_blocked(503, "busy", {"server": "cloudflare"}) is True
    assert S._looks_blocked(200, "<html>ok</html>", {}) is False


def test_fetch_and_parse_json_api() -> None:
    payload = json.dumps([{"geo_district_id": 12, "district_name_eng": "Chandpur"}])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("path") == "geo/districts"
        return httpx.Response(200, text=payload)

    with S.JudiciaryScraper(min_interval=0.0, client=_mock_client(handler)) as scraper:
        assert scraper.get_districts()[0]["geo_district_id"] == 12


def test_district_flattening_and_resolution() -> None:
    payload = json.dumps(
        [{"geo_division_id": 2, "districts": [{"geo_district_id": 12, "district_name_eng": "Chandpur"}]}]
    )

    with S.JudiciaryScraper(
        min_interval=0.0, client=_mock_client(lambda r: httpx.Response(200, text=payload))
    ) as scraper:
        assert scraper.resolve_district_id("Chandpur") == 12


def test_blocked_primary_falls_back_to_secondary() -> None:
    class _Blocked:
        name = "curl_cffi"

        def fetch(self, url, params):  # noqa: ANN001, ANN201
            return S.FetchResult(403, "<title>Just a moment...</title>", {"server": "cloudflare"}, url)

        def close(self):  # noqa: ANN201
            pass

    class _Good:
        name = "httpx"

        def fetch(self, url, params):  # noqa: ANN001, ANN201
            return S.FetchResult(200, "<div class='office-unit-name'>CJM</div>", {}, str(url))

        def close(self):  # noqa: ANN201
            pass

    scraper = S.JudiciaryScraper(min_interval=0.0, transport="curl_cffi")
    scraper._transport_cache["curl_cffi"] = _Blocked()
    scraper._transport_cache["httpx"] = _Good()
    assert scraper._transport_order() == ["curl_cffi", "httpx"]
    assert "office-unit-name" in scraper.fetch_cause_list(900)
    scraper.close()


def test_all_blocked_raises() -> None:
    scraper = S.JudiciaryScraper(
        min_interval=0.0,
        client=_mock_client(lambda r: httpx.Response(403, text="<title>Just a moment...</title>")),
    )
    with pytest.raises(S.ScraperBlocked):
        scraper.fetch_cause_list(900)
    scraper.close()


def test_404_raises_not_found() -> None:
    scraper = S.JudiciaryScraper(
        min_interval=0.0, client=_mock_client(lambda r: httpx.Response(404, text="x"))
    )
    with pytest.raises(S.ScraperNotFound):
        scraper.fetch("caseinfo", {"courtId": 1})
    scraper.close()


def test_format_date() -> None:
    assert S._format_date(__import__("datetime").date(2026, 10, 9)) == "09-10-2026"
    assert S._format_date("০৯-১০-২০২৬") == "০৯-১০-২০২৬"
    assert S._format_date(None) is None
