"""
Owner (propietario) endpoints — licencias multi-cuenta y gestión de conductores.

Un usuario con `role == "propietario"` puede:
  - Registrar múltiples licencias en su perfil (una flota).
  - Crear cuentas de "conductor" atadas a una de sus licencias (le da usuario+
    contraseña; el conductor entra normalmente con ese usuario).
  - Ver en la pestaña "Gestión" la facturación y métricas de todos sus
    conductores, filtrando por licencia y conductor.
  - Ver una comparativa (top) entre sus conductores.

Endpoints (todos bajo `/api/owner`):
  POST   /register           registrar un propietario nuevo con licencias
  GET    /licencias          listar mis licencias
  POST   /licencias          añadir una licencia
  DELETE /licencias/{numero} quitar una licencia
  GET    /drivers            listar mis conductores (?licencia=xxx opcional)
  POST   /drivers            crear una cuenta de conductor
  DELETE /drivers/{driver_id} eliminar (desactivar) un conductor
  GET    /comparativa        comparativa top-conductor por rango de fechas
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from shared import (
    db,
    users_collection,
    get_current_user_required,
    get_password_hash,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from datetime import timedelta

router = APIRouter(prefix="/owner", tags=["Owner"])

JOURNAL_COLLECTION = db["taxi_journals"]

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────
class LicenciaModel(BaseModel):
    numero: str
    alias: Optional[str] = None

    @field_validator("numero")
    @classmethod
    def _numeric(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\d{3,7}", v):
            raise ValueError("El número de licencia debe tener 3-7 dígitos")
        return v


class OwnerRegister(BaseModel):
    username: str
    password: str
    full_name: str
    phone: Optional[str] = None
    licencias: List[LicenciaModel] = Field(default_factory=list)

    @field_validator("licencias")
    @classmethod
    def _at_least_one(cls, v):
        if not v:
            raise ValueError("Un propietario necesita al menos una licencia")
        return v


class DriverCreate(BaseModel):
    username: str
    password: str
    full_name: str
    licencia_asignada: str  # número de licencia del propietario
    phone: Optional[str] = None
    preferred_shift: Optional[str] = "all"


class DriverResponse(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    licencia_asignada: Optional[str] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _sanitize_user(u: Dict[str, Any]) -> Dict[str, Any]:
    """Strip Mongo _id and hashed_password for safe JSON return."""
    if not u:
        return u
    u = {**u}
    u.pop("_id", None)
    u.pop("hashed_password", None)
    return u


def _require_owner(user: Dict[str, Any]):
    if user.get("role") != "propietario":
        raise HTTPException(
            status_code=403,
            detail="Sólo los propietarios pueden usar este endpoint.",
        )


def _owner_licencia_numbers(user: Dict[str, Any]) -> List[str]:
    return [lic_["numero"] for lic_ in (user.get("licencias") or []) if lic_.get("numero")]


# ─────────────────────────────────────────────────────────────────────────────
# Registration (public)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/register")
async def register_owner(payload: OwnerRegister):
    """Registro público de un propietario con una o más licencias."""
    # Comprobar username único
    existing = await users_collection.find_one({"username": payload.username})
    if existing:
        raise HTTPException(status_code=409, detail="Ese usuario ya existe.")

    # Comprobar que ninguna licencia esté ya registrada por otro usuario
    for lic in payload.licencias:
        clash = await users_collection.find_one({
            "$or": [
                {"license_number": lic.numero},
                {"licencias.numero": lic.numero},
            ]
        })
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"La licencia {lic.numero} ya está registrada.",
            )

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    doc = {
        "id": user_id,
        "username": payload.username.strip(),
        "hashed_password": get_password_hash(payload.password),
        "full_name": payload.full_name.strip(),
        "phone": (payload.phone or "").strip() or None,
        "role": "propietario",
        "licencias": [lic_.model_dump() for lic_ in payload.licencias],
        # Los propietarios también pueden trabajar como conductores: usamos la
        # primera licencia como suya por defecto (podrán cambiarla en el
        # dropdown de Gestión).
        "license_number": payload.licencias[0].numero,
        "licencia_asignada": payload.licencias[0].numero,
        "preferred_shift": "all",
        "created_at": now,
        "updated_at": now,
    }
    await users_collection.insert_one(doc)

    token = create_access_token(
        {"sub": user_id},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _sanitize_user(doc),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Licencias (mis licencias)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/licencias")
async def list_licencias(user=Depends(get_current_user_required)):
    _require_owner(user)
    return {"licencias": user.get("licencias") or []}


@router.post("/licencias")
async def add_licencia(lic: LicenciaModel, user=Depends(get_current_user_required)):
    _require_owner(user)
    # Comprobar que no esté ya en otro sitio
    clash = await users_collection.find_one({
        "id": {"$ne": user["id"]},
        "$or": [
            {"license_number": lic.numero},
            {"licencias.numero": lic.numero},
        ]
    })
    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"La licencia {lic.numero} ya está registrada por otro usuario.",
        )
    # Comprobar que no esté ya en mi lista
    existing = [lic_.get("numero") for lic_ in (user.get("licencias") or [])]
    if lic.numero in existing:
        raise HTTPException(status_code=409, detail="Ya tienes esa licencia.")

    await users_collection.update_one(
        {"id": user["id"]},
        {"$push": {"licencias": lic.model_dump()},
         "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    updated = await users_collection.find_one({"id": user["id"]})
    return {"licencias": updated.get("licencias") or []}


@router.delete("/licencias/{numero}")
async def delete_licencia(numero: str, user=Depends(get_current_user_required)):
    _require_owner(user)
    if len(user.get("licencias") or []) <= 1:
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar tu última licencia.",
        )
    # Comprobar que no haya conductores atados a esa licencia
    drivers_using = await users_collection.count_documents({
        "owner_id": user["id"],
        "licencia_asignada": numero,
    })
    if drivers_using:
        raise HTTPException(
            status_code=400,
            detail=f"Tienes {drivers_using} conductor(es) usando esa licencia. Reasígnalos primero.",
        )
    await users_collection.update_one(
        {"id": user["id"]},
        {"$pull": {"licencias": {"numero": numero}},
         "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    updated = await users_collection.find_one({"id": user["id"]})
    return {"licencias": updated.get("licencias") or []}


# ─────────────────────────────────────────────────────────────────────────────
# Conductores (mis empleados)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/drivers")
async def list_drivers(
    licencia: Optional[str] = None,
    user=Depends(get_current_user_required),
):
    _require_owner(user)
    query: Dict[str, Any] = {"owner_id": user["id"]}
    if licencia:
        if licencia not in _owner_licencia_numbers(user):
            raise HTTPException(status_code=403, detail="Esa licencia no es tuya.")
        query["licencia_asignada"] = licencia
    cursor = users_collection.find(query, {"_id": 0, "hashed_password": 0}).sort("created_at", -1)
    drivers = await cursor.to_list(length=200)
    return {"drivers": drivers}


@router.post("/drivers")
async def create_driver(payload: DriverCreate, user=Depends(get_current_user_required)):
    _require_owner(user)
    if payload.licencia_asignada not in _owner_licencia_numbers(user):
        raise HTTPException(
            status_code=400,
            detail="La licencia asignada no está entre tus licencias.",
        )
    # username único
    existing = await users_collection.find_one({"username": payload.username})
    if existing:
        raise HTTPException(status_code=409, detail="Ese usuario ya existe.")

    driver_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    doc = {
        "id": driver_id,
        "username": payload.username.strip(),
        "hashed_password": get_password_hash(payload.password),
        "full_name": payload.full_name.strip(),
        "phone": (payload.phone or "").strip() or None,
        "role": "user",  # conductor normal
        "owner_id": user["id"],
        "licencia_asignada": payload.licencia_asignada,
        # NB: no ponemos `license_number` porque hay un índice único en ese
        # campo; la licencia pertenece al propietario y varios conductores
        # pueden compartirla. Se expone `licencia_asignada` para el UI.
        "preferred_shift": payload.preferred_shift or "all",
        "created_at": now,
        "updated_at": now,
    }
    await users_collection.insert_one(doc)
    return {"driver": _sanitize_user(doc)}


@router.delete("/drivers/{driver_id}")
async def delete_driver(driver_id: str, user=Depends(get_current_user_required)):
    _require_owner(user)
    driver = await users_collection.find_one({"id": driver_id})
    if not driver or driver.get("owner_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Conductor no encontrado.")
    await users_collection.delete_one({"id": driver_id})
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Comparativa (top conductores por rango)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/comparativa")
async def comparativa(
    start: str,
    end: str,
    user=Depends(get_current_user_required),
):
    """Devuelve la lista de conductores (incluyéndote a ti mismo) con
    métricas agregadas del rango [start..end] y un ranking por total_ingresos."""
    _require_owner(user)
    from datetime import date as _date
    try:
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fechas inválidas (YYYY-MM-DD).")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end debe ser ≥ start.")

    # Users a comparar: yo + mis conductores
    my_id = user["id"]
    driver_ids = [my_id]
    async for d in users_collection.find({"owner_id": my_id}, {"_id": 0, "id": 1}):
        driver_ids.append(d["id"])

    # Traer todos los usuarios (para nombres) en un solo query
    users_map = {}
    async for u in users_collection.find(
        {"id": {"$in": driver_ids}},
        {"_id": 0, "id": 1, "username": 1, "full_name": 1, "licencia_asignada": 1, "license_number": 1},
    ):
        users_map[u["id"]] = u

    # Traer todas las jornadas cerradas del rango de estos usuarios
    cursor = JOURNAL_COLLECTION.find(
        {
            "user_id": {"$in": driver_ids},
            "status": "closed",
        },
        {"_id": 0},
    ).sort("end_at", -1).limit(2000)
    journals = await cursor.to_list(length=2000)

    # Agrupar por driver, filtrando por fecha
    from collections import defaultdict
    stats: Dict[str, Dict[str, float]] = defaultdict(lambda: {
        "ingresos_eur": 0.0, "gasolina_eur": 0.0, "neto_eur": 0.0,
        "km_total": 0.0, "horas_on": 0.0, "servicios": 0, "jornadas": 0,
    })
    for j in journals:
        end_at = j.get("end_at") or j.get("start_at")
        if not end_at:
            continue
        try:
            j_date = datetime.fromisoformat(end_at).date()
        except ValueError:
            continue
        if not (start_d <= j_date <= end_d):
            continue
        t = j.get("totals") or {}
        s = stats[j["user_id"]]
        s["ingresos_eur"] += float(t.get("total_ingresos_eur", 0) or 0)
        s["gasolina_eur"] += float(t.get("gasto_gasolina_eur", 0) or 0)
        s["neto_eur"] += float(t.get("total_neto_eur", 0) or 0)
        s["km_total"] += float(t.get("dist_total_diff_km", 0) or 0)
        s["horas_on"] += float(t.get("tiempo_on_min", 0) or 0) / 60.0
        s["servicios"] += int(t.get("num_servicios_diff", 0) or 0)
        s["jornadas"] += 1

    rows = []
    for did in driver_ids:
        u = users_map.get(did) or {"id": did, "username": "?"}
        s = stats[did]
        eur_h = round(s["ingresos_eur"] / s["horas_on"], 2) if s["horas_on"] > 0 else None
        eur_km = round(s["ingresos_eur"] / s["km_total"], 2) if s["km_total"] > 0 else None
        rows.append({
            "driver_id": did,
            "username": u.get("username"),
            "full_name": u.get("full_name"),
            "licencia": u.get("licencia_asignada") or u.get("license_number"),
            "is_me": did == my_id,
            "ingresos_eur": round(s["ingresos_eur"], 2),
            "gasolina_eur": round(s["gasolina_eur"], 2),
            "neto_eur": round(s["neto_eur"], 2),
            "km_total": round(s["km_total"], 1),
            "horas_on": round(s["horas_on"], 2),
            "servicios": s["servicios"],
            "jornadas": s["jornadas"],
            "eur_por_hora": eur_h,
            "eur_por_km": eur_km,
        })
    # Ordenar por ingresos DESC (top). Los conductores sin jornada al final.
    rows.sort(key=lambda r: (r["jornadas"] > 0, r["ingresos_eur"]), reverse=True)
    return {"start": start, "end": end, "drivers": rows}
