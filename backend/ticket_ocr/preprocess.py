"""Image preprocessing: validation, deskew and multi-version generation.

We produce several images for OCR because Tesseract's accuracy on thermal
tickets swings a lot with binarisation choices. Feeding it 3-4 variants and
comparing results is essentially free and buys us a lot of robustness.

None of these steps ever raises — we return `PreprocessResult.ok=False` and
let the pipeline decide what to do.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

from .constants import (
    ALLOWED_MIME_PREFIXES, ALLOWED_MIME_TYPES,
    MAX_UPLOAD_BYTES, MIN_BLUR_SCORE,
    MIN_IMAGE_HEIGHT_PX, MIN_IMAGE_WIDTH_PX,
)

logger = logging.getLogger(__name__)


@dataclass
class PreprocessResult:
    ok: bool
    variants: dict[str, np.ndarray]     # name → grayscale/binary image
    original_bgr: Optional[np.ndarray]
    error: Optional[str] = None
    warnings: list[str] = None
    blur_score: float = 0.0

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# ─────────────────────── Public entry ───────────────────────
def preprocess(image_bytes: bytes, mime_type: str) -> PreprocessResult:
    """Run the full image-side pipeline. Never raises."""
    err = _validate_upload(image_bytes, mime_type)
    if err:
        return PreprocessResult(False, {}, None, error=err)

    try:
        bgr = _decode(image_bytes)
    except Exception as e:  # unreadable / corrupt
        return PreprocessResult(False, {}, None, error=f"decode_failed: {e}")

    h, w = bgr.shape[:2]
    if w < MIN_IMAGE_WIDTH_PX or h < MIN_IMAGE_HEIGHT_PX:
        return PreprocessResult(
            False, {}, bgr,
            error=f"resolution_too_low: {w}x{h}",
        )

    warnings: list[str] = []

    # Try to isolate the ticket + fix perspective. If detection fails, keep
    # the original image — a lot of phone photos are already framed OK.
    detected = _detect_and_deskew_ticket(bgr)
    ticket_bgr = detected if detected is not None else bgr

    # Fix rotation (upside-down / sideways) using Tesseract OSD.
    ticket_bgr = _auto_rotate(ticket_bgr)

    gray = cv2.cvtColor(ticket_bgr, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_score < MIN_BLUR_SCORE:
        warnings.append(f"low_sharpness: laplacian_var={blur_score:.1f}")

    # Upscale small crops — OCR quality drops fast under ~1000 px width.
    upscaled_gray = _upscale_if_small(gray, target_width=1600)

    variants = {
        "gray": upscaled_gray,
        "clahe": _clahe(upscaled_gray),
        "adaptive": _adaptive_threshold(upscaled_gray),
        "otsu": _otsu_threshold(upscaled_gray),
    }

    return PreprocessResult(
        ok=True,
        variants=variants,
        original_bgr=ticket_bgr,
        warnings=warnings,
        blur_score=blur_score,
    )


# ─────────────────────── Validation & decode ───────────────────────
def _validate_upload(image_bytes: bytes, mime_type: str) -> Optional[str]:
    if not image_bytes:
        return "empty_file"
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        return f"file_too_large: {len(image_bytes)}"
    mime = (mime_type or "").lower()
    if mime and mime not in ALLOWED_MIME_TYPES and not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        return f"unsupported_mime: {mime}"
    return None


def _decode(image_bytes: bytes) -> np.ndarray:
    # Prefer PIL: it handles HEIC/EXIF orientation better than OpenCV.
    pil = Image.open(io.BytesIO(image_bytes))
    pil = ImageOps.exif_transpose(pil).convert("RGB")
    arr = np.array(pil)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


# ─────────────────────── Ticket detection / deskew ───────────────────────
def _auto_rotate(bgr: np.ndarray) -> np.ndarray:
    """Detect 90°/180°/270° rotations via Tesseract OSD and fix them.

    OSD (Orientation and Script Detection) reads global text orientation.
    We only trust it when confidence is decent — a low-confidence guess on
    a blurry photo would rotate the image the wrong way and make things
    worse. Falls back to the input silently on any error.
    """
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(bgr, output_type=pytesseract.Output.DICT)
        angle = int(osd.get("rotate", 0))
        confidence = float(osd.get("orientation_conf", 0.0))
        if confidence < 2.0 or angle == 0:
            return bgr
        rot_map = {
            90:  cv2.ROTATE_90_COUNTERCLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_CLOCKWISE,
        }
        return cv2.rotate(bgr, rot_map[angle]) if angle in rot_map else bgr
    except Exception as e:  # noqa: BLE001 - never let OSD kill a scan
        logger.debug("auto-rotate skipped: %s", e)
        return bgr


def _detect_and_deskew_ticket(bgr: np.ndarray) -> Optional[np.ndarray]:
    """Find the largest bright quadrilateral and warp it to a rectangle.

    Returns None if we can't confidently isolate the ticket — the caller
    should fall back to the raw image.
    """
    try:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        # Bright paper → high threshold isolates it from the (usually darker) hand.
        _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        image_area = bgr.shape[0] * bgr.shape[1]
        best_quad = None
        best_area = 0.0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < image_area * 0.15:  # ignore small blobs
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            if len(approx) == 4 and area > best_area:
                best_quad = approx
                best_area = area
        if best_quad is None:
            return None
        warped = _four_point_warp(bgr, best_quad.reshape(4, 2).astype("float32"))
        # Sanity check: the warped image should be taller than wide (portrait ticket).
        wh, ww = warped.shape[:2]
        if wh < ww:  # rotate to portrait
            warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
        return warped
    except Exception as e:  # noqa: BLE001
        logger.debug("ticket detection failed: %s", e)
        return None


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Return points ordered as [top-left, top-right, bottom-right, bottom-left]."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _four_point_warp(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_w = int(max(width_a, width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_h = int(max(height_a, height_b))
    if max_w < 100 or max_h < 100:
        return image
    dst = np.array([
        [0, 0], [max_w - 1, 0],
        [max_w - 1, max_h - 1], [0, max_h - 1],
    ], dtype="float32")
    m = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, m, (max_w, max_h))


# ─────────────────────── Binarisation variants ───────────────────────
def _upscale_if_small(gray: np.ndarray, target_width: int) -> np.ndarray:
    h, w = gray.shape[:2]
    if w >= target_width:
        return gray
    scale = target_width / float(w)
    return cv2.resize(gray, (target_width, int(h * scale)), interpolation=cv2.INTER_CUBIC)


def _clahe(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _adaptive_threshold(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def _otsu_threshold(gray: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


# ─────────────────────── Region re-crop (for per-field second pass) ───────────────────────
def crop_region(gray: np.ndarray, bbox: tuple[int, int, int, int], pad: int = 6) -> np.ndarray:
    """Return the bbox-cropped region with padding, clamped to the image.

    bbox = (x, y, w, h). Used by the pipeline when a validator fails and we
    want to re-OCR just one field with higher zoom.
    """
    x, y, w, h = bbox
    H, W = gray.shape[:2]
    x0 = max(0, x - pad); y0 = max(0, y - pad)
    x1 = min(W, x + w + pad); y1 = min(H, y + h + pad)
    return gray[y0:y1, x0:x1]
