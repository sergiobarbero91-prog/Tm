"""
Taxi-driver journal (jornada) router.

A "jornada" is one work shift. The driver photographs the printed parciales
ticket of the taximeter at the start and at the end of the shift; we OCR
those photos with Gemini Vision and the difference between both readings is
the *real* shift totals. The driver can also log fuel expenses during the
shift and enter the cash collected at fixed-price (precio cerrado) plus card
and app earnings.

Endpoints (all under /api/journal):
  POST  /start            body: multipart with `photo` (image of opening ticket)
  POST  /fuel             body: {amount_eur, liters?, note?}
  POST  /end              body: multipart with `photo` + form fields
                          (precio_cerrado, cobrado_tarjeta, cobrado_app)
  GET   /active           current open journal for the user
  GET   /list             paginated history (last 30 by default)
  POST  /{id}/reparse     re-run OCR on an existing photo (manual correction)
  PUT   /{id}/manual      overwrite OCR values with manual entries
  DELETE /{id}            delete an entire journal (admin / owner only)
"""
from __future__ import annotations

import base64
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from shared import db, get_current_user_required, logger

router = APIRouter(prefix="/journal", tags=["Journal"])

MADRID_TZ = pytz.timezone("Europe/Madrid")
JOURNAL_COLLECTION = db["taxi_journals"]
PARCIAL_PHOTOS_DIR = "/app/backend/uploads/parciales"
os.makedirs(PARCIAL_PHOTOS_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────
class ParcialReading(BaseModel):
    """Numeric values extracted from a parciales ticket."""
    fecha: Optional[str] = None              # YYYY-MM-DD
    hora: Optional[str] = None               # HH:MM
    num_servicios: Optional[int] = None
    carreras_eur: Optional[float] = None     # facturación (€) del turno (sección P)
    dist_total_km: Optional[float] = None
    dist_ocupado_km: Optional[float] = None
    dist_libre_km: Optional[float] = None
    tiempo_ocupado: Optional[float] = None   # unidades tal cual las imprime el taxímetro
    tiempo_on: Optional[float] = None        # unidades tal cual las imprime el taxímetro
    # Bloques originales conservados para auditoría / edición manual
    totales_taximetro: Optional[Dict[str, Any]] = None   # sección superior (acumulado histórico)
    parcial_turno: Optional[Dict[str, Any]] = None       # sección "P " completa
    raw_ocr_text: Optional[str] = None       # for debugging & manual correction
    ocr_warnings: List[str] = Field(default_factory=list)


class FuelExpense(BaseModel):
    amount_eur: float
    liters: Optional[float] = None
    note: Optional[str] = None
    at: str  # ISO timestamp
    km_total_at_refuel: Optional[float] = None  # taximeter dist_total (km) when the refuel happened


class JournalEnd(BaseModel):
    precio_cerrado: float = 0.0     # cash from fixed-price rides
    cobrado_tarjeta: float = 0.0
    cobrado_app: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Local OCR via Tesseract (no external AI, no rate limits, no quota)
# ─────────────────────────────────────────────────────────────────────────────
#
# Estrategia:
#   1. Cargar bytes → PIL Image → np.ndarray (OpenCV BGR).
#   2. Preprocesado: escala de grises → resize x2 si es pequeño → CLAHE →
#      threshold adaptativo (Otsu) → deskew opcional.
#   3. Tesseract con lang=spa+eng, PSM 6 (bloque uniforme de texto).
#   4. Parsear el texto con regex tolerantes a variaciones de etiquetas
#      típicas de taxímetros españoles (Digitax, Semel, Taxitronic, etc.).
#   5. Devolver un dict con los mismos campos que antes + raw_ocr_text para
#      auditar y editar manualmente si algo sale mal.

# Etiquetas alternativas encontradas en tickets parciales de taxímetros ES
# (Digitax D5/D8, Semel Turmix, Taxitronic TM7, Ikon TX-80, etc.)
# Se compilan patrones flexibles: espacios variables, mayúsculas/minúsculas,
# acentos opcionales, y valores en formato español (1.234,56 o 1234,56).

_NUM_ES = r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+[.,]\d+|\d+)"
_TIME_HHMM = r"(\d{1,3}[:h]\d{2}(?:[:.]\d{2})?)"


def _es_to_float(s: str) -> Optional[float]:
    """Convierte '1.234,56' o '23,45' o '150.75' a float."""
    if not s:
        return None
    s = s.strip().replace(" ", "")
    # Formato español: coma decimal
    if "," in s and "." in s:
        # p.ej. "1.234,56" → "1234.56"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _hhmm_to_str(s: str) -> Optional[str]:
    """Normaliza '2h35', '2:35:04', '02:35' → 'HH:MM'."""
    if not s:
        return None
    m = re.search(r"(\d{1,3})[:h.](\d{2})", s)
    if not m:
        return None
    h, mm = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mm:02d}"


def _preprocess_for_ocr(image_bytes: bytes):
    """Devuelve una imagen PIL lista para pasar a Tesseract.

    Aplica auto-rotación probando las 4 orientaciones y quedándose con la que
    contiene más palabras-clave del ticket (más fiable que Tesseract OSD sobre
    fotos hechas encima de una sábana / mesa con textura).
    """
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image
    import io

    # Bytes → OpenCV
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        # Puede ser HEIC / WEBP; intentar vía PIL
        img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    # 1. Reescalar. 2400px produce el mejor equilibrio calidad/velocidad
    #    (probado con fotos móviles 12+ Mpx de tickets térmicos españoles).
    h, w = img.shape[:2]
    if max(h, w) > 2400:
        scale = 2400 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif max(h, w) < 1200:
        scale = 1200 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    def _prep_bw(mat, adaptive: bool = False):
        gray = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        if adaptive:
            bw = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 31, 15
            )
        else:
            gray = cv2.medianBlur(gray, 3)
            _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return bw

    # 2. Detectar rotación sobre MINIATURA para acelerar (~800ms vs 6s).
    KEYWORDS = ("FECHA", "LICENCIA", "CARRERAS", "SERVICIOS", "DIST", "TIEMPO",
                "TOTAL", "OCUPADO", "LIBRE", "PARCIAL", "SUPLEM", "BORRADOS")
    hh, ww = img.shape[:2]
    thumb_scale = 800 / max(hh, ww)
    thumb = cv2.resize(img, None, fx=thumb_scale, fy=thumb_scale, interpolation=cv2.INTER_AREA)

    best_score = -1
    best_angle = 0
    for angle, rot in [(0, None), (90, cv2.ROTATE_90_CLOCKWISE),
                       (180, cv2.ROTATE_180), (270, cv2.ROTATE_90_COUNTERCLOCKWISE)]:
        cand = thumb if rot is None else cv2.rotate(thumb, rot)
        try:
            sample = pytesseract.image_to_string(
                Image.fromarray(_prep_bw(cand)),
                lang="spa+eng",
                config="--oem 3 --psm 6",
            )
        except Exception:
            continue
        up = sample.upper()
        score = sum(1 for k in KEYWORDS if k in up)
        if score > best_score:
            best_score = score
            best_angle = angle

    # Aplicar rotación ganadora a la imagen grande y preprocesar UNA vez.
    if best_angle == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif best_angle == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif best_angle == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

    best_bw = _prep_bw(img)

    # 3. Deskew fino sobre la mejor rotación (corrige inclinaciones <15°)
    coords = np.column_stack(np.where(best_bw < 128))
    deskew_angle = 0.0
    if len(coords) > 500:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if 0.5 < abs(angle) < 15:
            deskew_angle = angle
            (h2, w2) = best_bw.shape
            M = cv2.getRotationMatrix2D((w2 // 2, h2 // 2), angle, 1.0)
            best_bw = cv2.warpAffine(
                best_bw, M, (w2, h2), flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            # Aplicar el mismo deskew a la imagen color para poder generar
            # la variante adaptativa alineada.
            img = cv2.warpAffine(
                img, M, (w2, h2), flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )

    # 4. Generar TAMBIÉN una variante con threshold adaptativo + unsharp mask
    #    (mejor con papel arrugado y sombras). El caller probará ambas y
    #    elegirá la que produzca más números decimales bien formados.
    adaptive_bw = _prep_bw(img, adaptive=True)

    return Image.fromarray(best_bw), Image.fromarray(adaptive_bw)


# ─── Regex patterns adaptados al formato REAL del taxímetro del usuario ────
#
# Un ticket parcial tiene DOS secciones:
#
#   Sección 1 — TOTALES ACUMULADOS del taxímetro (parte superior):
#     FECHA:           18/07/26 15:06
#     Nº LICENCIA:     09218
#     Num. Servicios:  4628
#     Carreras:        49854,10       ← acumulado histórico
#     Suplementos:     204,90
#     Total:           50059,00
#     Dist. Total:     52537,9
#     Dist. Ocupado:   25457,1
#     Dist. Libre:     26742,5
#     Dist. OFF:       339,0
#     Tiempo Ocupado:  557761
#     Tiempo On:       156015
#     Borrados:        454
#
#   Sección 2 — PARCIALES del turno actual (líneas con prefijo "P "):
#     P Nº de servs:      X
#     P Carreras:         X,XX        ← facturación del turno
#     P Suplementos:      X,XX
#     P Total:            X,XX
#     P Dist. Total:      X,X         ← km del turno
#     P Dist. Ocupado:    X,X
#     P Dist. Libre:      X,X
#     P Dist. OFF:        X,X
#     P Tiempo Ocupado:   X,X
#     P Tiempo On:        X
#
# Los campos principales que la app usa (num_servicios, carreras_eur, dist_*,
# tiempo_*) reflejan LA SECCIÓN P (parcial de la jornada). Los TOTALES
# acumulados se guardan aparte en `totales_taximetro` para auditoría.

# Número en formato español. IMPORTANTE: el orden de las alternativas importa
# (Python regex es first-match, no longest-match). Ponemos primero las
# variantes con decimal para que "49854,10" no se trunque a "498".
_NUM_ES = r"(-?\d+[.,]\d+|-?\d{1,3}(?:[.\s]\d{3})+|-?\d+)"


def _es_to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().replace(" ", "")
    if "," in s and "." in s:
        # p.ej. "1.234,56" (español) o "1,234.56" (inglés) — asumimos español
        # cuando la última coma es el separador decimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _es_to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"-?\d+", s.replace(".", "").replace(" ", ""))
    return int(m.group(0)) if m else None


def _fix_ocr_digits(s: str) -> str:
    """Corrige confusiones comunes de OCR en números: O→0, o→0, l/I→1, S→5, B→8."""
    if not s:
        return s
    return (
        s.replace("O", "0").replace("o", "0")
         .replace("l", "1").replace("I", "1").replace("|", "1")
    )


def _label_to_regex(lab: str) -> str:
    """Convierte una etiqueta legible en un patrón regex tolerante.

    Regla:
      - Cada espacio → `\\s+` (uno o más espacios/tabs)
      - Cada punto → `[.,]?` (punto opcional; a veces el OCR se lo come)
      - El resto de caracteres se escapan literalmente.
    """
    out: List[str] = []
    for ch in lab:
        if ch == " ":
            out.append(r"\s+")
        elif ch == ".":
            out.append(r"[.,]?")
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _find_value(text: str, label_variants: List[str], value_re: str) -> Optional[str]:
    """Busca cualquier variante de etiqueta seguida del valor en la misma línea."""
    for lab in label_variants:
        lab_re = _label_to_regex(lab)
        pat = rf"{lab_re}\s*[:!\-–—]?\s*{value_re}"
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


# Etiquetas exactas del ticket del usuario. Cada entrada es una lista con
# variantes (por si el OCR se traga acentos, espacios, etc.).
LABELS_ACUM = {
    "num_servicios":  ["Num. Servicios", "Num Servicios", "N Servicios",
                        "Numero Servicios", "Servicios"],
    "carreras_eur":   ["Carreras"],
    "suplementos":    ["Suplementos", "Surlementos"],  # (Tesseract a veces lee 'Surlementos')
    "total_eur":      ["Total"],
    "dist_total_km":  ["Dist. Total", "Dist Total"],
    "dist_ocupado_km":["Dist. Ocupado", "Dist Ocupado"],
    "dist_libre_km":  ["Dist. Libre", "Dist Libre"],
    "dist_off_km":    ["Dist. OFF", "Dist OFF", "Dist. Off", "Dist Off"],
    "tiempo_ocupado": ["Tiempo Ocupado"],
    "tiempo_on":      ["Tiempo On", "Tiempo ON"],
    "borrados":       ["Borrados"],
    "licencia":       ["Nº LICENCIA", "N LICENCIA", "N9 LICENCIA", "NS LICENCIA",
                        "N2 LICENCIA", "LICENCIA"],
}

LABELS_PARCIAL = {
    "num_servicios":  ["P N de servs", "P Nº de servs", "P N9 de servs",
                        "P Num servicios", "P Num. Servicios", "P Servicios"],
    "carreras_eur":   ["P Carreras"],
    "suplementos":    ["P Suplementos", "P Surlementos"],
    "total_eur":      ["P Total"],
    "dist_total_km":  ["P Dist Total", "P Dist. Total", "P.Dist. Total", "P.Dist Total"],
    "dist_ocupado_km":["P Dist Ocupado", "P Dist. Ocupado", "P.Dist. Ocupado", "P.Dist Ocupado"],
    "dist_libre_km":  ["P Dist Libre", "P Dist. Libre", "P.Dist. Libre"],
    "dist_off_km":    ["P Dist OFF", "P Dist. OFF", "P.Dist. OFF"],
    "tiempo_ocupado": ["P Tiempo Ocupado"],
    "tiempo_on":      ["P Tiempo On", "P Tiempo ON"],
}


def _parse_section(text: str, labels_map: Dict[str, List[str]]) -> Dict[str, Any]:
    """Parsea un bloque de texto contra un diccionario de etiquetas."""
    out: Dict[str, Any] = {}
    for key, variants in labels_map.items():
        raw = _find_value(text, variants, _NUM_ES)
        if raw is None:
            continue
        if key in ("num_servicios", "borrados", "licencia"):
            out[key] = _es_to_int(raw)
        else:
            out[key] = _es_to_float(_fix_ocr_digits(raw))
    return out


# Patrón que identifica una línea como PARCIAL: la palabra "P" (aislada por
# espacios o puntos) seguida en el mismo tramo por una etiqueta conocida
# (Carreras, Dist, Tiempo, Total, N, Suplementos, etc.).
_PARCIAL_LINE_RE = re.compile(
    r"\bP[\s.]+(?:N[°º9]?|Nº|Num|N |Carreras|Dist|Tiempo|Total|Suplem)",
    re.IGNORECASE,
)


def _parse_ticket_text(raw: str) -> Dict[str, Any]:
    """Extrae los campos del texto plano OCR con regex tolerantes.

    IMPORTANTE (política del usuario):
      - Los CAMPOS PRINCIPALES se toman SIEMPRE de la sección superior
        (TOTALES ACUMULADOS del taxímetro), NUNCA de las líneas "P …".
      - La jornada se calcula como `end.TOTALES - start.TOTALES` en el
        backend (_compute_totals).
      - La sección "P …" se ignora para el cálculo, sólo se guarda como
        referencia en `parcial_turno` (dato secundario).

    Devuelve un dict con:
      - campos principales (acumulados del taxímetro):
        fecha, hora, num_servicios, carreras_eur, dist_*_km, tiempo_*
      - `parcial_turno`: sección "P " (referencia, no usada en cálculos)
      - `raw_ocr_text`: texto crudo (se añade fuera)
    """
    text = raw
    out: Dict[str, Any] = {}

    # ── Fecha y hora (línea única "FECHA: DD/MM/YY HH:MM")
    m = re.search(
        r"FECHA[:!\s]*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:\s+(\d{1,2})[:.](\d{2}))?",
        text, re.IGNORECASE
    )
    if m:
        d, mth, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            y = "20" + y
        out["fecha"] = f"{y}-{int(mth):02d}-{int(d):02d}"
        if m.group(4):
            out["hora"] = f"{int(m.group(4)):02d}:{m.group(5)}"

    # ── Separar líneas de la sección "P " (para descartarlas del acumulado).
    #    Una línea es de la sección P si contiene "P <etiqueta_conocida>"
    #    en cualquier parte (tolerante a ruido OCR al inicio de la línea).
    acum_lines: List[str] = []
    parcial_lines: List[str] = []
    for line in text.splitlines():
        if _PARCIAL_LINE_RE.search(line):
            parcial_lines.append(line)
        else:
            acum_lines.append(line)

    acumulados = _parse_section("\n".join(acum_lines), LABELS_ACUM)
    parciales = _parse_section("\n".join(parcial_lines), LABELS_PARCIAL)

    # ── CAMPOS PRINCIPALES: SIEMPRE de los acumulados (política del usuario).
    #    La jornada se calcula como end.TOTAL - start.TOTAL.
    for key in ("num_servicios", "carreras_eur", "dist_total_km",
                "dist_ocupado_km", "dist_libre_km", "tiempo_ocupado", "tiempo_on"):
        if key in acumulados:
            out[key] = acumulados[key]

    # ── Fallback dist_libre si tenemos total y ocupado pero no libre
    if out.get("dist_total_km") and out.get("dist_ocupado_km") and out.get("dist_libre_km") is None:
        libre = out["dist_total_km"] - out["dist_ocupado_km"]
        if libre >= 0:
            out["dist_libre_km"] = round(libre, 2)

    # ── Guardar bloque de acumulados completo (extras: suplementos, total, etc.)
    if acumulados:
        out["totales_taximetro"] = acumulados

    # ── Guardar bloque parcial (referencia — no usado en cálculos)
    if parciales:
        out["parcial_turno"] = parciales

    return out


def _ocr_parcial_sync(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """OCR local con Tesseract. NO usa Gemini ni ninguna API externa.

    Estrategia de calidad:
      - Preprocesado Otsu (más limpio que adaptativo en tickets térmicos).
      - Doble pasada Tesseract con dos PSMs (Page Segmentation Modes):
          · PSM 4 → single column of text of variable sizes (mejor para
            tickets con dos columnas: etiqueta + valor).
          · PSM 6 → single uniform block (mejor para líneas densas).
      - MERGE de resultados: cada campo se toma del OCR que lo detectó.
        Si ambos lo detectan y difieren, se prefiere el PSM con mejor
        score total (más campos válidos).
    """
    import pytesseract

    try:
        img_bw, _adaptive = _preprocess_for_ocr(image_bytes)
    except Exception as e:
        logger.exception("[journal-ocr] preprocessing failed")
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo abrir la imagen: {e}",
        )

    def _try(psm: int) -> str:
        try:
            return pytesseract.image_to_string(
                img_bw, lang="spa+eng",
                config=f"--oem 3 --psm {psm} -c preserve_interword_spaces=1",
            )
        except Exception:
            return ""

    text_psm4 = _try(4)
    text_psm6 = _try(6)

    parsed_4 = _parse_ticket_text(text_psm4)
    parsed_6 = _parse_ticket_text(text_psm6)

    # Score = número de campos válidos en totales_taximetro (para desempatar)
    score_4 = len(parsed_4.get("totales_taximetro") or {})
    score_6 = len(parsed_6.get("totales_taximetro") or {})

    # ── Merge inteligente por campo ──
    # Para cada campo, elegimos entre PSM 4 y PSM 6 el valor "más fiable":
    #   - Valores en rango razonable
    #   - Valores con decimales (los tickets siempre imprimen X,Y en km)
    #     preferentes frente a enteros grandes (probable OCR sin coma)
    #   - Si no hay preferencia, cogemos el que exista

    def _looks_ocr_corrupt(key: str, val: Any) -> bool:
        """Heurísticas para detectar valores que huelen a error de OCR."""
        try:
            f = float(val)
        except (TypeError, ValueError):
            return True
        if key.startswith("dist_") and key.endswith("_km"):
            if f < 0 or f > 1_000_000:
                return True
            # Distancias en el taxímetro SIEMPRE tienen decimales.
            # Un entero grande sin coma sugiere OCR se comió el ',' → sospechoso.
            if f > 10_000 and f == int(f):
                return True
        if key == "carreras_eur":
            if f < 0 or f > 10_000_000:
                return True
            # Facturación €: también con decimales en cents.
            if f > 100_000 and f == int(f):
                return True
        if key == "num_servicios":
            if f < 0 or f > 999_999:
                return True
        return False

    def _pick(key: str) -> Any:
        v4 = parsed_4.get(key)
        v6 = parsed_6.get(key)
        c4 = _looks_ocr_corrupt(key, v4) if v4 is not None else True
        c6 = _looks_ocr_corrupt(key, v6) if v6 is not None else True
        # Prefer un valor NO corrupto sobre uno corrupto.
        if not c4 and c6: return v4
        if not c6 and c4: return v6
        if not c4 and not c6:
            # Ambos válidos: prefer decimal (no int) para campos numéricos.
            def has_dec(v):
                try: return float(v) != int(float(v))
                except (TypeError, ValueError): return False
            if has_dec(v4) and not has_dec(v6): return v4
            if has_dec(v6) and not has_dec(v4): return v6
            # Empate: prefer el del PSM con mejor score total
            return v4 if score_4 >= score_6 else v6
        # Ambos corruptos → devuelve cualquiera (o None)
        return v4 if v4 is not None else v6

    # Aplicar picking a los campos principales
    parsed: Dict[str, Any] = {}
    for key in ("fecha", "hora", "num_servicios", "carreras_eur",
                "dist_total_km", "dist_ocupado_km", "dist_libre_km",
                "tiempo_ocupado", "tiempo_on"):
        v = _pick(key)
        if v is not None:
            parsed[key] = v

    # totales_taximetro: merge campo-por-campo con la misma lógica
    tot_4 = parsed_4.get("totales_taximetro") or {}
    tot_6 = parsed_6.get("totales_taximetro") or {}
    tot_merged: Dict[str, Any] = {}
    all_keys = set(tot_4.keys()) | set(tot_6.keys())
    for k in all_keys:
        v4 = tot_4.get(k)
        v6 = tot_6.get(k)
        c4 = _looks_ocr_corrupt(k, v4) if v4 is not None else True
        c6 = _looks_ocr_corrupt(k, v6) if v6 is not None else True
        if not c4 and c6: tot_merged[k] = v4
        elif not c6 and c4: tot_merged[k] = v6
        elif not c4 and not c6: tot_merged[k] = v4 if score_4 >= score_6 else v6
        else: tot_merged[k] = v4 if v4 is not None else v6
    if tot_merged:
        parsed["totales_taximetro"] = tot_merged

    # parcial_turno (referencia): del que más tenga
    for src in (parsed_4, parsed_6):
        if src.get("parcial_turno") and "parcial_turno" not in parsed:
            parsed["parcial_turno"] = src["parcial_turno"]

    # Texto crudo del PSM con mayor score (para el usuario si abre "Corregir")
    raw_text = text_psm4 if score_4 >= score_6 else text_psm6

    # Score log (ya lo tenías arriba)
    logger.info(f"[journal-ocr] scores → psm4={score_4}, psm6={score_6}")

    # Consistency check: en el bloque acumulado del taxímetro debe cumplirse
    #     dist_total ≈ dist_ocupado + dist_libre  (+ dist_off, si existe)
    # Si el total detectado se desvía >20 % de esa suma, es MUY probable que
    # el OCR lo haya leído mal (números pegados de la línea anterior). En
    # ese caso lo recalculamos y avisamos.
    consistency_fixed: List[str] = []
    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    total = _num(parsed.get("dist_total_km"))
    ocup = _num(parsed.get("dist_ocupado_km"))
    libre = _num(parsed.get("dist_libre_km"))
    off = _num((parsed.get("totales_taximetro") or {}).get("dist_off_km"))

    if ocup is not None and libre is not None:
        computed = ocup + libre + (off or 0)
        if total is None or (computed > 0 and abs(total - computed) / computed > 0.20):
            parsed["dist_total_km"] = round(computed, 2)
            if "totales_taximetro" in parsed:
                parsed["totales_taximetro"]["dist_total_km"] = round(computed, 2)
            consistency_fixed.append(
                f"dist_total_km recalculado como ocupado+libre+off = {computed:.2f} km"
            )

    parsed["raw_ocr_text"] = raw_text.strip()

    # Warnings — campos que no se detectaron.
    warnings: List[str] = []
    for key in ("carreras_eur", "dist_total_km", "dist_ocupado_km", "dist_libre_km"):
        v = parsed.get(key)
        if v is None:
            warnings.append(f"campo {key} no detectado — revisa manualmente")

    # Sanity checks — rangos generosos (son acumulados históricos del taxímetro,
    # un taxi puede tener millones de € o cientos de miles de km acumulados).
    if parsed.get("dist_total_km") is not None:
        if parsed["dist_total_km"] < 0 or parsed["dist_total_km"] > 10_000_000:
            warnings.append("dist_total_km fuera de rango — revisa manualmente")
    if parsed.get("carreras_eur") is not None:
        if parsed["carreras_eur"] < 0 or parsed["carreras_eur"] > 10_000_000:
            warnings.append("carreras_eur fuera de rango — revisa manualmente")

    warnings.extend(consistency_fixed)
    parsed["ocr_warnings"] = warnings
    return parsed


async def _ocr_parcial(image_bytes: bytes, mime_type: str) -> ParcialReading:
    import asyncio
    data = await asyncio.to_thread(_ocr_parcial_sync, image_bytes, mime_type)
    return ParcialReading(**{k: v for k, v in data.items() if k in ParcialReading.model_fields})


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(MADRID_TZ).isoformat()


def _hhmm_to_minutes(t: Optional[str]) -> Optional[int]:
    if not t or ":" not in t:
        return None
    try:
        h, m = t.split(":")[:2]
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def _strip_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the BSON _id from a Mongo doc so it's JSON-serializable."""
    if doc is None:
        return doc
    doc = {**doc}
    doc.pop("_id", None)
    return doc


async def _save_photo(file: UploadFile, journal_id: str, suffix: str):
    """Persist the uploaded photo on disk, return (bytes, filename)."""
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "heic", "heif"):
            ext = "jpg"
    fname = f"{journal_id}_{suffix}.{ext}"
    fpath = os.path.join(PARCIAL_PHOTOS_DIR, fname)
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Imagen vacía. Vuelve a hacer la foto e inténtalo de nuevo.")
    size_mb = len(body) / (1024 * 1024)
    if size_mb > 20:
        raise HTTPException(
            status_code=413,
            detail=(
                f"La imagen ocupa {size_mb:.1f} MB y el máximo son 20 MB. "
                "Reduce la resolución antes de subirla."
            ),
        )
    logger.info(f"[journal] saving photo {fname} ({size_mb:.2f} MB, ext={ext})")
    with open(fpath, "wb") as f:
        f.write(body)
    return body, fname


def _compute_totals(journal: Dict[str, Any]) -> Dict[str, Any]:
    """Compute the diff between end and start parciales + revenue summary
    + extended productivity metrics."""
    start = journal.get("start_reading") or {}
    end = journal.get("end_reading") or {}
    end_payload = journal.get("end_payload") or {}
    fuel_entries = journal.get("fuel", []) or []

    def _diff(key: str) -> Optional[float]:
        a = start.get(key)
        b = end.get(key)
        if a is None or b is None:
            return None
        try:
            return round(float(b) - float(a), 2)
        except (ValueError, TypeError):
            return None

    def _diff_minutes(key: str) -> Optional[int]:
        """Return the difference of HH:MM fields in *minutes* (positive)."""
        a = _hhmm_to_minutes(start.get(key))
        b = _hhmm_to_minutes(end.get(key))
        if a is None or b is None:
            return None
        return (b - a + 24 * 60) % (24 * 60)

    def _fmt_hhmm(minutes: Optional[int]) -> Optional[str]:
        if minutes is None:
            return None
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    def _safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
        if num is None or den is None:
            return None
        try:
            if float(den) <= 0:
                return None
            return num / float(den)
        except (ValueError, TypeError):
            return None

    # ── Money ──
    carreras = _diff("carreras_eur") or 0.0
    fuel_total = sum(float(f.get("amount_eur", 0) or 0) for f in fuel_entries)
    precio_cerrado = float(end_payload.get("precio_cerrado", 0) or 0)
    tarjeta = float(end_payload.get("cobrado_tarjeta", 0) or 0)
    app_eur = float(end_payload.get("cobrado_app", 0) or 0)
    total_ingresos = round(carreras + precio_cerrado, 2)            # facturación
    total_neto = round(total_ingresos - fuel_total, 2)
    efectivo = round(total_ingresos - tarjeta - app_eur, 2)

    # ── Distance ──
    km_total = _diff("dist_total_km")
    km_ocupado = _diff("dist_ocupado_km")
    km_libre = _diff("dist_libre_km")
    pct_dist_ocupado = None
    if km_total and km_total > 0 and km_ocupado is not None:
        pct_dist_ocupado = round((km_ocupado / km_total) * 100, 1)

    # ── Time ──
    min_on = _diff_minutes("tiempo_on")           # work-effective minutes
    min_ocupado = _diff_minutes("tiempo_ocupado") # loaded minutes
    pct_tiempo_ocupacion = None
    if min_on and min_on > 0 and min_ocupado is not None:
        pct_tiempo_ocupacion = round((min_ocupado / min_on) * 100, 1)
    # Clock time (start_reading.hora → end_reading.hora)
    start_hhmm = _hhmm_to_minutes(start.get("hora"))
    end_hhmm = _hhmm_to_minutes(end.get("hora"))
    min_jornada = None
    if start_hhmm is not None and end_hhmm is not None:
        # Wrap past midnight
        min_jornada = (end_hhmm - start_hhmm + 24 * 60) % (24 * 60) or (24 * 60)

    # ── Rates ──
    eur_por_hora = None
    if min_jornada and min_jornada > 0:
        eur_por_hora = round(total_ingresos / (min_jornada / 60), 2)
    eur_por_km = _safe_div(total_ingresos, km_total)
    if eur_por_km is not None:
        eur_por_km = round(eur_por_km, 2)

    # ── Fuel cost per km (since last refuel, or whole shift) ──
    # Strategy: sum all refuels and divide by km between earliest refuel km and
    # end-of-shift km (best estimate). If km_total_at_refuel is missing, use
    # proportional approximation based on number of refuels.
    gasto_gasolina_por_km = None
    rendimiento_por_km = None
    rendimiento_por_eur_gasolina = None
    refuel_warning = None

    if fuel_total > 0:
        # km traveled since first refuel that has km_total_at_refuel recorded
        refuels_with_km = [f for f in fuel_entries if f.get("km_total_at_refuel") is not None]
        end_km_total = end.get("dist_total_km")
        if refuels_with_km and end_km_total is not None:
            try:
                first_refuel_km = float(min(f["km_total_at_refuel"] for f in refuels_with_km))
                km_since_first_refuel = float(end_km_total) - first_refuel_km
                # Only count refuels at or after the first valid one
                fuel_since_first = sum(
                    float(f.get("amount_eur", 0) or 0)
                    for f in fuel_entries
                    if f.get("km_total_at_refuel") is None
                    or float(f["km_total_at_refuel"]) >= first_refuel_km
                )
                if km_since_first_refuel > 0:
                    gasto_gasolina_por_km = round(fuel_since_first / km_since_first_refuel, 3)
                    # Facturación atribuida al mismo tramo (proporcional al km)
                    if km_total and km_total > 0:
                        facturacion_tramo = (km_since_first_refuel / km_total) * total_ingresos
                        rendimiento_por_eur_gasolina = round(facturacion_tramo / fuel_since_first, 2)
            except (ValueError, TypeError, KeyError):
                pass
        else:
            # Fallback: use the whole shift km
            if km_total and km_total > 0:
                gasto_gasolina_por_km = round(fuel_total / km_total, 3)
                rendimiento_por_eur_gasolina = round(total_ingresos / fuel_total, 2)
            refuel_warning = (
                "Para un cálculo más preciso del coste por km, repón gasolina justo "
                "antes de cerrar la jornada y anota los km del taxímetro al repostar."
            )

        # Rendimiento por km = €/km facturado − €/km gasolina
        if eur_por_km is not None and gasto_gasolina_por_km is not None:
            rendimiento_por_km = round(eur_por_km - gasto_gasolina_por_km, 2)

    media_eur_servicio = None
    ns_diff = _diff("num_servicios")
    if ns_diff and ns_diff > 0:
        media_eur_servicio = round(total_ingresos / ns_diff, 2)

    return {
        # Money
        "facturacion_taximetro_eur": round(carreras, 2),
        "precio_cerrado_eur": round(precio_cerrado, 2),
        "total_ingresos_eur": total_ingresos,                # facturación total (carreras + cerrado)
        "cobrado_tarjeta_eur": round(tarjeta, 2),
        "cobrado_app_eur": round(app_eur, 2),
        "cobrado_efectivo_eur": efectivo,
        "gasto_gasolina_eur": round(fuel_total, 2),
        "total_neto_eur": total_neto,
        # Counts / averages
        "num_servicios_diff": ns_diff,
        "media_eur_servicio": media_eur_servicio,
        # Time
        "tiempo_jornada_min": min_jornada,                   # horas trabajadas (reloj)
        "tiempo_jornada_str": _fmt_hhmm(min_jornada),
        "tiempo_on_min": min_on,                             # horas de trabajo efectivo
        "tiempo_on_diff": _fmt_hhmm(min_on),
        "tiempo_ocupado_min": min_ocupado,                   # horas cargado
        "tiempo_ocupado_diff": _fmt_hhmm(min_ocupado),
        "pct_tiempo_ocupacion": pct_tiempo_ocupacion,        # ocupado / on × 100
        # Distance
        "dist_total_diff_km": km_total,
        "dist_ocupado_diff_km": km_ocupado,
        "dist_libre_diff_km": km_libre,
        "pct_dist_ocupado": pct_dist_ocupado,                # km ocupado / km total × 100
        # Productivity
        "eur_por_hora": eur_por_hora,                        # facturación / horas trabajadas
        "eur_por_km": eur_por_km,                            # facturación / km totales
        "gasto_gasolina_por_km": gasto_gasolina_por_km,      # €/km de gasolina
        "rendimiento_por_km": rendimiento_por_km,            # €/km facturado − €/km gasolina
        "rendimiento_por_eur_gasolina": rendimiento_por_eur_gasolina,  # €facturados / €gasolina
        "refuel_warning": refuel_warning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stats aggregation (last N days / weeks / months)
# ─────────────────────────────────────────────────────────────────────────────
def _aggregate_period(journals: List[Dict[str, Any]], bucket: str) -> List[Dict[str, Any]]:
    """Group closed journals into day/week/month buckets and compute totals."""
    from collections import defaultdict
    buckets: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "neto_eur": 0.0, "ingresos_eur": 0.0, "gasolina_eur": 0.0,
        "km_total": 0.0, "km_ocupado": 0.0, "min_on": 0.0,
        "servicios": 0, "jornadas": 0,
    })
    for j in journals:
        if j.get("status") != "closed":
            continue
        end_at = j.get("end_at") or j.get("start_at")
        if not end_at:
            continue
        try:
            dt = datetime.fromisoformat(end_at)
        except ValueError:
            continue
        # Determine bucket key
        if bucket == "day":
            key = dt.strftime("%Y-%m-%d")
        elif bucket == "week":
            iso = dt.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:  # month
            key = dt.strftime("%Y-%m")
        t = j.get("totals") or {}
        b = buckets[key]
        b["neto_eur"] += float(t.get("total_neto_eur", 0) or 0)
        b["ingresos_eur"] += float(t.get("total_ingresos_eur", 0) or 0)
        b["gasolina_eur"] += float(t.get("gasto_gasolina_eur", 0) or 0)
        b["km_total"] += float(t.get("dist_total_diff_km", 0) or 0)
        b["km_ocupado"] += float(t.get("dist_ocupado_diff_km", 0) or 0)
        b["min_on"] += float(t.get("tiempo_on_min", 0) or 0)
        b["servicios"] += int(t.get("num_servicios_diff", 0) or 0)
        b["jornadas"] += 1
    # Sort chronologically
    out = []
    for k in sorted(buckets.keys()):
        d = buckets[k]
        eur_h = round(d["ingresos_eur"] / (d["min_on"] / 60), 2) if d["min_on"] > 0 else None
        eur_km = round(d["ingresos_eur"] / d["km_total"], 2) if d["km_total"] > 0 else None
        out.append({
            "bucket": k,
            "neto_eur": round(d["neto_eur"], 2),
            "ingresos_eur": round(d["ingresos_eur"], 2),
            "gasolina_eur": round(d["gasolina_eur"], 2),
            "km_total": round(d["km_total"], 1),
            "km_ocupado": round(d["km_ocupado"], 1),
            "horas_on": round(d["min_on"] / 60, 2),
            "servicios": d["servicios"],
            "jornadas": d["jornadas"],
            "eur_por_hora": eur_h,
            "eur_por_km": eur_km,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{journal_id}/photo/{which}")
async def get_journal_photo(
    journal_id: str,
    which: str,   # "start" or "end"
    thumb: int = 0,  # ?thumb=1 → return 400px width JPEG (~15-40 KB)
    user=Depends(get_current_user_required),
):
    """Serve a taximeter photo (start or end) for a given journal.

    Enforces ownership: only the user who owns the journal (or an admin) can
    fetch the file. Passing ?thumb=1 returns a resized JPEG optimised for
    listing thumbnails.
    """
    if which not in ("start", "end"):
        raise HTTPException(status_code=400, detail="which must be 'start' or 'end'")

    journal = await JOURNAL_COLLECTION.find_one({"id": journal_id}, {"_id": 0})
    if not journal:
        raise HTTPException(status_code=404, detail="Jornada no encontrada.")
    if journal["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="No autorizado.")

    fname = journal.get(f"{which}_photo")
    if not fname:
        raise HTTPException(status_code=404, detail=f"Foto de {which} no disponible.")

    fpath = os.path.join(PARCIAL_PHOTOS_DIR, fname)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Fichero de foto no encontrado en el servidor.")

    if thumb:
        # Miniatura on-the-fly: 400px ancho, JPEG q=75 → ~20 KB.
        try:
            from PIL import Image
            import io
            with Image.open(fpath) as im:
                im = im.convert("RGB")
                im.thumbnail((400, 400), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=75, optimize=True)
                buf.seek(0)
                from fastapi.responses import Response
                return Response(
                    content=buf.getvalue(),
                    media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"},
                )
        except Exception as e:
            logger.exception("[journal] thumbnail generation failed: %s", e)
            # Fallback: servir original
            pass

    from fastapi.responses import FileResponse
    return FileResponse(fpath, headers={"Cache-Control": "private, max-age=3600"})


@router.post("/start")
async def start_journal(
    photo: UploadFile = File(...),
    user=Depends(get_current_user_required),
):
    """Open a new journal by uploading the photo of the opening parciales."""
    existing = await JOURNAL_COLLECTION.find_one(
        {"user_id": user["id"], "status": "open"},
        {"_id": 0},
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ya tienes una jornada abierta. Ciérrala antes de iniciar otra.",
        )

    journal_id = str(uuid.uuid4())
    body, fname = await _save_photo(photo, journal_id, "start")
    mime = photo.content_type or "image/jpeg"
    reading = await _ocr_parcial(body, mime)

    doc = {
        "id": journal_id,
        "user_id": user["id"],
        "status": "open",
        "start_reading": reading.model_dump(),
        "start_photo": fname,
        "start_at": _now_iso(),
        "fuel": [],
        "end_reading": None,
        "end_photo": None,
        "end_payload": None,
        "end_at": None,
        "totals": None,
        "created_at": _now_iso(),
    }
    await JOURNAL_COLLECTION.insert_one(doc.copy())
    return _strip_id(doc)


@router.post("/fuel")
async def add_fuel(
    amount_eur: float = Form(...),
    liters: Optional[float] = Form(None),
    note: Optional[str] = Form(None),
    km_total_at_refuel: Optional[float] = Form(None),
    user=Depends(get_current_user_required),
):
    """Add a fuel expense to the currently-open journal."""
    if amount_eur <= 0:
        raise HTTPException(status_code=400, detail="El importe debe ser mayor que 0.")
    journal = await JOURNAL_COLLECTION.find_one(
        {"user_id": user["id"], "status": "open"},
        {"_id": 0},
    )
    if not journal:
        raise HTTPException(status_code=404, detail="No hay jornada abierta.")
    entry = FuelExpense(
        amount_eur=round(amount_eur, 2),
        liters=liters,
        note=(note or "").strip() or None,
        at=_now_iso(),
        km_total_at_refuel=round(km_total_at_refuel, 2) if km_total_at_refuel is not None else None,
    ).model_dump()
    await JOURNAL_COLLECTION.update_one(
        {"id": journal["id"]},
        {"$push": {"fuel": entry}},
    )
    journal["fuel"].append(entry)
    return _strip_id(journal)


@router.post("/end")
async def end_journal(
    photo: UploadFile = File(...),
    precio_cerrado: float = Form(0.0),
    cobrado_tarjeta: float = Form(0.0),
    cobrado_app: float = Form(0.0),
    user=Depends(get_current_user_required),
):
    """Close the journal with the closing parciales photo + manual entries."""
    journal = await JOURNAL_COLLECTION.find_one(
        {"user_id": user["id"], "status": "open"},
        {"_id": 0},
    )
    if not journal:
        raise HTTPException(status_code=404, detail="No hay jornada abierta.")

    body, fname = await _save_photo(photo, journal["id"], "end")
    mime = photo.content_type or "image/jpeg"
    reading = await _ocr_parcial(body, mime)

    end_payload = JournalEnd(
        precio_cerrado=round(precio_cerrado, 2),
        cobrado_tarjeta=round(cobrado_tarjeta, 2),
        cobrado_app=round(cobrado_app, 2),
    ).model_dump()

    journal.update({
        "status": "closed",
        "end_reading": reading.model_dump(),
        "end_photo": fname,
        "end_payload": end_payload,
        "end_at": _now_iso(),
    })
    journal["totals"] = _compute_totals(journal)

    await JOURNAL_COLLECTION.update_one(
        {"id": journal["id"]},
        {"$set": {
            "status": journal["status"],
            "end_reading": journal["end_reading"],
            "end_photo": journal["end_photo"],
            "end_payload": journal["end_payload"],
            "end_at": journal["end_at"],
            "totals": journal["totals"],
        }},
    )
    return _strip_id(journal)


@router.get("/active")
async def active_journal(user=Depends(get_current_user_required)):
    """Return the user's open journal, if any."""
    doc = await JOURNAL_COLLECTION.find_one(
        {"user_id": user["id"], "status": "open"},
        {"_id": 0},
    )
    return doc or {"active": False}


@router.get("/list")
async def list_journals(
    limit: int = 30,
    user=Depends(get_current_user_required),
):
    """List the user's recent journals (most recent first)."""
    limit = max(1, min(limit, 200))
    cursor = JOURNAL_COLLECTION.find(
        {"user_id": user["id"]},
        {"_id": 0},
    ).sort("start_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


@router.get("/stats")
async def journal_stats(
    bucket: str = "day",   # day | week | month
    days: int = 90,        # window
    user=Depends(get_current_user_required),
):
    """Aggregated stats for charts: neto, ingresos, gasolina, km, €/h, €/km
    grouped by day/week/month over the last `days` days."""
    if bucket not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail="bucket debe ser day|week|month")
    days = max(7, min(days, 365))
    # Get all closed journals within window
    cursor = JOURNAL_COLLECTION.find(
        {"user_id": user["id"], "status": "closed"},
        {"_id": 0},
    ).sort("end_at", -1).limit(500)
    journals = await cursor.to_list(length=500)
    series = _aggregate_period(journals, bucket)
    # Filter to the last `days`
    cutoff = datetime.now(MADRID_TZ).date()
    if series and bucket == "day":
        from datetime import timedelta as _td
        min_date = (cutoff - _td(days=days)).isoformat()
        series = [s for s in series if s["bucket"] >= min_date]
    # Overall summary across the filtered series
    totals = {
        "neto_eur": round(sum(s["neto_eur"] for s in series), 2),
        "ingresos_eur": round(sum(s["ingresos_eur"] for s in series), 2),
        "gasolina_eur": round(sum(s["gasolina_eur"] for s in series), 2),
        "km_total": round(sum(s["km_total"] for s in series), 1),
        "horas_on": round(sum(s["horas_on"] for s in series), 2),
        "jornadas": sum(s["jornadas"] for s in series),
        "servicios": sum(s["servicios"] for s in series),
    }
    totals["eur_por_hora"] = round(totals["ingresos_eur"] / totals["horas_on"], 2) if totals["horas_on"] > 0 else None
    totals["eur_por_km"] = round(totals["ingresos_eur"] / totals["km_total"], 2) if totals["km_total"] > 0 else None
    return {"bucket": bucket, "days": days, "series": series, "totals": totals}


@router.get("/summary")
async def journal_summary(
    start: str,
    end: str,
    user=Depends(get_current_user_required),
):
    """Return aggregated metrics for closed journals within an inclusive date range.

    `start` and `end` must be YYYY-MM-DD. The end date is inclusive (matches the
    full day in Madrid local time)."""
    from datetime import date as _date, timedelta as _td
    try:
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fechas inválidas (YYYY-MM-DD)")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="La fecha final debe ser ≥ inicial.")

    cursor = JOURNAL_COLLECTION.find(
        {"user_id": user["id"], "status": "closed"},
        {"_id": 0},
    ).sort("end_at", 1).limit(1000)
    all_journals = await cursor.to_list(length=1000)

    # Filter by date
    def _journal_date(j: Dict[str, Any]) -> Optional[_date]:
        at = j.get("end_at") or j.get("start_at")
        if not at:
            return None
        try:
            return datetime.fromisoformat(at).date()
        except ValueError:
            return None

    journals = [
        j for j in all_journals
        if (d := _journal_date(j)) is not None and start_d <= d <= end_d
    ]

    # Per-day breakdown (for variable-daily salary mode)
    daily_map: Dict[str, Dict[str, float]] = {}
    for j in journals:
        d = _journal_date(j)
        if not d:
            continue
        key = d.isoformat()
        t = j.get("totals") or {}
        row = daily_map.setdefault(key, {
            "ingresos_eur": 0.0, "gasolina_eur": 0.0, "neto_eur": 0.0,
            "km_total": 0.0, "horas_on": 0.0, "servicios": 0, "jornadas": 0,
        })
        row["ingresos_eur"] += float(t.get("total_ingresos_eur", 0) or 0)
        row["gasolina_eur"] += float(t.get("gasto_gasolina_eur", 0) or 0)
        row["neto_eur"] += float(t.get("total_neto_eur", 0) or 0)
        row["km_total"] += float(t.get("dist_total_diff_km", 0) or 0)
        row["horas_on"] += float(t.get("tiempo_on_min", 0) or 0) / 60.0
        row["servicios"] += int(t.get("num_servicios_diff", 0) or 0)
        row["jornadas"] += 1

    daily = [
        {"date": k, **{kk: round(vv, 2) for kk, vv in v.items()}}
        for k, v in sorted(daily_map.items())
    ]

    # Totals across the whole range
    totals = {
        "ingresos_eur": round(sum(d["ingresos_eur"] for d in daily), 2),
        "gasolina_eur": round(sum(d["gasolina_eur"] for d in daily), 2),
        "neto_eur": round(sum(d["neto_eur"] for d in daily), 2),
        "km_total": round(sum(d["km_total"] for d in daily), 1),
        "horas_on": round(sum(d["horas_on"] for d in daily), 2),
        "servicios": sum(int(d["servicios"]) for d in daily),
        "jornadas": sum(int(d["jornadas"]) for d in daily),
        "dias_trabajados": len(daily),
    }
    totals["eur_por_hora"] = round(totals["ingresos_eur"] / totals["horas_on"], 2) if totals["horas_on"] > 0 else None
    totals["eur_por_km"] = round(totals["ingresos_eur"] / totals["km_total"], 2) if totals["km_total"] > 0 else None

    # Also aggregate detailed time/distance from journals' raw totals (sum)
    extra = {
        "carreras_eur": 0.0, "precio_cerrado_eur": 0.0,
        "cobrado_tarjeta_eur": 0.0, "cobrado_app_eur": 0.0, "cobrado_efectivo_eur": 0.0,
        "tiempo_jornada_min": 0, "tiempo_on_min": 0, "tiempo_ocupado_min": 0,
        "dist_total_diff_km": 0.0, "dist_ocupado_diff_km": 0.0, "dist_libre_diff_km": 0.0,
    }
    for j in journals:
        t = j.get("totals") or {}
        for k in extra:
            v = t.get(k)
            if v is not None:
                extra[k] += float(v)
    # Round
    for k in extra:
        extra[k] = round(extra[k], 2 if "eur" in k else 1)
    # Percentages
    pct_tiempo = round(extra["tiempo_ocupado_min"] / extra["tiempo_on_min"] * 100, 1) if extra["tiempo_on_min"] > 0 else None
    pct_dist = round(extra["dist_ocupado_diff_km"] / extra["dist_total_diff_km"] * 100, 1) if extra["dist_total_diff_km"] > 0 else None
    extra["pct_tiempo_ocupacion"] = pct_tiempo
    extra["pct_dist_ocupado"] = pct_dist

    return {
        "start": start,
        "end": end,
        "totals": {**totals, **extra},
        "daily": daily,
    }


@router.put("/{journal_id}/manual")
async def manual_override(
    journal_id: str,
    field: str = Form(...),         # "start" or "end"
    payload: str = Form(...),       # JSON string of overrides
    user=Depends(get_current_user_required),
):
    """Manually correct OCR mistakes for a given parciales reading."""
    import json as _json
    if field not in ("start", "end"):
        raise HTTPException(status_code=400, detail="field must be 'start' or 'end'")
    try:
        data = _json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="payload no es JSON válido")

    journal = await JOURNAL_COLLECTION.find_one(
        {"id": journal_id, "user_id": user["id"]},
        {"_id": 0},
    )
    if not journal:
        raise HTTPException(status_code=404, detail="Jornada no encontrada.")

    reading_key = "start_reading" if field == "start" else "end_reading"
    current = journal.get(reading_key) or {}
    merged = {**current}
    for k, v in data.items():
        if k in ParcialReading.model_fields:
            merged[k] = v
    journal[reading_key] = merged

    update = {reading_key: merged}
    if journal.get("status") == "closed":
        journal["totals"] = _compute_totals(journal)
        update["totals"] = journal["totals"]

    await JOURNAL_COLLECTION.update_one({"id": journal_id}, {"$set": update})
    return _strip_id(journal)


@router.delete("/{journal_id}")
async def delete_journal(
    journal_id: str,
    user=Depends(get_current_user_required),
):
    journal = await JOURNAL_COLLECTION.find_one(
        {"id": journal_id, "user_id": user["id"]},
        {"_id": 0},
    )
    if not journal:
        raise HTTPException(status_code=404, detail="Jornada no encontrada.")
    await JOURNAL_COLLECTION.delete_one({"id": journal_id})
    return {"success": True, "id": journal_id}
