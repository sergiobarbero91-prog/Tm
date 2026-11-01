"""Live and scheduled bus arrivals for Estación Sur (Avanza live API) and Av. América (Alsa GTFS)."""
import asyncio
import csv
import io
import json
import logging
import math
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import pytz

logger = logging.getLogger(__name__)
MADRID_TZ = pytz.timezone("Europe/Madrid")

# Estación Sur: public API behind estacionsurmadrid.avanzagrupo.com
AVANZA_URL = "https://apisvt.avanzagrupo.com/sge/getServicios?estacion=ESAM&horas=15&grupo=T&previstas=1&tipo=L"
AVANZA_STATUS = {"SITUADO": "En dársena", "RETRASADO": "Retrasado"}

# Av. América: official Alsa GTFS (Punto de Acceso Nacional, mirrored by the Mobility Database)
ALSA_GTFS_URL = "https://files.mobilitydatabase.org/mdb-2825/latest.zip"
AV_AMERICA_STOP = "0000515500000001"
MIN_ORIGIN_KM = 70  # long-distance only: drops Alcalá, Guadalajara, Torrejón, Estación Sur shuttles
DATA_FILE = Path(__file__).parent / "data" / "alsa_avamerica.json"
MAX_AGE_DAYS = 7
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_schedule: Optional[Dict] = None


def _title(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"(^|[\s\-/(.,])(\w)", lambda m: m.group(1) + m.group(2).upper(), s)
    return re.sub(r" (De|Del|La|Las|Los|El|Y) ", lambda m: m.group(0).lower(), s)


# ─── Estación Sur (live) ─────────────────────────────────────────────────────

def parse_avanza(data: Dict, now: Optional[datetime] = None) -> List[Dict]:
    now = now or datetime.now(MADRID_TZ)
    out = []
    for x in data.get("data") or []:
        try:
            d, m, y = map(int, str(x.get("fx", "")).split("/"))
            hh, mm = map(int, str(x.get("hora", "")).split(":"))
            at = MADRID_TZ.localize(datetime(2000 + y, m, d, hh, mm))
        except (ValueError, TypeError):
            continue
        if not now - timedelta(minutes=60) <= at <= now + timedelta(hours=15):
            continue
        origin = (x.get("parada") or "").strip()
        out.append({
            "time": at.strftime("%H:%M"),
            "scheduled_time": at.strftime("%H:%M"),
            "origin": _title(origin) if origin and origin != "-" else "Origen sin indicar",
            "bus_company": (x.get("empresa") or "").strip() or "BUS",
            "line": (x.get("empresa") or "").strip(),
            "platform": x.get("darsena") or x.get("darsenaprevista"),
            "status": AVANZA_STATUS.get(str(x.get("cc") or "").upper(), "Programado"),
            "source": "avanza_live",
            "at": at.isoformat(),
        })
    out.sort(key=lambda a: a["at"])
    return out


async def fetch_estacion_sur_live() -> Optional[List[Dict]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(AVANZA_URL, headers={"User-Agent": "Mozilla/5.0"},
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    logger.warning(f"[Avanza] HTTP {r.status}")
                    return None
                data = await r.json(content_type=None)
    except Exception as e:
        logger.warning(f"[Avanza] Estación Sur live unavailable: {e}")
        return None
    if data.get("status") != "ok":
        return None
    arrivals = parse_avanza(data)
    logger.info(f"[Avanza] Estación Sur live: {len(arrivals)} arrivals")
    return arrivals


# ─── Av. América (Alsa GTFS schedule) ────────────────────────────────────────

def _km(a: Dict, b: Dict) -> float:
    la1, lo1, la2, lo2 = map(math.radians, map(float, (a["stop_lat"], a["stop_lon"], b["stop_lat"], b["stop_lon"])))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _clean_origin(name: str) -> str:
    name = re.sub(r"\s*\(.*?\)", "", name or "")
    return re.sub(r"\s+E\.A\.?$", "", name).strip()


def build_schedule(zip_bytes: bytes) -> Dict:
    """Reduce the Alsa GTFS to the long-distance arrivals at Av. América (+ the calendars they need)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        def rows(name):
            with z.open(name) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

        stops = {r["stop_id"]: r for r in rows("stops.txt")}
        first, hit = {}, {}
        for r in rows("stop_times.txt"):
            seq, tid = int(r["stop_sequence"]), r["trip_id"]
            if tid not in first or seq < first[tid][0]:
                first[tid] = (seq, r["stop_id"])
            if r["stop_id"] == AV_AMERICA_STOP:
                hit[tid] = (seq, r["arrival_time"], r.get("drop_off_type"))
        trip_service = {r["trip_id"]: r["service_id"] for r in rows("trips.txt") if r["trip_id"] in hit}

        target = stops[AV_AMERICA_STOP]
        trips, seen = [], set()
        for tid, (seq, t, drop) in hit.items():
            if seq == first[tid][0] or drop == "1" or tid not in trip_service:
                continue
            origin = stops.get(first[tid][1])
            if not origin or _km(origin, target) < MIN_ORIGIN_KM:
                continue
            h, m = map(int, t.split(":")[:2])
            item = (trip_service[tid], f"{h % 24:02d}:{m:02d}", h // 24, _clean_origin(origin["stop_name"]))
            if item not in seen:
                seen.add(item)
                trips.append(list(item))

        services = {t[0] for t in trips}
        calendar = {r["service_id"]: ["".join(r[d] for d in WEEKDAYS), r["start_date"], r["end_date"]]
                    for r in rows("calendar.txt") if r["service_id"] in services}
        exceptions: Dict[str, Dict[str, str]] = defaultdict(dict)
        if "calendar_dates.txt" in z.namelist():
            for r in rows("calendar_dates.txt"):
                if r["service_id"] in services:
                    exceptions[r["service_id"]][r["date"]] = r["exception_type"]

    return {
        "source": "GTFS de Alsa · Punto de Acceso Nacional (MITMS)",
        "generated": datetime.now(MADRID_TZ).isoformat(),
        "trips": trips,
        "calendar": calendar,
        "exceptions": exceptions,
    }


def _active(schedule: Dict, service_id: str, day: datetime) -> bool:
    ds = day.strftime("%Y%m%d")
    exc = schedule["exceptions"].get(service_id, {}).get(ds)
    if exc:
        return exc == "1"
    cal = schedule["calendar"].get(service_id)
    return bool(cal) and cal[1] <= ds <= cal[2] and cal[0][day.weekday()] == "1"


def avamerica_arrivals(schedule: Dict, now: Optional[datetime] = None) -> List[Dict]:
    """Scheduled long-distance arrivals at Av. América in [now-60min, now+8h]."""
    now = now or datetime.now(MADRID_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    out, seen = [], set()
    for delta in (-2, -1, 0, 1):
        svc_day = today + timedelta(days=delta)
        for service_id, hhmm, offset, origin in schedule["trips"]:
            if not _active(schedule, service_id, svc_day):
                continue
            h, m = map(int, hhmm.split(":"))
            at = MADRID_TZ.localize(datetime(svc_day.year, svc_day.month, svc_day.day, h, m) + timedelta(days=offset))
            key = (at, origin)
            if key in seen or not now - timedelta(minutes=60) <= at <= now + timedelta(hours=8):
                continue
            seen.add(key)
            out.append({
                "time": hhmm, "scheduled_time": hhmm, "origin": origin,
                "bus_company": "ALSA", "line": "Largo recorrido", "platform": None,
                "status": "Programado", "source": "alsa_gtfs", "at": at.isoformat(),
            })
    out.sort(key=lambda a: a["at"])
    return out


async def ensure_alsa_schedule(force: bool = False) -> Optional[Dict]:
    """Load the reduced Alsa schedule from disk; rebuild from the GTFS when missing or older than a week."""
    global _schedule
    if _schedule is None and DATA_FILE.exists():
        _schedule = json.loads(DATA_FILE.read_text())
    if _schedule and not force:
        age = datetime.now(MADRID_TZ) - datetime.fromisoformat(_schedule["generated"])
        if age < timedelta(days=MAX_AGE_DAYS):
            return _schedule
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(ALSA_GTFS_URL, timeout=aiohttp.ClientTimeout(total=180)) as r:
                r.raise_for_status()
                blob = await r.read()
        built = await asyncio.to_thread(build_schedule, blob)
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(built, ensure_ascii=False))
        _schedule = built
        logger.info(f"[AlsaGTFS] Av. América schedule rebuilt: {len(built['trips'])} trips")
    except Exception as e:
        logger.error(f"[AlsaGTFS] Could not refresh schedule: {e}")
    return _schedule


def get_alsa_schedule() -> Optional[Dict]:
    return _schedule


async def alsa_schedule_refresh_loop():
    while True:
        await ensure_alsa_schedule()
        await asyncio.sleep(6 * 3600)
