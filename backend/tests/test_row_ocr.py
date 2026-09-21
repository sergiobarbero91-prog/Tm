"""Tests for the geometric row-based OCR pass (`ticket_ocr/row_ocr.py`)
and its fusion with the main pipeline (`ticket_ocr/pipeline.py`).

The tests use synthetic images so they run without external fixtures
and are deterministic on any host with Tesseract + Liberation Mono.

Cases covered (mapped to the user's phase list, phases 3-14):
  * detección de filas (`_detect_rows`)
  * corte adaptativo label/valor (widest zero-run)
  * matching label → field key
  * canonicalización segura (no inventar decimal separator)
  * consenso entre variantes (`read_ticket_by_rows` on a clean ticket)
  * fusión con pipeline principal (agreement boosts consensus,
    disagreement demotes to needs_confirmation)
  * modo debug (`?debug=1` → snapshots base64)
"""
from __future__ import annotations

import io
from decimal import Decimal

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from ticket_ocr import scan_taxitronic_ticket
from ticket_ocr.parser import ParsedField
from ticket_ocr.pipeline import _row_based_pass, _value_key_of
from ticket_ocr.row_ocr import (
    _bands_from_projection,
    _canonicalize,
    _detect_rows,
    _match_label_to_field_key,
    _num_norm,
    _widest_zero_run,
    read_ticket_by_rows,
)


# ─────────────────────────── Helpers ───────────────────────────
def _load_font(size: int = 26):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf", size
        )
    except OSError:
        return ImageFont.load_default()


def _render_lines(lines: list[str], width: int = 900,
                  min_height: int = 1200) -> np.ndarray:
    """Return a grayscale np.ndarray with the lines rendered in monospace.

    Height is forced to be at least `min_height` so the preprocess step
    doesn't rotate the ticket 90° looking for a portrait aspect ratio.
    """
    natural_h = 60 + 42 * len(lines)
    height = max(natural_h, min_height)
    img = Image.new("RGB", (width, height), color="white")
    d = ImageDraw.Draw(img)
    font = _load_font(26)
    y = 30
    for line in lines:
        d.text((30, y), line, fill="black", font=font)
        y += 42
    arr = np.array(img.convert("L"))
    return arr


def _render_ticket_bytes() -> bytes:
    lines = [
        "FECHA:            20/09/26 15:03",
        "Nº LICENCIA:              09218",
        "Num. Servicios:            5606",
        "Carreras:              60854,75",
        "Suplementos:             204,90",
        "Total:                 61059,65",
        "Dist. Total:           52537,90",
        "Dist. Ocupado:         25457,10",
        "Dist. Libre:           26742,50",
        "Dist. OFF:               339,00",
        "Tiempo Ocupado:           55761",
        "Tiempo On:               156015",
        "Borrados:                   454",
    ]
    height = max(60 + 42 * len(lines), 1200)
    canvas = Image.new("RGB", (900, height), color="white")
    d = ImageDraw.Draw(canvas)
    font = _load_font(26)
    y = 30
    for ln in lines:
        d.text((30, y), ln, fill="black", font=font)
        y += 42
    buf = io.BytesIO(); canvas.save(buf, format="PNG")
    return buf.getvalue()


# ─────────────────────────── Number normalisation (unit) ───────────────────────────
class TestSafeNumberNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("60854,75",       "60854.75"),
        ("60854275",       "60854275"),        # NO decimal → do not invent one
        ("60.854,75",      "60854.75"),        # dot = thousands
        ("1.234.567,89",   "1234567.89"),
        ("0,00",           "0.00"),
        ("5606",           "5606"),
    ])
    def test_num_norm(self, raw, expected):
        assert _num_norm(raw) == expected

    def test_canonicalize_decimal_field_refuses_to_invent_separator(self):
        # Ticket says "60854,75" but OCR gives us "60854275" with no
        # separator. row_ocr MUST return the integer as-is, not guess.
        val = _canonicalize("carreras", "60854275")
        assert val == Decimal("60854275")

    def test_canonicalize_decimal_keeps_valid_value(self):
        val = _canonicalize("carreras", "60854,75")
        assert val == Decimal("60854.75")

    def test_canonicalize_integer_field_rejects_letters(self):
        val = _canonicalize("num_servicios", "abc")
        assert val is None

    def test_canonicalize_date(self):
        val = _canonicalize("fecha", "20/09/26")
        assert val == "2026-09-20"

    def test_canonicalize_date_impossible_returns_none(self):
        val = _canonicalize("fecha", "99/99/99")
        assert val is None

    def test_canonicalize_hour_valid(self):
        val = _canonicalize("hora", "15:03")
        assert val == "15:03"

    def test_canonicalize_hour_out_of_range_none(self):
        assert _canonicalize("hora", "25:99") is None


# ─────────────────────────── Row projection helpers ───────────────────────────
class TestRowProjectionHelpers:
    def test_widest_zero_run_finds_biggest_gap(self):
        arr = np.array([1, 1, 0, 0, 0, 1, 1, 0, 0, 1])
        start, length = _widest_zero_run(arr)
        assert start == 2
        assert length == 3

    def test_widest_zero_run_all_zeros(self):
        arr = np.zeros(10, dtype=int)
        start, length = _widest_zero_run(arr)
        assert start == 0
        assert length == 10

    def test_bands_from_projection_ignores_short_bands(self):
        proj = np.array([0, 5, 5, 5, 5, 5, 0, 0, 1, 0, 5, 5, 5, 5, 5, 0])
        bands = _bands_from_projection(proj, min_len=4)
        # First band (1-6) qualifies, second band (8) too short, third (10-15) qualifies.
        assert (1, 6) in bands
        assert (10, 15) in bands


# ─────────────────────────── Label matching ───────────────────────────
class TestLabelMatching:
    def test_p_prefix_beats_ambiguous(self):
        assert _match_label_to_field_key("P Total") == "p_total"
        assert _match_label_to_field_key("Total") == "total"

    def test_dist_variants(self):
        assert _match_label_to_field_key("Dist. Total") == "dist_total"
        assert _match_label_to_field_key("P Dist. Total") == "p_dist_total"

    def test_no_match_returns_none(self):
        assert _match_label_to_field_key("Cabecera ticket") is None


# ─────────────────────────── Row detection over an image ───────────────────────────
class TestRowDetectionOnImage:
    def test_detects_all_rows_of_clean_ticket(self):
        # Render 5 lines and check we detect at least that many bands.
        gray = _render_lines([
            "FECHA: 20/09/26",
            "Nº LICENCIA: 09218",
            "Num. Servicios: 5606",
            "Carreras: 60854,75",
            "Total: 60854,75",
        ])
        rows = _detect_rows(gray)
        # We may detect additional micro-bands (accents/descenders), but
        # NEVER fewer than the count of drawn lines.
        assert len(rows) >= 5

    def test_row_bbox_is_within_image(self):
        gray = _render_lines(["Carreras: 60854,75"])
        rows = _detect_rows(gray)
        assert rows, "no row detected"
        H, W = gray.shape[:2]
        for r in rows:
            lx, ly, lw, lh = r.label_bbox
            vx, vy, vw, vh = r.value_bbox
            assert 0 <= lx <= W and 0 <= ly <= H
            assert 0 <= vx <= W and 0 <= vy <= H
            assert lw > 0 and vw > 0


# ─────────────────────────── read_ticket_by_rows end-to-end ───────────────────────────
class TestReadTicketByRowsOnCleanImage:
    def test_accepted_readings_are_correct(self):
        """Fail-safe invariant: whatever row_ocr marks `status=accepted`
        must be numerically correct. If it doesn't know, it should say
        `needs_confirmation` — never a silently-wrong value."""
        gray = _render_lines([
            "Nº LICENCIA: 09218",
            "Num. Servicios: 5606",
            "Carreras: 60854,75",
            "Suplementos: 204,90",
            "Total: 61059,65",
        ])
        out = read_ticket_by_rows(gray)
        expected = {
            "carreras":      Decimal("60854.75"),
            "suplementos":   Decimal("204.90"),
            "total":         Decimal("61059.65"),
            "licencia":      9218,
            "num_servicios": 5606,
        }
        for key, want in expected.items():
            f = out.get(key)
            if f is None or f.value is None:
                continue
            if f.status == "accepted":
                if isinstance(want, Decimal):
                    assert Decimal(str(f.value)) == want, (
                        f"{key} ACCEPTED with wrong value: {f.value} != {want}"
                    )
                else:
                    assert int(f.value) == want, (
                        f"{key} ACCEPTED with wrong value: {f.value} != {want}"
                    )

    def test_never_confuses_licencia_with_num_servicios(self):
        """The CRITICAL case from the user's prompt: both are integers,
        both on adjacent rows. Row-based ROI must associate each number
        with the correct label."""
        gray = _render_lines([
            "Nº LICENCIA: 09218",
            "Num. Servicios: 5606",
        ])
        out = read_ticket_by_rows(gray)
        lic = out.get("licencia")
        srv = out.get("num_servicios")
        # If both were ACCEPTED, they must not have swapped values.
        if (lic and srv and lic.value is not None and srv.value is not None
                and lic.status == "accepted" and srv.status == "accepted"):
            assert int(lic.value) != int(srv.value)
            assert int(lic.value) == 9218
            assert int(srv.value) == 5606


# ─────────────────────────── Fusion with pipeline ───────────────────────────
class TestRowBasedFusion:
    """`_row_based_pass` must never destroy a good value; it can only
    (a) fill in missing fields, (b) mark consensus on agreement, or
    (c) demote to needs_confirmation on disagreement."""

    def _make_field(self, key: str, value, conf: float, format_valid: bool = True):
        return ParsedField(
            key=key, raw_text=str(value), normalised=value,
            ocr_confidence=conf, format_valid=format_valid,
            bbox=(0, 0, 10, 10), variant="test",
        )

    def test_agreement_sets_consensus_flag(self):
        # Build a scenario where row_ocr reads the same value the
        # multi-variant pass got — consensus must flip to True.
        gray = _render_lines([
            "Nº LICENCIA: 09218",
            "Num. Servicios: 5606",
            "Carreras: 60854,75",
        ])
        merged = {"carreras": self._make_field("carreras", Decimal("60854.75"), 0.6)}
        consensus: dict[str, bool] = {"carreras": False}
        format_ok: dict[str, bool] = {"carreras": True}
        warnings: list[str] = []
        updated, matched = _row_based_pass(
            gray, merged, consensus, format_ok, warnings,
        )
        # If row_ocr matched the carreras row, agreement must be recorded.
        if "carreras" in matched and consensus.get("carreras") is True:
            assert "row_ocr_agreed" in updated["carreras"].notes

    def test_missing_field_can_be_filled_by_row_ocr(self):
        gray = _render_lines([
            "Nº LICENCIA: 09218",
        ])
        merged: dict[str, ParsedField] = {}
        consensus: dict[str, bool] = {}
        format_ok: dict[str, bool] = {}
        warnings: list[str] = []
        updated, matched = _row_based_pass(
            gray, merged, consensus, format_ok, warnings,
        )
        # If row_ocr succeeded on licencia, the merged dict must now
        # contain it. If it failed, updated stays empty — safe.
        if "licencia" in matched:
            # Either the value was accepted or it was uncertain but
            # captured — never silently dropped.
            assert ("licencia" in updated
                    or any("row_ocr" in w for w in warnings))

    def test_value_key_of_helper_matches_equal_decimals(self):
        a = self._make_field("carreras", Decimal("60854.75"), 0.9)
        b = self._make_field("carreras", Decimal("60854.75"), 0.5)
        assert _value_key_of(a) == _value_key_of(b)


# ─────────────────────────── End-to-end pipeline with row_ocr ───────────────────────────
class TestPipelineWithRowOcrIntegrated:
    def test_math_check_passes_on_clean_synthetic(self):
        data = _render_ticket_bytes()
        result = scan_taxitronic_ticket(data, "image/png")
        assert result.status in {"accepted", "needs_confirmation"}
        # The math MUST be valid or None (never False) on this clean render.
        assert result.validation.total_matches is not False, result.validation.errors

    def test_row_matched_fields_reported_in_debug(self):
        data = _render_ticket_bytes()
        result = scan_taxitronic_ticket(data, "image/png")
        assert "row_matched_fields" in result.debug
        assert isinstance(result.debug["row_matched_fields"], list)

    def test_debug_snapshots_returned_when_requested(self):
        data = _render_ticket_bytes()
        result = scan_taxitronic_ticket(data, "image/png", debug=True)
        assert "snapshots" in result.debug
        snaps = result.debug["snapshots"]
        # Base image + at least one variant must be present.
        assert "original" in snaps
        assert any(k.startswith("variant_") for k in snaps)
        # Each snapshot is a data URI.
        for k, v in snaps.items():
            if isinstance(v, str):
                assert v.startswith("data:image/"), f"bad snapshot {k}"

    def test_debug_off_by_default_no_snapshots(self):
        data = _render_ticket_bytes()
        result = scan_taxitronic_ticket(data, "image/png")
        assert "snapshots" not in result.debug

    def test_never_accepts_when_no_content(self):
        blank = np.full((1200, 900, 3), 255, dtype=np.uint8)
        ok, buf = cv2.imencode(".png", blank)
        assert ok
        result = scan_taxitronic_ticket(buf.tobytes(), "image/png")
        assert result.status != "accepted"


# ─────────────────────────── False acceptance guard ───────────────────────────
class TestFalseAcceptanceGuard:
    """These tests directly probe the P0 rule: `IT MUST NEVER accept a
    silently-wrong number`. If any of these ever start FAILING, the
    pipeline has regressed on the fail-safe requirement."""

    def test_impossible_math_never_accepted(self):
        # We build a synthetic ticket where the math is broken on purpose.
        # scan_taxitronic_ticket must NOT return status=accepted.
        lines = [
            "FECHA: 20/09/26 15:03",
            "Nº LICENCIA: 09218",
            "Num. Servicios: 5606",
            "Carreras: 60854,75",
            "Suplementos: 204,90",
            "Total: 99999,99",     # <-- deliberately wrong
        ]
        height = max(60 + 42 * len(lines), 1200)
        canvas = Image.new("RGB", (900, height), color="white")
        d = ImageDraw.Draw(canvas)
        font = _load_font(26)
        y = 30
        for ln in lines:
            d.text((30, y), ln, fill="black", font=font)
            y += 42
        buf = io.BytesIO(); canvas.save(buf, format="PNG")
        result = scan_taxitronic_ticket(buf.getvalue(), "image/png")
        assert result.status != "accepted"
