"""Puntos de Interés (POI) router.

Serves a small catalogue of important places for Madrid taxi drivers:
hospitales con urgencias, farmacias 24 h, gasolineras 24 h, estancos 24 h,
discotecas y ocio nocturno. Two collections back the feature:

- `poi_types`: catalogue of types. Six built-in types are seeded on startup
  (idempotent) and admins/moderators can add custom ones.
- `pois`: individual places (name, coords, address). Seeded with a curated
  Madrid dataset for the auto-filled types; admins/moderators can add,
  edit or delete entries. When the closest-by-distance ranking runs, the
  manual/staff entry wins if it sits nearer than the seed.

Endpoints (all under `/api/pois`):
- `GET  /nearby?lat=&lon=`                    → closest POI per type
- `GET  /types`                                → list POI types
- `POST /types`     (admin/mod)                → create custom type
- `DELETE /types/{id}` (admin only, non-builtin)
- `GET  /`         → list POIs (optional `type_key` filter)
- `POST /`         (admin/mod) → create POI
- `PUT  /{id}`     (admin/mod) → update POI
- `DELETE /{id}`   (admin/mod) → delete POI
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from math import radians, sin, cos, asin, sqrt
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from shared import db, get_current_user_required, get_moderator_or_admin_user

router = APIRouter(prefix="/pois", tags=["POI"])

poi_types_collection = db.poi_types
pois_collection = db.pois


# ─────────────────────── Built-in catalogue ───────────────────────
BUILT_IN_TYPES = [
    {"key": "hospital_er",  "label": "Hospital con urgencias", "icon": "medkit",         "manual_only": False},
    {"key": "pharmacy_24",  "label": "Farmacia 24h",            "icon": "medical",         "manual_only": False},
    {"key": "fuel_24",      "label": "Gasolinera 24h",          "icon": "car-sport",       "manual_only": False},
    {"key": "nightlife",    "label": "Ocio nocturno",           "icon": "wine",            "manual_only": True},
    {"key": "tobacco_24",   "label": "Estanco 24h",             "icon": "flame",           "manual_only": False},
    {"key": "nightclub",    "label": "Discoteca",               "icon": "musical-notes",   "manual_only": False},
]

# Curated Madrid seed data. Coordinates are approximate but usable for
# distance ranking. Admins can override any of these from the UI.
SEED_POIS: dict = {
    "hospital_er": [
        {"name": "Hospital 12 de Octubre", "address": "Av. de Córdoba, s/n", "lat": 40.3728, "lon": -3.6963},
        {"name": "Hospital Universitario La Paz", "address": "Paseo de la Castellana, 261", "lat": 40.4796, "lon": -3.6907},
        {"name": "Hospital Gregorio Marañón", "address": "C. del Dr. Esquerdo, 46", "lat": 40.4213, "lon": -3.6688},
        {"name": "Hospital Clínico San Carlos", "address": "C. Prof. Martín Lagos", "lat": 40.4409, "lon": -3.7304},
        {"name": "Hospital Ramón y Cajal", "address": "Ctra. Colmenar Viejo km 9,100", "lat": 40.4805, "lon": -3.6842},
        {"name": "Hospital La Princesa", "address": "C. de Diego de León, 62", "lat": 40.4356, "lon": -3.6802},
        {"name": "Hospital Puerta de Hierro", "address": "C. Manuel de Falla, 1, Majadahonda", "lat": 40.4629, "lon": -3.8462},
    ],
    "pharmacy_24": [
        {"name": "Farmacia Central de Madrid", "address": "C. de la Palma, 1", "lat": 40.4222, "lon": -3.7069},
        {"name": "Farmacia Atocha 46", "address": "C. de Atocha, 46", "lat": 40.4139, "lon": -3.6969},
        {"name": "Farmacia Goya 89", "address": "C. de Goya, 89", "lat": 40.4290, "lon": -3.6764},
        {"name": "Farmacia Real de Palacio", "address": "C. Mayor, 59", "lat": 40.4157, "lon": -3.7106},
        {"name": "Farmacia Calle Toledo 46", "address": "C. de Toledo, 46", "lat": 40.4109, "lon": -3.7098},
        {"name": "Farmacia Cea Bermúdez 72", "address": "C. de Cea Bermúdez, 72", "lat": 40.4407, "lon": -3.7136},
    ],
    "fuel_24": [
        {"name": "Repsol Castellana 89", "address": "P.º de la Castellana, 89", "lat": 40.4437, "lon": -3.6907},
        {"name": "Cepsa Príncipe de Vergara", "address": "C. Príncipe de Vergara, 88", "lat": 40.4348, "lon": -3.6784},
        {"name": "Repsol Menéndez Pelayo", "address": "Av. de Menéndez Pelayo, 71", "lat": 40.4147, "lon": -3.6788},
        {"name": "Galp Nuevos Ministerios", "address": "C. Raimundo Fernández Villaverde", "lat": 40.4468, "lon": -3.6928},
        {"name": "Repsol Alcalá 200", "address": "C. de Alcalá, 200", "lat": 40.4302, "lon": -3.6656},
        {"name": "BP Bravo Murillo", "address": "C. de Bravo Murillo, 202", "lat": 40.4599, "lon": -3.7013},
    ],
    "tobacco_24": [
        {"name": "Estanco 24h Puerta del Sol", "address": "Puerta del Sol, 4", "lat": 40.4168, "lon": -3.7033},
        {"name": "Estanco Aeropuerto Barajas T4", "address": "Aeropuerto T4 llegadas", "lat": 40.4936, "lon": -3.5668},
        {"name": "Estanco Estación de Atocha", "address": "Estación Puerta de Atocha", "lat": 40.4067, "lon": -3.6906},
    ],
    "nightclub": [
        {"name": "Kapital", "address": "C. de Atocha, 125", "lat": 40.4083, "lon": -3.6928},
        {"name": "Fabrik", "address": "Av. de la Industria, 82, Humanes", "lat": 40.2711, "lon": -3.7863},
        {"name": "Teatro Barceló", "address": "C. de Barceló, 11", "lat": 40.4258, "lon": -3.6994},
        {"name": "Joy Eslava", "address": "C. del Arenal, 11", "lat": 40.4171, "lon": -3.7075},
        {"name": "Mondo Disko", "address": "C. de Alcalá, 20", "lat": 40.4189, "lon": -3.6996},
        {"name": "Sala Sala", "address": "Callejón de la Ternera", "lat": 40.4162, "lon": -3.7052},
    ],
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    h = sin(dlat / 2) ** 2 + cos(lat1r) * cos(lat2r) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(h))


async def seed_pois_if_empty() -> None:
    """Idempotent seeding — types are always upserted, seed POIs only inserted
    once (skip if any doc already exists for the type_key with is_seed=True)."""
    now = datetime.now(timezone.utc)
    for t in BUILT_IN_TYPES:
        await poi_types_collection.update_one(
            {"key": t["key"]},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "key": t["key"],
                    "label": t["label"],
                    "icon": t["icon"],
                    "manual_only": t["manual_only"],
                    "builtin": True,
                    "created_at": now,
                },
            },
            upsert=True,
        )
    for type_key, entries in SEED_POIS.items():
        existing = await pois_collection.count_documents({"type_key": type_key, "is_seed": True})
        if existing > 0:
            continue
        docs = [
            {
                "id": str(uuid.uuid4()),
                "type_key": type_key,
                "name": e["name"],
                "address": e["address"],
                "lat": e["lat"],
                "lon": e["lon"],
                "notes": None,
                "is_seed": True,
                "created_by": "seed",
                "created_at": now,
                "updated_at": now,
            }
            for e in entries
        ]
        if docs:
            await pois_collection.insert_many(docs)


# ─────────────────────── Response helpers ───────────────────────
def _clean_type(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "key": doc["key"],
        "label": doc["label"],
        "icon": doc["icon"],
        "manual_only": doc.get("manual_only", False),
        "builtin": doc.get("builtin", False),
    }


def _clean_poi(doc: dict, distance_km: Optional[float] = None) -> dict:
    out = {
        "id": doc["id"],
        "type_key": doc["type_key"],
        "name": doc["name"],
        "address": doc.get("address"),
        "lat": doc["lat"],
        "lon": doc["lon"],
        "notes": doc.get("notes"),
        "is_seed": doc.get("is_seed", False),
        "created_by": doc.get("created_by"),
    }
    if distance_km is not None:
        out["distance_km"] = distance_km
    return out


# ─────────────────────── Models ───────────────────────
class PoiTypeCreateBody(BaseModel):
    key: str = Field(..., min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=2, max_length=80)
    icon: str = Field("location", min_length=2, max_length=40)
    manual_only: bool = False


class PoiCreateBody(BaseModel):
    type_key: str = Field(..., min_length=2, max_length=40)
    name: str = Field(..., min_length=2, max_length=140)
    address: Optional[str] = Field(None, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    notes: Optional[str] = Field(None, max_length=400)


class PoiUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=140)
    address: Optional[str] = Field(None, max_length=200)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    notes: Optional[str] = Field(None, max_length=400)


# ─────────────────────── Endpoints ───────────────────────
@router.get("/types")
async def list_poi_types(_who: dict = Depends(get_current_user_required)) -> List[dict]:
    cursor = poi_types_collection.find({}).sort("builtin", -1)
    return [_clean_type(d) async for d in cursor]


@router.post("/types")
async def create_poi_type(body: PoiTypeCreateBody, _staff: dict = Depends(get_moderator_or_admin_user)) -> dict:
    if await poi_types_collection.find_one({"key": body.key}):
        raise HTTPException(status_code=409, detail="Ya existe un tipo con esa clave")
    doc = {
        "id": str(uuid.uuid4()),
        "key": body.key,
        "label": body.label,
        "icon": body.icon,
        "manual_only": body.manual_only,
        "builtin": False,
        "created_at": datetime.now(timezone.utc),
    }
    await poi_types_collection.insert_one(doc)
    return _clean_type(doc)


@router.delete("/types/{type_id}", status_code=204)
async def delete_poi_type(type_id: str, _staff: dict = Depends(get_moderator_or_admin_user)):
    doc = await poi_types_collection.find_one({"id": type_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Tipo no encontrado")
    if doc.get("builtin"):
        raise HTTPException(status_code=400, detail="No puedes borrar un tipo integrado")
    await pois_collection.delete_many({"type_key": doc["key"]})
    await poi_types_collection.delete_one({"id": type_id})


@router.get("")
async def list_pois(
    type_key: Optional[str] = Query(None),
    _who: dict = Depends(get_current_user_required),
) -> List[dict]:
    q: dict = {}
    if type_key:
        q["type_key"] = type_key
    cursor = pois_collection.find(q).sort("name", 1).limit(500)
    return [_clean_poi(d) async for d in cursor]


@router.post("")
async def create_poi(body: PoiCreateBody, staff: dict = Depends(get_moderator_or_admin_user)) -> dict:
    if not await poi_types_collection.find_one({"key": body.type_key}):
        raise HTTPException(status_code=400, detail="Tipo desconocido")
    doc = {
        "id": str(uuid.uuid4()),
        "type_key": body.type_key,
        "name": body.name.strip(),
        "address": (body.address or "").strip() or None,
        "lat": body.lat,
        "lon": body.lon,
        "notes": (body.notes or "").strip() or None,
        "is_seed": False,
        "created_by": staff.get("username") or "staff",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await pois_collection.insert_one(doc)
    return _clean_poi(doc)


@router.put("/{poi_id}")
async def update_poi(poi_id: str, body: PoiUpdateBody, _staff: dict = Depends(get_moderator_or_admin_user)) -> dict:
    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    for k in ("name", "address", "lat", "lon", "notes"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v.strip() if isinstance(v, str) else v
    r = await pois_collection.update_one({"id": poi_id}, {"$set": updates})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="POI no encontrado")
    doc = await pois_collection.find_one({"id": poi_id})
    return _clean_poi(doc or {})


@router.delete("/{poi_id}", status_code=204)
async def delete_poi(poi_id: str, _staff: dict = Depends(get_moderator_or_admin_user)):
    r = await pois_collection.delete_one({"id": poi_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="POI no encontrado")


@router.get("/nearby")
async def nearest_pois(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    _who: dict = Depends(get_current_user_required),
) -> List[dict]:
    """Return the closest POI for every registered type ordered by category."""
    types_cursor = poi_types_collection.find({}).sort("builtin", -1)
    types = [t async for t in types_cursor]
    out = []
    for t in types:
        pois_cursor = pois_collection.find({"type_key": t["key"]}, {"_id": 0})
        best: Optional[dict] = None
        best_dist: Optional[float] = None
        async for p in pois_cursor:
            d = _haversine_km(lat, lon, p["lat"], p["lon"])
            if best_dist is None or d < best_dist:
                best_dist = d
                best = p
        entry = {
            "type": _clean_type(t),
            "closest": _clean_poi(best, round(best_dist, 2)) if best and best_dist is not None else None,
        }
        out.append(entry)
    return out
