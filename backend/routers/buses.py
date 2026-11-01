"""
Bus arrivals router - Avenida de América (ALSA) and Estación Sur (Avanza)
Web scraping with schedule-based fallback.
"""
import asyncio

from fastapi import APIRouter
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pytz
import logging
import re

from bus_sources import fetch_estacion_sur_live, avamerica_arrivals, get_alsa_schedule

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/buses", tags=["buses"])

MADRID_TZ = pytz.timezone('Europe/Madrid')

# URLs for scraping
ESTACION_SUR_URL = "https://estacionsurmadrid.avanzagrupo.com/horarios/llegadas"
CHECKMYBUS_URL = "https://www.checkmybus.es/parada-de-autobus/madrid-intercambiador-avenida-de-america/a9ym8"

# Cache
_bus_cache = {
    "avenida_america": {"data": None, "timestamp": None},
    "estacion_sur": {"data": None, "timestamp": None, "source": None},
}
CACHE_TTL_MINUTES = 10
LIVE_CACHE_TTL_SECONDS = 120

SOURCE_LABELS = {
    "avanza_live": "En directo · panel de Estación Sur (Avanza)",
    "alsa_gtfs": "Horarios programados de Alsa (sin retrasos)",
    "scraping": "Web de la estación",
    "fallback": "Horarios aproximados",
}

# =============================================================================
# WEB SCRAPING
# =============================================================================

async def scrape_estacion_sur() -> List[Dict]:
    """Scrape real-time arrivals from Estación Sur website."""
    import aiohttp
    from bs4 import BeautifulSoup

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(ESTACION_SUR_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logger.warning(f"Estación Sur returned status {response.status}")
                    return []
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        if not table:
            logger.warning("No table found in Estación Sur page")
            return []

        arrivals = []
        rows = table.find_all('tr')
        for row in rows[1:]:  # Skip header
            cells = row.find_all('td')
            if len(cells) >= 4:
                time_text = cells[0].get_text(strip=True)
                company = cells[1].get_text(strip=True)
                origin = cells[2].get_text(strip=True)
                platform = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                status = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                if not time_text or not re.match(r'\d{1,2}:\d{2}', time_text):
                    continue

                arrivals.append({
                    "time": time_text,
                    "scheduled_time": time_text,
                    "origin": origin.title() if origin else "-",
                    "bus_company": company,
                    "line": company,
                    "platform": platform if platform else None,
                    "status": status if status and status != "-" else "Programado",
                })

        logger.info(f"Estación Sur: scraped {len(arrivals)} arrivals")
        return arrivals
    except Exception as e:
        logger.error(f"Error scraping Estación Sur: {e}")
        return []


async def scrape_avenida_america() -> List[Dict]:
    """Scrape arrival data from CheckMyBus for Avenida de América."""
    import aiohttp
    from bs4 import BeautifulSoup

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECKMYBUS_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    logger.warning(f"CheckMyBus returned status {response.status}")
                    return []
                html = await response.text()

        soup = BeautifulSoup(html, 'html.parser')
        arrivals = []

        # Find the arrivals section (after "Llegadas hoy" header)
        # The page has both departures and arrivals sections
        # Arrivals contain "llegando a" or have Madrid as destination
        all_text = html

        # Parse arrival entries from the page text
        # Pattern: Origin city -> Arrival time at Madrid
        arrival_pattern = re.findall(
            r'sale de .*?, (\w[\w\s-]*?) \(.*?\) a las .*? hacia .*?Avenida de Am[eé]rica.*?llegando a las \d+/\d+/\d+ (\d{1,2}:\d{2}):\d{2}',
            all_text
        )

        seen_times = set()
        for origin, arrival_time in arrival_pattern:
            origin_clean = origin.strip()
            # Simplify origin: take first word for station names
            if "Estación" in origin_clean:
                parts = origin_clean.split(",")
                if len(parts) > 0:
                    origin_clean = parts[0].replace("Estación de Autobuses", "").replace("Estación Central de Autobuses", "").replace("Estación Central", "").strip()
            if "Intermodal" in origin_clean:
                origin_clean = origin_clean.replace("Intermodal", "").strip()
            if "Parada de Autobús" in origin_clean:
                origin_clean = origin_clean.replace("Parada de Autobús", "").strip()
            if "Av. España" in origin_clean:
                origin_clean = origin_clean.replace("Av. España", "").strip()

            # Deduplicate by time+origin
            key = f"{arrival_time}_{origin_clean}"
            if key in seen_times:
                continue
            seen_times.add(key)

            # Pad time to HH:MM
            h, m = arrival_time.split(":")
            time_str = f"{int(h):02d}:{m}"

            arrivals.append({
                "time": time_str,
                "scheduled_time": time_str,
                "origin": origin_clean if origin_clean else "Desconocido",
                "bus_company": "ALSA",
                "line": "ALSA",
                "platform": None,
                "status": "Programado",
            })

        # Sort by time
        arrivals.sort(key=lambda x: x["time"])
        logger.info(f"Av. América (CheckMyBus): scraped {len(arrivals)} arrivals")
        return arrivals
    except Exception as e:
        logger.error(f"Error scraping CheckMyBus: {e}")
        return []


# =============================================================================
# FALLBACK STATIC SCHEDULES
# =============================================================================

ALSA_SCHEDULE = [
    (6, 0, "Burgos", "ALSA"), (6, 30, "Bilbao", "ALSA"), (6, 45, "Guadalajara", "ALSA"),
    (7, 0, "Zaragoza", "ALSA"), (7, 15, "Soria", "ALSA"), (7, 30, "Santander", "ALSA"),
    (7, 45, "Guadalajara", "ALSA"), (8, 0, "San Sebastián", "ALSA"), (8, 15, "Logroño", "ALSA"),
    (8, 30, "Pamplona", "ALSA"), (8, 45, "Alcalá de Henares", "Interurbano"),
    (9, 0, "Burgos", "ALSA"), (9, 15, "Guadalajara", "ALSA"), (9, 45, "Zaragoza", "ALSA"),
    (10, 0, "Bilbao", "ALSA"), (10, 30, "Santander", "ALSA"), (10, 45, "Guadalajara", "ALSA"),
    (11, 0, "Soria", "ALSA"), (11, 30, "Alcalá de Henares", "Interurbano"),
    (11, 45, "Logroño", "ALSA"), (12, 0, "Zaragoza", "ALSA"), (12, 30, "Burgos", "ALSA"),
    (12, 45, "Guadalajara", "ALSA"), (13, 0, "San Sebastián", "ALSA"), (13, 30, "Pamplona", "ALSA"),
    (14, 0, "Bilbao", "ALSA"), (14, 30, "Santander", "ALSA"), (14, 45, "Guadalajara", "ALSA"),
    (15, 0, "Zaragoza", "ALSA"), (15, 30, "Soria", "ALSA"),
    (16, 0, "Burgos", "ALSA"), (16, 30, "Logroño", "ALSA"), (16, 45, "Guadalajara", "ALSA"),
    (17, 0, "Bilbao", "ALSA"), (17, 30, "San Sebastián", "ALSA"),
    (18, 0, "Zaragoza", "ALSA"), (18, 30, "Santander", "ALSA"), (18, 45, "Guadalajara", "ALSA"),
    (19, 0, "Pamplona", "ALSA"), (19, 30, "Burgos", "ALSA"),
    (20, 0, "Bilbao", "ALSA"), (20, 30, "Soria", "ALSA"), (20, 45, "Guadalajara", "ALSA"),
    (21, 0, "Zaragoza", "ALSA"), (21, 30, "Logroño", "ALSA"),
    (22, 0, "Santander", "ALSA"), (22, 30, "Bilbao", "ALSA"),
    (23, 0, "San Sebastián", "ALSA"), (23, 30, "Burgos", "ALSA"),
]

AVANZA_SCHEDULE = [
    (6, 0, "Salamanca", "Avanza"), (6, 30, "Segovia", "Avanza"), (6, 45, "Ávila", "Avanza"),
    (7, 0, "Cáceres", "Avanza"), (7, 15, "Segovia", "Avanza"), (7, 30, "Badajoz", "Avanza"),
    (7, 45, "Toledo", "SAMAR"), (8, 0, "Salamanca", "Avanza"), (8, 15, "Mérida", "Avanza"),
    (8, 30, "Segovia", "Avanza"), (8, 45, "Toledo", "SAMAR"), (9, 0, "Ávila", "Avanza"),
    (9, 15, "Cáceres", "Avanza"), (9, 30, "Salamanca", "Avanza"), (9, 45, "Segovia", "Avanza"),
    (10, 0, "Badajoz", "Avanza"), (10, 15, "Toledo", "SAMAR"), (10, 30, "Zamora", "Avanza"),
    (10, 45, "Segovia", "Avanza"), (11, 0, "Salamanca", "Avanza"), (11, 30, "Ávila", "Avanza"),
    (11, 45, "Toledo", "SAMAR"), (12, 0, "Cáceres", "Avanza"), (12, 15, "Segovia", "Avanza"),
    (12, 30, "Salamanca", "Avanza"), (12, 45, "Toledo", "SAMAR"), (13, 0, "Mérida", "Avanza"),
    (13, 15, "Segovia", "Avanza"), (13, 30, "Badajoz", "Avanza"), (13, 45, "Ávila", "Avanza"),
    (14, 0, "Salamanca", "Avanza"), (14, 15, "Toledo", "SAMAR"), (14, 30, "Segovia", "Avanza"),
    (14, 45, "Zamora", "Avanza"), (15, 0, "Cáceres", "Avanza"), (15, 30, "Salamanca", "Avanza"),
    (15, 45, "Segovia", "Avanza"), (16, 0, "Toledo", "SAMAR"), (16, 15, "Ávila", "Avanza"),
    (16, 30, "Badajoz", "Avanza"), (16, 45, "Segovia", "Avanza"),
    (17, 0, "Salamanca", "Avanza"), (17, 15, "Mérida", "Avanza"), (17, 30, "Toledo", "SAMAR"),
    (17, 45, "Segovia", "Avanza"), (18, 0, "Cáceres", "Avanza"), (18, 15, "Salamanca", "Avanza"),
    (18, 30, "Ávila", "Avanza"), (18, 45, "Segovia", "Avanza"), (19, 0, "Toledo", "SAMAR"),
    (19, 15, "Badajoz", "Avanza"), (19, 30, "Salamanca", "Avanza"), (19, 45, "Segovia", "Avanza"),
    (20, 0, "Zamora", "Avanza"), (20, 15, "Toledo", "SAMAR"), (20, 30, "Cáceres", "Avanza"),
    (20, 45, "Salamanca", "Avanza"), (21, 0, "Segovia", "Avanza"), (21, 30, "Ávila", "Avanza"),
    (21, 45, "Toledo", "SAMAR"), (22, 0, "Salamanca", "Avanza"), (22, 30, "Badajoz", "Avanza"),
    (23, 0, "Mérida", "Avanza"), (23, 30, "Segovia", "Avanza"),
]


def generate_fallback_arrivals(schedule: list) -> List[Dict]:
    """Generate arrivals from static schedule as fallback."""
    arrivals = []
    for hour, minute, origin, company in schedule:
        arrivals.append({
            "time": f"{hour:02d}:{minute:02d}",
            "scheduled_time": f"{hour:02d}:{minute:02d}",
            "origin": origin,
            "bus_company": company,
            "line": company,
            "platform": None,
            "status": "Programado",
        })
    return arrivals


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def filter_and_count_arrivals(arrivals: List[Dict], minutes: int) -> tuple:
    """Filter arrivals within the next N minutes and count them."""
    now = datetime.now(MADRID_TZ)
    cutoff = now + timedelta(minutes=minutes)
    past_cutoff = now - timedelta(minutes=minutes // 2)

    future_count = 0
    past_count = 0

    for a in arrivals:
        try:
            h, m = map(int, a["time"].split(":"))
            arr_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if arr_dt < now - timedelta(hours=2):
                arr_dt += timedelta(days=1)
            if now <= arr_dt <= cutoff:
                future_count += 1
            elif past_cutoff <= arr_dt < now:
                past_count += 1
        except Exception:
            continue

    return future_count, past_count


def calculate_score(future_count: int, past_count: int) -> float:
    return round(future_count * 0.7 + past_count * 0.3, 2)


def filter_upcoming(arrivals: List[Dict]) -> List[Dict]:
    """Filter to show arrivals in a reasonable window around now."""
    now = datetime.now(MADRID_TZ)
    result = []
    for a in arrivals:
        try:
            h, m = map(int, a["time"].split(":"))
            arr_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if arr_dt < now - timedelta(hours=1):
                arr_dt += timedelta(days=1)
            if now - timedelta(minutes=5) <= arr_dt <= now + timedelta(hours=3):
                result.append(a)
        except Exception:
            continue
    return result


# =============================================================================
# API ENDPOINT
# =============================================================================

async def _estacion_sur(now: datetime) -> tuple:
    cache = _bus_cache["estacion_sur"]
    if cache["data"] and cache["timestamp"] and (now - cache["timestamp"]).total_seconds() < LIVE_CACHE_TTL_SECONDS:
        return cache["data"], cache["source"]
    arrivals, source = await fetch_estacion_sur_live(), "avanza_live"
    if not arrivals:
        arrivals, source = await scrape_estacion_sur(), "scraping"
    if arrivals:
        _bus_cache["estacion_sur"] = {"data": arrivals, "timestamp": now, "source": source}
        return arrivals, source
    return generate_fallback_arrivals(AVANZA_SCHEDULE), "fallback"


async def _avenida_america(now: datetime) -> tuple:
    schedule = get_alsa_schedule()
    if schedule:
        arrivals = avamerica_arrivals(schedule, now)
        if arrivals:
            return arrivals, "alsa_gtfs"
    cache = _bus_cache["avenida_america"]
    if cache["data"] and cache["timestamp"] and (now - cache["timestamp"]).total_seconds() < CACHE_TTL_MINUTES * 60:
        return cache["data"], "scraping"
    arrivals = await scrape_avenida_america()
    if arrivals:
        _bus_cache["avenida_america"] = {"data": arrivals, "timestamp": now}
        return arrivals, "scraping"
    return generate_fallback_arrivals(ALSA_SCHEDULE), "fallback"


def _station_payload(key: str, name: str, arrivals: List[Dict], source: str) -> Dict:
    display = filter_upcoming(arrivals)
    if not display and source in ("scraping",):
        arrivals = generate_fallback_arrivals(ALSA_SCHEDULE if key == "avenida_america" else AVANZA_SCHEDULE)
        display, source = filter_upcoming(arrivals), "fallback"
    c30, p30 = filter_and_count_arrivals(arrivals, 30)
    c60, p60 = filter_and_count_arrivals(arrivals, 60)
    return {
        "station_id": key,
        "station_name": name,
        "arrivals": display,
        "total_next_30min": c30,
        "total_next_60min": c60,
        "score_30min": calculate_score(c30, p30),
        "score_60min": calculate_score(c60, p60),
        "past_30min": p30,
        "past_60min": p60,
        "source": source,
        "source_label": SOURCE_LABELS[source],
    }


@router.get("")
async def get_bus_comparison():
    """Bus arrivals: Estación Sur live (Avanza API) and Av. América scheduled (Alsa GTFS)."""
    now = datetime.now(MADRID_TZ)
    (aa_arrivals, aa_source), (es_arrivals, es_source) = await asyncio.gather(_avenida_america(now), _estacion_sur(now))
    aa = _station_payload("avenida_america", "Av. América (ALSA)", aa_arrivals, aa_source)
    es = _station_payload("estacion_sur", "Estación Sur (Avanza)", es_arrivals, es_source)

    winner_30 = "avenida_america" if aa["score_30min"] >= es["score_30min"] else "estacion_sur"
    winner_60 = "avenida_america" if aa["score_60min"] >= es["score_60min"] else "estacion_sur"
    for st in (aa, es):
        st["is_winner_30min"] = st["station_id"] == winner_30
        st["is_winner_60min"] = st["station_id"] == winner_60

    return {
        "avenida_america": aa,
        "estacion_sur": es,
        "winner_30min": winner_30,
        "winner_60min": winner_60,
        "last_update": now.isoformat(),
        "data_source": f"Av. América: {aa['source_label']} · Estación Sur: {es['source_label']}",
        "message": None,
    }
