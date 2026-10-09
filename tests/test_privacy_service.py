"""Tests for PII redaction."""

from __future__ import annotations

from app.services import privacy_service as PV


def test_masks_ascii_phone_and_email() -> None:
    result = PV.redact("যোগাযোগ: 01711234567, email rahim@example.com।")
    assert result.by_type["phone"] == 1
    assert result.by_type["email"] == 1
    assert "01711234567" not in result.text
    assert "rahim@example.com" not in result.text
    assert PV.PLACEHOLDERS["phone"] in result.text


def test_masks_bengali_numeral_pii() -> None:
    result = PV.redact("মোবাইল ০১৭১১২৩৪৫৬৭ এবং এনআইডি ১৯৮৭৬৫৪৩২১০৯১।")
    assert result.by_type["phone"] == 1
    assert result.by_type["nid"] == 1
    assert "০১৭১১২৩৪৫৬৭" not in result.text
    assert "১৯৮৭৬৫৪৩২১০৯১" not in result.text


def test_masks_address_phrase() -> None:
    result = PV.redact("ঠিকানা: গ্রাম-রামপুর, ডাকঘর-চাঁদপুর।")
    assert result.by_type["address"] >= 1
    assert "গ্রাম-রামপুর" not in result.text


def test_masks_bank_account() -> None:
    result = PV.redact("Account No: 12345678901")
    assert result.by_type["bank_account"] == 1
    assert "12345678901" not in result.text


def test_sanitize_returns_text_only() -> None:
    assert isinstance(PV.sanitize("মোবাইল ০১৭১১২৩৪৫৬৭"), str)
    assert PV.sanitize(None) == ""


def test_no_pii_leaves_text_unchanged() -> None:
    result = PV.redact("মামলাটি নিষ্পত্তি হয়েছে।")
    assert result.applied is False
    assert result.total == 0
    assert result.text == "মামলাটি নিষ্পত্তি হয়েছে।"
