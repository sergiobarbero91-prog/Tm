"""Router for taximeter ticket OCR endpoints.

Exposes:
    POST /api/tickets/taxitronic/scan     — read a Taxitronic partials photo
    POST /api/tickets/taxitronic/confirm  — persist a reviewed reading
    GET  /api/tickets/taxitronic          — list the caller's readings

The scan endpoint is intentionally stateless: it only extracts + validates
and returns evidence. Persistence happens only after the caller has
reviewed any `needs_confirmation` fields and calls `/confirm`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from shared import db, get_current_user_required
from ticket_ocr import scan_taxitronic_ticket
from ticket_ocr.constants import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES
from ticket_ocr.ocr_engine import build_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["Tickets OCR"])


class ConfirmedReading(BaseModel):
    """Payload written by the review UI after the driver validates a scan."""
    status: str = Field(..., description="accepted | needs_confirmation")
    ticket: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    distance: dict[str, Any] = Field(default_factory=dict)
    time: dict[str, Any] = Field(default_factory=dict)
    deleted: Optional[int] = None
    period: dict[str, Any] = Field(default_factory=dict)
    overall_confidence: float = 0.0
    user_edited_fields: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


@router.post("/taxitronic/scan")
async def scan_taxitronic(
    photo: UploadFile = File(...),
    engine: Optional[str] = Query(
        default=None,
        description="Override OCR engine: 'tesseract' | 'paddleocr'. "
                    "Defaults to TICKET_OCR_ENGINE env var, else 'tesseract'.",
    ),
    debug: bool = Query(
        default=False,
        description="Include base64-encoded debug snapshots of every "
                    "preprocess variant and the detected row ROIs.",
    ),
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
        selected_engine = build_engine(engine)
        result = await run_in_threadpool(
            scan_taxitronic_ticket, data, mime, selected_engine, debug,
        )
    except Exception:
        logger.exception("taxitronic scan failed unexpectedly")
        raise HTTPException(status_code=500, detail="ocr_pipeline_error")

    # Pydantic v2 → dict, dropping big binary blobs (we never put them in).
    return result.model_dump()


@router.post("/taxitronic/confirm")
async def confirm_taxitronic(
    payload: ConfirmedReading = Body(...),
    user: dict = Depends(get_current_user_required),
):
    """Persist a reviewed Taxitronic reading in `taxitronic_readings`.

    The frontend calls this after the driver has reviewed the evidence
    returned by `/scan` and either accepted the raw values or corrected
    the flagged ones. We store *what the driver confirmed*, not the raw
    OCR output — the audit trail is the `user_edited_fields` list.
    """
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": payload.status,
        "ticket": payload.ticket,
        "totals": payload.totals,
        "distance": payload.distance,
        "time": payload.time,
        "deleted": payload.deleted,
        "period": payload.period,
        "overall_confidence": payload.overall_confidence,
        "user_edited_fields": payload.user_edited_fields,
        "notes": payload.notes,
    }
    try:
        await db.taxitronic_readings.insert_one(doc)
    except Exception:
        logger.exception("failed to persist taxitronic reading")
        raise HTTPException(status_code=500, detail="persistence_error")
    return {"id": doc["_id"], "created_at": doc["created_at"]}


@router.get("/taxitronic")
async def list_taxitronic_readings(
    limit: int = 50,
    user: dict = Depends(get_current_user_required),
):
    """List the caller's most recent Taxitronic readings."""
    limit = max(1, min(limit, 200))
    cursor = (
        db.taxitronic_readings
        .find({"user_id": user["id"]}, {"_id": 1, "created_at": 1,
                                        "status": 1, "ticket": 1,
                                        "totals": 1, "period": 1,
                                        "overall_confidence": 1})
        .sort("created_at", -1)
        .limit(limit)
    )
    docs = []
    async for doc in cursor:
        doc["id"] = doc.pop("_id")
        docs.append(doc)
    return docs
