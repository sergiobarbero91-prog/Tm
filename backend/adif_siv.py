"""Live train arrivals from Adif's station display panels (SIV, wss://info.adif.es/InfoStation).

Same SignalR feed that powers the screens/QR panels at Atocha and Chamartín: every operator
(Renfe, Iryo, Ouigo), real delay, platform, cancellations and station notices.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytz
import websockets

logger = logging.getLogger(__name__)

SIV_HUB = "wss://info.adif.es/InfoStation"
SIV_RS = "\x1e"
SIV_TIMEOUT_S = 12
SIV_ATTEMPTS = 2
SIV_MAX_DATA_AGE_S = 5 * 60
MADRID_TZ = pytz.timezone("Europe/Madrid")

PRODUCT_NAMES = {"ICITY": "INTERCITY", "INTC": "INTERCITY", "REX": "REG.EXP", "REG": "REGIONAL", "ESPECRF": "ESPECIAL"}

# station_id -> last parsed result (used to remember trains Adif drops once they arrive)
_last: Dict[str, Dict] = {}


async def read_siv_payload(code: str) -> Dict:
    """Join the station topic and return the first fresh station snapshot."""
    topics = [f"dnv3-gravita-{code}", f"PRO-ECM-{code}"]
    raise RuntimeError("server rejected WebSocket connection: HTTP 403 (SIMULATED)")

    async def _read() -> Dict:
        async with websockets.connect(
            SIV_HUB, origin="https://info.adif.es", max_size=None, open_timeout=SIV_TIMEOUT_S
        ) as ws:
            await ws.send(json.dumps({"protocol": "json", "version": 1}) + SIV_RS)
            while True:
                raw = await ws.recv()
                for part in str(raw).split(SIV_RS):
                    if not part:
                        continue
                    msg = json.loads(part)
                    mtype = msg.get("type")
                    if mtype is None:
                        if msg.get("error"):
                            raise RuntimeError(msg["error"])
                        for t in topics:
                            await ws.send(json.dumps({"type": 1, "target": "JoinInfo", "arguments": [t]}) + SIV_RS)
                            await ws.send(json.dumps({"type": 1, "target": "GetLastMessage", "arguments": [t]}) + SIV_RS)
                    elif mtype == 1 and msg.get("target") == "ReceiveMessage":
                        data = json.loads(msg["arguments"][0])
                        settings = data.get("station_settings") or {}
                        if settings.get("code") and str(settings["code"]) != str(code):
                            continue
                        data_time = settings.get("data_time")
                        if data_time:
                            age = (datetime.now(pytz.utc) - datetime.fromisoformat(data_time)).total_seconds()
                            if age > SIV_MAX_DATA_AGE_S:
                                continue
                        return data
                    elif mtype == 7:
                        raise RuntimeError(msg.get("error") or "SIV closed the connection")

    return await asyncio.wait_for(_read(), SIV_TIMEOUT_S)


def _status_for(delay: int) -> str:
    if delay > 0:
        return f"Retraso {delay} min"
    if delay < 0:
        return "Adelantado"
    return "En hora"


def parse_siv_payload(data: Dict, prev_arrivals: Optional[List[Dict]] = None, now: Optional[datetime] = None) -> Dict:
    """SIV snapshot -> arrivals (media/larga distancia only), cancelled count and station alerts."""
    now = now or datetime.now(MADRID_TZ)
    stations = data.get("stations") or {}

    def station_name(code: Optional[str]) -> str:
        names = (stations.get(str(code)) or {}).get("name") or []
        return names[0] if names else "—"

    arrivals: List[Dict] = []
    seen, skip = set(), set()
    cancelled = 0
    for t in data.get("trains") or []:
        if t.get("class_stop") not in ("destination", "intermediate") or t.get("traffic_type") not in ("L", "R"):
            continue
        ci = (t.get("commercial_id") or [{}])[0]
        numbers = ci.get("numbers") or []
        number = numbers[0] if numbers else (t.get("technical_number_in") or str(t.get("id", "")))
        if not number or number in seen or number in skip or not t.get("arrival_time"):
            continue
        skip.update(numbers[1:])  # the other half of a coupled train
        try:
            sched = datetime.fromisoformat(t["arrival_time"]).astimezone(MADRID_TZ)
        except ValueError:
            continue
        if t.get("status") == "cancelled":
            if sched > now - timedelta(minutes=30):
                cancelled += 1
            continue
        delay = int(t.get("delay_in") or 0)
        est = sched + timedelta(minutes=delay)
        if est < now - timedelta(minutes=60) or est > now + timedelta(hours=12):
            continue
        seen.add(number)
        product = (ci.get("product") or "").upper()
        origins = t.get("origins") or [{}]
        arrivals.append({
            "time": est.strftime("%H:%M"),
            "scheduled_time": sched.strftime("%H:%M"),
            "origin": station_name(origins[0].get("code")),
            "train_type": PRODUCT_NAMES.get(product, product or "TREN"),
            "train_number": number,
            "platform": t.get("platform_in") or t.get("platform") or "-",
            "status": _status_for(delay),
            "delay_minutes": delay,
            "operator": t.get("company") or "",
            "source": "SIV",
            "est_iso": est.isoformat(),
        })

    # Adif removes trains from the panel once they arrive: keep them ~1h as "Llegado" for past counts
    for p in prev_arrivals or []:
        if p["train_number"] in seen or p["train_number"] in skip:
            continue
        try:
            est = datetime.fromisoformat(p["est_iso"])
        except (KeyError, ValueError):
            continue
        if now - timedelta(minutes=60) <= est <= now + timedelta(minutes=5):
            arrivals.append({**p, "status": "Llegado"})
            seen.add(p["train_number"])

    arrivals.sort(key=lambda a: a["est_iso"])

    alerts = []
    for a in data.get("station_alerts") or []:
        types = ((a.get("filter") or {}).get("traffic_types")) or []
        if types and not any(x in ("L", "R") for x in types):
            continue
        msg = ((a.get("message") or {}).get("ESP")) or {}
        if msg.get("header") or msg.get("description"):
            alerts.append({
                "id": a.get("id", ""),
                "level": a.get("level", "info"),
                "header": msg.get("header", ""),
                "text": msg.get("description", ""),
            })

    return {
        "arrivals": arrivals,
        "cancelled": cancelled,
        "alerts": alerts,
        "data_time": (data.get("station_settings") or {}).get("data_time"),
        "fetched_at": now.isoformat(),
    }


async def fetch_siv_station(station_id: str) -> Optional[Dict]:
    """Return parsed SIV data for a station, or None if the panel feed is unavailable."""
    payload = None
    for attempt in range(SIV_ATTEMPTS):
        try:
            payload = await read_siv_payload(station_id)
            break
        except Exception as e:
            logger.warning(f"[SIV] Station {station_id} attempt {attempt + 1} failed: {type(e).__name__} {e}")
            if "403" in str(e):
                break  # Adif blocks this server's IP: phones relay the panels instead
    if payload is None:
        return None
    return _store(station_id, payload)


def _store(station_id: str, payload: Dict) -> Dict:
    prev = (_last.get(station_id) or {}).get("arrivals")
    result = parse_siv_payload(payload, prev)
    result["station_id"] = station_id
    _last[station_id] = result
    logger.info(f"[SIV] Station {station_id}: {len(result['arrivals'])} arrivals, "
                f"{result['cancelled']} cancelled, {len(result['alerts'])} alerts")
    return result


def ingest_relayed_payload(station_id: str, payload: Dict) -> Optional[Dict]:
    """Snapshot read by a driver's phone. Accepted only if it is fresh and newer than what we have."""
    data_time = (payload.get("station_settings") or {}).get("data_time")
    if not data_time:
        return None
    try:
        dt = datetime.fromisoformat(data_time)
    except ValueError:
        return None
    if (datetime.now(pytz.utc) - dt).total_seconds() > SIV_MAX_DATA_AGE_S:
        return None
    last = _last.get(station_id) or {}
    if last.get("data_time"):
        try:
            if datetime.fromisoformat(last["data_time"]) >= dt:
                return None
        except ValueError:
            pass
    return _store(station_id, payload)


def get_siv_info(station_id: str, max_age_minutes: int = 20) -> Optional[Dict]:
    """Last SIV snapshot (alerts, cancelled, timestamp) if recent enough."""
    last = _last.get(station_id)
    if not last:
        return None
    age = datetime.now(MADRID_TZ) - datetime.fromisoformat(last["fetched_at"])
    return last if age <= timedelta(minutes=max_age_minutes) else None
