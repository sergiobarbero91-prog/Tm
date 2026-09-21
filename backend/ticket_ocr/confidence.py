"""Confidence scoring.

For each field we combine four signals into a single 0..1 number:

    final = 0.40 * ocr_confidence
          + 0.20 * format_valid
          + 0.25 * consensus            (multiple variants agreed)
          + 0.15 * validation_valid     (math / cross-field ok)

Design choice: weights sum to 1 and formula is fully documented so the
threshold behaviour is auditable. Tweaking a weight is trivial.
"""
from __future__ import annotations

from .models import FieldEvidence


W_OCR = 0.40
W_FORMAT = 0.20
W_CONSENSUS = 0.25
W_VALIDATION = 0.15


def field_confidence(evidence: FieldEvidence) -> float:
    return round(
        W_OCR * evidence.ocr_confidence
        + W_FORMAT * (1.0 if evidence.format_valid else 0.0)
        + W_CONSENSUS * (1.0 if evidence.consensus else 0.0)
        + W_VALIDATION * (1.0 if evidence.validation_valid else 0.0),
        4,
    )


def overall_confidence(evidences: dict[str, FieldEvidence]) -> float:
    """Weighted mean, giving REQUIRED fields double weight."""
    from .constants import REQUIRED_FIELDS
    total_weight = 0.0
    accum = 0.0
    for key, ev in evidences.items():
        w = 2.0 if key in REQUIRED_FIELDS else 1.0
        accum += ev.final_confidence * w
        total_weight += w
    if total_weight == 0:
        return 0.0
    return round(accum / total_weight, 4)
