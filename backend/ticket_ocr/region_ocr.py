"""Structural / field-by-field OCR pass.

Rationale
---------
Reading the full ticket in one go is fast but fragile: Tesseract's line
grouping can merge two rows, split a number in half, or drop punctuation.
Once we know *where* a label is on the image, we can:

  * crop only the row to the right of the label,
  * upscale that strip 2-3×,
  * re-binarise locally (Otsu on a small crop is much stabler than global),
  * run OCR with a task-tuned config (numeric whitelist, PSM 7 = single line).

That converts "OCR the whole ticket" into "read one number with maximum
focus" — the accuracy jump on decimal fields is dramatic on noisy photos.

Design
------
We do NOT replace the multi-variant pass; we augment it:
  1. Full pipeline runs normally.
  2. Anchor detection: for every label alias, find its position on the
     preprocessed image (best variant).
  3. For each `key` in FIELD_LABELS:
       - if the multi-variant pass captured it AND ocr_confidence >= 0.75
         and format_valid → leave it alone;
       - else → attempt a targeted read using the anchor.
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Optional

import cv2
import numpy as np

from .constants import DECIMAL_FIELDS, FIELD_LABELS, INTEGER_FIELDS
from .ocr_engine import OcrEngine, OcrWord
from .parser import ParsedField, normalise_value

logger = logging.getLogger(__name__)

# A confident-enough field never needs a targeted re-read.
GOOD_FIELD_MIN_CONF = 0.75


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


# ─────────────────────── Anchor detection ───────────────────────
def find_label_anchors(engine: OcrEngine, gray: np.ndarray
                       ) -> dict[str, tuple[int, int, int, int]]:
    """Return `{field_key: (x, y, w, h)}` for each label we can locate.

    Uses a full-image OCR with sentence-level PSM (11 = sparse text) to
    catch labels even when the row is spatially cramped. We then compact
    consecutive words into label spans and match them by prefix.
    """
    words = engine.read(gray, lang="spa+eng", psm=11)
    if not words:
        # Fallback to PSM 6 which is more permissive.
        words = engine.read(gray, lang="spa+eng", psm=6)

    # Group into visual lines by y-center clustering (independent of the
    # engine's line grouping which is unreliable in sparse PSM).
    lines = _cluster_lines_by_y(words)

    anchors: dict[str, tuple[int, int, int, int]] = {}
    for line in lines:
        text = " ".join(w.text for w in line)
        norm = _norm(text)
        for key, aliases in FIELD_LABELS:
            if key in anchors:
                continue
            for alias in aliases:
                if norm.startswith(alias):
                    # Compute the bbox of the label tokens (leftmost
                    # portion of the line) so the value-side crop is
                    # unambiguous.
                    label_bbox = _label_span_bbox(line, alias)
                    if label_bbox is not None:
                        anchors[key] = label_bbox
                    break
    return anchors


def _cluster_lines_by_y(words: list[OcrWord]) -> list[list[OcrWord]]:
    if not words:
        return []
    heights = [w.bbox[3] for w in words if w.bbox[3] > 0]
    avg_h = float(np.median(heights)) if heights else 20.0
    threshold = max(avg_h * 0.6, 6.0)

    sorted_words = sorted(words, key=lambda w: (w.bbox[1] + w.bbox[3] / 2))
    lines: list[list[OcrWord]] = [[sorted_words[0]]]
    for w in sorted_words[1:]:
        y_center = w.bbox[1] + w.bbox[3] / 2
        prev_line = lines[-1]
        prev_y = np.mean([t.bbox[1] + t.bbox[3] / 2 for t in prev_line])
        if abs(y_center - prev_y) <= threshold:
            prev_line.append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: w.bbox[0])
    return lines


def _label_span_bbox(line: list[OcrWord], alias: str) -> Optional[tuple[int, int, int, int]]:
    """Bbox of the leftmost tokens whose norm covers `alias`."""
    consumed = 0
    span: list[OcrWord] = []
    for w in line:
        span.append(w)
        consumed += len(_norm(w.text)) + 1
        if consumed >= len(alias):
            break
    if not span:
        return None
    xs = [t.bbox[0] for t in span]
    ys = [t.bbox[1] for t in span]
    xe = [t.bbox[0] + t.bbox[2] for t in span]
    ye = [t.bbox[1] + t.bbox[3] for t in span]
    return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))


# ─────────────────────── Targeted row read ───────────────────────
def _read_value_next_to_label(engine: OcrEngine, gray: np.ndarray,
                              label_bbox: tuple[int, int, int, int],
                              numeric: bool) -> Optional[tuple[str, float]]:
    """Crop the row *right of* the label and OCR just the value strip."""
    H, W = gray.shape[:2]
    lx, ly, lw, lh = label_bbox
    # Value strip: from `label_end + small pad` to the right edge, with
    # some vertical padding to catch descenders/ascenders.
    pad_v = max(6, lh // 4)
    x0 = min(W - 2, lx + lw + 6)
    y0 = max(0, ly - pad_v)
    y1 = min(H, ly + lh + pad_v)
    if x0 >= W:
        return None
    strip = gray[y0:y1, x0:W]
    if strip.size == 0:
        return None

    # Upscale strongly — Tesseract loves ~40 px x-height.
    h_strip = strip.shape[0]
    if h_strip < 60:
        scale = 60.0 / h_strip
        strip = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Local binarisation is dramatically better than global on a narrow strip.
    _, bw = cv2.threshold(strip, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # PSM 7 = single line of text.
    words = engine.read(bw, lang="spa+eng" if not numeric else "eng",
                        psm=7, numeric_only=numeric)
    if not words:
        return None
    words.sort(key=lambda w: w.bbox[0])
    text = " ".join(w.text for w in words).strip(" :;.-")
    conf = sum(w.confidence for w in words) / len(words)
    return text, conf


# ─────────────────────── Public entry ───────────────────────
def structural_pass(engine: OcrEngine, gray: np.ndarray,
                    already: dict[str, ParsedField]
                    ) -> dict[str, ParsedField]:
    """Run field-by-field targeted OCR to improve or complete `already`.

    Returns a new dict merging original fields with targeted reads. A
    targeted read only replaces an existing field when its confidence
    beats the previous value's; if the field was missing entirely, the
    targeted read is added.
    """
    anchors = find_label_anchors(engine, gray)
    if not anchors:
        return already
    merged = dict(already)
    for key, bbox in anchors.items():
        prev = merged.get(key)
        if prev and prev.ocr_confidence >= GOOD_FIELD_MIN_CONF and prev.format_valid:
            continue  # already reliable
        numeric = key in DECIMAL_FIELDS or key in INTEGER_FIELDS
        outcome = _read_value_next_to_label(engine, gray, bbox, numeric=numeric)
        if outcome is None:
            continue
        text, conf = outcome
        normalised, valid, notes = normalise_value(key, text)
        if not valid or normalised is None:
            continue
        # Only replace when the new reading looks better than the previous.
        if prev is not None and (prev.ocr_confidence >= conf and prev.format_valid):
            continue
        # Absolute bbox of the value-side strip we just read.
        H, W = gray.shape[:2]
        lx, ly, lw, lh = bbox
        value_bbox = (
            min(W - 2, lx + lw + 6), max(0, ly - lh // 4),
            max(1, W - (lx + lw + 6)), lh + max(6, lh // 2),
        )
        merged[key] = ParsedField(
            key=key, raw_text=text, normalised=normalised,
            ocr_confidence=conf, format_valid=True,
            bbox=value_bbox, variant="structural",
            notes=list(notes) + ["from_structural_pass"],
        )
    return merged
