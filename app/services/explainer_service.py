"""Plain-language, bilingual (বাংলা / English) explanations of case data.

Turns the raw, jargon-heavy output of :mod:`app.services.parser_service` into
courtesy of the court: a short, understandable summary a lay citizen can read,
plus concrete next steps. Every free-text field is passed through
:mod:`app.services.privacy_service` first, so no personal data (phone numbers,
NIDs, addresses, ...) is ever echoed back to the caller.

The module is pure and offline — it never performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.schemas import CaseKind, CaseSummary, Language, ParsedCaseNumber
from app.services import parser_service, privacy_service

__all__ = [
    "CaseExplanation",
    "explain_case",
    "explain_case_number",
    "explain_status",
    "explain_next_hearing",
]

_BN = Language.BN
_EN = Language.EN

_HELPLINE_BN = "সহায়তা প্রয়োজন হলে চাঁদপুর জেলা জুডিশিয়াল হেল্পলাইন ০১৩৩৫১৪৫০২৭ নম্বরে কল করুন।"
_HELPLINE_EN = "For help, call the Chandpur district judicial helpline at 01335145027."

_BN_MONTHS = (
    "জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন",
    "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর",
)

# -- vocabulary --------------------------------------------------------------

_KIND_LABELS: dict[CaseKind, dict[Language, str]] = {
    CaseKind.CIVIL: {_BN: "দেওয়ানি (civil)", _EN: "civil"},
    CaseKind.CRIMINAL: {_BN: "ফৌজদারি (criminal)", _EN: "criminal"},
    CaseKind.CR: {_BN: "সি.আর. — ফৌজদারি রিভিশন/রুল", _EN: "Criminal Revision/Rule (CR)"},
    CaseKind.GR: {_BN: "জি.আর. — থানার মামলা", _EN: "police-reported criminal case (GR)"},
    CaseKind.UNKNOWN: {_BN: "অনির্ধারিত ধরন", _EN: "unspecified type"},
}

# Canonical status keys used throughout the module.
_FILED, _PENDING, _HEARING, _ADJOURNED, _DISPOSED, _DISMISSED, _UNKNOWN = (
    "filed", "pending", "hearing", "adjourned", "disposed", "dismissed", "unknown",
)

# Exact matches against our own ``CaseStatus`` enum values first.
_ENUM_STATUS = {
    "filed": _FILED,
    "pending": _PENDING,
    "in_hearing": _HEARING,
    "adjourned": _ADJOURNED,
    "disposed": _DISPOSED,
    "dismissed": _DISMISSED,
}

# Substring matches against Bengali/English order language, in priority order.
_KEYWORD_STATUS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("নিষ্পত্তি", "disposed", "রায় সম্পন্ন"), _DISPOSED),
    (("খারিজ", "dismiss"), _DISMISSED),
    (("মুলতবি", "মুলতবী", "স্থগিত", "adjourn"), _ADJOURNED),
    (("সাক্ষ্য", "সাক্ষী", "witness", "evidence", "অভিযোগ", "চার্জ", "charge"), _HEARING),
    (("রায়", "verdict", "judgment", "রায় ঘোষণা"), _DISPOSED),
    (("বিচার", "trial", "শুনানি", "hearing", "জামিন", "bail"), _HEARING),
    (("চলমান", "pending", "বিচারাধীন"), _PENDING),
    (("দায়ের", "filed"), _FILED),
)

_STATUS_SENTENCES: dict[str, dict[Language, str]] = {
    _FILED: {
        _BN: "মামলাটি দায়ের হয়েছে এবং প্রাথমিক কার্যক্রম চলছে।",
        _EN: "The case has been filed and initial proceedings are under way.",
    },
    _PENDING: {
        _BN: "মামলাটি বিচারাধীন (চলমান)।",
        _EN: "The case is pending before the court.",
    },
    _HEARING: {
        _BN: "মামলার শুনানি ও বিচার কার্যক্রম চলছে।",
        _EN: "Hearings and trial proceedings are in progress.",
    },
    _ADJOURNED: {
        _BN: "মামলার শুনানি স্থগিত (মুলতবি) করা হয়েছে।",
        _EN: "The hearing has been adjourned.",
    },
    _DISPOSED: {
        _BN: "মামলাটি নিষ্পত্তি হয়েছে।",
        _EN: "The case has been disposed of.",
    },
    _DISMISSED: {
        _BN: "মামলাটি খারিজ করা হয়েছে।",
        _EN: "The case has been dismissed.",
    },
    _UNKNOWN: {
        _BN: "মামলার সর্বশেষ অবস্থা স্পষ্ট নয় — নিশ্চিত হতে সংশ্লিষ্ট আদালত অফিসে যোগাযোগ করুন।",
        _EN: "The latest status is unclear — contact the relevant court office to confirm.",
    },
}

_MAX_ORDER_CHARS = 320


@dataclass(slots=True)
class CaseExplanation:
    """A ready-to-render explanation plus suggested next steps."""

    text: str
    next_steps: list[str]
    language: Language = _BN
    redactions: dict[str, int] = field(default_factory=dict)


# -- helpers -----------------------------------------------------------------


def _coerce_language(language: Language | str) -> Language:
    return language if isinstance(language, Language) else Language(str(language))


def _detect_status(status: str | None) -> str:
    """Reduce a free-form status/order string to a canonical status key."""
    if not status:
        return _UNKNOWN
    key = status.strip().casefold()
    if key in _ENUM_STATUS:
        return _ENUM_STATUS[key]
    for keywords, canonical in _KEYWORD_STATUS:
        if any(keyword in key for keyword in keywords):
            return canonical
    return _UNKNOWN


def _format_localized_date(value: date, language: Language) -> str:
    if language is _EN:
        return value.strftime("%d %B %Y")
    day = parser_service.en_to_bn_digits(f"{value.day:02d}")
    year = parser_service.en_to_bn_digits(str(value.year))
    return f"{day} {_BN_MONTHS[value.month - 1]} {year}"


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parser_service.parse_bn_date(value)


def _truncate(text: str, limit: int = _MAX_ORDER_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _merge_counts(*counts: dict[str, int]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for mapping in counts:
        for key, value in mapping.items():
            merged[key] = merged.get(key, 0) + value
    return merged


# -- public API --------------------------------------------------------------


def explain_case_number(
    parsed: ParsedCaseNumber, *, language: Language | str = _BN
) -> str:
    """One-line, plain description of a parsed case number."""
    language = _coerce_language(language)
    kind = _KIND_LABELS.get(parsed.kind, _KIND_LABELS[CaseKind.UNKNOWN])[language]
    number = parsed.normalized or parsed.raw
    if language is _BN:
        year = parser_service.en_to_bn_digits(str(parsed.year)) if parsed.year else "অজানা"
        return f"স্বীকৃত মামলা নম্বর: {number} — ধরন: {kind}, বছর: {year}।"
    year = str(parsed.year) if parsed.year else "unknown"
    return f"Recognized case number: {number} — type: {kind}, year: {year}."


def explain_status(status: str | None, *, language: Language | str = _BN) -> str:
    """Translate a status/order string into one plain sentence."""
    language = _coerce_language(language)
    return _STATUS_SENTENCES[_detect_status(status)][language]


def explain_next_hearing(
    when: date | datetime | str | None,
    *,
    language: Language | str = _BN,
    today: date | None = None,
) -> str:
    """Describe the next hearing date relative to ``today`` (default: today)."""
    language = _coerce_language(language)
    today = today or date.today()
    target = _as_date(when)

    if target is None:
        if language is _BN:
            return "পরবর্তী শুনানির তারিখ এখনো প্রকাশিত হয়নি।"
        return "The next hearing date has not been published yet."

    days = (target - today).days
    formatted = _format_localized_date(target, language)

    if days < 0:
        if language is _BN:
            return f"নির্ধারিত শুনানির তারিখ {formatted} ছিল, যা {parser_service.en_to_bn_digits(str(-days))} দিন আগে পেরিয়ে গেছে।"
        return f"The scheduled hearing was on {formatted}, {abs(days)} day(s) ago."
    if days == 0:
        return "আজ শুনানি নির্ধারিত আছে।" if language is _BN else "The hearing is scheduled for today."
    if language is _BN:
        return f"পরবর্তী শুনানি {formatted} — আর {parser_service.en_to_bn_digits(str(days))} দিন বাকি।"
    return f"Next hearing on {formatted} — {days} day(s) to go."


def _build_next_steps(
    status_key: str,
    target: date | None,
    today: date,
    language: Language,
    has_court: bool,
) -> list[str]:
    steps: list[str] = []
    if status_key in (_DISPOSED, _DISMISSED):
        steps.append(
            "মামলার কার্যক্রম শেষ হয়েছে; প্রয়োজনে রায়/আদেশের সত্যায়িত কপির জন্য আদালত অফিসে আবেদন করুন।"
            if language is _BN
            else "The matter is closed; apply to the court office for a certified copy of the order if needed."
        )
    elif target is None:
        steps.append(
            "পরবর্তী তারিখ নিশ্চিত হতে নিয়মিত আদালতের কার্যতালিকা (cause list) দেখুন।"
            if language is _BN
            else "Check the court's cause list regularly to confirm the next date."
        )
    elif target < today:
        steps.append(
            "নির্ধারিত তারিখ পেরিয়ে গেছে; আপনার আইনজীবী বা সংশ্লিষ্ট আদালত অফিসে দ্রুত যোগাযোগ করুন।"
            if language is _BN
            else "The date has passed; contact your lawyer or the court office without delay."
        )
    else:
        if language is _BN:
            steps.append(
                f"পরবর্তী শুনানির দিন ({_format_localized_date(target, language)}) সংশ্লিষ্ট আদালতে উপস্থিত থাকুন।"
            )
        else:
            steps.append(
                f"Attend the relevant court on the next hearing date ({_format_localized_date(target, language)})."
            )

    steps.append(
        "মামলার নম্বর ও আদালতের তথ্য সংরক্ষণ করুন এবং প্রতিবার একই নম্বর ব্যবহার করুন।"
        if language is _BN
        else "Keep the case number and court details safe and use the same number each time."
    )
    if has_court:
        steps.append(_HELPLINE_BN if language is _BN else _HELPLINE_EN)
    return steps


def explain_case(
    summary: CaseSummary,
    parsed: ParsedCaseNumber | None = None,
    *,
    language: Language | str = _BN,
    today: date | None = None,
) -> CaseExplanation:
    """Build a bilingual plain-language explanation for a case summary."""
    language = _coerce_language(language)
    today = today or date.today()
    parsed = parsed or parser_service.parse_case_number(summary.case_number)

    kind = summary.kind if summary.kind is not CaseKind.UNKNOWN else parsed.kind
    subject = privacy_service.redact(summary.subject)
    order = privacy_service.redact(summary.last_order_summary)
    redactions = _merge_counts(subject.by_type, order.by_type)
    cleaned_subject = _truncate(subject.text, 200)
    cleaned_order = _truncate(order.text)

    status_key = _detect_status(summary.status)
    target = _as_date(summary.next_hearing_date)

    number = summary.normalized_number or summary.case_number

    if language is _BN:
        lines = [f"মামলা নম্বর: {number}"]
        lines.append(f"ধরন: {_KIND_LABELS.get(kind, _KIND_LABELS[CaseKind.UNKNOWN])[_BN]}")
        if summary.court:
            lines.append(f"আদালত: {summary.court}")
        lines.append(_STATUS_SENTENCES[status_key][_BN])
        lines.append(explain_next_hearing(target, language=_BN, today=today))
        if cleaned_subject:
            lines.append(f"বিষয়: {cleaned_subject}")
        if cleaned_order:
            lines.append(f"সর্বশেষ আদেশ (সারাংশ): {cleaned_order}")
    else:
        lines = [f"Case number: {number}"]
        lines.append(f"Type: {_KIND_LABELS.get(kind, _KIND_LABELS[CaseKind.UNKNOWN])[_EN]}")
        if summary.court:
            lines.append(f"Court: {summary.court}")
        lines.append(_STATUS_SENTENCES[status_key][_EN])
        lines.append(explain_next_hearing(target, language=_EN, today=today))
        if cleaned_subject:
            lines.append(f"Subject: {cleaned_subject}")
        if cleaned_order:
            lines.append(f"Latest order (summary): {cleaned_order}")

    text = "\n".join(lines)
    steps = _build_next_steps(
        status_key, target, today, language, bool(summary.court)
    )
    return CaseExplanation(text=text, next_steps=steps, language=language, redactions=redactions)
