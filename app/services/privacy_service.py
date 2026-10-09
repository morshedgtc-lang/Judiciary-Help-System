"""Privacy guardrails: automated masking of confidential PII.

The judiciary portal frequently exposes phone numbers, national IDs, e-mail
addresses, bank/account numbers and home addresses in order papers and party
details. Per human-rights and data-privacy standards this module masks those
values *before* they are stored, explained or rendered, so the public app never
re-publishes personal data.

The module is deterministic and offline (pure regex), returns only aggregate
counts — never the original values — and is safe to call on any text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["RedactionResult", "redact", "sanitize", "PLACEHOLDERS"]

PLACEHOLDERS: dict[str, str] = {
    "phone": "[PHONE_REDACTED]",
    "nid": "[NID_REDACTED]",
    "email": "[EMAIL_REDACTED]",
    "address": "[ADDRESS_REDACTED]",
    "bank_account": "[ACCOUNT_REDACTED]",
}

# Bengali digits -> ASCII, applied to a same-length copy so regex spans map
# 1:1 back onto the original text. Portals here are Bengali-numeral heavy, so
# matching raw text would silently miss most phone numbers and NIDs.
_BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_EN_DIGITS = "0123456789"
_BN_TO_EN = str.maketrans(_BN_DIGITS, _EN_DIGITS)

# -- patterns (BD-aware, order of application matters) ----------------------

_PHONE = re.compile(
    r"(?:\+?\s?880|0)\s?1[3-9](?:[\s.\-]?\d){8}\b"
)

_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# 17, 13 then 10 digit national-ID style numbers.
_NID = re.compile(r"(?<!\d)(?:\d{17}|\d{13}|\d{10})(?!\d)")

_BANK_ACCOUNT = re.compile(
    r"(?i)(?:account|a/c|acc\.?|হিসাব|একাউন্ট)\s*(?:no\.?|number|নম্বর)?\s*:?\s*"
    r"([\d\-]{6,20})"
)

# Best-effort address masking: a phrase containing an address keyword.
_ADDRESS_KEYWORDS = (
    r"গ্রাম|বাসা|বাড়ি|রোড|সড়ক|ডাকঘর|পোস্ট\s?অফিস|উপজেলা|থানা|ওয়ার্ড|মহল্লা|"
    r"village|house|road|post\s?office|ward|holding"
)
_ADDRESS = re.compile(rf"[^,।\n;]*?(?:{_ADDRESS_KEYWORDS})[^,।\n;]*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Sanitized text plus aggregate counts of what was masked."""

    text: str
    total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)

    @property
    def applied(self) -> bool:
        return self.total > 0


def _apply(
    text: str, pattern: re.Pattern[str], kind: str, counts: dict[str, int]
) -> str:
    # Match against a digit-normalized, same-length view so Bengali numerals are
    # caught too; spans are valid on the original string because translation is
    # strictly one character to one character.
    normalized = text.translate(_BN_TO_EN)
    matches = list(pattern.finditer(normalized))
    if not matches:
        return text

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        pieces.append(PLACEHOLDERS[kind])
        cursor = match.end()
        counts[kind] = counts.get(kind, 0) + 1
    pieces.append(text[cursor:])
    return "".join(pieces)


def redact(text: str | None) -> RedactionResult:
    """Mask PII in ``text`` and return the sanitized text with counts."""
    if not text:
        return RedactionResult(text=text or "", total=0, by_type={})

    counts: dict[str, int] = {}
    result = text
    # Address first: it may otherwise swallow phone/ID tokens within it.
    result = _apply(result, _ADDRESS, "address", counts)
    result = _apply(result, _PHONE, "phone", counts)
    result = _apply(result, _EMAIL, "email", counts)
    result = _apply(result, _BANK_ACCOUNT, "bank_account", counts)
    result = _apply(result, _NID, "nid", counts)

    return RedactionResult(text=result, total=sum(counts.values()), by_type=counts)


def sanitize(text: str | None) -> str:
    """Convenience wrapper returning only the sanitized text."""
    return redact(text).text
