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
    carreras_eur: Optional[float] = None     # facturación (€)
    dist_total_km: Optional[float] = None
    dist_ocupado_km: Optional[float] = None
    dist_libre_km: Optional[float] = None
    tiempo_ocupado: Optional[str] = None     # HH:MM
    tiempo_on: Optional[str] = None          # HH:MM
    raw_ocr_text: Optional[str] = None       # for debugging
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
# Gemini Vision OCR
# ─────────────────────────────────────────────────────────────────────────────
OCR_MODEL = "gemini-2.5-flash"
OCR_MODEL_FALLBACK = "gemini-2.5-flash-lite"

OCR_PROMPT = """Eres un sistema OCR experto en tickets impresos de taxímetros españoles
(parciales). Lee la imagen y devuelve EXCLUSIVAMENTE un JSON válido (sin markdown,
sin texto antes ni después) con estos campos. Si un campo no se ve, ponlo a null.

{
  "fecha": "YYYY-MM-DD",
  "hora": "HH:MM",
  "num_servicios": entero,
  "carreras_eur": decimal (la facturación total en €, valor numérico),
  "dist_total_km": decimal,
  "dist_ocupado_km": decimal,
  "dist_libre_km": decimal,
  "tiempo_ocupado": "HH:MM",
  "tiempo_on": "HH:MM",
  "raw_ocr_text": "todo el texto que ves en la imagen, tal cual"
}

Notas críticas:
- Lee SOLO la sección de TOTALES (cabecera arriba), NO los desgloses por servicio.
- Si ves un punto y una coma juntos (ej "1.234,56") es formato español: el punto
  es separador de miles y la coma es decimal. Conviértelo a 1234.56.
- Si solo ves coma (ej "23,45") la coma es el decimal → 23.45.
- "carreras_eur" es el importe total facturado en euros, lo que coloquialmente se
  llama "facturación" o "recaudación".
- Si la fecha viene en formato DD/MM/YYYY, conviértela a YYYY-MM-DD.
- Si algún campo no aparece o está ilegible, pon null. No inventes valores.
"""


def _build_genai_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY no configurada.")
    from google import genai
    return genai.Client(api_key=api_key)


def _ocr_parcial_sync(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    """Run OCR on a parciales photo via Gemini Vision. Returns parsed dict."""
    from google.genai import types as gtypes

    client = _build_genai_client()
    image_part = gtypes.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    def _call(model_name: str):
        return client.models.generate_content(
            model=model_name,
            contents=[OCR_PROMPT, image_part],
            config=gtypes.GenerateContentConfig(temperature=0.0),
        )

    try:
        response = _call(OCR_MODEL)
    except Exception as e:
        msg = str(e)
        # Quota exhausted → return a clean 503 with Retry-After so the frontend
        # can show a friendly retry message.
        if any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "quota")):
            logger.warning(f"[journal-ocr] Gemini quota exhausted: {msg[:200]}")
            raise HTTPException(
                status_code=503,
                detail="El servicio de IA está temporalmente saturado. Espera unos segundos e inténtalo de nuevo.",
                headers={"Retry-After": "60"},
            )
        if any(k in msg for k in ("503", "UNAVAILABLE", "overloaded", "high demand")):
            logger.warning(f"[journal-ocr] {OCR_MODEL} overloaded, using fallback")
            try:
                response = _call(OCR_MODEL_FALLBACK)
            except Exception as e2:
                msg2 = str(e2)
                if any(k in msg2 for k in ("429", "RESOURCE_EXHAUSTED", "quota")):
                    raise HTTPException(
                        status_code=503,
                        detail="El servicio de IA está temporalmente saturado. Espera unos segundos e inténtalo de nuevo.",
                        headers={"Retry-After": "60"},
                    )
                raise
        else:
            raise

    text = (getattr(response, "text", None) or "").strip()
    # Strip code fences if Gemini added them despite the instruction
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    import json as _json
    try:
        parsed = _json.loads(text)
    except Exception:
        logger.exception("[journal-ocr] failed to parse JSON, raw text was: %s", text[:500])
        raise HTTPException(
            status_code=502,
            detail="No se pudo interpretar el ticket. Hazlo más nítido y vuelve a intentar.",
        )

    warnings: List[str] = []
    for key in ("carreras_eur", "dist_total_km", "dist_ocupado_km", "dist_libre_km"):
        v = parsed.get(key)
        if v is None:
            warnings.append(f"campo {key} no detectado")

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
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
    fname = f"{journal_id}_{suffix}.{ext}"
    fpath = os.path.join(PARCIAL_PHOTOS_DIR, fname)
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Imagen vacía.")
    if len(body) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Imagen demasiado grande (>12MB).")
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
