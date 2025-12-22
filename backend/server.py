from fastapi import FastAPI, APIRouter, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timedelta
import aiohttp
from bs4 import BeautifulSoup
import re
import asyncio
from dateutil import parser as date_parser
import json

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Station IDs for ADIF
STATION_IDS = {
    "atocha": "60000",
    "chamartin": "17000"
}

STATION_NAMES = {
    "atocha": "Madrid Puerta de Atocha",
    "chamartin": "Madrid Chamartín Clara Campoamor"
}

# Valid train types for media/larga distancia (NO cercanías)
VALID_TRAIN_TYPES = ["AVE", "AVANT", "ALVIA", "IRYO", "OUIGO", "AVLO", "EUROMED", "TALGO", "TRENHOTEL"]

TERMINALS = ["T1", "T2", "T3", "T4", "T4S"]

# Models
class TrainArrival(BaseModel):
    time: str
    origin: str
    train_type: str
    train_number: str
    platform: Optional[str] = None
    status: Optional[str] = None

class PeakHourInfo(BaseModel):
    start_hour: str
    end_hour: str
    count: int

class StationData(BaseModel):
    station_id: str
    station_name: str
    arrivals: List[TrainArrival]
    total_next_30min: int
    total_next_60min: int
    is_winner_30min: bool = False
    is_winner_60min: bool = False
    morning_arrivals: int = 0
    peak_hour: Optional[PeakHourInfo] = None

class FlightArrival(BaseModel):
    time: str
    origin: str
    flight_number: str
    airline: str
    terminal: str
    gate: Optional[str] = None
    status: Optional[str] = None

class TerminalData(BaseModel):
    terminal: str
    arrivals: List[FlightArrival]
    total_next_30min: int
    total_next_60min: int
    is_winner_30min: bool = False
    is_winner_60min: bool = False

class TrainComparisonResponse(BaseModel):
    atocha: StationData
    chamartin: StationData
    winner_30min: str
    winner_60min: str
    last_update: str
    is_night_time: bool = False
    message: Optional[str] = None

class FlightComparisonResponse(BaseModel):
    terminals: Dict[str, TerminalData]
    winner_30min: str
    winner_60min: str
    last_update: str
    is_night_time: bool = False
    message: Optional[str] = None

class NotificationSubscription(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    push_token: str
    train_alerts: bool = True
    flight_alerts: bool = True
    threshold: int = 10
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Headers for requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

# Station asset IDs for ADIF API
STATION_ASSETS = {
    "60000": "3061889",  # Atocha
    "17000": "3061911"   # Chamartín
}

def is_valid_media_larga_distancia(train_type: str) -> bool:
    """Check if train type is media/larga distancia (not cercanías)."""
    train_type_upper = train_type.upper().strip()
    # Check if it's a valid type
    for valid_type in VALID_TRAIN_TYPES:
        if valid_type in train_type_upper:
            return True
    # Reject cercanías (typically marked as C1, C2, C3, etc. or just "C")
    if train_type_upper.startswith("C") and (len(train_type_upper) <= 3 or train_type_upper[1:].isdigit()):
        return False
    return False

async def fetch_adif_arrivals_api(station_id: str) -> List[Dict]:
    """Fetch train arrivals from ADIF API - ONLY media/larga distancia."""
    arrivals = []
    
    # URL paths for each station (using /w/ format as recommended)
    url_paths = {
        "60000": "60000-madrid-pta-de-atocha",
        "17000": "17000-madrid-chamart%C3%ADn"
    }
    
    url_path = url_paths.get(station_id, url_paths["60000"])
    base_url = f"https://www.adif.es/w/{url_path}"
    asset_id = STATION_ASSETS.get(station_id, "3061889")
    
    try:
        async with aiohttp.ClientSession() as session:
            # First get the page to obtain auth token
            async with session.get(base_url, headers=HEADERS, timeout=30) as response:
                if response.status != 200:
                    logger.warning(f"Failed to get page for station {station_id}")
                    return await fetch_adif_arrivals_scrape(station_id)
                
                html = await response.text()
                
                # Extract auth token
                auth_match = re.search(r'p_p_auth=([^"&]+)', html)
                if not auth_match:
                    logger.warning(f"Could not find auth token for station {station_id}")
                    return await fetch_adif_arrivals_scrape(station_id)
                
                auth_token = auth_match.group(1)
                
                # Make API call for media/larga distancia
                api_url = f"https://www.adif.es/w/{url_path}?p_p_id=servicios_estacion_ServiciosEstacionPortlet&p_p_lifecycle=2&p_p_state=normal&p_p_mode=view&p_p_resource_id=%2FconsultarHorario&p_p_cacheability=cacheLevelPage&assetEntryId={asset_id}&p_p_auth={auth_token}"
                
                api_headers = {
                    **HEADERS,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": base_url,
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                }
                
                # Load multiple pages to get more results
                for page in range(3):
                    data_str = f"_servicios_estacion_ServiciosEstacionPortlet_searchType=proximasLlegadas&_servicios_estacion_ServiciosEstacionPortlet_trafficType=avldmd&_servicios_estacion_ServiciosEstacionPortlet_numPage={page}&_servicios_estacion_ServiciosEstacionPortlet_commuterNetwork=MADRID&_servicios_estacion_ServiciosEstacionPortlet_stationCode={station_id}"
                    
                    # Try up to 3 times per page
                    success = False
                    for retry in range(3):
                        try:
                            async with session.post(api_url, headers=api_headers, data=data_str, timeout=30) as api_response:
                                if api_response.status != 200:
                                    logger.warning(f"API returned status {api_response.status} for station {station_id} page {page}")
                                    await asyncio.sleep(0.5)
                                    continue
                                
                                result = await api_response.json()
                                
                                if result.get("error"):
                                    logger.warning(f"API error for station {station_id} page {page}, retry {retry+1}")
                                    await asyncio.sleep(0.5)
                                    continue
                                
                                horarios = result.get("horarios", [])
                                logger.info(f"Station {station_id} page {page}: API returned {len(horarios)} trains")
                                
                                if not horarios:
                                    success = True
                                    break
                                
                                for h in horarios:
                                    train_code = h.get("tren", "")
                                    type_match = re.search(r'([A-Z]{2,})', train_code)
                                    train_type = type_match.group(1) if type_match else "TREN"
                                    number_match = re.search(r'(\d{4,5})', train_code)
                                    train_number = number_match.group(1) if number_match else train_code
                                    
                                    arrivals.append({
                                        "time": h.get("hora", "00:00"),
                                        "origin": h.get("estacion", "Unknown"),
                                        "train_type": train_type.upper(),
                                        "train_number": train_number,
                                        "platform": h.get("via", "-") or "-",
                                        "status": "En hora" if not h.get("horaEstado") else h.get("horaEstado")
                                    })
                                
                                success = True
                                break
                        except Exception as e:
                            logger.warning(f"Error on retry {retry+1} for station {station_id} page {page}: {e}")
                            await asyncio.sleep(0.5)
                    
                    if not success:
                        break
                    if len(arrivals) < (page + 1) * 20:
                        break
                        
    except Exception as e:
        logger.error(f"Error fetching ADIF API for station {station_id}: {e}")
        if not arrivals:
            return await fetch_adif_arrivals_scrape(station_id)
    
    if not arrivals:
        logger.info(f"Station {station_id}: API returned 0 trains, trying HTML scrape...")
        arrivals = await fetch_adif_arrivals_scrape(station_id)
    else:
        logger.info(f"Station {station_id}: Found {len(arrivals)} media/larga distancia trains via API")
    
    return arrivals

async def fetch_adif_arrivals_scrape(station_id: str) -> List[Dict]:
    """Fallback: Fetch train arrivals by scraping ADIF website HTML directly - ONLY media/larga distancia."""
    arrivals = []
    
    # URL paths for each station (using /w/ format)
    url_paths = {
        "60000": "60000-madrid-pta-de-atocha",
        "17000": "17000-madrid-chamart%C3%ADn"
    }
    
    url_path = url_paths.get(station_id, url_paths["60000"])
    url = f"https://www.adif.es/w/{url_path}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=30) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')
                    
                    # Find the arrivals tab section
                    llegadas_section = soup.find('div', id='tab-llegadas')
                    if llegadas_section:
                        # Find the table
                        table = llegadas_section.find('table')
                        if table:
                            # Find all rows with class 'horario-row resto' (AV/Media distancia)
                            rows = table.find_all('tr', class_='horario-row')
                            
                            for row in rows:
                                try:
                                    # Check if this is a resto (AV/Media distancia) row
                                    row_classes = row.get('class', [])
                                    if 'resto' not in row_classes:
                                        continue  # Skip cercanías rows
                                    
                                    # Get all columns
                                    cols = row.find_all('td')
                                    if len(cols) < 3:
                                        continue
                                    
                                    # Get time (col 0)
                                    time_text = cols[0].get_text(strip=True)
                                    if not time_text:
                                        continue
                                    
                                    # Get origin (col 1)
                                    origin = cols[1].get_text(strip=True)
                                    origin = origin.split('\n')[0].strip()
                                    
                                    # Get train info (col 2) - format: "RF - AVANT08063"
                                    train_info = cols[2].get_text(strip=True)
                                    
                                    # Get platform (col 3)
                                    platform = cols[3].get_text(strip=True) if len(cols) > 3 else "-"
                                    
                                    # Parse train type and number
                                    # Format: "RF - AVE03063" or "IL - IRYO06261" or "RI - OUIGO06476"
                                    train_match = re.search(r'([A-Z]+)\s*-\s*([A-Z]+)(\d+)', train_info)
                                    if train_match:
                                        train_type = train_match.group(2)
                                        train_number = train_match.group(3)
                                    else:
                                        # Try simpler pattern
                                        simple_match = re.search(r'([A-Z]+)(\d+)', train_info)
                                        if simple_match:
                                            train_type = simple_match.group(1)
                                            train_number = simple_match.group(2)
                                        else:
                                            train_type = train_info[:4] if len(train_info) > 4 else train_info
                                            train_number = train_info[4:] if len(train_info) > 4 else ""
                                    
                                    # ONLY include media/larga distancia trains
                                    if is_valid_media_larga_distancia(train_type):
                                        arrivals.append({
                                            "time": time_text,
                                            "origin": origin,
                                            "train_type": train_type.upper(),
                                            "train_number": train_number,
                                            "platform": platform if platform else "-",
                                            "status": "En hora"
                                        })
                                except Exception as e:
                                    logger.debug(f"Error parsing row: {e}")
                                    continue
    except Exception as e:
        logger.error(f"Error scraping ADIF HTML for station {station_id}: {e}")
    
    logger.info(f"Station {station_id}: Scraped {len(arrivals)} media/larga distancia trains from HTML")
    return arrivals

async def fetch_aena_arrivals() -> Dict[str, List[Dict]]:
    """Fetch real flight arrivals from aeropuertomadrid-barajas.com."""
    terminal_arrivals = {t: [] for t in TERMINALS}
    
    # Fetch multiple time ranges to get more flights
    time_ranges = ["0-3", "3-6", "6-9", "9-12"]
    
    for time_range in time_ranges:
        url = f"https://www.aeropuertomadrid-barajas.com/llegadas.html?t={time_range}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'lxml')
                        
                        # Find all flight records using the specific class
                        flight_records = soup.find_all('div', class_='flightListRecord')
                        
                        for record in flight_records:
                            try:
                                # Get terminal
                                terminal_div = record.find('div', class_='flightListTerminal')
                                if not terminal_div:
                                    continue
                                terminal = terminal_div.get_text(strip=True)
                                # Normalize terminal
                                terminal = terminal.replace("T4-S", "T4S")
                                
                                if terminal not in terminal_arrivals:
                                    continue
                                
                                # Get time and origin
                                airport_div = record.find('div', class_='flightListOtherAirport')
                                if not airport_div:
                                    continue
                                
                                airport_text = airport_div.get_text(strip=True)
                                # Format: "00:15 - Milan (MXP)"
                                time_match = re.match(r'(\d{1,2}:\d{2})\s*-\s*(.+?)(?:\s*\([A-Z]{3}\))?$', airport_text)
                                if time_match:
                                    arrival_time = time_match.group(1)
                                    origin = time_match.group(2).strip()
                                else:
                                    # Fallback: just get time
                                    time_match = re.search(r'(\d{1,2}:\d{2})', airport_text)
                                    if not time_match:
                                        continue
                                    arrival_time = time_match.group(1)
                                    origin = airport_text.split('-')[-1].strip() if '-' in airport_text else "Unknown"
                                
                                # Get airline and flight number
                                airline_link = record.find('a', class_='flightListFlightIDAirline')
                                airline = airline_link.get_text(strip=True) if airline_link else "Unknown"
                                
                                flight_link = record.find('a', class_='flightListFlightIDLink')
                                flight_number = flight_link.get_text(strip=True) if flight_link else "Unknown"
                                
                                # Get status
                                status_div = record.find('div', class_='flightListStatus')
                                if status_div:
                                    status_text = status_div.get_text(strip=True).lower()
                                    if "llegado" in status_text:
                                        status = "Aterrizado"
                                    elif "retrasado" in status_text:
                                        status = "Retrasado"
                                    elif "cancelado" in status_text:
                                        status = "Cancelado"
                                    elif "adelantado" in status_text:
                                        status = "Adelantado"
                                    else:
                                        status = "En hora"
                                else:
                                    status = "En hora"
                                
                                # Avoid duplicates
                                existing = [f for f in terminal_arrivals[terminal] if f['flight_number'] == flight_number and f['time'] == arrival_time]
                                if not existing:
                                    terminal_arrivals[terminal].append({
                                        "time": arrival_time,
                                        "origin": origin,
                                        "flight_number": flight_number,
                                        "airline": airline,
                                        "terminal": terminal,
                                        "gate": "-",
                                        "status": status
                                    })
                            except Exception as e:
                                logger.debug(f"Error parsing flight record: {e}")
                                continue
        except Exception as e:
            logger.error(f"Error fetching AENA data for time range {time_range}: {e}")
    
    # Sort arrivals by time
    for terminal in TERMINALS:
        terminal_arrivals[terminal].sort(key=lambda x: x['time'])
    
    # Count total flights found
    total = sum(len(v) for v in terminal_arrivals.values())
    logger.info(f"Flights fetched: {total} total across all terminals")
    
    return terminal_arrivals

def count_arrivals_in_window(arrivals: List[Dict], minutes: int) -> int:
    """Count arrivals within the next X minutes."""
    now = datetime.now()
    count = 0
    
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            arrival_time = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            
            # Handle day rollover
            if arrival_time < now - timedelta(hours=2):
                arrival_time += timedelta(days=1)
            
            time_diff = (arrival_time - now).total_seconds() / 60
            
            if 0 <= time_diff <= minutes:
                count += 1
        except Exception:
            pass
    
    return count

def is_hour_in_shift(hour: int, shift: str) -> bool:
    """Check if an hour belongs to the specified shift.
    
    Shifts:
    - 'day' (diurno): 05:00 - 16:59 (5 AM to 5 PM)
    - 'night' (nocturno): 17:00 - 04:59 (5 PM to 5 AM)
    - 'all': All hours
    """
    if shift == "all":
        return True
    elif shift == "day":
        return 5 <= hour < 17
    elif shift == "night":
        return hour >= 17 or hour < 5
    return True

def filter_arrivals_by_shift(arrivals: List[Dict], shift: str) -> List[Dict]:
    """Filter arrivals to only include those within the specified shift."""
    if shift == "all":
        return arrivals
    
    filtered = []
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            hour = int(time_str.split(":")[0])
            if is_hour_in_shift(hour, shift):
                filtered.append(arrival)
        except:
            pass
    return filtered

def calculate_peak_hour(arrivals: List[Dict], shift: str = "all") -> Optional[Dict]:
    """Calculate the peak hour (hour with most arrivals) for a station within a shift."""
    if not arrivals:
        return None
    
    # Count arrivals per hour (only within the shift)
    hour_counts = {}
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            hour = int(time_str.split(":")[0])
            # Only count hours within the selected shift
            if is_hour_in_shift(hour, shift):
                hour_counts[hour] = hour_counts.get(hour, 0) + 1
        except:
            pass
    
    if not hour_counts:
        return None
    
    # Find the hour with most arrivals
    peak_hour = max(hour_counts, key=hour_counts.get)
    peak_count = hour_counts[peak_hour]
    
    return {
        "start_hour": f"{peak_hour:02d}:00",
        "end_hour": f"{(peak_hour + 1) % 24:02d}:00",
        "count": peak_count
    }

def count_arrivals_extended(arrivals: List[Dict], minutes: int) -> tuple:
    """Count arrivals and also count next morning arrivals if currently night time."""
    now = datetime.now()
    count = 0
    
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            arrival_time = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            
            # Handle day rollover
            if arrival_time < now - timedelta(hours=2):
                arrival_time += timedelta(days=1)
            
            time_diff = (arrival_time - now).total_seconds() / 60
            
            if 0 <= time_diff <= minutes:
                count += 1
        except Exception:
            pass
    
    # If it's night time (00:00-06:00), count morning trains
    morning_count = 0
    if now.hour < 6:
        for arrival in arrivals:
            try:
                time_str = arrival.get("time", "")
                hour = int(time_str.split(":")[0])
                if 6 <= hour <= 10:
                    morning_count += 1
            except Exception:
                pass
        return count, morning_count
    
    return count, 0

# API Endpoints
@api_router.get("/")
async def root():
    return {"message": "TransportMeter API - Frecuencia de Trenes y Aviones en Madrid"}

@api_router.get("/trains", response_model=TrainComparisonResponse)
async def get_train_comparison(shift: str = "all"):
    """Get train arrivals comparison between Atocha and Chamartín - ONLY media/larga distancia.
    
    Parameters:
    - shift: 'all' (default), 'day' (05:00-16:59), or 'night' (17:00-04:59)
    """
    now = datetime.now()
    is_night_time = now.hour < 6
    
    # Validate shift parameter
    if shift not in ["all", "day", "night"]:
        shift = "all"
    
    # Fetch data for both stations using the API
    atocha_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["atocha"])
    chamartin_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["chamartin"])
    
    # Filter arrivals by shift
    atocha_arrivals = filter_arrivals_by_shift(atocha_arrivals_raw, shift)
    chamartin_arrivals = filter_arrivals_by_shift(chamartin_arrivals_raw, shift)
    
    # Count arrivals in real time windows (always based on current time)
    atocha_30 = count_arrivals_in_window(atocha_arrivals, 30)
    atocha_60 = count_arrivals_in_window(atocha_arrivals, 60)
    chamartin_30 = count_arrivals_in_window(chamartin_arrivals, 30)
    chamartin_60 = count_arrivals_in_window(chamartin_arrivals, 60)
    
    # Calculate peak hours (within the selected shift)
    atocha_peak = calculate_peak_hour(atocha_arrivals_raw, shift)
    chamartin_peak = calculate_peak_hour(chamartin_arrivals_raw, shift)
    
    # Determine winner based on real counts
    winner_30 = "atocha" if atocha_30 >= chamartin_30 else "chamartin"
    winner_60 = "atocha" if atocha_60 >= chamartin_60 else "chamartin"
    
    # Build response
    atocha_data = StationData(
        station_id=STATION_IDS["atocha"],
        station_name=STATION_NAMES["atocha"],
        arrivals=[TrainArrival(**a) for a in atocha_arrivals[:20]],
        total_next_30min=atocha_30,
        total_next_60min=atocha_60,
        is_winner_30min=(winner_30 == "atocha"),
        is_winner_60min=(winner_60 == "atocha"),
        morning_arrivals=0,
        peak_hour=PeakHourInfo(**atocha_peak) if atocha_peak else None
    )
    
    chamartin_data = StationData(
        station_id=STATION_IDS["chamartin"],
        station_name=STATION_NAMES["chamartin"],
        arrivals=[TrainArrival(**a) for a in chamartin_arrivals[:20]],
        total_next_30min=chamartin_30,
        total_next_60min=chamartin_60,
        is_winner_30min=(winner_30 == "chamartin"),
        is_winner_60min=(winner_60 == "chamartin"),
        morning_arrivals=0,
        peak_hour=PeakHourInfo(**chamartin_peak) if chamartin_peak else None
    )
    
    message = None
    if is_night_time and atocha_30 == 0 and chamartin_30 == 0:
        message = "Horario nocturno - Sin trenes en los próximos minutos. Próximas llegadas listadas abajo."
    
    return TrainComparisonResponse(
        atocha=atocha_data,
        chamartin=chamartin_data,
        winner_30min=winner_30,
        winner_60min=winner_60,
        last_update=now.isoformat(),
        is_night_time=is_night_time,
        message=message
    )

@api_router.get("/flights", response_model=FlightComparisonResponse)
async def get_flight_comparison():
    """Get REAL flight arrivals comparison between terminals at Madrid-Barajas."""
    now = datetime.now()
    
    # Fetch real flight data from aeropuertomadrid-barajas.com
    all_arrivals = await fetch_aena_arrivals()
    
    terminal_data = {}
    max_30 = 0
    max_60 = 0
    winner_30 = "T4"
    winner_60 = "T4"
    
    for terminal in TERMINALS:
        arrivals = all_arrivals.get(terminal, [])
        count_30 = count_arrivals_in_window(arrivals, 30)
        count_60 = count_arrivals_in_window(arrivals, 60)
        
        if count_30 > max_30:
            max_30 = count_30
            winner_30 = terminal
        if count_60 > max_60:
            max_60 = count_60
            winner_60 = terminal
        
        terminal_data[terminal] = TerminalData(
            terminal=terminal,
            arrivals=[FlightArrival(**a) for a in arrivals[:15]],
            total_next_30min=count_30,
            total_next_60min=count_60
        )
    
    # Set winners
    for terminal in TERMINALS:
        terminal_data[terminal].is_winner_30min = (terminal == winner_30)
        terminal_data[terminal].is_winner_60min = (terminal == winner_60)
    
    return FlightComparisonResponse(
        terminals=terminal_data,
        winner_30min=winner_30,
        winner_60min=winner_60,
        last_update=now.isoformat()
    )

@api_router.post("/notifications/subscribe")
async def subscribe_notifications(subscription: NotificationSubscription):
    """Subscribe to push notifications."""
    sub_dict = subscription.dict()
    await db.notification_subscriptions.update_one(
        {"push_token": subscription.push_token},
        {"$set": sub_dict},
        upsert=True
    )
    return {"status": "subscribed", "id": subscription.id}

@api_router.delete("/notifications/unsubscribe/{push_token}")
async def unsubscribe_notifications(push_token: str):
    """Unsubscribe from push notifications."""
    await db.notification_subscriptions.delete_one({"push_token": push_token})
    return {"status": "unsubscribed"}

@api_router.get("/notifications/subscriptions")
async def get_subscriptions():
    """Get all notification subscriptions."""
    subs = await db.notification_subscriptions.find().to_list(1000)
    return [{"push_token": s["push_token"], "train_alerts": s.get("train_alerts", True), "flight_alerts": s.get("flight_alerts", True)} for s in subs]

@api_router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
