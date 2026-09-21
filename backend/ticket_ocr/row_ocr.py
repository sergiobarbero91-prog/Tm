"""Row-based ROI OCR — the geometry-first strategy.

Design (matches the user's phase list):
  1. Preprocessed image → find rows via y-projection of dark pixels.
  2. For each row, split into `label_side` (left) and `value_side` (right)
     using an adaptive x-cut based on the widest gap in that row.
  3. OCR each side separately with a config tuned to what we expect
     (letters for labels, digits+separators for values).
  4. Anchor labels to internal field keys.
  5. Collect multiple readings per value ROI (variants × PSMs), keep every
     candidate, and require **consensus** — never invent a value.
  6. Return per-field {value, status, confidence, candidates}.

Fail-safe rule: if consensus isn't reached OR the value's format is
implausible, the field is emitted as `needs_confirmation` — never as
`accepted` with a guessed number.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import cv2
import numpy as np
import pytesseract

from .constants import DECIMAL_FIELDS, FIELD_LABELS, INTEGER_FIELDS

logger = logging.getLogger(__name__)


# ─────────────────────── Data classes ───────────────────────
@dataclass
class RowRoi:
    y0: int; y1: int
    label_bbox: tuple[int, int, int, int]   # x,y,w,h
    value_bbox: tuple[int, int, int, int]
    label_text: str


@dataclass
class FieldReading:
    key: str
    value: Any = None
    raw_text: str = ""
    status: str = "needs_confirmation"      # accepted | needs_confirmation | rejected
    confidence: float = 0.0
    candidates: list[tuple[str, float]] = field(default_factory=list)   # (raw, ocr_conf)
    notes: list[str] = field(default_factory=list)


# ─────────────────────── Public entry ───────────────────────
def read_ticket_by_rows(gray: np.ndarray) -> dict[str, FieldReading]:
    """Return `{field_key: FieldReading}` for what we could confidently
    extract using the row-based ROI strategy."""
    rows = _detect_rows(gray)
    if not rows:
        return {}
    matched: dict[str, RowRoi] = {}
    for r in rows:
        key = _match_label_to_field_key(r.label_text)
        if key and key not in matched:
            matched[key] = r
    out: dict[str, FieldReading] = {}
    for key, roi in matched.items():
        out[key] = _read_value_roi(gray, roi, key)
    return out


# ─────────────────────── Row detection ───────────────────────
def _detect_rows(gray: np.ndarray) -> list[RowRoi]:
    """Detect horizontal text rows via y-projection of a binary image,
    then split each row into label/value using the widest x-gap."""
    if gray is None or gray.size == 0:
        return []
    # Binarise robustly.
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = bw.shape[:2]
    # Horizontal projection: count of dark pixels per row.
    proj = (bw > 0).sum(axis=1).astype(np.int32)
    row_bands = _bands_from_projection(proj, min_len=6)
    if not row_bands:
        return []

    rois: list[RowRoi] = []
    for (y0, y1) in row_bands:
        strip = bw[y0:y1, :]
        # Column projection inside this strip.
        col_proj = (strip > 0).sum(axis=0).astype(np.int32)
        # Determine content bounds (crop leading/trailing whitespace columns).
        content_cols = np.where(col_proj > 0)[0]
        if len(content_cols) < 4:
            continue
        x_left = int(content_cols[0])
        x_right = int(content_cols[-1])
        # Find widest zero-run inside the content span → separator between
        # label and value. Value is on the right.
        run_start, run_len = _widest_zero_run(col_proj[x_left:x_right + 1])
        if run_len < 6:
            # No clear gap — fall back to a 60/40 split (labels are wider).
            cut = x_left + int((x_right - x_left) * 0.6)
        else:
            cut = x_left + run_start + run_len // 2
        label_bbox = (x_left, y0, max(1, cut - x_left), y1 - y0)
        value_bbox = (cut, y0, max(1, x_right - cut), y1 - y0)
        # OCR the label side with a permissive config to know which field this is.
        try:
            label_img = gray[y0:y1, x_left:cut]
            label_txt = pytesseract.image_to_string(
                label_img, lang="spa+eng",
                config="--psm 7 --oem 1 -c preserve_interword_spaces=1",
            ).strip()
        except Exception:
            label_txt = ""
        if not label_txt:
            continue
        rois.append(RowRoi(y0, y1, label_bbox, value_bbox, label_txt))
    return rois


def _bands_from_projection(proj: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Return (start, end) row bands where proj > 0 and length >= min_len."""
    bands: list[tuple[int, int]] = []
    in_band = False
    y0 = 0
    for i, v in enumerate(proj):
        if v > 0 and not in_band:
            y0 = i; in_band = True
        elif v == 0 and in_band:
            if i - y0 >= min_len:
                bands.append((y0, i))
            in_band = False
    if in_band and (len(proj) - y0) >= min_len:
        bands.append((y0, len(proj)))
    return bands


def _widest_zero_run(arr: np.ndarray) -> tuple[int, int]:
    """Return (start, length) of the widest run of zeros in arr."""
    best_start = 0; best_len = 0
    cur_start = 0; cur_len = 0
    for i, v in enumerate(arr):
        if v == 0:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_start = cur_start; best_len = cur_len
        else:
            cur_len = 0
    return best_start, best_len


# ─────────────────────── Label matching ───────────────────────
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def _match_label_to_field_key(label_text: str) -> Optional[str]:
    """Return the internal field key whose alias BEST matches this label.

    Uses prefix-startswith so "P Dist. Total" doesn't steal "Dist. Total".
    """
    norm = _norm(label_text)
    for key, aliases in FIELD_LABELS:
        for alias in aliases:
            if norm.startswith(alias):
                return key
    # Fallback: try substring match, but only for aliases longer than 6 chars
    # so short words like "total" don't overmatch.
    for key, aliases in FIELD_LABELS:
        for alias in aliases:
            if len(alias) >= 6 and alias in norm:
                return key
    return None


# ─────────────────────── Value ROI reading + consensus ───────────────────────
_NUM_RE = re.compile(r"[-+]?\d[\d\.,]*")


def _read_value_roi(gray: np.ndarray, roi: RowRoi, key: str) -> FieldReading:
    """OCR a value ROI multiple times and reach consensus. Never guesses."""
    x, y, w, h = roi.value_bbox
    if w <= 4 or h <= 4:
        return FieldReading(key=key, status="rejected",
                            notes=["value_bbox_too_small"])
    crop = gray[y:y + h, x:x + w]
    variants = _value_variants(crop)
    numeric = key in DECIMAL_FIELDS or key in INTEGER_FIELDS
    is_date = key == "fecha"

    # Whitelist per field type.
    if is_date:
        whitelist = "0123456789/:.- "
    elif numeric:
        whitelist = "0123456789.,-"
    else:
        whitelist = ""

    candidates: list[tuple[str, float]] = []
    for name, img in variants:
        for psm in (7, 8, 13):
            try:
                cfg = f"--oem 1 --psm {psm}"
                if whitelist:
                    cfg += f" -c tessedit_char_whitelist={whitelist}"
                data = pytesseract.image_to_data(
                    img, lang="spa+eng" if not numeric else "eng", config=cfg,
                    output_type=pytesseract.Output.DICT,
                )
            except Exception:
                continue
            texts, confs = data.get("text", []), data.get("conf", [])
            joined_parts, joined_confs = [], []
            for t, c in zip(texts, confs):
                t = (t or "").strip()
                if not t:
                    continue
                try:
                    ci = float(c)
                except (TypeError, ValueError):
                    ci = -1.0
                joined_parts.append(t)
                joined_confs.append(max(0.0, ci) / 100.0)
            if not joined_parts:
                continue
            raw = " ".join(joined_parts).strip(" :;.-")
            avg_conf = sum(joined_confs) / len(joined_confs)
            candidates.append((raw, avg_conf))

    if not candidates:
        return FieldReading(key=key, status="rejected", notes=["no_candidates"])

    # Normalise each candidate to its canonical form for consensus counting.
    norms: list[tuple[Any, float, str]] = []   # (normalised, ocr_conf, raw)
    for raw, conf in candidates:
        n = _canonicalize(key, raw)
        if n is None:
            continue
        norms.append((n, conf, raw))

    if not norms:
        return FieldReading(
            key=key, status="needs_confirmation",
            confidence=0.0, candidates=candidates,
            notes=["no_parseable_candidate"],
        )

    # Consensus: pick the value with the highest count; tie-break by
    # average confidence.
    counts = Counter(str(n[0]) for n in norms)
    top_key, top_n = counts.most_common(1)[0]
    top_pool = [n for n in norms if str(n[0]) == top_key]
    avg_conf = sum(c for _, c, _ in top_pool) / len(top_pool)
    winner_value = top_pool[0][0]
    winner_raw = top_pool[0][2]

    # Confidence combining OCR + consensus.
    total = len(norms)
    consensus_ratio = top_n / total
    final_conf = round(0.55 * avg_conf + 0.45 * consensus_ratio, 3)

    if top_n >= 3 and final_conf >= 0.70:
        status = "accepted"
    elif top_n >= 2 and final_conf >= 0.55:
        status = "needs_confirmation"
    else:
        status = "needs_confirmation"

    return FieldReading(
        key=key, value=winner_value, raw_text=winner_raw, status=status,
        confidence=final_conf, candidates=candidates,
        notes=[f"consensus={top_n}/{total}"],
    )


def _value_variants(crop: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """Return small controlled bank of pre-processed variants for the ROI."""
    h, w = crop.shape[:2]
    scale = max(1.0, 60.0 / max(h, 1))
    if scale != 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)
    variants = [("gray", crop)]
    # Otsu.
    _, otsu = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu))
    # Adaptive.
    adp = cv2.adaptiveThreshold(crop, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, 25, 12)
    variants.append(("adaptive", adp))
    # Sharpen moderado.
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharp = cv2.filter2D(crop, -1, kernel)
    variants.append(("sharpen", sharp))
    return variants


# ─────────────────────── Canonicalisation (no aggressive fixes) ───────────────────────
def _canonicalize(key: str, raw: str) -> Any:
    """Turn a raw OCR string into a comparable value WITHOUT guessing.

    Refuses to fabricate a decimal separator. Returns None when the
    raw text cannot be safely parsed as the field's expected type.
    """
    s = (raw or "").strip()
    if not s:
        return None
    if key == "fecha":
        m = re.search(r"(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})", s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            from datetime import date as _d
            return _d(y, mo, d).isoformat()
        except ValueError:
            return None
    if key == "hora":
        m = re.search(r"\b([01]?\d|2[0-3])[:;.]([0-5]\d)\b", s)
        if not m:
            return None
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if key in DECIMAL_FIELDS:
        m = _NUM_RE.search(s)
        if not m:
            return None
        num = _num_norm(m.group(0))
        try:
            return Decimal(num)
        except InvalidOperation:
            return None
    if key in INTEGER_FIELDS:
        m = _NUM_RE.search(s)
        if not m:
            return None
        num = re.sub(r"[.,]", "", m.group(0))
        try:
            return int(num)
        except ValueError:
            return None
    return s


def _num_norm(num_str: str) -> str:
    """Whichever of {,.}  appears LAST is the decimal; earlier are thousands."""
    last_comma = num_str.rfind(","); last_dot = num_str.rfind(".")
    if last_comma == -1 and last_dot == -1:
        return num_str
    if last_comma > last_dot:
        return num_str.replace(".", "").replace(",", ".")
    return num_str.replace(",", "")
