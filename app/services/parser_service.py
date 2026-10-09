"""Parsing layer for the Bangladesh judiciary e-services (cause list) portal.

Turns raw HTML/JSON fetched by :mod:`app.services.scraper_service` into typed,
immutable Python structures. No network access happens here, which makes every
function easy to unit-test against saved fixtures.

Target endpoints (all on ``causelist.judiciary.gov.bd``):

* ``/api?path=geo/divisions``            -> JSON, list of divisions
* ``/api?path=geo/districts``            -> JSON, divisions each with ``districts``
* ``/api?path=courts``                   -> JSON, list of offices (courts)
* ``/api?path=office/allOfficeUnitName`` -> JSON, flat list of office units
* ``/causelist?courtId=&date=``          -> HTML, daily cause list table
* ``/caseinfo?courtId=&caseno=``         -> HTML, case search results table
* ``/caseinfo?courtId=&case_type=&id=``  -> HTML, single case detail page

The portal renders dates and numbers in Bengali (e.g. ``০৯-১০-২০২৬``); helpers
here normalise them to ASCII so downstream code works with plain ``date``/``int``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from app.schemas import CaseKind, ParsedCaseNumber

__all__ = [
    "bn_to_en_digits",
    "en_to_bn_digits",
    "parse_bn_date",
    "clean_text",
    "Division",
    "District",
    "Court",
    "OfficeUnit",
    "parse_divisions",
    "parse_districts",
    "parse_courts",
    "parse_office_units",
    "CauseListEntry",
    "CauseListPage",
    "parse_cause_list",
    "CaseListEntry",
    "CaseListPage",
    "parse_case_list",
    "CaseDetailField",
    "CaseDetail",
    "parse_case_detail",
    "parse_case_detail_url",
    "parse_case_number",
    "parse_case_numbers",
    "normalize_case_number",
]

# ---------------------------------------------------------------------------
# Bengali <-> ASCII numeral helpers
# ---------------------------------------------------------------------------

_BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_EN_DIGITS = "0123456789"
_BN_TO_EN = str.maketrans(_BN_DIGITS, _EN_DIGITS)
_EN_TO_BN = str.maketrans(_EN_DIGITS, _BN_DIGITS)

_DATE_RE = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})")


def bn_to_en_digits(text: str | None) -> str:
    """Convert Bengali numerals in ``text`` to ASCII digits."""
    return text.translate(_BN_TO_EN) if text else ""


def en_to_bn_digits(text: str | None) -> str:
    """Convert ASCII digits in ``text`` to Bengali numerals."""
    return text.translate(_EN_TO_BN) if text else ""


def clean_text(node: str | Tag | None) -> str:
    """Collapse whitespace and strip a string or tag's text; ``""`` for None."""
    if node is None:
        return ""
    text = node.get_text(" ", strip=True) if isinstance(node, Tag) else str(node)
    return re.sub(r"\s+", " ", text).strip()


def parse_bn_date(text: str | None) -> date | None:
    """Parse a Bengali or ASCII ``dd-mm-yyyy`` date, e.g. ``০৯-১০-২০২৬``."""
    if not text:
        return None
    match = _DATE_RE.search(bn_to_en_digits(text))
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:  # two-digit years are 20xx here
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# JSON API models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Division:
    id: int
    name_bn: str | None = None
    name_en: str | None = None


@dataclass(frozen=True, slots=True)
class District:
    id: int
    name_bn: str | None = None
    name_en: str | None = None
    division_id: int | None = None


@dataclass(frozen=True, slots=True)
class Court:
    id: int
    name_bn: str | None = None
    name_en: str | None = None
    district_id: int | None = None
    office_origin_id: int | None = None
    office_layer_id: int | None = None
    parent_office_id: int | None = None


@dataclass(frozen=True, slots=True)
class OfficeUnit:
    id: int
    name_bn: str | None = None
    name_en: str | None = None


def _coerce_json(data: str | bytes | list | dict) -> Any:
    """Return parsed JSON from a raw body or an already-decoded object.

    The portal occasionally returns a JSON-*encoded string*, so decode twice.
    """
    if isinstance(data, (bytes, str)):
        parsed = json.loads(data)
    else:
        parsed = data
    if isinstance(parsed, str):
        parsed = json.loads(parsed)
    return parsed


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_divisions(data: str | bytes | list | dict) -> list[Division]:
    """Parse the ``geo/divisions`` response."""
    items = _coerce_json(data) or []
    return [
        Division(
            id=_int_or_none(item.get("geo_division_id")) or 0,
            name_bn=item.get("division_name_bng"),
            name_en=item.get("division_name_eng"),
        )
        for item in items
    ]


def _as_item_list(container: Tag | str | list | dict | None) -> list[Any]:
    """Normalise a portal collection to a flat list of records.

    The live ``geo/districts`` payload nests districts as a dict keyed by id
    ("1": {..}), while some deployments return lists — accept both.
    """
    if isinstance(container, dict):
        return [value for value in container.values() if isinstance(value, dict)]
    if isinstance(container, list):
        return [value for value in container if isinstance(value, dict)]
    return []


def parse_districts(data: str | bytes | list | dict) -> list[District]:
    """Parse the ``geo/districts`` response.

    Accepts the live portal shape (divisions wrapping a ``districts`` dict
    keyed by id), list-shaped nesting, and flat lists of district records.
    """
    groups = _coerce_json(data)
    if not isinstance(groups, list):
        groups = [groups] if isinstance(groups, dict) else []
    districts: list[District] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        division_id = _int_or_none(group.get("geo_division_id") or group.get("division_id"))
        if "geo_district_id" in group:
            # Flat record — no division wrapper.
            districts.append(
                District(
                    id=_int_or_none(group.get("geo_district_id")) or 0,
                    name_bn=group.get("district_name_bng"),
                    name_en=group.get("district_name_eng"),
                    division_id=division_id,
                )
            )
            continue
        for item in _as_item_list(group.get("districts")):
            districts.append(
                District(
                    id=_int_or_none(item.get("geo_district_id")) or 0,
                    name_bn=item.get("district_name_bng"),
                    name_en=item.get("district_name_eng"),
                    division_id=division_id,
                )
            )
    return districts


def parse_courts(data: str | bytes | list | dict) -> list[Court]:
    """Parse the ``courts`` response."""
    items = _coerce_json(data) or []
    return [
        Court(
            id=_int_or_none(item.get("id")) or 0,
            name_bn=item.get("office_name_bng"),
            name_en=item.get("office_name_eng"),
            district_id=_int_or_none(item.get("geo_district_id")),
            office_origin_id=_int_or_none(item.get("office_origin_id")),
            office_layer_id=_int_or_none(item.get("office_layer_id")),
            parent_office_id=_int_or_none(item.get("parent_office_id")),
        )
        for item in items
    ]


def parse_office_units(data: str | bytes | list | dict) -> list[OfficeUnit]:
    """Parse the ``office/allOfficeUnitName`` autocomplete response."""
    items = _coerce_json(data) or []
    units: list[OfficeUnit] = []
    for item in items:
        unit_id = _int_or_none(item.get("id"))
        if unit_id is None:
            continue
        units.append(
            OfficeUnit(
                id=unit_id,
                name_bn=item.get("unit_name_bng"),
                name_en=item.get("unit_name_eng"),
            )
        )
    return units


# ---------------------------------------------------------------------------
# Cause list (daily কার্যতালিকা)
# ---------------------------------------------------------------------------

# Column-header aliases -> canonical field names.
_CAUSE_HEADER_FIELDS: dict[str, str] = {
    "ক্রমিক নং": "serial_no",
    "ক্রমিক নম্বর": "serial_no",
    "serial": "serial_no",
    "serial no": "serial_no",
    "মামলার নম্বর": "case_number",
    "মামলা নম্বর": "case_number",
    "case no": "case_number",
    "case number": "case_number",
    "কার্যক্রম": "proceedings",
    "proceedings": "proceedings",
    "পরবর্তী তারিখ": "next_date",
    "next date": "next_date",
    "সংক্ষিপ্ত আদেশ": "order_summary",
    "order": "order_summary",
    "short order": "order_summary",
}
_CAUSE_POSITIONAL = ["serial_no", "case_number", "proceedings", "next_date", "order_summary"]


@dataclass(frozen=True, slots=True)
class CauseListEntry:
    serial_no: str | None = None
    case_number: str | None = None
    proceedings: str | None = None
    next_date: date | None = None
    next_date_raw: str | None = None
    order_summary: str | None = None
    detail_url: str | None = None


@dataclass(frozen=True, slots=True)
class CauseListPage:
    court_name: str | None = None
    cause_date: date | None = None
    cause_date_raw: str | None = None
    entries: list[CauseListEntry] = field(default_factory=list)


def _canonical_field(header: str) -> str | None:
    return _CAUSE_HEADER_FIELDS.get(header.lower().strip())


def _map_cells(headers: list[str], values: list[str]) -> dict[str, str]:
    """Map a table row to field names, preferring headers, falling back to order."""
    if headers and any(_canonical_field(h) for h in headers):
        row: dict[str, str] = {}
        for header, value in zip(headers, values):
            field_name = _canonical_field(header)
            if field_name and field_name not in row:
                row[field_name] = value
        return row
    return {
        field_name: values[index]
        for index, field_name in enumerate(_CAUSE_POSITIONAL)
        if index < len(values)
    }


def _data_table(soup: Tag) -> Tag | None:
    """Return the data-bearing table, skipping decoy tables.

    Portal pages embed a marquee notice <table> before the real data table;
    the decoy has no tbody rows and no recognised headers. Prefer the table
    with the most rows, tie-breaking on recognised headers.
    """
    best: Tag | None = None
    best_score = 0
    for table in soup.find_all("table"):
        rows = table.select("tbody tr")
        headers = [clean_text(h) for h in table.select("thead th")]
        header_score = len([h for h in headers if _canonical_field(h)])
        score = len(rows) * 10 + header_score
        if score > best_score:
            best_score = score
            best = table
    return best


def parse_cause_list(html: str | bytes) -> CauseListPage:
    """Parse a ``/causelist`` page into a :class:`CauseListPage`."""
    soup = BeautifulSoup(html, "lxml")

    court_name = clean_text(soup.select_one(".office-unit-name")) or None

    cause_date_raw = clean_text(soup.select_one(".cause-date")) or None
    if cause_date_raw:
        # Strip the leading "তারিখঃ" / "Date:" label if present.
        cause_date_raw = re.sub(r"^(তারিখ[:ঃ]?|date\s*:?)\s*", "", cause_date_raw, flags=re.I)
    cause_date = parse_bn_date(cause_date_raw)

    entries: list[CauseListEntry] = []
    table = _data_table(soup)
    if table is not None:
        headers = [clean_text(th) for th in table.select("thead th")]
        for row in table.select("tbody tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            values = [clean_text(cell) for cell in cells]
            if not any(values):
                continue
            mapped = _map_cells(headers, values)
            next_raw = mapped.get("next_date")
            anchor = row.find("a", href=True)
            entries.append(
                CauseListEntry(
                    serial_no=mapped.get("serial_no") or None,
                    case_number=mapped.get("case_number") or None,
                    proceedings=mapped.get("proceedings") or None,
                    next_date=parse_bn_date(next_raw),
                    next_date_raw=next_raw or None,
                    order_summary=mapped.get("order_summary") or None,
                    detail_url=anchor["href"] if anchor else None,
                )
            )

    return CauseListPage(
        court_name=court_name,
        cause_date=cause_date,
        cause_date_raw=cause_date_raw,
        entries=entries,
    )


# ---------------------------------------------------------------------------
# Case search results (মামলা অনুসন্ধান -> /caseinfo?courtId=&caseno=)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseListEntry:
    serial_no: str | None = None
    case_type: str | None = None
    case_number: str | None = None
    case_number_raw: str | None = None
    upazila: str | None = None
    plaintiff: str | None = None
    defendant: str | None = None
    detail_url: str | None = None
    court_id: int | None = None
    case_type_id: int | None = None
    case_id: str | None = None


@dataclass(frozen=True, slots=True)
class CaseListPage:
    court_name: str | None = None
    entries: list[CaseListEntry] = field(default_factory=list)


_UPAZILA_RE = re.compile(r"\(([^()]+)\)\s*$")


def parse_case_list(html: str | bytes) -> CaseListPage:
    """Parse the ``/caseinfo`` search-results table into a :class:`CaseListPage`."""
    soup = BeautifulSoup(html, "lxml")
    court_name = clean_text(soup.select_one(".office-unit-name")) or None

    entries: list[CaseListEntry] = []
    table = _data_table(soup)
    if table is not None:
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            serial_no = clean_text(cells[0]) or None

            case_type: str | None = None
            case_number_raw = ""
            upazila: str | None = None
            if len(cells) > 1:
                case_cell = cells[1]
                type_span = case_cell.select_one(".color-black-blue")
                case_type = clean_text(type_span) or None
                case_number_raw = clean_text(case_cell)
                upazila_match = _UPAZILA_RE.search(case_number_raw)
                if upazila_match:
                    upazila = upazila_match.group(1)
                if case_type:
                    case_number_raw = case_number_raw.replace(case_type, "", 1).strip(" -–—")

            plaintiff = defendant = None
            if len(cells) > 2:
                parties = cells[2].select(".fs-2")
                labels = [clean_text(p) for p in parties if clean_text(p)]
                if labels:
                    plaintiff = labels[0]
                if len(labels) > 1:
                    defendant = labels[-1]

            detail_url: str | None = None
            court_id = case_type_id = None
            case_id: str | None = None
            anchor = row.find("a", href=True)
            if anchor:
                detail_url = anchor["href"]
                parsed = parse_case_detail_url(detail_url)
                court_id = parsed["court_id"]
                case_type_id = parsed["case_type_id"]
                case_id = parsed["case_id"]

            entries.append(
                CaseListEntry(
                    serial_no=serial_no,
                    case_type=case_type,
                    case_number=case_number_raw or None,
                    case_number_raw=clean_text(cells[1]) if len(cells) > 1 else None,
                    upazila=upazila,
                    plaintiff=plaintiff,
                    defendant=defendant,
                    detail_url=detail_url,
                    court_id=court_id,
                    case_type_id=case_type_id,
                    case_id=case_id,
                )
            )

    return CaseListPage(court_name=court_name, entries=entries)


def parse_case_detail_url(url: str) -> dict[str, Any]:
    """Extract ``court_id``/``case_type_id``/``case_id`` from a case detail link."""
    query = parse_qs(urlparse(url).query)
    return {
        "court_id": _int_or_none((query.get("courtId") or [None])[0]),
        "case_type_id": _int_or_none((query.get("case_type") or [None])[0]),
        "case_id": (query.get("id") or [None])[0],
        "case_no": (query.get("caseno") or [None])[0],
    }


def portal_caseno(case_number: str | None) -> str | None:
    """Return the bare ``serial/year`` (Latin digits) the portal search needs.

    Live probing showed the portal matches ``caseno=1153/2025`` (or Bengali
    digits) but not prefix-styled forms.
    """
    parsed = parse_case_number(case_number) if case_number else None
    if not parsed or not parsed.serial:
        return None
    bare = f"{parsed.serial}/{parsed.year}" if parsed.year else str(parsed.serial)
    return bn_to_en_digits(bare)


# ---------------------------------------------------------------------------
# Single case detail page (/caseinfo?courtId=&case_type=&id=)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaseDetailField:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class CaseDetail:
    court_name: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    raw_text: str = ""


def parse_case_detail(html: str | bytes) -> CaseDetail:
    """Best-effort parse of a case detail page.

    The live portal renders the case identity (case number, filing date,
    parties) as rows followed by a **hearing-history table** with columns
    ``শুনানির তারিখ | কার্যক্রম | সংক্ষিপ্ত আদেশ | মামলার অবস্থা`` — the last
    row is the current state and is promoted to ``fields`` (পরবর্তী তারিখ,
    কার্যক্রম, সংক্ষিপ্ত আদেশ, অবস্থা). Older deployments use plain
    two-column label/value tables; both are supported.
    """
    soup = BeautifulSoup(html, "lxml")
    court_name = clean_text(soup.select_one(".office-unit-name")) or None

    fields: dict[str, str] = {}
    sections: dict[str, dict[str, str]] = {}
    current_section: dict[str, str] | None = None
    current_title: str | None = None

    for table in soup.select("table.table, table"):
        hearing_headers: list[str] | None = None
        hearing_records: list[dict[str, str]] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            texts = [clean_text(cell) for cell in cells]
            non_empty = [t for t in texts if t]

            if hearing_headers is None and _is_hearing_header_row(non_empty):
                hearing_headers = non_empty
                continue
            if hearing_headers is not None:
                if non_empty:
                    record = {
                        header: (texts[i] if i < len(texts) else "")
                        for i, header in enumerate(hearing_headers)
                    }
                    hearing_records.append(record)
                continue

            if non_empty and any(t.startswith(("মামলার নম্বর", "বাদী", "বিবাদী", "আসামি", "আসামী")) for t in non_empty):
                for t in non_empty:
                    _parse_identity(fields, t)
                continue

            if len(cells) == 1 and non_empty:
                # Single-cell row -> section header.
                current_title = non_empty[0]
                current_section = sections.setdefault(current_title, {})
                continue

            if len(texts) >= 2:
                label, value = texts[0], " ".join(texts[1:]).strip()
                if label:
                    target = current_section if current_section is not None else fields
                    target.setdefault(label, value)

        if hearing_records:
            latest = hearing_records[-1]
            for header, value in latest.items():
                field_name = _HEARING_TO_FIELDS.get(header)
                if field_name:
                    fields.setdefault(field_name, value)
            history = sections.setdefault("শুনানির ইতিহাস", {})
            for record in hearing_records:
                date = record.get("শুনানির তারিখ") or ""
                bits = " | ".join(
                    value for key, value in record.items()
                    if key != "শুনানির তারিখ" and value
                )
                history[date] = bits

    for dl in soup.find_all("dl"):
        terms = dl.find_all("dt")
        definitions = dl.find_all("dd")
        for term, definition in zip(terms, definitions):
            label = clean_text(term)
            if label:
                fields.setdefault(label, clean_text(definition))

    return CaseDetail(
        court_name=court_name,
        fields=fields,
        sections=sections,
        raw_text=clean_text(soup.get_text(" ")),
    )


_HEARING_HEADERS = ("শুনানির তারিখ", "কার্যক্রম", "সংক্ষিপ্ত আদেশ", "মামলার অবস্থা")
_HEARING_TO_FIELDS = {
    "শুনানির তারিখ": "পরবর্তী তারিখ",
    "কার্যক্রম": "কার্যক্রম",
    "সংক্ষিপ্ত আদেশ": "সংক্ষিপ্ত আদেশ",
    "মামলার অবস্থা": "অবস্থা",
}


def _is_hearing_header_row(texts: list[str]) -> bool:
    return len(texts) >= 3 and all(text in _HEARING_HEADERS for text in texts)


def _parse_identity(fields: dict[str, str], text: str) -> None:
    """Harvest case-number / filing-date / party fields from an identity row."""
    if "মামলার নম্বর" in text:
        match = re.search(r"মামলার নম্বর[ঃ:]?\s*(.+?)(?:\s+দায়েরের তারিখ|$)", text)
        if match:
            fields.setdefault("মামলার নম্বর", match.group(1).strip())
    if "দায়েরের তারিখ" in text:
        match = re.search(r"দায়েরের তারিখ[ঃ:]?\s*(.+?)\s*$", text)
        if match:
            fields.setdefault("দায়েরের তারিখ", match.group(1).strip())
    for key, label in (("বাদী", "বাদী"), ("বিবাদী", "বিবাদী"), ("আসামি", "আসামি"), ("আসামি", "আসামী")):
        if text.startswith(label):
            match = re.match(rf"^{re.escape(label)}[^ঃ:]*[ঃ:]\s*(.+)", text)
            if match:
                fields.setdefault(key, match.group(1).strip())
                break


# ---------------------------------------------------------------------------
# Case-number parsing engine
# ---------------------------------------------------------------------------
#
# Recognises Bangladesh case numbers such as ``844/2023``, ``সি.আর. ৮৪৪/২০২৩``,
# ``জি. আর. মামলা - ১৩৭/২০২৬`` and ``Civil Suit No. 45/2021`` in both English
# and Bengali numerals, and maps the prefix to a canonical form + case kind.

# ``serial/year`` core, e.g. ``844/2023`` or ``১৩৭/২০২৬``.
_CASE_NUMBER_RE = re.compile(r"(?P<serial>[\d০-৯]{1,6})\s*[/\\]\s*(?P<year>[\d০-৯]{2,4})")

# Normalised-prefix alias -> (canonical prefix, kind).
_PREFIX_ALIASES: dict[str, tuple[str, CaseKind]] = {
    "cr": ("CR", CaseKind.CR),
    "সিআর": ("CR", CaseKind.CR),
    "criminarule": ("CR", CaseKind.CR),
    "gr": ("GR", CaseKind.GR),
    "জিআর": ("GR", CaseKind.GR),
    "civil": ("CIVIL", CaseKind.CIVIL),
    "সিভিল": ("CIVIL", CaseKind.CIVIL),
    "দেওয়ানি": ("CIVIL", CaseKind.CIVIL),
    "দেওয়ানী": ("CIVIL", CaseKind.CIVIL),
    "criminal": ("CRIMINAL", CaseKind.CRIMINAL),
    "ফৌজদারি": ("CRIMINAL", CaseKind.CRIMINAL),
    "ফৌজদারী": ("CRIMINAL", CaseKind.CRIMINAL),
    "misc": ("MISC", CaseKind.UNKNOWN),
    "মিসকেস": ("MISC", CaseKind.UNKNOWN),
    "writ": ("WRIT", CaseKind.UNKNOWN),
    "রিট": ("WRIT", CaseKind.UNKNOWN),
    "appeal": ("APPEAL", CaseKind.UNKNOWN),
    "আপিল": ("APPEAL", CaseKind.UNKNOWN),
    "family": ("FAMILY", CaseKind.CIVIL),
    "পারিবারিক": ("FAMILY", CaseKind.CIVIL),
}

# Filler words stripped from the end of a prefix, e.g. ``জি. আর. মামলা``.
_TRAILING_FILLER = re.compile(
    r"(?:মামলা|মোকদ্দমা|অভিযোগ|নং|নম্বর|case|suit|no|number|mokaddama)+$"
)

# Keyword fallbacks when there is no recognisable prefix.
_KEYWORD_KINDS: tuple[tuple[str, CaseKind], ...] = (
    ("সি.আর", CaseKind.CR),
    ("সি আর", CaseKind.CR),
    ("জি.আর", CaseKind.GR),
    ("জি আর", CaseKind.GR),
    ("ফৌজদারি", CaseKind.CRIMINAL),
    ("ফৌজদারী", CaseKind.CRIMINAL),
    ("দেওয়ানি", CaseKind.CIVIL),
    ("দেওয়ানী", CaseKind.CIVIL),
    ("criminal", CaseKind.CRIMINAL),
    ("civil", CaseKind.CIVIL),
)


def _normalize_prefix(raw: str) -> str:
    """Reduce a prefix string to a comparable key (no punctuation/space/filler)."""
    # Drop only separators/punctuation; keep Bengali letters *and* vowel signs.
    key = re.sub(r"[\s.\-–—:।,]+", "", raw).casefold()
    return _TRAILING_FILLER.sub("", key)


def _match_prefix(key: str) -> tuple[str, CaseKind] | None:
    if not key:
        return None
    if key in _PREFIX_ALIASES:
        return _PREFIX_ALIASES[key]
    # Prefer a recognised type token at the end (e.g. "এইআদেশেসিআর" -> "সিআর"),
    # then at the start (e.g. "civilsuit" -> "civil"), longest alias first.
    for matcher in (str.endswith, str.startswith):
        for alias in sorted(_PREFIX_ALIASES, key=len, reverse=True):
            if matcher(key, alias):
                return _PREFIX_ALIASES[alias]
    return None


def _kind_from_keywords(text: str) -> CaseKind:
    lowered = text.casefold()
    for keyword, kind in _KEYWORD_KINDS:
        if keyword.casefold() in lowered:
            return kind
    return CaseKind.UNKNOWN


def _expand_two_digit_year(year: int) -> int:
    """Expand a 2-digit case year (``99`` -> 1999, ``23`` -> 2023)."""
    if year >= 100:
        return year
    candidate = 2000 + year
    # A 20xx reading in the future means the case predates 2000.
    return 1900 + year if candidate > date.today().year + 1 else candidate


def parse_case_number(text: str | None) -> ParsedCaseNumber:
    """Parse a single raw case number into a :class:`ParsedCaseNumber`.

    Never raises: unparseable input yields a low-confidence result with an
    empty/echoed normalized form so callers can still echo what was searched.
    """
    raw = clean_text(text) if text else ""
    if not raw:
        return ParsedCaseNumber(raw="", normalized="", kind=CaseKind.UNKNOWN, confidence=0.0)

    ascii_text = bn_to_en_digits(raw)
    match = _CASE_NUMBER_RE.search(ascii_text)
    if not match:
        return ParsedCaseNumber(
            raw=raw,
            normalized=raw,
            kind=_kind_from_keywords(raw),
            confidence=0.0,
        )

    serial = int(match.group("serial"))
    year = _expand_two_digit_year(int(match.group("year")))

    prefix_text = raw[: match.start()]
    alias = _match_prefix(_normalize_prefix(prefix_text))
    if alias is not None:
        canonical, kind = alias
        confidence = 1.0 if 1900 <= year <= 2100 else 0.7
    else:
        canonical = None
        kind = _kind_from_keywords(raw)
        confidence = 0.6 if not prefix_text.strip() else 0.5

    normalized = f"{canonical + '-' if canonical else ''}{serial}/{year}"
    return ParsedCaseNumber(
        raw=raw,
        normalized=normalized,
        kind=kind,
        prefix=canonical,
        serial=serial,
        year=year,
        confidence=confidence,
    )


def parse_case_numbers(text: str | None) -> list[ParsedCaseNumber]:
    """Extract every case number found in a block of text (e.g. an order)."""
    if not text:
        return []
    ascii_text = bn_to_en_digits(text)
    results: list[ParsedCaseNumber] = []
    prev_end = 0
    for match in _CASE_NUMBER_RE.finditer(ascii_text):
        # Only the text between the previous number and this one can hold the
        # prefix, which keeps unrelated leading words out of the match.
        segment = text[prev_end : match.start()]
        alias = _match_prefix(_normalize_prefix(segment))
        canonical = alias[0] if alias else None
        kind = alias[1] if alias else _kind_from_keywords(segment)
        serial = int(match.group("serial"))
        year = _expand_two_digit_year(int(match.group("year")))
        results.append(
            ParsedCaseNumber(
                raw=text[match.start() : match.end()],
                normalized=f"{canonical + '-' if canonical else ''}{serial}/{year}",
                kind=kind,
                prefix=canonical,
                serial=serial,
                year=year,
                confidence=1.0 if alias else 0.5,
            )
        )
        prev_end = match.end()
    return results


def normalize_case_number(text: str | None) -> str:
    """Return the canonical case-number string (e.g. ``CR-844/2023``)."""
    return parse_case_number(text).normalized
