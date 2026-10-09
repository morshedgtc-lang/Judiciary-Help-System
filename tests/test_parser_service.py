"""Tests for the case-number and HTML/JSON parsers."""

from __future__ import annotations

import datetime as dt

from app.schemas import CaseKind
from app.services import parser_service as P


def test_bengali_digit_roundtrip() -> None:
    assert P.bn_to_en_digits("০১৭১১২৩৪৫৬৭") == "01711234567"
    assert P.en_to_bn_digits("844") == "৮৪৪"


def test_parse_bn_date_variants() -> None:
    assert P.parse_bn_date("১৫/১০/২০২৬") == dt.date(2026, 10, 15)
    assert P.parse_bn_date("01-09-2026") == dt.date(2026, 9, 1)
    assert P.parse_bn_date("not a date") is None


def test_parse_case_number_english_and_bengali() -> None:
    parsed = P.parse_case_number("সি.আর. ৮৪৪/২০২৩")
    assert parsed is not None
    assert parsed.kind is CaseKind.CR
    assert parsed.normalized == "CR-844/2023"
    assert parsed.serial == 844
    assert parsed.year == 2023

    gr = P.parse_case_number("জি. আর. মামলা - ১৩৭/২০২৬")
    assert gr is not None
    assert gr.kind is CaseKind.GR
    assert gr.normalized == "GR-137/2026"


def test_two_digit_year_expansion() -> None:
    parsed = P.parse_case_number("G.R. 77/99")
    assert parsed is not None
    assert parsed.year == 1999


def test_parse_case_numbers_extracts_multiple() -> None:
    numbers = P.parse_case_numbers("সি.আর. ৮৪৪/২০২৩ এবং জি.আর. ১৩৭/২০২৬ শুনানির জন্য।")
    normalized = {n.normalized for n in numbers}
    assert "CR-844/2023" in normalized
    assert "GR-137/2026" in normalized


def test_normalize_case_number() -> None:
    assert P.normalize_case_number("সি.আর. ৮৪৪/২০২৩") == "CR-844/2023"


def test_parse_cause_list() -> None:
    html = """
    <div class="office-unit-name">চীফ জুডিসিয়াল ম্যাজিস্ট্রেট আদালত</div>
    <div class="cause-date">০৯-১০-২০২৬</div>
    <table><thead><tr><th>ক্রমিক নং</th><th>মামলার নম্বর</th></tr></thead>
    <tbody><tr><td>১</td><td>সি.আর. ১/২০২৬</td></tr></tbody></table>
    """
    page = P.parse_cause_list(html)
    assert page.court_name == "চীফ জুডিসিয়াল ম্যাজিস্ট্রেট আদালত"
    assert page.entries[0].case_number == "সি.আর. ১/২০২৬"


def test_parse_case_list_with_detail_link() -> None:
    html = """
    <div class="office-unit-name">CJM Chandpur</div>
    <table><tbody><tr>
      <td>১</td><td>সি.আর. ৮৪৪/২০২৩</td>
      <td><span class="fs-2">রহিম</span><span class="fs-2">করিম</span></td>
      <td><a href="/caseinfo?courtId=900&case_type=344&id=abc123">detail</a></td>
    </tr></tbody></table>
    """
    page = P.parse_case_list(html)
    entry = page.entries[0]
    assert entry.case_id == "abc123"
    assert entry.court_id == 900
    assert entry.case_type_id == 344
    assert entry.plaintiff == "রহিম"
    assert entry.defendant == "করিম"


def test_parse_case_detail_label_values() -> None:
    html = """
    <div class="office-unit-name">CJM</div>
    <table class="table">
      <tr><td>অবস্থা</td><td>চলমান</td></tr>
      <tr><td>পরবর্তী তারিখ</td><td>১৫/১০/২০২৬</td></tr>
    </table>
    """
    detail = P.parse_case_detail(html)
    assert detail.court_name == "CJM"
    assert detail.fields["অবস্থা"] == "চলমান"
    assert detail.fields["পরবর্তী তারিখ"] == "১৫/১০/২০২৬"
