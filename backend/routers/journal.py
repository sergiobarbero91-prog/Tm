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
from fastapi.concurrency import run_in_threadpool
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

    # 1. Reescalar. 2400 px produce el mejor equilibrio calidad/velocidad
    #    en tickets térmicos: dígitos ~35 px de alto — suficiente para
    #    distinguir 5/3, 8/6. Combinado con binarización POR FILA (abajo)
    #    en el OCR posicional, evita el sesgo Otsu global.
    h, w = img.shape[:2]
    if max(h, w) > 2400:
        scale = 2400 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    elif max(h, w) < 1200:
        scale = 1200 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    def _prep_bw(mat, adaptive: bool = False):
        """Preprocesado calibrado para tickets de taxímetros.

        Sencillo y efectivo: CLAHE + median blur + Otsu. Probado con foto
        real dando 8/9 campos correctos. Pruebas con denoising / bilateral
        filter / unsharp mask empeoraron el resultado (introducían
        falsos dígitos por sobre-enhancement).
        """
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

    # 3. Deskew fino sobre la mejor rotación (corrige inclinaciones <15°).
    #
    #    Estrategia dual (recomendada por el usuario):
    #      a) HoughLinesP → detecta líneas rectas del texto/marco del ticket
    #         y calcula la mediana del ángulo. Muy fiable con tickets
    #         térmicos que tienen líneas horizontales claras.
    #      b) minAreaRect sobre coords de píxeles negros (fallback).
    #    Elegimos HoughLinesP si detecta suficientes líneas horizontales;
    #    si no, caemos a minAreaRect.
    deskew_angle = 0.0

    # (a) HoughLinesP: detectar líneas ~horizontales
    edges = cv2.Canny(best_bw, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, rho=1, theta=np.pi / 180, threshold=200,
        minLineLength=best_bw.shape[1] // 4, maxLineGap=20,
    )
    hough_angle = None
    if lines is not None and len(lines) >= 5:
        angles = []
        for x1, y1, x2, y2 in lines[:, 0]:
            if x2 == x1:
                continue
            a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Sólo líneas cercanas a horizontales (±15°)
            if -15 < a < 15:
                angles.append(a)
        if len(angles) >= 5:
            hough_angle = float(np.median(angles))

    # (b) Fallback: minAreaRect
    minarea_angle = None
    coords = np.column_stack(np.where(best_bw < 128))
    if len(coords) > 500:
        a = cv2.minAreaRect(coords)[-1]
        if a < -45:
            a = -(90 + a)
        else:
            a = -a
        if 0.5 < abs(a) < 15:
            minarea_angle = a

    # Elegir el ángulo — preferir Hough (más robusto en tickets)
    chosen_angle = hough_angle if hough_angle is not None else minarea_angle

    if chosen_angle is not None and 0.5 < abs(chosen_angle) < 15:
        deskew_angle = chosen_angle
        (h2, w2) = best_bw.shape
        M = cv2.getRotationMatrix2D((w2 // 2, h2 // 2), chosen_angle, 1.0)
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

    # Grayscale con CLAHE aplicada — para binarización POR FILA en el
    # OCR posicional. Cada crop de fila se binariza con Otsu local, lo
    # que evita que un umbral global engorde los trazos en filas de
    # tinta térmica más apagada (típico de dígitos 5/3, 8/6 mal leídos).
    gray_clahe = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray_clahe = _clahe.apply(gray_clahe)

    return Image.fromarray(best_bw), Image.fromarray(adaptive_bw), Image.fromarray(gray_clahe)


# Palabras que identifican cada campo en la sección de acumulados.
# Cada key mapea a: (palabras de la etiqueta a buscar, campo destino).
# Para OCR posicional se busca la última palabra clave y se extrae la región
# a la derecha en la misma fila.
POSITIONAL_LABELS = [
    # (last_word_of_label, dest_key, must_not_be_preceded_by_P)
    ("Servicios",  "num_servicios",   True),
    ("Carreras",   "carreras_eur",    True),
    ("Suplementos","suplementos",     True),
    ("Total",      "total_eur",       True),   # "Total" solo (no "Dist. Total")
    ("Total",      "dist_total_km",   True),   # segunda ocurrencia después de "Dist"
    ("Ocupado",    "dist_ocupado_km", True),
    ("Libre",      "dist_libre_km",   True),
    ("OFF",        "dist_off_km",     True),
    ("Ocupado",    "tiempo_ocupado",  True),   # segunda ocurrencia (Tiempo Ocupado)
    ("On",         "tiempo_on",       True),
    ("Borrados",   "borrados",        True),
    ("LICENCIA",   "licencia",        True),
]


def _ocr_values_positional(pil_bw, pil_adp=None, pil_gray=None) -> Dict[str, Any]:
    """OCR posicional: usa image_to_data para localizar etiquetas y hacer
    una segunda pasada de OCR sobre la región a la derecha de cada etiqueta,
    con whitelist restrictiva de dígitos + coma + punto.

    Esto es mucho más robusto que parsear el texto plano del OCR porque:
      1. Cada valor se OCR-ea aislado con `--psm 7` (una sola línea).
      2. Con `-c tessedit_char_whitelist=0123456789.,` Tesseract sólo puede
         devolver esos caracteres — imposible confundir ',' con '/', '5'
         con letra, etc.
      3. No depende de que la salida de texto plano preserve el layout.

    Si se pasa `pil_adp` (variante adaptativa), el OCR final del recorte
    numérico se hace sobre AMBAS imágenes y se elige el valor con más dígitos
    y decimales. Si se pasa `pil_gray` (grayscale con CLAHE), se hace
    binarización LOCAL POR FILA (evita el sesgo Otsu global que engorda
    trazos en filas de tinta apagada).
    """
    import pytesseract
    import cv2
    import numpy as np

    # Convertir PIL → numpy para poder recortar con OpenCV
    arr = np.array(pil_bw)  # ya es escala de grises B/N
    arr_adp = np.array(pil_adp) if pil_adp is not None else None
    arr_gray = np.array(pil_gray) if pil_gray is not None else None
    H, W = arr.shape[:2]

    # 1) image_to_data para ubicar las palabras (usamos la Otsu — más fiable
    #    para detectar etiquetas de texto en tickets térmicos).
    try:
        data = pytesseract.image_to_data(
            pil_bw, lang="spa+eng",
            config="--oem 3 --psm 6 -c load_system_dawg=0 -c load_freq_dawg=0",
            output_type=pytesseract.Output.DICT,
        )
    except Exception:
        return {}

    words = []
    for i, txt in enumerate(data.get("text") or []):
        t = (txt or "").strip()
        if not t:
            continue
        try:
            words.append({
                "text": t,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
                "line": int(data["line_num"][i]),
                "block": int(data["block_num"][i]),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    if not words:
        return {}

    # ── Estimar el borde derecho del TICKET (área útil) ──
    # Las palabras que son numéricas o etiquetas típicas ("Dist.", "Total:", etc.)
    # marcan el área real del ticket. El máximo x de esos elementos + un pequeño
    # margen es el límite derecho global — evita meter basura del fondo
    # (sábana, marco, texturas) en los crops.
    _ANCHOR_KEYWORDS = {"DIST", "TOTAL", "TIEMPO", "BORRADOS", "CARRERAS", "SUPLEMENTOS",
                        "OCUPADO", "LIBRE", "OFF", "SERVICIOS", "LICENCIA", "FECHA", "NUM"}
    right_edges = []
    for w in words:
        wu = re.sub(r"[^\w]", "", w["text"].upper())
        is_numeric = sum(1 for c in w["text"] if c.isdigit()) >= 2
        is_anchor = wu in _ANCHOR_KEYWORDS
        if is_numeric or is_anchor:
            right_edges.append(w["x"] + w["w"])
    # Usar el percentil 95 para descartar palabras "outlier" (basura extrema)
    if len(right_edges) >= 10:
        right_edges.sort()
        right_edge = right_edges[int(len(right_edges) * 0.95)] + 30
        right_edge = min(right_edge, W)
    else:
        right_edge = W
    logger.debug(f"[positional] right_edge = {right_edge}/{W}")

    # ── Estrategia: para cada etiqueta, encontrar en la MISMA fila la
    # palabra que Tesseract ya identificó como numérica (dígitos + coma)
    # y hacer crop EXACTO de esa palabra. Es mucho más preciso que
    # cortar "desde la etiqueta hasta el borde", porque:
    #   1. El crop es tiny → OCR más rápido y sin ruido.
    #   2. Ignoramos automáticamente la columna P y basura del fondo.
    #   3. Podemos AMPLIAR ese crop lateralmente para recuperar decimales
    #      que Tesseract se comió (ej: leyó "3233/79" en vez de "52537,9").
    _NUM_LOOKS_LIKE = re.compile(r"^[\d.,:]+[/-]?\d*$")

    def _numeric_words_on_line(label_w: Dict) -> List[Dict]:
        """Devuelve palabras a la DERECHA del label, en la misma línea,
        cuyo texto parece un número (dígitos + coma/punto/dos-puntos)."""
        out = []
        for w in words:
            if (w["block"] == label_w["block"]
                and w["line"] == label_w["line"]
                and w["x"] > label_w["x"] + label_w["w"] // 2):
                # Filtrar por contenido: al menos 2 dígitos
                if sum(1 for c in w["text"] if c.isdigit()) >= 2:
                    out.append(w)
        out.sort(key=lambda o: o["x"])
        return out

    # 2) Para cada etiqueta buscada, encontrar sus ocurrencias por texto
    def _find_word_occurrences(keyword: str, must_not_preceded_by_P: bool) -> List[Dict]:
        """Devuelve todas las words cuyo texto contiene keyword (case-insensitive),
        opcionalmente descartando aquellas cuya línea empieza por 'P '.

        Búsqueda tolerante: acepta hasta 1 carácter distinto en labels de
        ≥6 letras (p.ej. 'Suplementos' vs 'Surlementos' — típica confusión
        OCR P↔R). Esto evita perder valores cuando Tesseract confunde una
        letra de la etiqueta."""
        keyword_up = keyword.upper()
        kk = re.sub(r"[^\w]", "", keyword_up)

        def _fuzzy_match(a: str, b: str) -> bool:
            """True si a y b coinciden con hasta 1 sustitución (misma longitud)."""
            if len(a) != len(b):
                return False
            diff = sum(1 for x, y in zip(a, b) if x != y)
            return diff <= 1

        hits = []
        for w in words:
            wu = re.sub(r"[^\w]", "", w["text"].upper())
            matched = (
                wu == kk
                or (len(kk) >= 4 and kk in wu)
                or (len(kk) >= 6 and _fuzzy_match(wu, kk))
            )
            if not matched:
                continue
            if must_not_preceded_by_P:
                # Comprobar si en la MISMA línea hay una "P" al inicio
                same_line_words = [
                    ow for ow in words
                    if ow["block"] == w["block"] and ow["line"] == w["line"]
                ]
                same_line_words.sort(key=lambda o: o["x"])
                if same_line_words:
                    first = same_line_words[0]
                    # Si la primera palabra es exactamente "P" o "P." descartar
                    if re.fullmatch(r"[Pp][.,:]?", first["text"]):
                        continue
            hits.append(w)
        return hits

    # 3) Extraer el número de cada campo
    result: Dict[str, Any] = {}
    _all_candidates: Dict[str, List[str]] = {}   # todos los raw_values por campo
    label_used_positions = set()  # (block, line, x) para no reutilizar la misma etiqueta

    # Recorrido en orden: primero labels específicas (Servicios, Carreras, etc.),
    # luego "Total" (dos ocurrencias — 1º Total, 2º Dist. Total),
    # luego "Ocupado" (dos: Dist. Ocupado y Tiempo Ocupado).
    for keyword, dest_key, no_p in POSITIONAL_LABELS:
        occurrences = _find_word_occurrences(keyword, no_p)
        # Descartar ocurrencias ya usadas
        remaining = [w for w in occurrences
                     if (w["block"], w["line"], w["x"]) not in label_used_positions]
        if not remaining:
            continue
        # Ordenar por posición vertical (top-down)
        remaining.sort(key=lambda w: (w["y"], w["x"]))
        # Tomar la primera no usada
        label_word = remaining[0]
        label_used_positions.add((label_word["block"], label_word["line"], label_word["x"]))

        # ── Estrategia principal: usar coordenadas de la palabra numérica
        # que Tesseract ya localizó en la MISMA fila que el label.
        num_words = _numeric_words_on_line(label_word)

        # Coordenadas del crop AMPLIO (fallback): desde el fin del label
        # hasta el borde derecho DETECTADO del ticket. Sirve cuando Tesseract
        # identificó mal la palabra numérica (ej: "3233/79" en vez de "52537,9").
        wide_x0 = min(label_word["x"] + label_word["w"] + 10, W - 1)
        wide_x1 = min(label_word["x"] + label_word["w"] + 600, right_edge)
        wide_x1 = max(wide_x1, wide_x0 + 30)  # asegurar tamaño mínimo
        wide_y0 = max(label_word["y"] - 4, 0)
        wide_y1 = min(label_word["y"] + label_word["h"] + 4, H)

        # Crops candidatos: (nombre, crop_bw, crop_adp, crop_gray)
        # NOTA: crop_gray (binarización LOCAL) probado y desactivado —
        # genera candidatos con dígitos extra del contexto que ganan
        # por número de caracteres a los correctos. Se mantiene la
        # infraestructura por si en el futuro se quiere activar por
        # campo específico.
        crop_candidates: List[tuple] = []

        if num_words:
            v = num_words[0]
            v_right = v["x"] + v["w"]
            for extra in num_words[1:]:
                if extra["x"] - v_right < 40:
                    v_right = extra["x"] + extra["w"]
                else:
                    break
            x0 = max(v["x"] - 5, 0)
            x1 = min(v_right + 30, W)
            y0 = max(v["y"] - 4, 0)
            y1 = min(v["y"] + v["h"] + 4, H)
            crop_candidates.append((
                "narrow",
                arr[y0:y1, x0:x1],
                arr_adp[y0:y1, x0:x1] if arr_adp is not None else None,
                None,  # gray desactivado (ver nota arriba)
            ))

        # Siempre añadir el crop AMPLIO como candidato alternativo
        # (SIN gray — evita meter ruido del margen del ticket)
        crop_candidates.append((
            "wide",
            arr[wide_y0:wide_y1, wide_x0:wide_x1],
            arr_adp[wide_y0:wide_y1, wide_x0:wide_x1] if arr_adp is not None else None,
            None,  # gray desactivado en wide
        ))

        # OCR: primero el crop NARROW (más preciso, casi siempre acierta).
        # Solo se usa el WIDE si el narrow da resultado corto/vacío.
        # Guardamos también el ORIGEN (bw/adp) para desempatar cuando dos
        # candidatos empatan en score — la variante ADAPTATIVA suele leer
        # mejor los tickets térmicos apagados.
        narrow_values: List[str] = []
        wide_values: List[str] = []
        adaptive_values: set = set()  # valores leídos por la variante adaptativa

        variant_names = ("bw", "adp", "gray")
        for _label, cbw, cadp, cgray in crop_candidates:
            for c, vname in zip((cbw, cadp, cgray), variant_names):
                if c is None or c.size == 0 or c.shape[0] < 5 or c.shape[1] < 20:
                    continue
                val = _ocr_number_only(c)
                if val:
                    (narrow_values if _label == "narrow" else wide_values).append(val)
                    if vname == "adp":
                        adaptive_values.add(val)

        # Elegir fuente: narrow si tiene resultados con ≥3 dígitos, si no wide.
        def _n_dig(s: str) -> int:
            return sum(1 for c in s if c.isdigit())

        raw_values = narrow_values if narrow_values and max(_n_dig(v) for v in narrow_values) >= 3 else wide_values

        if not raw_values:
            continue

        # Descartar candidatos con demasiados dígitos (>10 = casi seguro
        # basura por unión de dos números adyacentes en el crop).
        raw_values = [v for v in raw_values if _n_dig(v) <= 10]
        if not raw_values:
            continue

        # Descartar el valor "0" / "0,0" / "0,00" para campos monetarios
        # y de distancia — casi siempre es del crop invadiendo la columna P
        # (parcial) que a inicio de turno vale 0,00. El valor acumulado real
        # nunca es 0 en un taxímetro que ha rodado.
        _NONZERO_FIELDS = {
            "carreras_eur", "suplementos", "total_eur",
            "dist_total_km", "dist_ocupado_km", "dist_libre_km", "dist_off_km",
            "tiempo_ocupado", "tiempo_on", "num_servicios",
        }
        if dest_key in _NONZERO_FIELDS:
            filtered = [v for v in raw_values if _es_to_float(v) not in (None, 0.0)]
            if filtered:
                raw_values = filtered

        # Score por candidato — la prioridad depende del tipo de campo:
        #   - Campos con decimal esperado (km, €): has_decimal PRIMERO.
        #     Los tickets IMPRIMEN 52537,9 con coma — un candidato entero
        #     de 7 dígitos casi siempre es OCR-corrupto (fusión de dos
        #     números adyacentes). El decimal es la mejor señal.
        #   - Campos enteros (num_servicios, borrados, licencia, tiempo_*):
        #     votes primero, luego n_dígitos.
        _DECIMAL_FIELDS = {
            "carreras_eur", "suplementos", "total_eur",
            "dist_total_km", "dist_ocupado_km", "dist_libre_km", "dist_off_km",
        }
        from collections import Counter
        counter = Counter(raw_values)

        def _score(s: str) -> tuple:
            n_dig = _n_dig(s)
            has_dec = 1 if ("," in s or "." in s) else 0
            votes = counter[s]
            is_adp = 1 if s in adaptive_values else 0
            if dest_key in _DECIMAL_FIELDS:
                # Decimal esperado: has_dec > votes > n_dig > is_adp
                return (has_dec, votes, n_dig, is_adp)
            # Enteros: votes > n_dig > is_adp (adp desempata cuando todo iguala)
            return (votes, n_dig, is_adp, has_dec)

        unique_vals = list(counter.keys())
        unique_vals.sort(key=_score, reverse=True)
        val = unique_vals[0]

        # Guardar TODOS los candidatos alternativos para validación cruzada
        # posterior (permite corregir empates usando relaciones como
        # total ≈ carreras + suplementos o dist_total ≈ ocupado + libre + off).
        _all_candidates.setdefault(dest_key, []).extend(unique_vals)

        if dest_key in ("num_servicios", "borrados", "licencia"):
            iv = _es_to_int(val)
            if iv is not None:
                result[dest_key] = iv
        else:
            fv = _es_to_float(val)
            if fv is not None:
                result[dest_key] = fv

    # ── Validación cruzada matemática ──
    # Los tickets tienen relaciones estrictas entre campos. Si el candidato
    # ganador no las cumple pero HAY otro candidato que sí lo hace, sustituir.
    def _best_candidate_matching(key: str, target: float, tol: float) -> Optional[float]:
        """Devuelve el candidato float del campo `key` más cercano a `target`
        dentro de `tol`; None si ninguno cumple."""
        cands = _all_candidates.get(key) or []
        best = None
        best_diff = tol
        for c in cands:
            fv = _es_to_float(c)
            if fv is None:
                continue
            diff = abs(fv - target)
            if diff <= best_diff:
                best_diff = diff
                best = fv
        return best

    # Regla 1: total_eur ≈ carreras + suplementos
    #   Estrategia combinada: probar todas las combinaciones de candidatos
    #   de (total_eur, suplementos) y elegir la que mejor satisfaga
    #   total = carreras + suplementos (±1€). Esto rescata ambos campos
    #   simultáneamente cuando el crop de suplementos invadió la columna P
    #   (leyó 0,00 en vez del acumulado real 204,90).
    if "carreras_eur" in result:
        carreras = float(result["carreras_eur"])
        total_cands = [_es_to_float(v) for v in _all_candidates.get("total_eur", [])]
        supl_cands = [_es_to_float(v) for v in _all_candidates.get("suplementos", [])]
        total_cands = [t for t in total_cands if t is not None]
        supl_cands = [s for s in supl_cands if s is not None]
        # Añadir el valor 0 explícitamente por si suplementos = 0 en algún ticket
        if 0.0 not in supl_cands:
            supl_cands.append(0.0)

        best_pair = None
        best_diff = 1.0
        for t in total_cands:
            for s in supl_cands:
                diff = abs(t - (carreras + s))
                if diff < best_diff:
                    best_diff = diff
                    best_pair = (t, s)
        if best_pair is not None:
            t_ok, s_ok = best_pair
            if result.get("total_eur") != t_ok:
                logger.info(f"[positional-xcheck] total_eur {result.get('total_eur')} → {t_ok}")
                result["total_eur"] = t_ok
            if result.get("suplementos") != s_ok:
                logger.info(f"[positional-xcheck] suplementos {result.get('suplementos')} → {s_ok}")
                result["suplementos"] = s_ok

    # Regla 2 (combinada): buscar la MEJOR combinación de candidatos de
    # (dist_total, dist_ocupado, dist_libre, dist_off) que satisfaga:
    #   dist_total ≈ dist_ocupado + dist_libre + dist_off  (±3 km).
    # Esto es más robusto que corregir campos uno a uno cuando VARIOS
    # están mal a la vez (por ejemplo, dist_ocupado=20 y dist_total=525379
    # sólo se resuelven considerando las 4 combinaciones simultáneamente).
    def _plausible_dist_cands(field: str) -> List[float]:
        """Devuelve candidatos convertidos a float, sin duplicados y filtrados
        a valores plausibles (0 ≤ x ≤ 1_000_000 y menos de 8 dígitos)."""
        out = []
        seen = set()
        for v in _all_candidates.get(field, []):
            fv = _es_to_float(v)
            if fv is None or fv < 0 or fv > 1_000_000:
                continue
            # Descartar valores con demasiados dígitos totales (>=8 = probable
            # OCR corrupto por fusión de dos números)
            if sum(1 for c in v if c.isdigit()) > 7:
                continue
            key = round(fv, 2)
            if key in seen:
                continue
            seen.add(key)
            out.append(fv)
        return out

    total_c = _plausible_dist_cands("dist_total_km")
    ocup_c = _plausible_dist_cands("dist_ocupado_km")
    libre_c = _plausible_dist_cands("dist_libre_km")
    off_c = _plausible_dist_cands("dist_off_km") or [
        float(result.get("dist_off_km") or 0.0)
    ]

    # Añadir el valor actual del result si no está entre los candidatos
    for field, cands in (("dist_total_km", total_c), ("dist_ocupado_km", ocup_c),
                         ("dist_libre_km", libre_c), ("dist_off_km", off_c)):
        cur = result.get(field)
        if cur is not None and float(cur) not in cands:
            cands.append(float(cur))

    if total_c and ocup_c and libre_c:
        best_combo = None
        best_diff = 3.0  # tolerancia ±3 km
        for t in total_c:
            # dist_total debe ser ≥ ocupado (por definición) y de orden similar
            for o in ocup_c:
                if o > t:
                    continue
                for l_ in libre_c:
                    if l_ > t:
                        continue
                    for off in off_c:
                        diff = abs(t - (o + l_ + off))
                        if diff < best_diff:
                            best_diff = diff
                            best_combo = (t, o, l_, off)

        if best_combo is not None:
            t_ok, o_ok, l_ok, off_ok = best_combo
            for field, new_val in (("dist_total_km", t_ok), ("dist_ocupado_km", o_ok),
                                    ("dist_libre_km", l_ok), ("dist_off_km", off_ok)):
                cur = result.get(field)
                if cur is None or abs(float(cur) - new_val) > 0.05:
                    logger.info(f"[positional-xcheck-combined] {field} {cur} → {new_val}")
                    result[field] = new_val

    return result


def _ocr_number_only(crop) -> Optional[str]:
    """OCR sobre un recorte con whitelist estricta de dígitos + coma + punto.

    Estrategia: upscale x3 + padding blanco + doble pasada Tesseract con
    PSM 7 y PSM 8 (single line / single word). Los diccionarios se
    desactivan para que Tesseract no "corrija" dígitos a letras.
    """
    import pytesseract
    import cv2
    import numpy as np
    from PIL import Image as _Image

    if crop is None or crop.size == 0:
        return None

    # Preprocesar crop → escala de grises si viene en color
    if len(crop.shape) == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Upscaling x2.5 con INTER_CUBIC para trazos más nítidos.
    h, w = crop.shape[:2]
    if max(h, w) < 800:
        scale = min(2.5, 800 / max(h, w))
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Umbralizar con Otsu (no daña si ya viene binario)
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Añadir padding blanco alrededor — Tesseract necesita "aire" alrededor
    # de los caracteres para reconocerlos con precisión, especialmente en
    # PSM 7/8 donde asume una sola línea/palabra.
    bw = cv2.copyMakeBorder(bw, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)

    pil_bw = _Image.fromarray(bw)

    all_candidates: List[str] = []
    for psm in (7, 8, 13):
        # PSM 7: single line. PSM 8: single word. PSM 13: raw line
        # (bypass del layout analyzer — puede desambiguar 5/3 cuando los
        # trazos se funden por Otsu).
        # Whitelist: dígitos + coma + punto + '/' (se reemplaza a ',' post-OCR).
        # NO incluye '-' (evita signos negativos falsos).
        # Diccionarios desactivados: evita que Tesseract "corrija" 5→S, 0→O.
        cfg = (
            f"--oem 3 --psm {psm} "
            f"-c tessedit_char_whitelist=0123456789.,/ "
            f"-c load_system_dawg=0 -c load_freq_dawg=0"
        )
        try:
            text = pytesseract.image_to_string(pil_bw, lang="eng", config=cfg)
        except Exception:
            continue
        # Reemplazar '/' por ',' — casi siempre es un decimal mal leído
        # ("3233/79" → "3233,79"). Nunca aparece '/' en un valor numérico
        # de ticket parcial (las fechas se leen en otra sección).
        text = text.replace("/", ",")
        for match in re.findall(r"\d+(?:[.,]\d+)?", text):
            if match.strip():
                all_candidates.append(match)

    if not all_candidates:
        return None

    # Preferir el que tenga más dígitos (los números completos ganan),
    # y a igualdad de dígitos, el que TIENE decimal (los tickets casi
    # siempre imprimen X,Y en las distancias).
    def _score(s: str) -> tuple:
        n_dig = sum(1 for c in s if c.isdigit())
        has_dec = 1 if ("," in s or "." in s) else 0
        return (n_dig, has_dec)

    all_candidates.sort(key=_score, reverse=True)
    return all_candidates[0]


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
# Incluimos '/' como posible separador decimal — Tesseract muy frecuentemente
# lee la coma como '/' en tickets térmicos ("3233/79" en vez de "3233,79").
_NUM_ES = r"(-?\d+[.,/]\d+|-?\d{1,3}(?:[.\s]\d{3})+|-?\d+)"


def _es_to_float(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    s = s.strip().replace(" ", "")
    # Coma-decimal mal leída como '/' — muy común en OCR de tickets.
    s = s.replace("/", ",")
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
        img_bw, img_adaptive, img_gray = _preprocess_for_ocr(image_bytes)
    except Exception as e:
        logger.exception("[journal-ocr] preprocessing failed")
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo abrir la imagen: {e}",
        )

    def _try(img_variant, psm: int) -> str:
        try:
            return pytesseract.image_to_string(
                img_variant, lang="spa+eng",
                config=(
                    f"--oem 3 --psm {psm} -c preserve_interword_spaces=1 "
                    f"-c load_system_dawg=0 -c load_freq_dawg=0"
                ),
            )
        except Exception:
            return ""

    # 4 pasadas: 2 PSM × 2 variantes de umbralizado (Otsu + adaptativo)
    text_psm4 = _try(img_bw, 4)
    text_psm6 = _try(img_bw, 6)
    text_psm4_adp = _try(img_adaptive, 4)
    text_psm6_adp = _try(img_adaptive, 6)

    parsed_4 = _parse_ticket_text(text_psm4)
    parsed_6 = _parse_ticket_text(text_psm6)
    parsed_4_adp = _parse_ticket_text(text_psm4_adp)
    parsed_6_adp = _parse_ticket_text(text_psm6_adp)

    # ── Tercera pasada: OCR POSICIONAL con whitelist de dígitos ──
    # Localiza cada etiqueta por `image_to_data` y OCR-ea el recorte a la
    # derecha con `--psm 7 -c tessedit_char_whitelist=0123456789.,`. Esto es
    # el método MÁS FIABLE porque Tesseract sólo puede devolver dígitos.
    try:
        parsed_pos = _ocr_values_positional(img_bw, img_adaptive, img_gray)
        logger.info(f"[journal-ocr] positional → {parsed_pos}")
    except Exception:
        logger.exception("[journal-ocr] positional OCR failed")
        parsed_pos = {}

    # Score = número de campos válidos en totales_taximetro (para desempatar)
    score_4 = len(parsed_4.get("totales_taximetro") or {})
    score_6 = len(parsed_6.get("totales_taximetro") or {})
    score_4a = len(parsed_4_adp.get("totales_taximetro") or {})
    score_6a = len(parsed_6_adp.get("totales_taximetro") or {})

    # ── Merge inteligente por campo ──
    # Para cada campo, elegimos entre las 4 variantes + posicional el valor
    # "más fiable":
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
        if key.startswith("tiempo_"):
            # Tiempos son enteros acumulados (segundos o cs desde encendido).
            # Rango típico: 1000-9999999. Un valor < 100 con OCR es sospechoso.
            if f < 100 or f > 100_000_000:
                return True
        return False

    # Lista de fuentes ordenada por prioridad (score total mayor = mayor peso).
    all_sources = [
        ("psm4",     parsed_4,     score_4),
        ("psm6",     parsed_6,     score_6),
        ("psm4_adp", parsed_4_adp, score_4a),
        ("psm6_adp", parsed_6_adp, score_6a),
    ]

    def _pick(key: str) -> Any:
        vp = parsed_pos.get(key)  # OCR posicional (más fiable)
        cp = _looks_ocr_corrupt(key, vp) if vp is not None else True
        # Regla 1: si el POSICIONAL da un valor válido, lo usamos SIEMPRE (es
        # el método más fiable — OCR con whitelist estricta de dígitos).
        if vp is not None and not cp:
            return vp

        # Reunir valores de las 4 variantes con su estado y score
        candidates = []  # (val, corrupt, score, has_decimal)
        for _name, src, sc in all_sources:
            v = src.get(key)
            if v is None:
                continue
            c = _looks_ocr_corrupt(key, v)
            try:
                has_dec = float(v) != int(float(v))
            except (TypeError, ValueError):
                has_dec = False
            candidates.append((v, c, sc, has_dec))

        if not candidates:
            return vp  # todo None → devuelve el posicional (aunque sea None)

        # Preferir: no-corrupto > tiene decimal > mayor score
        candidates.sort(key=lambda t: (not t[1], t[3], t[2]), reverse=True)
        return candidates[0][0]

    # Aplicar picking a los campos principales
    parsed: Dict[str, Any] = {}
    for key in ("fecha", "hora", "num_servicios", "carreras_eur",
                "dist_total_km", "dist_ocupado_km", "dist_libre_km",
                "tiempo_ocupado", "tiempo_on"):
        v = _pick(key)
        if v is not None:
            parsed[key] = v

    # totales_taximetro: merge campo-por-campo con la misma lógica (incl. posicional + 4 variantes)
    tots = [
        (parsed_4.get("totales_taximetro") or {}, score_4),
        (parsed_6.get("totales_taximetro") or {}, score_6),
        (parsed_4_adp.get("totales_taximetro") or {}, score_4a),
        (parsed_6_adp.get("totales_taximetro") or {}, score_6a),
    ]
    tot_merged: Dict[str, Any] = {}
    all_keys = set(parsed_pos.keys())
    for t, _s in tots:
        all_keys |= set(t.keys())

    for k in all_keys:
        vp = parsed_pos.get(k)
        cp = _looks_ocr_corrupt(k, vp) if vp is not None else True
        if vp is not None and not cp:
            tot_merged[k] = vp
            continue
        # Reunir candidatos de las 4 variantes
        cands = []
        for t, sc in tots:
            v = t.get(k)
            if v is None:
                continue
            c = _looks_ocr_corrupt(k, v)
            try:
                has_dec = float(v) != int(float(v))
            except (TypeError, ValueError):
                has_dec = False
            cands.append((v, c, sc, has_dec))
        if cands:
            cands.sort(key=lambda t: (not t[1], t[3], t[2]), reverse=True)
            tot_merged[k] = cands[0][0]
        elif vp is not None:
            tot_merged[k] = vp
    if tot_merged:
        parsed["totales_taximetro"] = tot_merged

    # parcial_turno (referencia): del que más tenga
    for src in (parsed_4, parsed_6, parsed_4_adp, parsed_6_adp):
        if src.get("parcial_turno") and "parcial_turno" not in parsed:
            parsed["parcial_turno"] = src["parcial_turno"]

    # Texto crudo del PSM con mayor score (para el usuario si abre "Corregir")
    scored = [(text_psm4, score_4), (text_psm6, score_6),
              (text_psm4_adp, score_4a), (text_psm6_adp, score_6a)]
    scored.sort(key=lambda x: x[1], reverse=True)
    raw_text = scored[0][0]

    # ── Validación cruzada dist_total_km ──
    # Si el dist_total detectado es MUCHO mayor que la suma de ocupado+libre
    # (por ejemplo por un dígito extra al principio: "852537" vs "52537"),
    # es OCR-corrupto. Probamos las otras 2 lecturas y nos quedamos con la
    # que más se acerque a `ocupado + libre` (sin recalcular ni sumar off).
    # Esto NO es un "cálculo inventado" — es SELECCIÓN entre lecturas del OCR.
    ocup_val = parsed.get("dist_ocupado_km")
    libre_val = parsed.get("dist_libre_km")
    total_val = parsed.get("dist_total_km")
    if all(isinstance(v, (int, float)) for v in (ocup_val, libre_val, total_val)):
        expected_min = float(ocup_val) + float(libre_val)
        if float(total_val) > expected_min * 1.5:
            # dist_total muy alto — probable OCR-corrupto. Buscar candidato más plausible.
            candidates = []
            for src in (parsed_pos.get("dist_total_km"),
                        parsed_4.get("dist_total_km"),
                        parsed_6.get("dist_total_km"),
                        parsed_4_adp.get("dist_total_km"),
                        parsed_6_adp.get("dist_total_km"),
                        (parsed_pos.get("totales_taximetro") or {}).get("dist_total_km"),
                        (parsed_4.get("totales_taximetro") or {}).get("dist_total_km"),
                        (parsed_6.get("totales_taximetro") or {}).get("dist_total_km"),
                        (parsed_4_adp.get("totales_taximetro") or {}).get("dist_total_km"),
                        (parsed_6_adp.get("totales_taximetro") or {}).get("dist_total_km")):
                if isinstance(src, (int, float)) and src != total_val:
                    candidates.append(float(src))
            # Descartar candidatos también absurdos
            valid = [c for c in candidates if expected_min * 0.9 <= c <= expected_min * 1.5]
            if valid:
                # Elegir el más cercano a expected_min (más consistente con la suma)
                best = min(valid, key=lambda c: abs(c - expected_min))
                logger.info(f"[journal-ocr] dist_total {total_val} → {best} (validación cruzada)")
                parsed["dist_total_km"] = best
                if "totales_taximetro" in parsed:
                    parsed["totales_taximetro"]["dist_total_km"] = best

    # Score log
    logger.info(
        f"[journal-ocr] scores → psm4={score_4}, psm6={score_6}, "
        f"psm4_adp={score_4a}, psm6_adp={score_6a}"
    )

    parsed["raw_ocr_text"] = raw_text.strip()

    # Warnings — campos que no se detectaron.
    # NOTA: NO se recalcula dist_total_km desde ocupado+libre+off. El ticket
    # se lee tal cual — si falla, el usuario corrige en el modal.
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


def _hhmm_to_minutes(t: Any) -> Optional[int]:
    """Convierte HH:MM (str) → minutos totales. Devuelve None si no aplica.

    Es tolerante a floats/ints (los nuevos campos tiempo_* del taxímetro son
    numéricos, no HH:MM) — en ese caso devuelve None y `_diff_minutes`
    fallará silenciosamente, se calcula por _diff numérico en otro sitio.
    """
    if not isinstance(t, str):
        return None
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
    # NOTA: los campos tiempo_* del ticket son ACUMULADOS del taxímetro EN
    # MINUTOS. La diferencia end - start da los minutos del turno.
    def _diff_min(key: str) -> Optional[int]:
        v = _diff(key)
        if v is None or v < 0:
            return None
        return int(round(v))

    min_on = _diff_min("tiempo_on")
    min_ocupado = _diff_min("tiempo_ocupado")
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


@router.post("/{journal_id}/reparse")
async def reparse_ocr(
    journal_id: str,
    which: str = Form(...),  # "start" or "end"
    method: str = Form("ai"),  # "tesseract" (default local) or "ai" (Gemini Vision)
    user=Depends(get_current_user_required),
):
    """Re-ejecuta el OCR sobre la foto YA subida de una jornada, usando el
    método indicado.

    - `method=tesseract`: repite el pipeline local (3 pasadas Tesseract).
    - `method=ai`: usa Gemini Vision (más lento y consume cuota, pero
      MUCHO más preciso en tickets arrugados / mal iluminados). Devuelve
      el ParcialReading recomputado + totales si la jornada está cerrada.
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
        raise HTTPException(status_code=404, detail=f"No hay foto {which} para re-escanear.")
    fpath = os.path.join(PARCIAL_PHOTOS_DIR, fname)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Fichero de foto no encontrado.")

    with open(fpath, "rb") as f:
        image_bytes = f.read()

    ext = os.path.splitext(fname)[1].lower().lstrip(".") or "jpeg"
    mime = f"image/{'jpeg' if ext == 'jpg' else ext}"

    if method == "ai":
        parsed = await _ocr_parcial_with_ai(image_bytes, mime)
    else:
        parsed = await run_in_threadpool(_ocr_parcial_sync, image_bytes, mime)

    reading = ParcialReading(**{k: v for k, v in parsed.items() if k in ParcialReading.model_fields})
    update = {f"{which}_reading": reading.model_dump()}
    if journal.get("status") == "closed" and journal.get("start_reading") and journal.get("end_reading"):
        merged = {**journal, **update}
        update["totals"] = _compute_totals(merged)
    await JOURNAL_COLLECTION.update_one({"id": journal_id}, {"$set": update})
    journal.update(update)
    return journal


async def _ocr_parcial_with_ai(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """OCR usando Gemini Vision (mucho más preciso para tickets difíciles).

    Devuelve el mismo shape que _ocr_parcial_sync. Usa reintentos con
    backoff exponencial ante 429/503, y modelo fallback si el principal
    está saturado.
    """
    import asyncio
    from google.genai import types as gtypes

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY no configurada.")
    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = """Eres un experto OCR de tickets impresos de taxímetros españoles.
Lee la imagen y devuelve EXCLUSIVAMENTE un JSON válido (sin markdown ni texto extra)
con los TOTALES ACUMULADOS del taxímetro (parte SUPERIOR del ticket, IGNORA las
líneas que empiezan con "P " que son parciales del turno):

{
  "fecha": "YYYY-MM-DD",
  "hora": "HH:MM",
  "num_servicios": entero (Num. Servicios),
  "carreras_eur": decimal en €,
  "dist_total_km": decimal,
  "dist_ocupado_km": decimal,
  "dist_libre_km": decimal,
  "tiempo_ocupado": entero (Tiempo Ocupado, en minutos totales tal cual imprime el ticket),
  "tiempo_on": entero (Tiempo On, en minutos totales)
}

Reglas:
- Los números españoles usan coma decimal (49854,10 → 49854.10).
- Fecha DD/MM/YY → conviértela a YYYY-MM-DD (asume 20YY).
- Si un campo no se ve o no estás seguro, ponlo a null. NO inventes.
"""

    image_part = gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    def _call(model_name: str):
        return client.models.generate_content(
            model=model_name,
            contents=[prompt, image_part],
            config=gtypes.GenerateContentConfig(temperature=0.0),
        )

    TRANSIENT = ("429", "RESOURCE_EXHAUSTED", "quota", "503",
                 "UNAVAILABLE", "overloaded", "high demand", "deadline")

    async def _try(model: str, attempts: int = 3):
        last = None
        for i in range(attempts):
            try:
                return await asyncio.to_thread(_call, model)
            except Exception as e:
                if not any(k in str(e) for k in TRANSIENT):
                    raise
                last = e
                await asyncio.sleep(2 ** (i + 1))
        raise last  # type: ignore[misc]

    try:
        response = await _try("gemini-2.5-flash")
    except Exception:
        logger.warning("[reparse-ai] flash agotado, cambio a flash-lite")
        try:
            response = await _try("gemini-2.5-flash-lite")
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="El servicio de IA está temporalmente saturado. Reintenta en 1 min.",
            )

    text = (getattr(response, "text", None) or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    import json as _json
    try:
        parsed = _json.loads(text)
    except Exception:
        logger.exception("[reparse-ai] JSON parse failed: %s", text[:400])
        raise HTTPException(
            status_code=502,
            detail="La IA no devolvió un JSON válido. Reintenta.",
        )

    parsed["raw_ocr_text"] = text
    parsed["ocr_warnings"] = []
    return parsed


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
