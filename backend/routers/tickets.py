"""Router for taximeter ticket OCR endpoints.

Currently exposes:
    POST /api/tickets/taxitronic/scan   — scan a Taxitronic partials ticket

The endpoint is intentionally stateless: it does NOT persist the reading
(the pipeline is fail-safe and the caller must review `needs_confirmation`
results before writing to the journal). Persistence is handled by the
existing journal router, which can be wired to consume this pipeline in a
follow-up step.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from shared import get_current_user_required
from ticket_ocr import scan_taxitronic_ticket
from ticket_ocr.constants import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["Tickets OCR"])


@router.post("/taxitronic/scan")
async def scan_taxitronic(
    photo: UploadFile = File(...),
    _user: dict = Depends(get_current_user_required),
):
    """Run the fail-safe OCR pipeline against a Taxitronic partials photo.

    Returns a `ScanResult` JSON:
        - `status`: accepted / needs_confirmation / rejected
        - `overall_confidence`: 0..1
        - `fields`: per-field evidence (OCR conf, format, consensus, math)
        - `ticket` / `totals` / `distance` / `time` / `period`: ergonomic tops
        - `validation`: math-check outcomes
        - `warnings`, `debug`: non-blocking metadata

    The response is deliberately verbose so the frontend can decide
    whether to auto-save (`accepted`) or ask the user to review flagged
    fields (`needs_confirmation`).
    """
    # ── Content-type & size guards ────────────────────────────────────────
    mime = (photo.content_type or "").lower()
    if mime and mime not in ALLOWED_MIME_TYPES and not mime.startswith("image/"):
        raise HTTPException(status_code=415, detail=f"unsupported_media_type: {mime}")

    data = await photo.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    # ── Run pipeline in a threadpool (OCR + OpenCV are CPU-bound) ─────────
    try:
        result = await run_in_threadpool(scan_taxitronic_ticket, data, mime)
    except Exception:
        logger.exception("taxitronic scan failed unexpectedly")
        raise HTTPException(status_code=500, detail="ocr_pipeline_error")

    # Pydantic v2 → dict, dropping big binary blobs (we never put them in).
    return result.model_dump()
