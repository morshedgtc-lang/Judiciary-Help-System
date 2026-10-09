"""End-to-end case lookup: scrape -> parse -> cache -> explain.

This is the single entry point the API (and web UI) call. It hides the messy
reality of the source portal behind one function:

* resolve the court (from the request, or from configured defaults),
* serve an unexpired cached result when possible (so we never spam the
  government servers and stay available when they are down),
* otherwise fetch live, parse the search results + detail page, and build a
  :class:`~app.schemas.CaseSummary`,
* render a bilingual explanation,
* persist the result for next time, falling back to a stale cache entry if the
  live fetch is blocked or fails.

The function is synchronous (the underlying client is sync) but cheap; call it
from a FastAPI worker thread. It never raises for upstream failures — those are
reported through :class:`~app.schemas.CaseLookupResponse`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import CaseQueryCache
from app.schemas import (
    CaseKind,
    CaseLookupRequest,
    CaseLookupResponse,
    CaseSummary,
    ParsedCaseNumber,
    Party,
    PartyRole,
    PrivacyReport,
)
from app.services import explainer_service, parser_service, privacy_service
from app.services.scraper_service import JudiciaryScraper, ScraperError

logger = logging.getLogger(__name__)

__all__ = ["lookup_case", "build_query_key"]


def _utcnow() -> datetime:
    """Naive UTC timestamp, matching how the cache model stores datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_query_key(normalized_number: str, court_id: int | None) -> str:
    """Stable cache key for a normalized case number within a court scope."""
    return f"{normalized_number}|{court_id if court_id is not None else '-'}"


def _find(fields: dict[str, str], *needles: str) -> str | None:
    """Return the first field value whose label contains any of ``needles``."""
    for label, value in fields.items():
        lowered = label.casefold()
        if any(needle.casefold() in lowered for needle in needles):
            if value:
                return value
    return None


def _resolve_court(
    scraper: JudiciaryScraper, request: CaseLookupRequest
) -> tuple[int | None, str | None]:
    """Resolve ``(court_id, district_name)`` from the request, else defaults."""
    if request.court_id is not None:
        return request.court_id, None

    district = settings.judiciary_default_district
    court_name = request.court or settings.judiciary_default_court

    if request.court and "," in request.court:
        head, _, tail = request.court.rpartition(",")
        candidate = tail.strip()
        if candidate and scraper.resolve_district_id(candidate) is not None:
            district = candidate
            court_name = head.strip() or settings.judiciary_default_court

    court_id = scraper.resolve_court_id(district, court_name)
    return court_id, district


def _party_from(value: str | None, role: PartyRole) -> Party | None:
    if not value:
        return None
    cleaned = privacy_service.sanitize(value)
    return Party(name=cleaned, role=role)


def _build_summary(
    request: CaseLookupRequest,
    parsed: ParsedCaseNumber,
    *,
    court_id: int | None,
    court_name: str | None,
    page: parser_service.CaseListPage | None,
    entry: parser_service.CaseListEntry | None,
    detail: parser_service.CaseDetail | None,
) -> CaseSummary:
    fields = detail.fields if detail else {}

    next_raw = _find(fields, "পরবর্তী তারিখ", "পরবর্তী শুনানি", "next hearing", "next date")
    next_date = parser_service.parse_bn_date(next_raw) if next_raw else None

    parties = [
        candidate
        for candidate in (
            _party_from(
                (entry.plaintiff if entry else None) or _find(fields, "বাদী", "plaintiff"),
                PartyRole.PLAINTIFF,
            ),
            _party_from(
                (entry.defendant if entry else None) or _find(fields, "বিবাদী", "defendant"),
                PartyRole.DEFENDANT,
            ),
            _party_from(_find(fields, "আসামি", "accused"), PartyRole.ACCUSED),
        )
        if candidate is not None
    ]

    resolved_court = (detail.court_name if detail else None) or (
        page.court_name if page else None
    ) or court_name

    return CaseSummary(
        case_number=entry.case_number if entry and entry.case_number else request.case_number,
        normalized_number=parsed.normalized or parser_service.normalize_case_number(
            request.case_number
        ),
        kind=parsed.kind,
        year=parsed.year,
        court=resolved_court,
        court_id=court_id,
        subject=_find(fields, "বিষয়", "মামলার বিষয়", "subject", "ধরন"),
        parties=parties,
        status=_find(fields, "অবস্থা", "স্থিতি", "status", "কার্যক্রম"),
        next_hearing_date=next_date,
        last_order_summary=_find(
            fields, "সংক্ষিপ্ত আদেশ", "আদেশ", "order", "রায়"
        ),
        source_url=entry.detail_url if entry else None,
        fetched_at=_utcnow(),
    )


def _cached_response(
    entry: CaseQueryCache,
    request: CaseLookupRequest,
    *,
    cached: bool,
    source: str,
) -> CaseLookupResponse:
    """Re-render a cached payload in the caller's requested language."""
    payload = json.loads(entry.payload) if entry.payload else {}
    parsed = ParsedCaseNumber(**payload["parsed"]) if payload.get("parsed") else None
    summary = CaseSummary(**payload["summary"]) if payload.get("summary") else None
    privacy = PrivacyReport(**payload.get("privacy", {}))

    explanation = None
    next_steps: list[str] = []
    if summary is not None:
        rendered = explainer_service.explain_case(
            summary, parsed, language=request.language
        )
        explanation = rendered.text
        next_steps = rendered.next_steps

    return CaseLookupResponse(
        found=bool(payload.get("found", False)),
        cached=cached,
        source=source,
        language=request.language,
        parsed=parsed,
        summary=summary,
        explanation=explanation,
        next_steps=next_steps,
        privacy=privacy,
        message=None if payload.get("found") else "এই নম্বরে কোনো মামলা পাওয়া যায়নি।",
        fetched_at=entry.fetched_at,
    )


def _store(
    db: Session,
    row: CaseQueryCache | None,
    *,
    query_key: str,
    request: CaseLookupRequest,
    parsed: ParsedCaseNumber,
    summary: CaseSummary | None,
    found: bool,
    status: str,
    source: str,
    privacy: PrivacyReport,
) -> None:
    payload: dict[str, Any] = {
        "found": found,
        "parsed": parsed.model_dump(mode="json"),
        "summary": summary.model_dump(mode="json") if summary else None,
        "privacy": privacy.model_dump(mode="json"),
    }
    expires_at = _utcnow() + timedelta(minutes=settings.judiciary_cache_ttl_minutes)

    if row is None:
        row = CaseQueryCache(query_key=query_key, case_number=request.case_number)
        db.add(row)

    row.query_key = query_key
    row.case_number = request.case_number
    row.normalized_number = parsed.normalized or request.case_number
    row.court_id = summary.court_id if summary else request.court_id
    row.status = status
    row.source = source
    row.payload = json.dumps(payload, ensure_ascii=False)
    row.fetched_at = _utcnow()
    # Only successful hits are worth caching long-term; misses expire quickly.
    row.expires_at = expires_at if found else _utcnow() + timedelta(minutes=15)
    db.commit()


def lookup_case(
    db: Session,
    request: CaseLookupRequest,
    *,
    scraper: JudiciaryScraper | None = None,
) -> CaseLookupResponse:
    """Look up a case number and return a fully-rendered response."""
    language = request.language
    parsed = parser_service.parse_case_number(request.case_number)
    if parsed is None:
        parsed = ParsedCaseNumber(
            raw=request.case_number,
            normalized=parser_service.normalize_case_number(request.case_number),
            kind=CaseKind.UNKNOWN,
            confidence=0.0,
        )

    cache_row = db.scalar(
        select(CaseQueryCache).where(
            CaseQueryCache.normalized_number == (parsed.normalized or request.case_number)
        )
    )
    if (
        not request.force_refresh
        and cache_row is not None
        and cache_row.is_fresh
        and cache_row.payload
    ):
        cache_row.hit_count += 1
        db.commit()
        return _cached_response(cache_row, request, cached=True, source="cache")

    owns_scraper = scraper is None

    try:
        if owns_scraper:
            scraper = JudiciaryScraper(
                base_url=settings.judiciary_base_url,
                timeout=settings.judiciary_timeout,
                min_interval=settings.judiciary_min_interval,
            )
            scraper.__enter__()

        court_id, court_name = _resolve_court(scraper, request)
        if court_id is None:
            return CaseLookupResponse(
                found=False,
                source="live",
                language=language,
                parsed=parsed,
                message=(
                    "আদালত শনাক্ত করা যায়নি। অনুগ্রহ করে জেলার নাম ও আদালত উল্লেখ করুন "
                    "অথবা court_id দিন।"
                ),
                fetched_at=_utcnow(),
            )

        page = parser_service.parse_case_list(
            scraper.fetch_case_info(court_id, request.case_number)
        )
        target = parsed.normalized or request.case_number
        entry = next(
            (
                item
                for item in page.entries
                if parser_service.normalize_case_number(item.case_number or "")
                == target
            ),
            page.entries[0] if page.entries else None,
        )

        detail = None
        if entry and entry.case_id:
            detail = parser_service.parse_case_detail(
                scraper.fetch_case_detail(
                    court_id=entry.court_id or court_id,
                    case_type=entry.case_type_id or "",
                    case_id=entry.case_id,
                )
            )

        if entry is None:
            privacy = PrivacyReport(applied=False, total=0, by_type={})
            response = CaseLookupResponse(
                found=False,
                source="live",
                language=language,
                parsed=parsed,
                message="এই নম্বরে কোনো মামলা পাওয়া যায়নি।",
                fetched_at=_utcnow(),
            )
            _store(
                db, cache_row,
                query_key=build_query_key(target, court_id),
                request=request, parsed=parsed, summary=None, found=False,
                status="not_found", source="live", privacy=privacy,
            )
            return response

        summary = _build_summary(
            request, parsed,
            court_id=court_id, court_name=court_name,
            page=page, entry=entry, detail=detail,
        )
        rendered = explainer_service.explain_case(summary, parsed, language=language)
        privacy = PrivacyReport(
            applied=bool(rendered.redactions),
            total=sum(rendered.redactions.values()),
            by_type=rendered.redactions,
        )

        _store(
            db, cache_row,
            query_key=build_query_key(summary.normalized_number, court_id),
            request=request, parsed=parsed, summary=summary, found=True,
            status="found", source="live", privacy=privacy,
        )

        return CaseLookupResponse(
            found=True,
            cached=False,
            source="live",
            language=language,
            parsed=parsed,
            summary=summary,
            explanation=rendered.text,
            next_steps=rendered.next_steps,
            privacy=privacy,
            fetched_at=summary.fetched_at,
        )

    except ScraperError as exc:
        logger.warning("Live case lookup failed (%s); trying cache", exc)
        if cache_row is not None and cache_row.payload:
            response = _cached_response(cache_row, request, cached=True, source="fallback")
            response.message = "সরকারি সার্ভার এখন সাড়া দিচ্ছে না; সংরক্ষিত ফলাফল দেখানো হচ্ছে।"
            return response
        return CaseLookupResponse(
            found=False,
            source="live",
            language=language,
            parsed=parsed,
            message="সরকারি সার্ভারে সংযোগ করা যায়নি। কিছুক্ষণ পরে আবার চেষ্টা করুন।",
            fetched_at=_utcnow(),
        )
    finally:
        if owns_scraper and scraper is not None:
            scraper.close()
