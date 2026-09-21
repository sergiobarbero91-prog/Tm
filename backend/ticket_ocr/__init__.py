"""Taxitronic ticket OCR pipeline (fail-safe).

Public entry point: `pipeline.scan_taxitronic_ticket(image_bytes, mime_type)`.

Design goals:
  * Never store a wrong value silently — prefer `needs_confirmation`.
  * Every field carries evidence (OCR conf, format valid, consensus, math valid).
  * OCR engine is behind an interface (`OcrEngine`) so it can be swapped
    (Tesseract today, PaddleOCR or vision-LLM tomorrow) without touching
    the pipeline.
"""

from .pipeline import scan_taxitronic_ticket  # re-export

__all__ = ["scan_taxitronic_ticket"]
