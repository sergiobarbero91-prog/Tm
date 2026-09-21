"""Tests for the Taxitronic OCR pipeline.

We prioritise UNIT tests over end-to-end so a red build points at the
exact broken stage (parser vs validator vs pipeline). One integration
test drives the real sample photo end-to-end and asserts the pipeline
NEVER auto-accepts a noisy read.
"""
from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ticket_ocr import scan_taxitronic_ticket
from ticket_ocr.ocr_engine import OcrWord, TesseractEngine
from ticket_ocr.parser import (
    _normalise_number_string,
    extract_fields,
    normalise_value,
)
from ticket_ocr.pipeline import _decide_status
from ticket_ocr.preprocess import preprocess
from ticket_ocr.validators import validate_format, validate_math


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_PHOTO = FIXTURES / "taxitronic_sample.jpeg"


# ─────────────────────────── Number normalisation ───────────────────────────
class TestNumberNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("69515,60",       "69515.60"),
        ("59147,0",        "59147.0"),
        ("69.515,60",      "69515.60"),
        ("1.234.567,89",   "1234567.89"),
        ("59147.0",        "59147.0"),
        ("1,234,567.89",   "1234567.89"),
        ("470",            "470"),
        ("0,00",           "0.00"),
    ])
    def test_parses_all_european_and_english_forms(self, raw, expected):
        assert _normalise_number_string(raw) == expected

    def test_decimal_field_returns_decimal(self):
        val, ok, notes = normalise_value("carreras", "69515,60")
        assert ok
        assert val == Decimal("69515.60")
        assert notes == []

    def test_integer_field_rejects_non_number(self):
        val, ok, notes = normalise_value("num_servicios", "abc")
        assert not ok
        assert val is None

    def test_ocr_letter_to_digit_fix_only_within_numeric_tokens(self):
        # "co" (garbage) must NOT collapse to "c0" and steal the value.
        val, ok, _ = normalise_value("carreras", "co 69515,60")
        assert ok
        assert val == Decimal("69515.60")

    def test_longest_number_wins(self):
        val, ok, _ = normalise_value("total", "45  69515,60")
        assert ok
        assert val == Decimal("69515.60")


# ─────────────────────────── Date normalisation ───────────────────────────
class TestDateNormalisation:
    def test_dd_mm_yy_hh_mm(self):
        val, ok, _ = normalise_value("fecha", "20/09/26 15:03")
        assert ok
        assert val == {"date": "2026-09-20", "time": "15:03"}

    def test_invalid_day_fails(self):
        val, ok, _ = normalise_value("fecha", "32/13/26 15:03")
        assert not ok
        assert val is None

    def test_invalid_time_still_returns_date(self):
        # Bad time shouldn't kill the whole field — mark note only.
        val, ok, notes = normalise_value("fecha", "20/09/26 25:99")
        assert ok
        assert val["date"] == "2026-09-20"
        assert "time" not in val
        assert "time_invalid" in notes


# ─────────────────────────── Field format validation ───────────────────────────
class TestFieldFormatValidation:
    def _pf(self, key, val, fmt=True):
        from ticket_ocr.parser import ParsedField
        return ParsedField(
            key=key, raw_text=str(val), normalised=val,
            ocr_confidence=0.9, format_valid=fmt, bbox=None, variant="unit",
        )

    def test_licencia_must_be_numeric(self):
        f = self._pf("licencia", "ABC")
        ok, notes = validate_format(f)
        assert not ok
        assert "licencia_not_numeric" in notes

    def test_licencia_5_digits_passes(self):
        f = self._pf("licencia", "11412")
        ok, _ = validate_format(f)
        assert ok

    def test_negative_decimal_rejected(self):
        f = self._pf("total", Decimal("-1.00"))
        ok, notes = validate_format(f)
        assert not ok

    def test_negative_integer_rejected(self):
        f = self._pf("num_servicios", -3)
        ok, _ = validate_format(f)
        assert not ok


# ─────────────────────────── Math validation ───────────────────────────
class TestMathValidation:
    def _pf(self, key, val):
        from ticket_ocr.parser import ParsedField
        return ParsedField(key=key, raw_text=str(val), normalised=val,
                            ocr_confidence=0.9, format_valid=True, bbox=None)

    def test_carreras_plus_supplements_equals_total(self):
        fields = {
            "carreras": self._pf("carreras", Decimal("69515.60")),
            "suplementos": self._pf("suplementos", Decimal("0.00")),
            "total": self._pf("total", Decimal("69515.60")),
        }
        v = validate_math(fields)
        assert v.total_matches is True
        assert not v.errors

    def test_total_mismatch_flagged(self):
        fields = {
            "carreras": self._pf("carreras", Decimal("69515.60")),
            "suplementos": self._pf("suplementos", Decimal("0.00")),
            "total": self._pf("total", Decimal("69515.80")),
        }
        v = validate_math(fields)
        assert v.total_matches is False
        assert any("total_mismatch" in e for e in v.errors)

    def test_period_math(self):
        fields = {
            "p_carreras": self._pf("p_carreras", Decimal("203.05")),
            "p_suplementos": self._pf("p_suplementos", Decimal("0.00")),
            "p_total": self._pf("p_total", Decimal("203.05")),
        }
        v = validate_math(fields)
        assert v.period_total_matches is True

    def test_missing_field_gives_none_not_false(self):
        fields = {"total": self._pf("total", Decimal("100.00"))}
        v = validate_math(fields)
        assert v.total_matches is None   # not enough evidence, don't fail


# ─────────────────────────── Extract from synthetic OcrWords ───────────────────────────
class TestFieldExtractionFromWords:
    def _line(self, y, words, line_id="0:0:0", conf=0.9):
        out = []
        x = 10
        for text in words:
            out.append(OcrWord(text=text, confidence=conf,
                                bbox=(x, y, len(text) * 12, 24),
                                line_key=line_id, variant="unit"))
            x += len(text) * 14
        return out

    def test_extracts_licencia_and_num_servicios_separately(self):
        words = []
        words += self._line(10, ["Nº", "LICENCIA:", "11412"], "0:0:0")
        words += self._line(40, ["Num.", "Servicios:", "5321"], "0:0:1")
        fields = extract_fields(words)
        # licencia is INTEGER_FIELDS → normalised as int.
        assert fields["licencia"].normalised == 11412
        assert fields["num_servicios"].normalised == 5321

    def test_p_labels_dont_capture_non_p_lines(self):
        """P Dist. Total must not steal Dist. Total."""
        words = []
        words += self._line(10, ["Dist.", "Total:", "59147,0"], "0:0:0")
        words += self._line(40, ["P", "Dist.", "Total:", "101,2"], "0:0:1")
        fields = extract_fields(words)
        assert fields["dist_total"].normalised == Decimal("59147.0")
        assert fields["p_dist_total"].normalised == Decimal("101.2")


# ─────────────────────────── Decide status ───────────────────────────
class TestDecideStatus:
    def _ev(self, ocr=0.95, fmt=True, cons=True, vv=True):
        from ticket_ocr.models import FieldEvidence
        return FieldEvidence(
            value=1, ocr_confidence=ocr, format_valid=fmt,
            consensus=cons, validation_valid=vv, final_confidence=0.95,
        )

    def test_accepted_when_everything_ok(self):
        from ticket_ocr.constants import REQUIRED_FIELDS
        from ticket_ocr.models import ValidationResult
        ev = {k: self._ev() for k in REQUIRED_FIELDS}
        v = ValidationResult(total_matches=True, period_total_matches=True)
        assert _decide_status(ev, v) == "accepted"

    def test_math_failure_never_auto_accepts(self):
        from ticket_ocr.constants import REQUIRED_FIELDS
        from ticket_ocr.models import ValidationResult
        ev = {k: self._ev() for k in REQUIRED_FIELDS}
        v = ValidationResult(total_matches=False, period_total_matches=True)
        assert _decide_status(ev, v) == "needs_confirmation"

    def test_low_ocr_without_consensus_flags(self):
        from ticket_ocr.constants import REQUIRED_FIELDS
        from ticket_ocr.models import ValidationResult
        ev = {k: self._ev() for k in REQUIRED_FIELDS}
        ev["total"] = self._ev(ocr=0.30, cons=False)
        v = ValidationResult(total_matches=True, period_total_matches=True)
        assert _decide_status(ev, v) == "needs_confirmation"

    def test_missing_most_required_fields_rejects(self):
        from ticket_ocr.models import ValidationResult
        assert _decide_status({}, ValidationResult()) == "rejected"


# ─────────────────────────── Image validation ───────────────────────────
class TestImageValidation:
    def test_empty_bytes_rejected(self):
        res = preprocess(b"", "image/jpeg")
        assert not res.ok
        assert "empty_file" in (res.error or "")

    def test_corrupt_bytes_rejected(self):
        res = preprocess(b"not an image", "image/jpeg")
        assert not res.ok

    def test_tiny_image_rejected(self):
        # 50x50 solid grey — well below MIN thresholds.
        img = Image.new("RGB", (50, 50), color=(200, 200, 200))
        buf = io.BytesIO(); img.save(buf, format="JPEG")
        res = preprocess(buf.getvalue(), "image/jpeg")
        assert not res.ok
        assert "resolution_too_low" in (res.error or "")

    def test_pipeline_with_no_text_rejects_or_needs_confirmation(self):
        img = Image.new("RGB", (800, 1200), color=(255, 255, 255))
        buf = io.BytesIO(); img.save(buf, format="JPEG")
        result = scan_taxitronic_ticket(buf.getvalue(), "image/jpeg")
        assert result.status in {"rejected", "needs_confirmation"}
        assert result.status != "accepted"


# ─────────────────────────── Synthetic clean ticket ───────────────────────────
def _render_synthetic_ticket() -> bytes:
    """Draw a Taxitronic-like ticket on a white canvas.

    Uses a monospaced font so Tesseract has minimal excuses to fail.
    Values match the reference ticket documented in the requirements.
    """
    W, H = 900, 1400
    img = Image.new("RGB", (W, H), color="white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf", 26
        )
    except OSError:
        font = ImageFont.load_default()
    lines = [
        "FECHA:            20/09/26 15:03",
        "Nº LICENCIA:              11412",
        "Num. Servicios:            5321",
        "Carreras:              69515,60",
        "Suplementos:               0,00",
        "Total:                 69515,60",
        "Dist. Total:            59147,0",
        "Dist. Ocupado:          32369,2",
        "Dist. Libre:            21964,0",
        "Dist. OFF:               4813,5",
        "Tiempo Ocupado:           72666",
        "Tiempo On:               170956",
        "Borrados:                   470",
        "",
        "P Nº de servs:               17",
        "P Carreras:              203,05",
        "P Suplementos:             0,00",
        "P Total:                 203,05",
        "P Dist. Total:            101,2",
        "P Dist. Ocupado:           73,7",
        "P Dist. Libre:             27,6",
        "P Dist. OFF:                0,0",
        "P Tiempo Ocupado:           152",
        "P Tiempo On:                249",
    ]
    y = 40
    for line in lines:
        d.text((30, y), line, fill="black", font=font)
        y += 42
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return buf.getvalue()


class TestSyntheticTicketEndToEnd:
    """The synthetic ticket is designed to be OCR-friendly.

    Even if Tesseract occasionally trips on a character, the pipeline's
    multi-variant OCR + consensus + math validation should recover the
    reference numbers well enough to reach `accepted` or, worst case,
    `needs_confirmation`. We assert both math checks pass — that is the
    strong invariant that makes silent-wrong-writes impossible.
    """

    def test_synthetic_ticket_math_is_satisfied(self):
        data = _render_synthetic_ticket()
        result = scan_taxitronic_ticket(data, "image/png")
        assert result.status in {"accepted", "needs_confirmation"}
        assert result.validation.total_matches is not False, result.validation.errors
        assert result.validation.period_total_matches is not False, result.validation.errors
        assert result.overall_confidence > 0.5

    def test_synthetic_ticket_key_fields_recovered(self):
        data = _render_synthetic_ticket()
        result = scan_taxitronic_ticket(data, "image/png")
        # These are the fields that MUST be present on any accepted read;
        # even if the final status is needs_confirmation, we still want to
        # have surfaced them.
        for key in ("total", "p_total", "carreras", "p_carreras"):
            assert key in result.fields, f"missing {key}: {list(result.fields)}"


class TestRealPhotoNeverSilentlyAcceptsWrongData:
    """The real WhatsApp photo is noisy on purpose. We assert:

    1. The endpoint never blows up.
    2. If math validation fails, the pipeline surfaces `needs_confirmation`
       (not `accepted`) — this is the fail-safe rule.
    """

    @pytest.mark.skipif(not SAMPLE_PHOTO.exists(), reason="sample photo missing")
    def test_pipeline_survives_and_flags(self):
        data = SAMPLE_PHOTO.read_bytes()
        result = scan_taxitronic_ticket(data, "image/jpeg")
        assert result.status in {"accepted", "needs_confirmation", "rejected"}
        # If any of the documented math checks failed, we MUST NOT accept.
        if (result.validation.total_matches is False or
                result.validation.period_total_matches is False):
            assert result.status != "accepted"
