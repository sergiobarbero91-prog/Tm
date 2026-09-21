"""Constants: field catalogue, label aliases, regexes, thresholds.

Everything printed on the ticket that we care about is declared here so the
parser and the validator can stay data-driven. Adding a new Taxitronic
firmware label is a one-line change.
"""
from __future__ import annotations

# ─────────────────────── Image / OCR thresholds ────────────────────────
MIN_IMAGE_WIDTH_PX = 300
MIN_IMAGE_HEIGHT_PX = 400
MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # 12 MB — reject anything bigger up-front
# Laplacian variance below this ⇒ image is likely blurred beyond OCR use.
MIN_BLUR_SCORE = 40.0
ALLOWED_MIME_PREFIXES = ("image/",)
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/heic", "image/heif",
}

# Values below this OCR confidence are treated as unreliable evidence.
LOW_OCR_CONFIDENCE = 60.0

# ─────────────────────── Field catalogue ────────────────────────
# Each label variation the taximeter can print maps to the internal key.
# Order matters: keep unambiguous forms first ("P Total" before "Total").
FIELD_LABELS: list[tuple[str, list[str]]] = [
    # -------- BLOQUE P (period / turno) --------
    # Must be matched BEFORE the "sin P" versions to avoid stealing them.
    ("p_num_servicios",     ["p n° de servs", "p no de servs", "p n de servs",
                             "p nº de servs", "p n de servicios", "p num servicios",
                             "p n° servicios"]),
    ("p_carreras",          ["p carreras"]),
    ("p_suplementos",       ["p suplementos"]),
    ("p_total",             ["p total"]),
    ("p_dist_total",        ["p dist. total", "p dist total"]),
    ("p_dist_ocupado",      ["p dist. ocupado", "p dist ocupado"]),
    ("p_dist_libre",        ["p dist. libre", "p dist libre"]),
    ("p_dist_off",          ["p dist. off", "p dist off"]),
    ("p_tiempo_ocupado",    ["p tiempo ocupado"]),
    ("p_tiempo_on",         ["p tiempo on"]),
    # -------- Bloque acumulado (totales del taxímetro) --------
    ("fecha",               ["fecha"]),
    ("licencia",            ["n° licencia", "no licencia", "nº licencia", "n licencia", "num licencia"]),
    ("num_servicios",       ["num. servicios", "num servicios", "n° servicios", "nº servicios"]),
    ("carreras",            ["carreras"]),
    ("suplementos",         ["suplementos"]),
    ("total",               ["total"]),
    ("dist_total",          ["dist. total", "dist total"]),
    ("dist_ocupado",        ["dist. ocupado", "dist ocupado"]),
    ("dist_libre",          ["dist. libre", "dist libre"]),
    ("dist_off",            ["dist. off", "dist off"]),
    ("tiempo_ocupado",      ["tiempo ocupado"]),
    ("tiempo_on",           ["tiempo on"]),
    ("borrados",            ["borrados"]),
]

# Numeric vs date/time typing per key — drives normalisation & validators.
DECIMAL_FIELDS = {
    "carreras", "suplementos", "total",
    "dist_total", "dist_ocupado", "dist_libre", "dist_off",
    "p_carreras", "p_suplementos", "p_total",
    "p_dist_total", "p_dist_ocupado", "p_dist_libre", "p_dist_off",
}
INTEGER_FIELDS = {
    "num_servicios", "borrados", "licencia",
    "tiempo_ocupado", "tiempo_on",
    "p_num_servicios", "p_tiempo_ocupado", "p_tiempo_on",
}
DATE_FIELDS = {"fecha"}   # value = "DD/MM/YY HH:MM" → we split date + time

REQUIRED_FIELDS = {
    "fecha", "licencia",
    "carreras", "suplementos", "total",
    "p_carreras", "p_suplementos", "p_total",
}

# Regex helpers (compiled at import time by consumers).
NUMBER_RE = r"[-+]?\d[\d\.\,]*"
DATE_RE = r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{2,4})(?:\s+(\d{1,2})\s*:\s*(\d{2}))?"

# Contextual OCR digit fixes — applied ONLY to numeric fields.
DIGIT_FIX_MAP = str.maketrans({
    "O": "0", "o": "0", "Q": "0", "D": "0",
    "I": "1", "l": "1", "|": "1",
    "S": "5", "s": "5",
    "B": "8",
    "Z": "2", "z": "2",
    "G": "6",
    "T": "7",
})
