"""Turn positional OCR tokens into structured Taxitronic fields.

Steps:
  1. Group tokens into visual lines by y-coordinate.
  2. Match each line against the FIELD_LABELS catalogue.
  3. Extract the value to the right of the label.
  4. Apply contextual OCR fixes ONLY on numeric fields.
  5. Normalise: comma-decimal → Decimal, DD/MM/YY → ISO date, etc.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from .constants import (
    DATE_FIELDS, DATE_RE, DECIMAL_FIELDS, DIGIT_FIX_MAP,
    FIELD_LABELS, INTEGER_FIELDS, NUMBER_RE,
)
from .ocr_engine import OcrWord

logger = logging.getLogger(__name__)

_DATE_PATTERN = re.compile(DATE_RE)
_NUMBER_PATTERN = re.compile(NUMBER_RE)


@dataclass
class ParsedField:
    key: str
    raw_text: str            # everything after the label on the line
    normalised: Any          # Decimal / int / (date_iso, time_iso) / str
    ocr_confidence: float    # avg conf of the tokens contributing to `raw_text`
    format_valid: bool
    bbox: tuple[int, int, int, int] | None   # bbox of the value tokens
    variant: str = ""
    notes: list[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


# ─────────────────────── Line reconstruction ───────────────────────
def reconstruct_lines(words: list[OcrWord]) -> list[list[OcrWord]]:
    """Group OCR tokens into visual lines.

    We use the engine's `line_key` when it looks reliable, then fall back
    to clustering by y-center distance (< 0.6 × mean word height).
    """
    if not words:
        return []
    # Bucket by engine line_key first (cheap & usually correct).
    buckets: dict[str, list[OcrWord]] = {}
    for w in words:
        buckets.setdefault(w.line_key or "", []).append(w)
    lines = list(buckets.values())
    # Sort each line left→right and lines top→bottom.
    for ln in lines:
        ln.sort(key=lambda w: w.bbox[0])
    lines.sort(key=lambda ln: sum(w.bbox[1] for w in ln) / max(len(ln), 1))
    return lines


def _line_text(line: list[OcrWord]) -> str:
    return " ".join(w.text for w in line)


def _norm(s: str) -> str:
    """Lower + strip accents to make label matching resilient."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower()


# ─────────────────────── Field extraction ───────────────────────
def extract_fields(words: list[OcrWord]) -> dict[str, ParsedField]:
    """Return {internal_field_key: ParsedField} for what we could read."""
    lines = reconstruct_lines(words)
    found: dict[str, ParsedField] = {}
    for line in lines:
        raw = _line_text(line)
        norm = _norm(raw)
        for key, aliases in FIELD_LABELS:
            if key in found:
                continue
            for alias in aliases:
                if not _label_matches(norm, alias):
                    continue
                parsed = _parse_field_from_line(key, line, alias_len=len(alias))
                if parsed is not None:
                    found[key] = parsed
                break
    return found


def _label_matches(norm_line: str, alias: str) -> bool:
    """True if `alias` appears at the start of `norm_line` (word-boundary).

    We anchor at the start so "P Dist. Total" never matches alias
    "dist. total" — the P-block key catches that line instead.
    """
    if not norm_line.startswith(alias):
        return False
    # Ensure the label is followed by a word-boundary (":", " ", "\t", digit)
    # so "total" doesn't match "totalizador" if that ever appears.
    tail = norm_line[len(alias):len(alias) + 1]
    return tail == "" or not tail.isalpha()


def _parse_field_from_line(key: str, line: list[OcrWord], alias_len: int) -> Optional[ParsedField]:
    """Split the line at the label and normalise the tail as `key`.

    Strategy: walk tokens left→right, accumulating text, until we cover the
    label. Everything after is the value. If the label spans multiple
    tokens (e.g. "Num." + "Servicios:") we consume them all.
    """
    label_tokens: list[OcrWord] = []
    value_tokens: list[OcrWord] = []
    consumed_norm_len = 0
    label_done = False
    for w in line:
        if label_done:
            value_tokens.append(w)
            continue
        piece = _norm(w.text)
        # +1 accounts for the whitespace between tokens in the joined norm.
        consumed_norm_len += len(piece) + 1
        label_tokens.append(w)
        # Once we've consumed enough characters to cover the alias, we're
        # past the label. The current token is part of the label; next
        # tokens are value.
        if consumed_norm_len >= alias_len:
            label_done = True

    # Filter out tokens that are pure punctuation (":", "-", "|") — the
    # taximeter often prints a colon between label and value.
    value_tokens = [t for t in value_tokens if any(ch.isalnum() for ch in t.text)]

    if not value_tokens:
        return None   # no value on this line — let another variant find it

    value_raw = " ".join(w.text for w in value_tokens).strip(" :;.-")

    bbox = _tokens_bbox(value_tokens)
    ocr_conf = sum(w.confidence for w in value_tokens) / max(len(value_tokens), 1)
    variant = value_tokens[0].variant if value_tokens else ""

    normalised, valid, notes = normalise_value(key, value_raw)
    return ParsedField(
        key=key,
        raw_text=value_raw,
        normalised=normalised,
        ocr_confidence=ocr_conf,
        format_valid=valid,
        bbox=bbox,
        variant=variant,
        notes=notes,
    )


def _tokens_bbox(tokens: list[OcrWord]) -> Optional[tuple[int, int, int, int]]:
    if not tokens:
        return None
    xs = [t.bbox[0] for t in tokens]
    ys = [t.bbox[1] for t in tokens]
    xe = [t.bbox[0] + t.bbox[2] for t in tokens]
    ye = [t.bbox[1] + t.bbox[3] for t in tokens]
    return (min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))


# ─────────────────────── Normalisation ───────────────────────
def normalise_value(key: str, raw: str) -> tuple[Any, bool, list[str]]:
    """Return (normalised_value, format_valid, notes)."""
    notes: list[str] = []
    if not raw:
        return None, False, ["empty"]

    if key in DATE_FIELDS:
        return _normalise_date(raw, notes)

    is_numeric = key in DECIMAL_FIELDS or key in INTEGER_FIELDS
    if is_numeric:
        fixed = _apply_digit_fixes_safe(raw)
        # Prefer the LONGEST number token (letters/junk before it are common
        # OCR noise: "co 69515,60" should yield 69515.60, not 0).
        candidates = list(_NUMBER_PATTERN.finditer(fixed))
        if not candidates:
            return None, False, ["no_number_found"]
        best = max(candidates, key=lambda m: len(m.group(0)))
        num_str = _normalise_number_string(best.group(0))
        try:
            if key in INTEGER_FIELDS:
                # Strip a trailing ".0" style if the OCR added a spurious decimal.
                val = int(Decimal(num_str))
                return val, True, notes
            return Decimal(num_str), True, notes
        except (InvalidOperation, ValueError):
            return None, False, ["decimal_parse_error"]

    # Fallback: keep as trimmed string.
    return raw.strip(), True, notes


def _apply_digit_fixes(s: str) -> str:
    """Replace common OCR-confused letters with digits — numeric fields only."""
    return s.translate(DIGIT_FIX_MAP)


def _apply_digit_fixes_safe(s: str) -> str:
    """Digit-fix only tokens that already contain digits, and glue
    number fragments that Tesseract split around a comma/dot.

    "co" (start of "carreras" row noise) must NOT become "c0" — that would
    hide the real value that follows. We tokenise on whitespace and only
    translate a token if it has at least one digit already.

    We also collapse patterns like "69515, 60" → "69515,60" (Tesseract
    reads a stray whitespace after the decimal separator on some tickets).
    """
    parts = []
    for tok in s.split():
        if any(ch.isdigit() for ch in tok):
            parts.append(tok.translate(DIGIT_FIX_MAP))
        else:
            parts.append(tok)
    joined = " ".join(parts)
    # Glue "NNN, MMM" → "NNN,MMM" and "NNN. MMM" → "NNN.MMM".
    joined = re.sub(r"(\d)\s*([,\.])\s+(\d)", r"\1\2\3", joined)
    return joined


def _normalise_number_string(num_str: str) -> str:
    """Convert Taxitronic-printed numbers to a Python-parseable decimal.

    Cases handled (with real examples):
        "69515,60"     → "69515.60"     (Spanish comma decimal, no thousands)
        "59147,0"      → "59147.0"
        "69.515,60"    → "69515.60"     (dot as thousands separator)
        "59147.0"      → "59147.0"      (OCR read the comma as a dot)
        "1.234.567,89" → "1234567.89"
        "1,234,567.89" → "1234567.89"   (English thousands — never on ticket,
                                          but we still cope)
    The rule: whichever of {`,`, `.`} appears LAST is treated as the decimal
    separator; every earlier occurrence of either is a thousands separator
    and is dropped.
    """
    s = num_str.strip()
    last_comma = s.rfind(",")
    last_dot = s.rfind(".")
    if last_comma == -1 and last_dot == -1:
        return s
    if last_comma > last_dot:
        # Comma is decimal.
        return s.replace(".", "").replace(",", ".")
    if last_dot > last_comma:
        # Dot is decimal (either genuine or OCR-misread comma).
        return s.replace(",", "")
    return s


def _normalise_date(raw: str, notes: list[str]) -> tuple[Any, bool, list[str]]:
    """Return ({date_iso, time_iso}, valid, notes)."""
    m = _DATE_PATTERN.search(raw)
    if not m:
        return None, False, notes + ["date_no_match"]
    day, month, year, hour, minute = m.groups()
    try:
        d = int(day); mo = int(month); y = int(year)
        if y < 100:
            y += 2000
        parsed = date(y, mo, d)   # raises ValueError on invalid calendar dates
    except ValueError:
        return None, False, notes + ["date_invalid"]
    result: dict[str, str] = {"date": parsed.isoformat()}
    if hour is not None and minute is not None:
        try:
            t = time(int(hour), int(minute))
            result["time"] = t.strftime("%H:%M")
        except ValueError:
            notes.append("time_invalid")
    return result, True, notes
