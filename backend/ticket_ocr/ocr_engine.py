"""Abstract OCR engine + Tesseract implementation.

Every OCR call returns a list of `OcrWord` — a token with text, confidence
(0..1) and its bounding box in the image the OCR ran on. The pipeline
reconstructs lines from those words, so a future engine (PaddleOCR, doctr,
vision-LLM) only needs to fulfil the same contract.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import cv2
import numpy as np
import pytesseract

logger = logging.getLogger(__name__)


@dataclass
class OcrWord:
    text: str
    confidence: float          # 0..1
    bbox: tuple[int, int, int, int]   # (x, y, w, h)
    line_key: str              # engine-specific line grouping hint
    variant: str = ""          # which preprocess variant produced this word


class OcrEngine(Protocol):
    """Anything that can produce positional tokens from an image."""

    name: str

    def read(self, image: np.ndarray, *, lang: str = "spa+eng",
             psm: int = 6, numeric_only: bool = False) -> list[OcrWord]:
        ...


# ─────────────────────── Tesseract implementation ───────────────────────
class TesseractEngine:
    """Default engine — already installed in the pod and battle-tested here.

    Swappable: to plug PaddleOCR later, create a new class with the same
    `read` signature and pass an instance to the pipeline.
    """

    name = "tesseract"

    def read(self, image: np.ndarray, *, lang: str = "spa+eng",
             psm: int = 6, numeric_only: bool = False) -> list[OcrWord]:
        # image_to_data works on 1-channel or 3-channel images alike.
        config = f"--psm {psm} --oem 1"
        if numeric_only:
            config += " -c tessedit_char_whitelist=0123456789.,:/- "
        try:
            data = pytesseract.image_to_data(
                image, lang=lang, config=config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("tesseract failed: %s", e)
            return []

        words: list[OcrWord] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                # Tesseract signals "unknown confidence" with -1: keep, but
                # penalise so downstream scoring reflects it.
                conf_norm = 0.30
            else:
                conf_norm = max(0.0, min(1.0, conf / 100.0))
            x = int(data["left"][i]); y = int(data["top"][i])
            w = int(data["width"][i]); h = int(data["height"][i])
            line_key = f"{data.get('block_num', [0]*n)[i]}:{data.get('par_num', [0]*n)[i]}:{data.get('line_num', [0]*n)[i]}"
            words.append(OcrWord(text=text, confidence=conf_norm,
                                 bbox=(x, y, w, h), line_key=line_key))
        return words


# ─────────────────────── Multi-variant reader (helper) ───────────────────────
def read_all_variants(engine: OcrEngine, variants: dict[str, np.ndarray],
                      lang: str = "spa+eng") -> dict[str, list[OcrWord]]:
    """Run the engine over every preprocess variant.

    Returns a dict `variant_name → words`. Adds the variant name onto each
    word so downstream consumers can pick the best per-field.
    """
    out: dict[str, list[OcrWord]] = {}
    for name, img in variants.items():
        words = engine.read(img, lang=lang, psm=6)
        for w in words:
            w.variant = name
        out[name] = words
    return out


def read_region_numeric(engine: OcrEngine, gray: np.ndarray) -> Optional[tuple[str, float]]:
    """Second-pass OCR of a cropped numeric region.

    Returns (text, confidence 0..1) or None. Uses a numeric whitelist and
    a higher PSM (single line) to prioritise digits.
    """
    if gray is None or gray.size == 0:
        return None
    # Upscale hard for tiny crops.
    h, w = gray.shape[:2]
    if w < 200:
        scale = 300.0 / max(w, 1)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # A second binarisation just for the region.
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    words = engine.read(bw, lang="eng", psm=7, numeric_only=True)
    if not words:
        return None
    # Concatenate in x-order.
    words.sort(key=lambda w: w.bbox[0])
    text = " ".join(w.text for w in words).strip()
    conf = sum(w.confidence for w in words) / len(words)
    return text, conf
