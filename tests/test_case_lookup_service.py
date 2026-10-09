"""Tests for the end-to-end case lookup orchestration (offline)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import Session

from app.schemas import CaseLookupRequest, Language
from app.services import case_lookup_service as CLS
from app.services import scraper_service as S

SEARCH_HTML = """
<div class="office-unit-name">চীফ জুডিসিয়াল ম্যাজিস্ট্রেট আদালত, চাঁদপুর</div>
<table class="table"><tbody><tr>
  <td>১</td><td>সি.আর. ৮৪৪/২০২৩</td>
  <td><span class="fs-2">রহিম</span><span class="fs-2">করিম</span></td>
  <td><a href="/caseinfo?courtId=900&case_type=344&id=abc123">detail</a></td>
</tr></tbody></table>
"""
DETAIL_HTML = """
<div class="office-unit-name">চীফ জুডিসিয়াল ম্যাজিস্ট্রেট আদালত, চাঁদপুর</div>
<table class="table">
  <tr><td>অবস্থা</td><td>চলমান</td></tr>
  <tr><td>পরবর্তী তারিখ</td><td>১৫/১০/২০২৬</td></tr>
  <tr><td>সংক্ষিপ্ত আদেশ</td><td>সাক্ষ্য গ্রহণ; মোবাইল ০১৭১১২৩৪৫৬৭</td></tr>
</table>
"""
EMPTY_HTML = '<div class="office-unit-name">CJM</div><table class="table"><tbody></tbody></table>'


def _handler(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    if "id" in params:
        return httpx.Response(200, text=DETAIL_HTML)
    if "caseno" in params:
        return httpx.Response(200, text=EMPTY_HTML if "9999" in params["caseno"] else SEARCH_HTML)
    return httpx.Response(404, text="not found")


@pytest.fixture()
def mock_scraper(monkeypatch: pytest.MonkeyPatch) -> None:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(
        CLS,
        "JudiciaryScraper",
        lambda **kwargs: S.JudiciaryScraper(min_interval=0.0, client=client),
    )


def test_live_lookup(db_session: Session, mock_scraper: None) -> None:
    response = CLS.lookup_case(
        db_session,
        CaseLookupRequest(case_number="সি.আর. ৮৪৪/২০২৩", court_id=900, language=Language.BN),
    )
    assert response.found is True
    assert response.source == "live"
    assert response.cached is False
    assert response.summary is not None
    assert response.summary.normalized_number == "CR-844/2023"
    assert response.summary.next_hearing_date is not None
    assert response.privacy.by_type.get("phone") == 1
    assert "০১৭১১২৩৪৫৬৭" not in (response.explanation or "")
    assert response.next_steps


def test_second_lookup_is_cached(db_session: Session, mock_scraper: None) -> None:
    request = CaseLookupRequest(case_number="সি.আর. ৮৪৪/২০২৩", court_id=900)
    CLS.lookup_case(db_session, request)
    cached = CLS.lookup_case(db_session, request)
    assert cached.cached is True
    assert cached.source == "cache"


def test_cached_result_relocalised(db_session: Session, mock_scraper: None) -> None:
    CLS.lookup_case(db_session, CaseLookupRequest(case_number="সি.আর. ৮৪৪/২০২৩", court_id=900))
    english = CLS.lookup_case(
        db_session,
        CaseLookupRequest(case_number="সি.আর. ৮৪৪/২০২৩", court_id=900, language=Language.EN),
    )
    assert english.explanation is not None
    assert english.explanation.startswith("Case number:")


def test_not_found(db_session: Session, mock_scraper: None) -> None:
    response = CLS.lookup_case(
        db_session, CaseLookupRequest(case_number="GR-9999/2024", court_id=900)
    )
    assert response.found is False
    assert response.summary is None


def test_scraper_failure_falls_back_to_cache(
    db_session: Session, mock_scraper: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = CaseLookupRequest(case_number="সি.আর. ৮৪৪/২০২৩", court_id=900)
    CLS.lookup_case(db_session, request)

    def _boom(**kwargs: object) -> object:
        raise S.ScraperBlocked("blocked")

    monkeypatch.setattr(CLS, "JudiciaryScraper", _boom)
    fallback = CLS.lookup_case(db_session, request.model_copy(update={"force_refresh": True}))
    assert fallback.cached is True
    assert fallback.source == "fallback"
    assert fallback.found is True
