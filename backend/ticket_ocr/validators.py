"""Field-level format validation + inter-field mathematical validation.

Design rule: a validator that FAILS invalidates the field's `format_valid`
or the pipeline's `validation` block, but never mutates the value. The
pipeline uses those flags to decide the final status.

We deliberately restrict math checks to relationships that are documented
and inequivocal for Taxitronic:
    Carreras + Suplementos = Total
    P Carreras + P Suplementos = P Total

Distance and Time totalizers depend on the specific firmware & unit; we
keep them as RAW and do NOT invent formulas.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from .models import ValidationResult
from .parser import ParsedField


# ─────────────────────── Field format checks ───────────────────────
def validate_format(field: ParsedField) -> tuple[bool, list[str]]:
    """Extra format checks that go beyond the parser's built-in validity."""
    if field.normalised is None:
        return False, ["value_missing"]
    key = field.key
    v = field.normalised
    notes: list[str] = []

    if key == "licencia":
        s = str(v)
        if not s.isdigit():
            return False, ["licencia_not_numeric"]
        if not (3 <= len(s) <= 7):
            notes.append(f"licencia_unusual_length_{len(s)}")

    if key == "fecha":
        # v is dict {date, time?}
        if not isinstance(v, dict) or "date" not in v:
            return False, ["fecha_missing_date"]
        try:
            date.fromisoformat(v["date"])
        except (TypeError, ValueError):
            return False, ["fecha_iso_invalid"]

    if key in {"num_servicios", "p_num_servicios", "borrados",
               "tiempo_ocupado", "tiempo_on", "p_tiempo_ocupado", "p_tiempo_on"}:
        if not isinstance(v, int) or v < 0:
            return False, [f"{key}_must_be_positive_int"]

    if key in {"carreras", "suplementos", "total",
               "p_carreras", "p_suplementos", "p_total",
               "dist_total", "dist_ocupado", "dist_libre", "dist_off",
               "p_dist_total", "p_dist_ocupado", "p_dist_libre", "p_dist_off"}:
        if not isinstance(v, Decimal):
            return False, [f"{key}_must_be_decimal"]
        if v < 0:
            return False, [f"{key}_negative"]

    return True, notes


# ─────────────────────── Cross-field math ───────────────────────
_EUR_TOLERANCE = Decimal("0.02")   # 2 cents — thermal reprint can lose a decimal


def _sum_matches(a: Optional[Decimal], b: Optional[Decimal], c: Optional[Decimal]) -> Optional[bool]:
    """Return True if a + b == c within tolerance, None if any operand missing."""
    if a is None or b is None or c is None:
        return None
    return abs((a + b) - c) <= _EUR_TOLERANCE


def validate_math(fields: dict[str, ParsedField]) -> ValidationResult:
    """Run the documented cross-field checks."""
    def num(key: str) -> Optional[Decimal]:
        f = fields.get(key)
        return f.normalised if f and isinstance(f.normalised, Decimal) else None

    total_ok = _sum_matches(num("carreras"), num("suplementos"), num("total"))
    period_ok = _sum_matches(num("p_carreras"), num("p_suplementos"), num("p_total"))

    errors: list[str] = []
    if total_ok is False:
        errors.append("total_mismatch: carreras + suplementos != total")
    if period_ok is False:
        errors.append("period_total_mismatch: p_carreras + p_suplementos != p_total")

    return ValidationResult(
        total_matches=total_ok,
        period_total_matches=period_ok,
        distance_validated=False,     # pending Taxitronic unit documentation
        time_validated=False,         # pending Taxitronic unit documentation
        errors=errors,
    )
