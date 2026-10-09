"""HTTP layer for the Bangladesh judiciary e-services (cause list) portal.

Handles transport concerns only — base URL, headers, timeouts, retries, polite
rate limiting, and typed errors. Responses are returned as raw ``str`` (HTML)
or decoded JSON (``list``/``dict``); turning them into domain objects is the job
of :mod:`app.services.parser_service`.

Usage::

    from app.services.scraper_service import JudiciaryScraper
    from app.services import parser_service

    with JudiciaryScraper() as scraper:
        court_id = scraper.resolve_court_id("Chandpur", "চীফ জুডিসিয়াল")
        html = scraper.fetch_cause_list(court_id, date=datetime.date.today())
        page = parser_service.parse_cause_list(html)

Configuration via environment variables:

* ``JUDICIARY_BASE_URL``    — default ``https://causelist.judiciary.gov.bd``
* ``JUDICIARY_USER_AGENT``  — override the default User-Agent
* ``JUDICIARY_TIMEOUT``     — request timeout in seconds (default ``20``)
* ``JUDICIARY_MIN_INTERVAL``— minimum seconds between requests (default ``1.0``)
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import date, datetime
from typing import Any, Sequence

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "JudiciaryScraper",
    "ScraperError",
    "ScraperHTTPError",
    "ScraperTimeout",
    "ScraperNotFound",
]

DEFAULT_BASE_URL = "https://causelist.judiciary.gov.bd"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20.0
DEFAULT_MIN_INTERVAL = 1.0

# Broad office-origin ids that cover district/tribunal courts (see portal JS).
DISTRICT_COURT_ORIGINS = "4,5,6,7,8,18,19,20,21,74,75,76,83,94,103"

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ScraperError(RuntimeError):
    """Base class for all scraper failures."""


class ScraperHTTPError(ScraperError):
    """The server returned an unexpected HTTP status."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} for {url}")
        self.status_code = status_code
        self.url = url


class ScraperTimeout(ScraperError):
    """The request timed out after all retries."""


class ScraperNotFound(ScraperError):
    """The requested resource does not exist (HTTP 404)."""


def _format_date(value: date | datetime | str | None) -> str | None:
    """Format a date as ``dd-mm-yyyy`` (ASCII); pass strings through untouched."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%d-%m-%Y")
    return str(value)


class JudiciaryScraper:
    """Synchronous, rate-limited client for the judiciary cause-list portal."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        user_agent: str | None = None,
        min_interval: float | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("JUDICIARY_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.timeout = float(
            timeout if timeout is not None else os.getenv("JUDICIARY_TIMEOUT", DEFAULT_TIMEOUT)
        )
        self.min_interval = float(
            min_interval
            if min_interval is not None
            else os.getenv("JUDICIARY_MIN_INTERVAL", DEFAULT_MIN_INTERVAL)
        )
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        headers = {
            "User-Agent": user_agent or os.getenv("JUDICIARY_USER_AGENT", DEFAULT_USER_AGENT),
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "bn-BD,bn;q=0.9,en;q=0.8",
        }
        self._client = client
        self._owns_client = client is None
        self._headers = headers
        self._rate_lock = threading.Lock()
        self._last_request_at = 0.0

    # -- lifecycle ---------------------------------------------------------

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers=self._headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> JudiciaryScraper:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- internals ---------------------------------------------------------

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._rate_lock:
            elapsed = time.monotonic() - self._last_request_at
            remaining = self.min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _request(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        client = self._ensure_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                response = client.get(url, params=params)
            except httpx.TimeoutException as exc:
                last_error = ScraperTimeout(f"Timed out requesting {url}")
                logger.warning("Timeout (attempt %d/%d): %s", attempt + 1, self.max_retries + 1, url)
            except httpx.HTTPError as exc:
                last_error = ScraperError(f"Transport error requesting {url}: {exc}")
                logger.warning("Transport error (attempt %d/%d): %s", attempt + 1, self.max_retries + 1, exc)
            else:
                if response.status_code == 404:
                    raise ScraperNotFound(f"404 Not Found: {url}")
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = ScraperHTTPError(response.status_code, url)
                    logger.warning(
                        "Retryable HTTP %d (attempt %d/%d): %s",
                        response.status_code,
                        attempt + 1,
                        self.max_retries + 1,
                        url,
                    )
                elif response.status_code >= 400:
                    raise ScraperHTTPError(response.status_code, url)
                else:
                    return response

            if attempt < self.max_retries:
                delay = self.backoff_factor * (2**attempt) + random.uniform(0, 0.25)
                time.sleep(delay)

        raise last_error or ScraperError(f"Request failed: {url}")

    def _api(self, path: str, **params: Any) -> Any:
        """Call ``GET {base}/api?path=<path>`` and return decoded JSON."""
        query = {"path": path, **{k: v for k, v in params.items() if v is not None}}
        response = self._request(f"{self.base_url}/api", query)
        try:
            return response.json()
        except json.JSONDecodeError:
            # The portal sometimes serves JSON with a non-JSON content type.
            return json.loads(response.text)

    # -- geography & court discovery --------------------------------------

    def get_divisions(self) -> list[dict[str, Any]]:
        return self._api("geo/divisions")

    def get_districts(self, division_id: int | str | None = None) -> list[dict[str, Any]]:
        return self._api("geo/districts", division_id=division_id)

    def get_courts(
        self,
        district_id: int | str,
        office_origin_id: int | str | Sequence[int | str] | None = None,
    ) -> list[dict[str, Any]]:
        if isinstance(office_origin_id, (list, tuple, set)):
            office_origin_id = ",".join(str(x) for x in office_origin_id)
        return self._api(
            "courts",
            district_id=district_id,
            office_origin_id=office_origin_id,
        )

    def get_all_office_units(self) -> list[dict[str, Any]]:
        return self._api("office/allOfficeUnitName")

    def search_office_units(self, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Substring search over all office/unit names (Bengali or English)."""
        needle = query.strip().casefold()
        if not needle:
            return []
        results = []
        for unit in self.get_all_office_units():
            name_bn = str(unit.get("unit_name_bng") or "").casefold()
            name_en = str(unit.get("unit_name_eng") or "").casefold()
            if needle in name_bn or needle in name_en:
                results.append(unit)
                if len(results) >= limit:
                    break
        return results

    def _iter_district_records(self) -> list[dict[str, Any]]:
        """Flatten the ``geo/districts`` payload.

        The portal returns divisions, each wrapping a ``districts`` array, but
        some deployments return a flat array of districts — support both.
        """
        records: list[dict[str, Any]] = []
        for group in self.get_districts() or []:
            nested = group.get("districts")
            if isinstance(nested, list):
                records.extend(nested)
            else:
                records.append(group)
        return records

    def resolve_district_id(self, district_name: str) -> int | None:
        """Return the ``geo_district_id`` for a district by Bengali or English name."""
        needle = district_name.strip().casefold()
        for district in self._iter_district_records():
            name_bn = str(district.get("district_name_bng") or "").casefold()
            name_en = str(district.get("district_name_eng") or "").casefold()
            if needle in name_bn or needle in name_en:
                district_id = district.get("geo_district_id")
                return int(district_id) if district_id is not None else None
        return None

    def list_courts(
        self,
        district_name: str,
        *,
        office_origin_id: int | str | Sequence[int | str] | None = DISTRICT_COURT_ORIGINS,
    ) -> list[dict[str, Any]]:
        """List courts for a district, resolved by district name."""
        district_id = self.resolve_district_id(district_name)
        if district_id is None:
            raise ScraperNotFound(f"Unknown district: {district_name!r}")
        return self.get_courts(district_id, office_origin_id=office_origin_id)

    def resolve_court_id(
        self,
        district_name: str,
        court_name: str | None = None,
        *,
        office_origin_id: int | str | Sequence[int | str] | None = DISTRICT_COURT_ORIGINS,
    ) -> int | None:
        """Resolve a court id by district and optional court-name substring.

        Returns the first match; ``None`` when nothing matches. Raises
        :class:`ScraperNotFound` when the district itself is unknown.
        """
        courts = self.list_courts(district_name, office_origin_id=office_origin_id)
        if not court_name:
            return int(courts[0]["id"]) if courts else None

        needle = court_name.strip().casefold()
        for court in courts:
            name_bn = str(court.get("office_name_bng") or "").casefold()
            name_en = str(court.get("office_name_eng") or "").casefold()
            if needle in name_bn or needle in name_en:
                return int(court["id"])
        return None

    # -- HTML pages --------------------------------------------------------

    def fetch_cause_list(
        self,
        court_id: int | str,
        date: date | datetime | str | None = None,
    ) -> str:
        """Fetch the daily cause list (কার্যতালিকা) HTML for a court.

        ``date`` may be a ``date``/``datetime`` (formatted ``dd-mm-yyyy``) or a
        pre-formatted string (e.g. Bengali numerals). ``None`` lets the portal
        default to today.
        """
        params: dict[str, Any] = {"courtId": court_id}
        formatted = _format_date(date)
        if formatted:
            params["date"] = formatted
        return self._request(f"{self.base_url}/causelist", params).text

    def fetch_case_list(self, court_id: int | str) -> str:
        """Fetch the case listing HTML for a court (``/caseinfo`` without caseno)."""
        return self._request(f"{self.base_url}/caseinfo", {"courtId": court_id}).text

    def fetch_case_info(self, court_id: int | str, case_no: str) -> str:
        """Search a court for a case number (``/caseinfo?caseno=``)."""
        return self._request(
            f"{self.base_url}/caseinfo",
            {"courtId": court_id, "caseno": case_no},
        ).text

    def fetch_case_detail(
        self,
        *,
        court_id: int | str,
        case_type: int | str,
        case_id: str,
    ) -> str:
        """Fetch the detail HTML for a single case."""
        return self._request(
            f"{self.base_url}/caseinfo",
            {"courtId": court_id, "case_type": case_type, "id": case_id},
        ).text

    def fetch(self, url: str, params: dict[str, Any] | None = None) -> str:
        """Fetch an arbitrary portal path (relative to ``base_url``) as HTML."""
        if url.startswith(("http://", "https://")):
            target = url
        else:
            target = f"{self.base_url}/{url.lstrip('/')}"
        return self._request(target, params).text
