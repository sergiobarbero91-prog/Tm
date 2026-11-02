"""Automatic Madrid agenda: football (ESPN), big venues (Movistar Arena, Vistalegre, La Riviera, IFEMA)
and the City Council open-data agenda (datos.madrid.es), normalised to one event shape."""
import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import aiohttp
import pytz

logger = logging.getLogger(__name__)
MADRID_TZ = pytz.timezone("Europe/Madrid")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
HORIZON_DAYS = 21

# ESPN team ids → home stadium
FOOTBALL_TEAMS = {86: "Real Madrid", 1068: "Atlético de Madrid", 101: "Rayo Vallecano", 2922: "Getafe", 17534: "Leganés"}
MADRID_STADIUMS = {
    "Santiago Bernabéu": "Santiago Bernabéu",
    "Riyadh Air Metropolitano": "Riyadh Air Metropolitano",
    "Metropolitano": "Riyadh Air Metropolitano",
    "Estadio de Vallecas": "Estadio de Vallecas",
    "Vallecas": "Estadio de Vallecas",
    "Coliseum": "Coliseum (Getafe)",
    "Butarque": "Butarque (Leganés)",
}
COMPETITION_ES = {"Spanish LALIGA": "LaLiga", "Spanish LALIGA 2": "LaLiga 2", "UEFA Champions League": "Champions",
                  "UEFA Europa League": "Europa League", "UEFA Conference League": "Conference League",
                  "Spanish Copa del Rey": "Copa del Rey", "Spanish Supercopa": "Supercopa"}

AYTO_URL = "https://datos.madrid.es/egob/catalogo/206974-0-agenda-eventos-culturales-100.json"
AYTO_VENUES = ("Teatro Español", "Teatro Circo Price", "Fernán Gómez", "Matadero", "CondeDuque", "Conde Duque")
AYTO_SKIP_TYPES = ("CursosTalleres", "Exposiciones", "ClubesLectura", "ActividadesEscolares", "CapacitacionDigital",
                   "CuentacuentosTiteresMarionetas", "ConferenciasColoquios", "ExcursionesItinerariosVisitas",
                   "ItinerariosOtrasActividadesAmbientales", "RecitalesPresentacionesActosLiterarios")
RRULE_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
AYTO_SKIP_TITLE = re.compile(r"\b(curso|taller|club de lectura|visita guiada|ciclo de conferencias|laboratorio|residencia|presentación del libro|presentación de libro)\b", re.I)


def _ev(source: str, uid: str, name: str, place: str, start: datetime, end: Optional[datetime],
        category: str, hot: bool, url: str = "") -> Dict:
    end = end or start + timedelta(hours=2, minutes=30)
    if end <= start:
        end = start + timedelta(hours=2, minutes=30)
    return {
        "uid": f"{source}:{uid}", "source": source, "name": html.unescape(name).strip(), "place": place,
        "date": start.strftime("%Y-%m-%d"), "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
        "start_at": start.isoformat(), "end_at": end.isoformat(),
        "start_utc": start.astimezone(pytz.utc).isoformat(), "end_utc": end.astimezone(pytz.utc).isoformat(),
        "category": category, "hot": hot, "url": url,
    }


async def _get(session: aiohttp.ClientSession, url: str, as_json: bool = False):
    async with session.get(url, headers=UA, timeout=aiohttp.ClientTimeout(total=40)) as r:
        r.raise_for_status()
        return await r.json(content_type=None) if as_json else await r.text()


def _in_horizon(dt: datetime, now: datetime) -> bool:
    return now - timedelta(hours=6) <= dt <= now + timedelta(days=HORIZON_DAYS)


# ─── Football (ESPN public schedule) ────────────────────────────────────────

def parse_espn(data: Dict, now: datetime) -> List[Dict]:
    out = []
    for e in data.get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        venue = (comp.get("venue") or {}).get("fullName") or ""
        place = next((v for k, v in MADRID_STADIUMS.items() if k.lower() in venue.lower()), None)
        if not place or (comp.get("status") or {}).get("type", {}).get("state") != "pre":
            continue
        try:
            start = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(MADRID_TZ)
        except (KeyError, ValueError):
            continue
        if not _in_horizon(start, now):
            continue
        teams = {c.get("homeAway"): (c.get("team") or {}).get("displayName", "") for c in comp.get("competitors") or []}
        league = e.get("league", {}).get("name") if isinstance(e.get("league"), dict) else ""
        season_type = (e.get("seasonType") or {}).get("name") or ""
        comp_name = COMPETITION_ES.get(league or "", league or season_type)
        name = f"{teams.get('home', '')} – {teams.get('away', '')}" + (f" · {comp_name}" if comp_name else "")
        out.append(_ev("futbol", str(e.get("id")), name, place, start, start + timedelta(hours=2), "futbol", True))
    return out


async def fetch_football(session, now) -> List[Dict]:
    out = []
    for team_id in FOOTBALL_TEAMS:
        try:
            data = await _get(session, f"https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{team_id}/schedule?fixture=true", True)
            out += parse_espn(data, now)
        except Exception as e:
            logger.warning(f"[Agenda] ESPN team {team_id}: {e}")
    return out


# ─── Venues ─────────────────────────────────────────────────────────────────

_MA_RE = re.compile(r'href="/programacion/evento/([^"/]+)/(\d{1,2})-(\d{1,2})-(\d{4})/(\d{1,2}):(\d{2})"[^>]*?data-event-detail="([^"]+)"')
_SPORT_RE = re.compile(r"\bvs\.?\s|\bjornada\b|euroliga|euroleague|liga endesa|copa del rey|final four", re.I)


def parse_movistar_arena(page: str, now: datetime) -> List[Dict]:
    out, seen = [], set()
    for slug, d, m, y, hh, mm, name in _MA_RE.findall(page):
        start = MADRID_TZ.localize(datetime(int(y), int(m), int(d), int(hh), int(mm)))
        key = (slug, start)
        if key in seen or not _in_horizon(start, now):
            continue
        seen.add(key)
        category = "deporte" if _SPORT_RE.search(name) else "concierto"
        out.append(_ev("movistar_arena", f"{slug}-{start:%Y%m%d%H%M}", name, "Movistar Arena", start, None, category, True,
                       f"https://www.movistararena.es/programacion/evento/{slug}/{d}-{m}-{y}/{hh}:{mm}"))
    return out


def parse_vistalegre(data: Dict, now: datetime) -> List[Dict]:
    out = []
    for e in data.get("events") or []:
        try:
            start = MADRID_TZ.localize(datetime.strptime(e["start_date"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, ValueError):
            continue
        if not _in_horizon(start, now):
            continue
        out.append(_ev("vistalegre", str(e.get("id")), e.get("title", ""), "Palacio Vistalegre", start, None, "concierto", True, e.get("url", "")))
    return out


def parse_jsonld_events(page: str, place: str, source: str, category: str, hot: bool, now: datetime,
                        daily_hours: Optional[tuple] = None) -> List[Dict]:
    out = []
    for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for x in items:
            if not isinstance(x, dict) or x.get("@type") != "Event" or not x.get("startDate"):
                continue
            try:
                s = datetime.fromisoformat(x["startDate"])
                e = datetime.fromisoformat(x["endDate"]) if x.get("endDate") else None
            except ValueError:
                continue
            if daily_hours:  # multi-day fairs: one entry per day still ahead
                first = s.date()
                last = (e or s).date() if hasattr(e or s, "date") else first
                if (last - first).days > 10:  # long-running shows/exhibitions are not taxi peaks
                    continue
                for i in range((last - first).days + 1):
                    day = first + timedelta(days=i)
                    st = MADRID_TZ.localize(datetime(day.year, day.month, day.day, daily_hours[0]))
                    if _in_horizon(st, now) and st.date() >= now.date():
                        out.append(_ev(source, f"{x.get('name')}-{day}", x.get("name", ""), place, st,
                                       st.replace(hour=daily_hours[1]), category, hot, x.get("url", "")))
                continue
            start = s if s.tzinfo else MADRID_TZ.localize(s)
            start = start.astimezone(MADRID_TZ)
            if not _in_horizon(start, now):
                continue
            end = e.astimezone(MADRID_TZ) if e and e.tzinfo else None
            out.append(_ev(source, f"{x.get('name')}-{start:%Y%m%d%H%M}", x.get("name", ""), place, start, end, category, hot, x.get("url", "")))
    return out


KAPITAL_DAYS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}
KAPITAL_DEFAULT = {2: ("23:00", "05:30"), 3: ("23:00", "05:30"), 4: ("23:00", "06:00"), 5: ("23:00", "06:00"), 6: ("23:00", "05:30")}
_KAPITAL_RE = re.compile(r"(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s*:\s*(\d{1,2}:\d{2})h?\s*[–-]\s*(\d{1,2}:\d{2})", re.I)


def parse_kapital(page: str, now: datetime) -> List[Dict]:
    """Teatro Kapital (7-floor club) has no event list: one entry per opening night, from the hours on its web."""
    hours = {KAPITAL_DAYS[d.lower()]: (a, b) for d, a, b in _KAPITAL_RE.findall(html.unescape(page)) if d.lower() in KAPITAL_DAYS}
    hours = hours or KAPITAL_DEFAULT
    out = []
    for i in range(-1, HORIZON_DAYS + 1):
        day = (now + timedelta(days=i)).date()
        if day.weekday() not in hours:
            continue
        (sh, sm), (eh, em) = (map(int, t.split(":")) for t in hours[day.weekday()])
        start = MADRID_TZ.localize(datetime(day.year, day.month, day.day, sh, sm))
        end = MADRID_TZ.localize(datetime(day.year, day.month, day.day, eh, em))
        if end <= start:
            end += timedelta(days=1)
        if end < now:
            continue
        weekend = day.weekday() in (4, 5)
        out.append(_ev("kapital", f"noche-{day}", "Teatro Kapital · sesión de discoteca", "Teatro Kapital", start, end,
                       "noche", weekend, "https://teatrokapital.com/"))
    return out


async def fetch_venues(session, now) -> List[Dict]:
    jobs = {
        "movistar_arena": ("https://www.movistararena.es/programacion", lambda p: parse_movistar_arena(p, now), False),
        "kapital": ("https://teatrokapital.com/", lambda p: parse_kapital(p, now), False),
        "vistalegre": ("https://www.palaciovistalegre.com/wp-json/tribe/events/v1/events?per_page=50", lambda d: parse_vistalegre(d, now), True),
        "riviera": ("https://salariviera.com/conciertossalariviera/", lambda p: parse_jsonld_events(p, "Sala La Riviera", "riviera", "concierto", False, now), False),
        "ifema": ("https://www.ifema.es/calendario", lambda p: parse_jsonld_events(p, "IFEMA", "ifema", "feria", False, now, (10, 19)), False),
    }
    out = []
    for name, (url, parse, as_json) in jobs.items():
        try:
            out += parse(await _get(session, url, as_json))
        except Exception as e:
            logger.warning(f"[Agenda] {name}: {e}")
    return out


# ─── City Council open data ────────────────────────────────────────────────

def parse_ayuntamiento(data: Dict, now: datetime) -> List[Dict]:
    out = []
    for x in data.get("@graph") or []:
        etype = (x.get("@type") or "").rsplit("/", 1)[-1]
        venue = x.get("event-location") or ""
        if etype in AYTO_SKIP_TYPES or AYTO_SKIP_TITLE.search(x.get("title") or ""):
            continue
        if not (etype == "FiestasNavidadesReyes" or any(v in venue for v in AYTO_VENUES)):
            continue
        t = (x.get("time") or "").strip()
        try:
            ds = datetime.strptime(x["dtstart"][:16], "%Y-%m-%d %H:%M")
            de = datetime.strptime(x["dtend"][:16], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            continue
        if not t and ds.strftime("%H:%M") == "00:00":
            continue
        hh, mm = map(int, (t or ds.strftime("%H:%M")).split(":")[:2])
        excluded = set(filter(None, (x.get("excluded-days") or "").split(";")))
        rec = (x.get("recurrence") or {}).get("days")
        days = set(rec.split(",")) if rec else None
        place = venue or "Madrid"
        category = "fiesta" if etype == "FiestasNavidadesReyes" else ("musica" if etype in ("Musica", "JazzSoulFunkySwingReagge", "Flamenco") else "cultura")
        for i in range((de.date() - ds.date()).days + 1):
            day = ds.date() + timedelta(days=i)
            if days and RRULE_DAYS[day.weekday()] not in days:
                continue
            if day.strftime("%Y-%m-%d") in excluded:
                continue
            start = MADRID_TZ.localize(datetime(day.year, day.month, day.day, hh, mm))
            if not _in_horizon(start, now):
                continue
            out.append(_ev("ayuntamiento", f"{x.get('id')}-{day}", x.get("title", ""), place, start, None, category,
                           etype == "FiestasNavidadesReyes", x.get("link", "")))
    return out


async def fetch_ayuntamiento(session, now) -> List[Dict]:
    try:
        return parse_ayuntamiento(await _get(session, AYTO_URL, True), now)
    except Exception as e:
        logger.warning(f"[Agenda] datos.madrid.es: {e}")
        return []


async def fetch_all_agenda() -> List[Dict]:
    now = datetime.now(MADRID_TZ)
    async with aiohttp.ClientSession() as session:
        parts = await asyncio.gather(fetch_football(session, now), fetch_venues(session, now), fetch_ayuntamiento(session, now))
    events = [e for part in parts for e in part]
    logger.info(f"[Agenda] {len(events)} events (fútbol {len(parts[0])}, recintos {len(parts[1])}, ayuntamiento {len(parts[2])})")
    return events
