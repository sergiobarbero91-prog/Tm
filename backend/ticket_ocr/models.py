"""Pydantic models for the scan pipeline."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict

ScanStatus = Literal["accepted", "needs_confirmation", "rejected"]


class FieldEvidence(BaseModel):
    """Per-field evidence — what the OCR saw and how much we trust it."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: Optional[Any] = None
    raw_text: Optional[str] = None
    ocr_confidence: float = 0.0            # 0..1 (normalised)
    format_valid: bool = False
    consensus: bool = False                # multiple OCR runs agreed
    validation_valid: bool = True          # math / cross-field checks passed
    final_confidence: float = 0.0          # 0..1 — combined score
    notes: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    total_matches: Optional[bool] = None            # carreras + suplementos == total
    period_total_matches: Optional[bool] = None     # p_carreras + p_suplementos == p_total
    # Reserved for when we document the exact Taxitronic units:
    distance_validated: bool = False
    time_validated: bool = False
    errors: list[str] = Field(default_factory=list)


class ScanResult(BaseModel):
    """Public shape returned by the endpoint."""
    document_type: Literal["taxitronic_partial"] = "taxitronic_partial"
    status: ScanStatus
    overall_confidence: float = 0.0
    fields: dict[str, FieldEvidence]                 # keyed by internal field name
    ticket: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    distance: dict[str, Any] = Field(default_factory=dict)
    time: dict[str, Any] = Field(default_factory=dict)
    deleted: Optional[int] = None
    period: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult
    warnings: list[str] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)   # keep small — no raw image
