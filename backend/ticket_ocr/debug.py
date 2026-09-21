"""Debug snapshot helpers.

When the scan endpoint is called with `?debug=1` we return small annotated
images alongside the normal result so we can eyeball what the pipeline
did on real tickets:
  * `original`       — the deskewed/rotated ticket as fed to OCR
  * `variant_<name>` — each preprocess variant (gray/clahe/adaptive/otsu)
  * `rows`           — original with row bands + label/value split overlaid
  * `rois`           — for every matched field, the value ROI cropped out

Every snapshot is a base64 PNG string capped at ~200 KB so a full debug
payload stays well under 2 MB (7 variants × 200 KB + rois).
"""
from __future__ import annotations

import base64
import logging
from typing import Any

import cv2
import numpy as np

from .row_ocr import RowRoi, _detect_rows

logger = logging.getLogger(__name__)

_MAX_SIDE = 1200
_JPEG_Q = 65


def _encode(img: np.ndarray) -> str:
    """Downscale + JPEG-encode + base64 (`data:image/jpeg;base64,...`)."""
    if img is None or img.size == 0:
        return ""
    h, w = img.shape[:2]
    scale = _MAX_SIDE / max(h, w) if max(h, w) > _MAX_SIDE else 1.0
    if scale != 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    if not ok:
        return ""
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def build_snapshots(original_bgr: np.ndarray | None,
                    variants: dict[str, np.ndarray],
                    matched_rows: dict[str, RowRoi] | None = None
                    ) -> dict[str, Any]:
    """Return a dict of {name: data-uri} debug images.

    `matched_rows` (optional) is `{field_key: RowRoi}` from row_ocr — when
    present we draw a color overlay on the base image showing each row's
    label ROI (blue) and value ROI (green) with the field key annotated.
    """
    out: dict[str, Any] = {}
    if original_bgr is not None:
        out["original"] = _encode(original_bgr)

    # Row detection preview — always compute it on the CLAHE variant when
    # available (best contrast for the projection).
    base_gray = variants.get("clahe")
    if base_gray is None:
        base_gray = variants.get("gray")
    if base_gray is not None:
        try:
            rows_preview = _draw_row_bands(base_gray, matched_rows or {})
            out["rows"] = _encode(rows_preview)
        except Exception:  # noqa: BLE001
            logger.exception("row overlay render failed")

    # Per-variant thumbnails (small — helps compare binarisations).
    for name, img in variants.items():
        out[f"variant_{name}"] = _encode(img)

    # ROI crops per matched field.
    if matched_rows and base_gray is not None:
        rois: dict[str, str] = {}
        for key, roi in matched_rows.items():
            x, y, w, h = roi.value_bbox
            H, W = base_gray.shape[:2]
            x0 = max(0, x - 4); y0 = max(0, y - 4)
            x1 = min(W, x + w + 4); y1 = min(H, y + h + 4)
            crop = base_gray[y0:y1, x0:x1]
            rois[key] = _encode(crop)
        out["rois"] = rois

    return out


def _draw_row_bands(gray: np.ndarray, matched: dict[str, RowRoi]) -> np.ndarray:
    """Overlay row bands + label/value split on a grayscale image.

    Uses the same detection code the pipeline uses so what we render is
    what got OCR-ed. Bands with a matched field are outlined and labeled;
    unmatched bands are shown with a thinner grey stroke.
    """
    canvas = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    rows = _detect_rows(gray)
    matched_by_bbox = {(r.y0, r.y1): key for key, r in matched.items()}
    for r in rows:
        key = matched_by_bbox.get((r.y0, r.y1))
        lx, ly, lw, lh = r.label_bbox
        vx, vy, vw, vh = r.value_bbox
        if key:
            cv2.rectangle(canvas, (lx, ly), (lx + lw, ly + lh),
                          (255, 128, 0), 2)   # blue label ROI
            cv2.rectangle(canvas, (vx, vy), (vx + vw, vy + vh),
                          (0, 200, 0), 2)     # green value ROI
            cv2.putText(canvas, key, (lx, max(12, ly - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 200), 1)
        else:
            cv2.rectangle(canvas, (lx, ly), (vx + vw, vy + vh),
                          (128, 128, 128), 1)  # unmatched — grey
    return canvas
