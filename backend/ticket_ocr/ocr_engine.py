"""Abstract OCR engine + Tesseract implementation.

Every OCR call returns a list of `OcrWord` — a token with text, confidence
(0..1) and its bounding box in the image the OCR ran on. The pipeline
reconstructs lines from those words, so a future engine (PaddleOCR, doctr,
vision-LLM) only needs to fulfil the same contract.
"""
from __future__ import annotations

import logging
import os
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


# ─────────────────────── PaddleOCR implementation (opt-in) ───────────────────────
class PaddleOcrEngine:
    """Alternative engine using PaddleOCR PP-OCRv4/v6 models.

    Rationale: on hi-res, well-framed photos PaddleOCR usually beats
    Tesseract on rotated / low-contrast tickets. It is however:
      * heavy (~1.5 GB models, paddlepaddle wheel ~250 MB);
      * x86_64 only in practice (ARM64 wheels segfault today).

    So we make it OPT-IN: enable by setting `TICKET_OCR_ENGINE=paddleocr`
    or by passing an instance explicitly to the pipeline. If import fails
    or inference raises, the engine returns [] and the pipeline transparently
    falls back to whatever variant Tesseract produced (see `pipeline.py`).

    Contract identical to `TesseractEngine.read`, so the pipeline is
    agnostic to which engine is active.
    """

    name = "paddleocr"

    def __init__(self, lang: str = "es", use_textline_orientation: bool = True):
        self._lang = lang
        self._use_textline_orientation = use_textline_orientation
        self._ocr = None  # lazy-init

    def _get(self):
        if self._ocr is not None:
            return self._ocr
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError as e:
            logger.warning("paddleocr not installed: %s. `pip install paddlepaddle paddleocr`.", e)
            return None
        try:
            self._ocr = PaddleOCR(
                lang=self._lang,
                use_textline_orientation=self._use_textline_orientation,
            )
            return self._ocr
        except Exception as e:  # noqa: BLE001
            logger.warning("paddleocr init failed: %s", e)
            return None

    def read(self, image: np.ndarray, *, lang: str = "es",
             psm: int = 6, numeric_only: bool = False) -> list[OcrWord]:
        # `psm` / `lang` / `numeric_only` are Tesseract-specific and are
        # accepted here only to honour the interface. Paddle is language-
        # agnostic per instance; `numeric_only` is best-effort post-filter.
        ocr = self._get()
        if ocr is None:
            return []
        # Paddle expects 3-channel; convert if we receive a grayscale.
        if image.ndim == 2:
            bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            bgr = image
        try:
            results = ocr.predict(bgr)
        except Exception as e:  # noqa: BLE001
            logger.warning("paddleocr predict failed: %s", e)
            return []

        words: list[OcrWord] = []
        # PaddleOCR 3.x returns a list of OCRResult objects each with a
        # `json` dict containing rec_texts / rec_scores / rec_polys.
        for r in (results or []):
            data = getattr(r, "json", None)
            if isinstance(data, dict):
                data = data.get("res", data)
            if not isinstance(data, dict):
                continue
            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or []
            polys = data.get("rec_polys") or data.get("dt_polys") or []
            for i, text in enumerate(texts):
                text = (text or "").strip()
                if not text:
                    continue
                if numeric_only and not any(ch.isdigit() for ch in text):
                    continue
                conf = float(scores[i]) if i < len(scores) else 0.5
                bbox = _poly_to_bbox(polys[i]) if i < len(polys) else (0, 0, 0, 0)
                # We fabricate a line_key from the y-band so the parser can
                # cluster tokens. Bucket size = 20 px is a good default.
                line_key = f"paddle:{bbox[1] // 20}"
                words.append(OcrWord(text=text, confidence=conf,
                                     bbox=bbox, line_key=line_key))
        return words


def _poly_to_bbox(poly) -> tuple[int, int, int, int]:
    """Convert a Paddle 4-point polygon into an (x, y, w, h) rectangle."""
    try:
        pts = np.asarray(poly).reshape(-1, 2)
        x0 = int(pts[:, 0].min()); y0 = int(pts[:, 1].min())
        x1 = int(pts[:, 0].max()); y1 = int(pts[:, 1].max())
        return (x0, y0, x1 - x0, y1 - y0)
    except Exception:  # noqa: BLE001
        return (0, 0, 0, 0)


# ─────────────────────── Engine factory ───────────────────────
def build_engine(name: Optional[str] = None) -> OcrEngine:
    """Return an OcrEngine instance based on `name` or `TICKET_OCR_ENGINE`.

    Values supported: `tesseract` (default), `paddleocr`. Unknown values
    fall back to Tesseract with a warning — we never want an obscure env
    misconfiguration to break scanning silently.
    """
    chosen = (name or os.environ.get("TICKET_OCR_ENGINE") or "tesseract").lower()
    if chosen == "paddleocr":
        return PaddleOcrEngine()
    if chosen != "tesseract":
        logger.warning("Unknown TICKET_OCR_ENGINE=%s, falling back to tesseract.", chosen)
    return TesseractEngine()


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
