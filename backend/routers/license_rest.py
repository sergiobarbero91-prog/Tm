"""Licence rest-day status for drivers + Madrid holidays calendar (admin-editable)."""
import asyncio
import csv
import io
import time as _time
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from license_rest import DEFAULT_HOLIDAYS_2026, SHIFT_LABELS, in_shift, license_status
from shared import db, get_admin_user, get_current_user_required, logger

router = APIRouter(prefix="/license-rest", tags=["License rest"])
holidays_collection = db["holidays"]

MADRID_CALENDAR_CSV = (
    "https://datos.madrid.es/dataset/300082-0-calendario_laboral/resource/"
    "300082-1-calendario_laboral-csv/download/300082-1-calendario_laboral-csv.csv"
)
_cache = {"at": 0.0, "dates": set()}


async def seed_default_holidays():
    for d, name in DEFAULT_HOLIDAYS_2026:
        await holidays_collection.update_one(
            {"date": d}, {"$setOnInsert": {"date": d, "name": name, "source": "default", "disabled": False}}, upsert=True
        )


async def sync_madrid_calendar() -> int:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(MADRID_CALENDAR_CSV)
        r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    count, this_year = 0, datetime.now(timezone.utc).year
    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if len(row) < 5 or row[2].strip().lower() != "festivo":
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%d/%m/%Y").date()
        except ValueError:
            continue
        if d.year < this_year:
            continue
        await holidays_collection.update_one(
            {"date": d.isoformat()},
            {"$set": {"name": row[4].strip() or row[3].strip(), "source": "ayuntamiento"},
             "$setOnInsert": {"date": d.isoformat(), "disabled": False}},
            upsert=True,
        )
        count += 1
    _cache["at"] = 0
    return count


async def holidays_sync_loop():
    await seed_default_holidays()
    while True:
        try:
            n = await sync_madrid_calendar()
            logger.info(f"[Festivos] synced {n} holidays from datos.madrid.es")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Festivos] sync failed: {e}")
        await asyncio.sleep(7 * 24 * 3600)


async def get_holiday_dates() -> set:
    if _time.time() - _cache["at"] < 600:
        return _cache["dates"]
    docs = await holidays_collection.find({"disabled": {"$ne": True}}, {"_id": 0, "date": 1}).to_list(1000)
    _cache["dates"] = {date.fromisoformat(d["date"]) for d in docs}
    _cache["at"] = _time.time()
    return _cache["dates"]


async def driver_availability(user: dict, at: datetime) -> dict:
    status = license_status(user.get("license_number"), at, await get_holiday_dates())
    shift = user.get("preferred_shift") or "all"
    ok_shift = in_shift(shift, at)
    status.update({"shift": shift, "shift_label": SHIFT_LABELS.get(shift, "Todo el día"), "in_shift": ok_shift})
    return status


@router.get("/me")
async def my_rest_status(user: dict = Depends(get_current_user_required)):
    status = await driver_availability(user, datetime.now(timezone.utc))
    status["license_number"] = user.get("license_number")
    return status


class HolidayBody(BaseModel):
    date: str
    name: str


@router.get("/holidays")
async def list_holidays(year: int | None = None, _: dict = Depends(get_current_user_required)):
    q = {"date": {"$regex": f"^{year}-"}} if year else {}
    docs = await holidays_collection.find(q, {"_id": 0}).sort("date", 1).to_list(1000)
    return {"holidays": docs}


@router.post("/holidays")
async def add_holiday(body: HolidayBody, _: dict = Depends(get_admin_user)):
    try:
        day = date.fromisoformat(body.date.strip()).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha inválida (AAAA-MM-DD)")
    await holidays_collection.update_one(
        {"date": day}, {"$set": {"name": body.name.strip(), "source": "manual", "disabled": False}}, upsert=True
    )
    _cache["at"] = 0
    return {"ok": True}


@router.delete("/holidays/{day}")
async def remove_holiday(day: str, _: dict = Depends(get_admin_user)):
    res = await holidays_collection.update_one({"date": day}, {"$set": {"disabled": True}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Festivo no encontrado")
    _cache["at"] = 0
    return {"ok": True}


@router.post("/holidays/sync")
async def force_sync(_: dict = Depends(get_admin_user)):
    try:
        return {"ok": True, "synced": await sync_madrid_calendar()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"No se pudo sincronizar: {e}")
