"""Tests for the bilingual explainer."""

from __future__ import annotations

import datetime as dt

from app.schemas import CaseKind, CaseSummary, Language
from app.services import explainer_service as E
from app.services import parser_service as P

TODAY = dt.date(2026, 10, 10)


def _summary(**overrides: object) -> CaseSummary:
    base = dict(
        case_number="সি.আর. ৮৪৪/২০২৩",
        normalized_number="CR-844/2023",
        kind=CaseKind.CR,
        court="চীফ জুডিসিয়াল ম্যাজিস্ট্রেট আদালত, চাঁদপুর",
        status="সাক্ষ্য গ্রহণ চলছে",
        next_hearing_date=dt.date(2026, 10, 15),
        last_order_summary="আসামির মোবাইল ০১৭১১২৩৪৫৬৭ নথিভুক্ত।",
        subject="চেক প্রতারণা",
    )
    base.update(overrides)
    return CaseSummary(**base)


def test_bengali_explanation_and_redaction() -> None:
    ex = E.explain_case(_summary(), language=Language.BN, today=TODAY)
    assert "মামলা নম্বর: CR-844/2023" in ex.text
    assert "আর ৫ দিন বাকি" in ex.text
    assert ex.redactions.get("phone") == 1
    assert "০১৭১১২৩৪৫৬৭" not in ex.text
    assert any("আদালতে উপস্থিত" in step for step in ex.next_steps)


def test_english_explanation_overdue() -> None:
    ex = E.explain_case(
        _summary(status="adjourned", next_hearing_date=dt.date(2026, 9, 1)),
        language="en",
        today=TODAY,
    )
    assert "The hearing has been adjourned." in ex.text
    assert "day(s) ago" in ex.text
    assert any("contact your lawyer" in step for step in ex.next_steps)


def test_disposed_case() -> None:
    ex = E.explain_case(
        _summary(status="মামলা নিষ্পত্তি হয়েছে", next_hearing_date=None),
        language=Language.BN,
        today=TODAY,
    )
    assert "নিষ্পত্তি হয়েছে।" in ex.text
    assert any("কার্যক্রম শেষ" in step for step in ex.next_steps)


def test_explain_status_translation() -> None:
    assert E.explain_status("খারিজ", language="en") == "The case has been dismissed."


def test_explain_next_hearing_none() -> None:
    assert E.explain_next_hearing(None, language="bn") == "পরবর্তী শুনানির তারিখ এখনো প্রকাশিত হয়নি।"
    assert E.explain_next_hearing(None, language="en").endswith("published yet.")


def test_explain_case_number_line() -> None:
    parsed = P.parse_case_number("সি.আর. ৮৪৪/২০২৩")
    assert parsed is not None
    assert E.explain_case_number(parsed, language="en").startswith("Recognized case number: CR-844/2023")
