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
from .validators import validate_format, validate_math

logger = logging.getLogger(__name__)


# ─────────────────────── Public entry ───────────────────────
def scan_taxitronic_ticket(image_bytes: bytes, mime_type: str,
                           engine: Optional[OcrEngine] = None) -> ScanResult:
    """Full pipeline. Returns a `ScanResult`. Never raises.

    When `engine` is None we honour the `TICKET_OCR_ENGINE` env variable
    (see `ocr_engine.build_engine`). If the primary engine returns no
    tokens (e.g. paddleocr not installed on this host), we transparently
    retry with Tesseract so the endpoint stays useful.
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

    if not merged:
        return _reject("no_fields_recognised", warnings=warnings)

    # 5. Format validation ----------------------------------------------------
    format_ok: dict[str, bool] = {}
    for key, field in merged.items():
        ok, notes = validate_format(field)
        format_ok[key] = ok and field.format_valid
        field.notes.extend(notes)

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
        },
    )
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
