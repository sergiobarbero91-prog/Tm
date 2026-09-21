"""Orchestrator — glue that turns image bytes into a ScanResult.

Flow (matches the requirements doc):
    validate → preprocess → multi-variant OCR → line reconstruction →
    field extraction per variant → cross-variant consensus →
    format validation → math validation → per-field second pass on
    disagreements → confidence scoring → final status.
"""
from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal
from typing import Any, Optional

from .confidence import field_confidence, overall_confidence
from .constants import LOW_OCR_CONFIDENCE, REQUIRED_FIELDS
from .models import FieldEvidence, ScanResult, ValidationResult
from .ocr_engine import (
    OcrEngine, TesseractEngine, build_engine,
    read_all_variants, read_region_numeric,
)
from .parser import ParsedField, extract_fields
from .preprocess import PreprocessResult, crop_region, preprocess
from .region_ocr import structural_pass
from .row_ocr import RowRoi, _detect_rows, _match_label_to_field_key, _read_value_roi
from .validators import validate_format, validate_math

# Below this raw OCR confidence, we refuse to display the value at all —
# a plausible-looking-but-wrong number is more dangerous than "not detected".
HARD_MIN_OCR_CONFIDENCE = 0.40

logger = logging.getLogger(__name__)


# ─────────────────────── Public entry ───────────────────────
def scan_taxitronic_ticket(image_bytes: bytes, mime_type: str,
                           engine: Optional[OcrEngine] = None,
                           debug: bool = False) -> ScanResult:
    """Full pipeline. Returns a `ScanResult`. Never raises.

    When `engine` is None we honour the `TICKET_OCR_ENGINE` env variable
    (see `ocr_engine.build_engine`). If the primary engine returns no
    tokens (e.g. paddleocr not installed on this host), we transparently
    retry with Tesseract so the endpoint stays useful.

    When `debug=True`, `result.debug["snapshots"]` is populated with
    base64-encoded images of the deskewed ticket, each preprocess variant
    and the detected row bands with their label/value ROIs highlighted.
    """
    primary = engine or build_engine()

    # 1. Preprocess -----------------------------------------------------------
    pre = preprocess(image_bytes, mime_type)
    if not pre.ok:
        return _reject(pre.error or "preprocess_failed", warnings=pre.warnings or [])

    warnings = list(pre.warnings)

    # 2. Multi-variant OCR ---------------------------------------------------
    per_variant_words = read_all_variants(primary, pre.variants)
    all_words = [w for words in per_variant_words.values() for w in words]
    used_engine = primary.name
    if not all_words and not isinstance(primary, TesseractEngine):
        # Fallback: never let a missing optional engine kill the request.
        warnings.append(f"primary_engine_returned_no_text:{primary.name}_falling_back_to_tesseract")
        fallback = TesseractEngine()
        per_variant_words = read_all_variants(fallback, pre.variants)
        all_words = [w for words in per_variant_words.values() for w in words]
        used_engine = fallback.name
    if not all_words:
        return _reject("no_text_detected", warnings=warnings)

    # 3. Extract fields per variant ------------------------------------------
    per_variant_fields: dict[str, dict[str, ParsedField]] = {
        name: extract_fields(words) for name, words in per_variant_words.items()
    }

    # 4. Consensus per field --------------------------------------------------
    merged: dict[str, ParsedField] = {}
    consensus_flags: dict[str, bool] = {}
    for key in _all_keys(per_variant_fields):
        chosen, has_consensus = _consensus_for(key, per_variant_fields)
        if chosen is not None:
            merged[key] = chosen
            consensus_flags[key] = has_consensus

    # NOTE: we DO NOT bail out here even if `merged` is empty. On some
    # photos the multi-variant grid returns zero because a single PSM
    # can't cluster the rows correctly. The row-based pass below can
    # still recover the fields geometrically. Only if BOTH strategies
    # come back empty at the end do we return `rejected`.

    # 5. Format validation ----------------------------------------------------
    format_ok: dict[str, bool] = {}
    for key, field in merged.items():
        ok, notes = validate_format(field)
        format_ok[key] = ok and field.format_valid
        field.notes.extend(notes)

    # 5b. Structural pass: for missing or low-confidence fields, locate the
    # label anchor and re-OCR only the value strip. Dramatic win on noisy
    # photos where the multi-variant grid missed a row.
    structural_gray = pre.variants.get("clahe")
    if structural_gray is None:
        structural_gray = pre.variants.get("gray")
    if structural_gray is not None:
        try:
            merged = structural_pass(primary, structural_gray, merged)
            # Re-run format validation for anything the structural pass added.
            for key, field in merged.items():
                if key not in format_ok:
                    ok, notes = validate_format(field)
                    format_ok[key] = ok and field.format_valid
                    field.notes.extend(notes)
                    consensus_flags.setdefault(key, False)
        except Exception:  # noqa: BLE001
            logger.exception("structural_pass failed — continuing with base result")

    # 5c. ROW-BASED GEOMETRIC PASS ─────────────────────────────────────────
    # Detect rows via y-projection, split each into label/value ROIs and
    # OCR each value ROI in isolation with field-type-specific whitelists +
    # multi-variant consensus. This is the "geometry first" strategy the
    # user asked for: it never invents a value — a field with weak
    # evidence stays `needs_confirmation` and the merged result is kept
    # only when row_ocr can safely improve on it.
    matched_rows: dict[str, RowRoi] = {}
    if structural_gray is not None:
        try:
            merged, matched_rows = _row_based_pass(
                structural_gray, merged, consensus_flags, format_ok, warnings,
            )
        except Exception:  # noqa: BLE001
            logger.exception("row_based_pass failed — continuing")

    # After ALL extraction strategies have run, decide if anything is worth
    # returning. Only rejecting here means we give geometry a chance too.
    if not merged:
        return _reject("no_fields_recognised", warnings=warnings)

    # 6. Math validation ------------------------------------------------------
    validation = validate_math(merged)

    # 7. Second-pass re-read on failing money fields --------------------------
    if validation.total_matches is False:
        _second_pass_numeric(merged, ["carreras", "suplementos", "total"], pre, primary, warnings)
        validation = validate_math(merged)
    if validation.period_total_matches is False:
        _second_pass_numeric(merged, ["p_carreras", "p_suplementos", "p_total"], pre, primary, warnings)
        validation = validate_math(merged)

    # Refresh format flags after second pass.
    for key, field in merged.items():
        ok, notes = validate_format(field)
        format_ok[key] = ok and field.format_valid
        # `notes` was already extended above; avoid duplicating.

    # 8. Build evidence + confidence -----------------------------------------
    evidences: dict[str, FieldEvidence] = {}
    for key, field in merged.items():
        # Confidence gating: if the OCR is dangerously low we hide the value
        # entirely so the driver has to type it in — a wrong-looking-right
        # value is worse than "not detected".
        if field.ocr_confidence < HARD_MIN_OCR_CONFIDENCE:
            warnings.append(f"field_dropped_low_ocr:{key}:{field.ocr_confidence:.2f}")
            continue
        validation_valid = _field_math_valid(key, validation)
        ev = FieldEvidence(
            value=_serialisable(field.normalised),
            raw_text=field.raw_text,
            ocr_confidence=round(field.ocr_confidence, 3),
            format_valid=format_ok.get(key, False),
            consensus=consensus_flags.get(key, False),
            validation_valid=validation_valid,
            notes=list(field.notes),
        )
        ev.final_confidence = field_confidence(ev)
        evidences[key] = ev

    overall = overall_confidence(evidences)

    # 9. Decide final status --------------------------------------------------
    status = _decide_status(evidences, validation)

    # 10. Assemble the response shape ----------------------------------------
    result = ScanResult(
        status=status,
        overall_confidence=overall,
        fields=evidences,
        validation=validation,
        warnings=warnings,
        debug={
            "engine": used_engine,
            "blur_score": pre.blur_score,
            "variants_used": list(pre.variants.keys()),
            "words_total": len(all_words),
            "row_matched_fields": sorted(matched_rows.keys()),
        },
    )
    if debug:
        try:
            from .debug import build_snapshots
            result.debug["snapshots"] = build_snapshots(
                pre.original_bgr, pre.variants, matched_rows,
            )
        except Exception:  # noqa: BLE001
            logger.exception("debug snapshots failed")
    _fill_public_sections(result, merged)
    return result


# ─────────────────────── Helpers ───────────────────────
def _all_keys(per_variant: dict[str, dict[str, ParsedField]]) -> list[str]:
    keys: list[str] = []
    for fields in per_variant.values():
        for k in fields:
            if k not in keys:
                keys.append(k)
    return keys


def _consensus_for(key: str, per_variant: dict[str, dict[str, ParsedField]]
                   ) -> tuple[Optional[ParsedField], bool]:
    """Pick the winning ParsedField for `key` across variants + consensus flag.

    Strategy:
      * Group by normalised value (stringified for hashing).
      * Prefer the largest group; ties broken by highest OCR confidence.
      * `consensus=True` if 2+ variants agreed on the same value.
    """
    candidates: list[ParsedField] = []
    for fields in per_variant.values():
        if key in fields and fields[key].format_valid:
            candidates.append(fields[key])
    # Fall back to invalid-format candidates if nothing else.
    if not candidates:
        for fields in per_variant.values():
            if key in fields:
                candidates.append(fields[key])
    if not candidates:
        return None, False

    def value_key(p: ParsedField) -> str:
        return f"{p.normalised!r}" if p.normalised is not None else f"raw:{p.raw_text}"

    counts = Counter(value_key(c) for c in candidates)
    winner_value, winner_count = counts.most_common(1)[0]
    winner_pool = [c for c in candidates if value_key(c) == winner_value]
    winner_pool.sort(key=lambda c: c.ocr_confidence, reverse=True)
    return winner_pool[0], winner_count >= 2


# ─────────────────────── Row-based geometric pass ───────────────────────
# Confidence at which row_ocr is allowed to REPLACE an existing field
# accepted by the multi-variant pass. Below this we only use row_ocr to
# fill in missing fields or to add a consensus/needs_confirmation flag.
_ROW_STRONG_ACCEPT = 0.70


def _row_based_pass(gray, merged: dict[str, ParsedField],
                    consensus_flags: dict[str, bool],
                    format_ok: dict[str, bool],
                    warnings: list[str]
                    ) -> tuple[dict[str, ParsedField], dict[str, "RowRoi"]]:
    """Run row_ocr and fuse its readings with the existing merged dict.

    Fusion rules (fail-safe, never invents data):
      * ROW ACCEPTED and there is NO existing field         → add it.
      * ROW ACCEPTED and matches the existing field         → mark consensus.
      * ROW ACCEPTED and disagrees with existing field      →
          - if row_ocr confidence >= 0.70 AND >= existing OCR conf ⇒ replace
            and record `row_ocr_overrode:<key>` in warnings for the audit
            trail. Otherwise ⇒ demote the existing field's format_valid to
            False (we're not sure any more) and note the disagreement.
      * ROW NEEDS_CONFIRMATION and existing field is missing → add it as
        best-effort with `format_valid=False` to force UI review.
      * ROW REJECTED                                        → ignore.
    """
    rows = _detect_rows(gray)
    matched: dict[str, "RowRoi"] = {}
    for r in rows:
        key = _match_label_to_field_key(r.label_text)
        if key and key not in matched:
            matched[key] = r
    if not matched:
        return merged, matched

    updated = dict(merged)
    for key, roi in matched.items():
        reading = _read_value_roi(gray, roi, key)
        if reading.status == "rejected":
            continue
        prev = updated.get(key)
        # Convert row_ocr FieldReading → ParsedField shape for merging.
        row_field = ParsedField(
            key=key,
            raw_text=reading.raw_text,
            normalised=reading.value,
            ocr_confidence=max(0.0, min(1.0, reading.confidence)),
            format_valid=(reading.status == "accepted"
                          and reading.value is not None),
            bbox=(roi.value_bbox[0], roi.value_bbox[1],
                  roi.value_bbox[2], roi.value_bbox[3]),
            variant="row_ocr",
            notes=list(reading.notes) + [f"row_ocr:{reading.status}"],
        )
        if prev is None:
            # No previous read — take the row reading. If it's only
            # `needs_confirmation` we still store it but flag it so the
            # `_decide_status` step demands review.
            updated[key] = row_field
            consensus_flags[key] = False
            format_ok[key] = row_field.format_valid
            if reading.status == "needs_confirmation":
                warnings.append(f"row_ocr_added_uncertain:{key}")
            else:
                warnings.append(f"row_ocr_added:{key}")
            continue

        # There is a previous reading. Do they agree?
        prev_value_key = _value_key_of(prev)
        new_value_key = _value_key_of(row_field)
        if prev_value_key == new_value_key and prev_value_key != "":
            # AGREEMENT — strong signal, boost consensus + keep the more
            # confident text.
            consensus_flags[key] = True
            prev.notes.append("row_ocr_agreed")
            if row_field.ocr_confidence > prev.ocr_confidence:
                prev.ocr_confidence = row_field.ocr_confidence
            continue

        # DISAGREEMENT — the risky path. Only replace if row_ocr is
        # strongly confident AND has stricter format guarantees.
        row_strong = (reading.status == "accepted"
                      and row_field.ocr_confidence >= _ROW_STRONG_ACCEPT
                      and row_field.format_valid)
        prev_weak = (not prev.format_valid) or (prev.ocr_confidence < 0.55)
        if row_strong and (prev_weak or row_field.ocr_confidence >= prev.ocr_confidence):
            warnings.append(
                f"row_ocr_overrode:{key}:{prev.normalised}->{row_field.normalised}"
            )
            row_field.notes.append("row_ocr_replaced_multivariant")
            updated[key] = row_field
            format_ok[key] = row_field.format_valid
            consensus_flags[key] = False
        else:
            # Not confident enough to override — demote to needs_confirmation.
            warnings.append(f"row_ocr_disagrees:{key}")
            prev.notes.append(
                f"row_ocr_alt:{row_field.normalised}({row_field.ocr_confidence:.2f})"
            )
            format_ok[key] = False
            consensus_flags[key] = False
    return updated, matched


def _value_key_of(f: ParsedField) -> str:
    if f.normalised is None:
        return f"raw:{(f.raw_text or '').strip()}"
    return f"{f.normalised!r}"


def _second_pass_numeric(merged: dict[str, ParsedField], keys: list[str],
                         pre: PreprocessResult, engine: OcrEngine,
                         warnings: list[str]) -> None:
    """Re-OCR just the bbox of each key using a numeric-only whitelist.

    Only overrides the current value when the new reading is a valid
    Decimal AND its OCR confidence beats the previous one.
    """
    gray = pre.variants.get("clahe")
    if gray is None:
        gray = pre.variants.get("gray")
    if gray is None:
        return
    from .parser import normalise_value
    for key in keys:
        f = merged.get(key)
        if not f or not f.bbox:
            continue
        crop = crop_region(gray, f.bbox, pad=8)
        out = read_region_numeric(engine, crop)
        if not out:
            continue
        text, conf = out
        norm, valid, notes = normalise_value(key, text)
        if not valid or norm is None:
            continue
        if conf < f.ocr_confidence:  # don't downgrade
            continue
        if norm == f.normalised:
            f.ocr_confidence = max(f.ocr_confidence, conf)
            continue
        warnings.append(f"second_pass_updated:{key}:{f.normalised}->{norm}")
        f.raw_text = text
        f.normalised = norm
        f.ocr_confidence = conf
        f.notes.append("second_pass_replaced")


def _field_math_valid(key: str, validation: ValidationResult) -> bool:
    if key in {"carreras", "suplementos", "total"}:
        return validation.total_matches is not False
    if key in {"p_carreras", "p_suplementos", "p_total"}:
        return validation.period_total_matches is not False
    return True


def _decide_status(evidences: dict[str, FieldEvidence],
                   validation: ValidationResult):
    """Pick accepted / needs_confirmation / rejected.

    Rules (fail-safe):
      * Missing required field ⇒ rejected if we lack more than half of them,
        else needs_confirmation.
      * Any documented math check failed ⇒ needs_confirmation.
      * Any required field with low OCR confidence and no consensus
        ⇒ needs_confirmation.
      * Otherwise ⇒ accepted.
    """
    present_required = [k for k in REQUIRED_FIELDS if k in evidences]
    missing_required = [k for k in REQUIRED_FIELDS if k not in evidences]

    if len(missing_required) > len(REQUIRED_FIELDS) // 2:
        return "rejected"

    # Math failures — never auto-accept.
    if validation.total_matches is False or validation.period_total_matches is False:
        return "needs_confirmation"

    if missing_required:
        return "needs_confirmation"

    for key in present_required:
        ev = evidences[key]
        low_ocr = ev.ocr_confidence * 100.0 < LOW_OCR_CONFIDENCE
        if (not ev.format_valid) or (low_ocr and not ev.consensus):
            return "needs_confirmation"

    return "accepted"


def _serialisable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)   # JSON-friendly; Decimal precision preserved internally.
    return v


def _fill_public_sections(result: ScanResult, merged: dict[str, ParsedField]) -> None:
    """Populate the ergonomic top-level dicts (ticket / totals / period / …)."""
    fecha = merged.get("fecha")
    if fecha and isinstance(fecha.normalised, dict):
        result.ticket["date"] = fecha.normalised.get("date")
        result.ticket["time"] = fecha.normalised.get("time")
    lic = merged.get("licencia")
    if lic and lic.normalised is not None:
        result.ticket["license"] = str(lic.normalised)

    def num(key: str):
        f = merged.get(key)
        return _serialisable(f.normalised) if f and f.normalised is not None else None

    result.totals = {
        "services": num("num_servicios"),
        "careers": num("carreras"),
        "supplements": num("suplementos"),
        "total": num("total"),
    }
    result.distance = {
        "total_raw": num("dist_total"),
        "occupied_raw": num("dist_ocupado"),
        "free_raw": num("dist_libre"),
        "off_raw": num("dist_off"),
    }
    result.time = {
        "occupied_raw": num("tiempo_ocupado"),
        "on_raw": num("tiempo_on"),
    }
    result.deleted = num("borrados")
    result.period = {
        "services": num("p_num_servicios"),
        "careers": num("p_carreras"),
        "supplements": num("p_suplementos"),
        "total": num("p_total"),
        "distance_total_raw": num("p_dist_total"),
        "distance_occupied_raw": num("p_dist_ocupado"),
        "distance_free_raw": num("p_dist_libre"),
        "distance_off_raw": num("p_dist_off"),
        "time_occupied_raw": num("p_tiempo_ocupado"),
        "time_on_raw": num("p_tiempo_on"),
    }


def _reject(reason: str, warnings: list[str]) -> ScanResult:
    return ScanResult(
        status="rejected",
        overall_confidence=0.0,
        fields={},
        validation=ValidationResult(),
        warnings=warnings + [reason],
    )
