from fastapi import FastAPI, APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
import pytz
from jose import JWTError, jwt
from passlib.context import CryptContext

# Madrid timezone
MADRID_TZ = pytz.timezone('Europe/Madrid')

# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "transportmeter-secret-key-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer(auto_error=False)

# Cache for train/flight data (to avoid excessive API calls)
arrival_cache = {
    "trains": {"data": {}, "timestamp": None},
    "flights": {"data": {}, "timestamp": None}
}
CACHE_TTL_SECONDS = 60  # Cache data for 60 seconds

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
users_collection = db['users']
street_activities_collection = db['street_activities']
taxi_status_collection = db['taxi_status']

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

# Coordinates for stations and terminals (for hotspot calculation)
STATION_COORDS = {
    "Atocha": {"lat": 40.4065, "lng": -3.6895},
    "Chamartín": {"lat": 40.4722, "lng": -3.6825}
}

TERMINAL_COORDS = {
    "T1": {"lat": 40.4936, "lng": -3.5668},
    "T2-T3": {"lat": 40.4950, "lng": -3.5700},
    "T4-T4S": {"lat": 40.4719, "lng": -3.5357}
}

# Terminal groupings for zone calculation
TERMINAL_GROUPS = {
    "T1": "T1",
    "T2": "T2-T3",
    "T3": "T2-T3",
    "T2-T3": "T2-T3",
    "T4": "T4-T4S",
    "T4S": "T4-T4S",
    "T4-T4S": "T4-T4S"
}

# Models
class TrainArrival(BaseModel):
    time: str  # Hora real de llegada (con retraso si aplica)
    scheduled_time: Optional[str] = None  # Hora programada original
    origin: str
    train_type: str
    train_number: str
    platform: Optional[str] = None
    status: Optional[str] = None
    delay_minutes: Optional[int] = None  # Minutos de retraso

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
    time: str  # Hora real de llegada
    scheduled_time: Optional[str] = None  # Hora programada
    origin: str
    flight_number: str
    airline: str
    terminal: str
    gate: Optional[str] = None
    status: Optional[str] = None
    delay_minutes: Optional[int] = None  # Minutos de retraso

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

# Street Work Models
class StreetActivity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    username: str
    action: str  # "load", "unload", "station_entry", "station_exit", "terminal_entry", "terminal_exit"
    latitude: float
    longitude: float
    street_name: str
    location_name: Optional[str] = None  # Name of station or terminal
    city: str = "Madrid"
    created_at: datetime = Field(default_factory=lambda: datetime.now(MADRID_TZ))
    duration_minutes: Optional[int] = None  # Duration for completed activities

class StreetActivityCreate(BaseModel):
    action: str  # "load" or "unload"
    latitude: float
    longitude: float
    street_name: str

class HotStreet(BaseModel):
    street_name: str
    count: int
    last_activity: datetime
    latitude: float
    longitude: float
    distance_km: Optional[float] = None  # Distance from user in km

class StreetWorkResponse(BaseModel):
    # Hottest street (only load/unload activities)
    hottest_street: Optional[str]
    hottest_street_lat: Optional[float] = None
    hottest_street_lng: Optional[float] = None
    hottest_count: int
    hottest_percentage: Optional[float] = None  # Percentage of total street loads
    hottest_total_loads: int = 0  # Total loads for context
    hottest_distance_km: Optional[float] = None
    hot_streets: List[HotStreet]
    
    # Hottest station (based on weighted score)
    hottest_station: Optional[str] = None
    hottest_station_count: int = 0
    hottest_station_lat: Optional[float] = None
    hottest_station_lng: Optional[float] = None
    hottest_station_score: Optional[float] = None
    hottest_station_avg_load_time: Optional[float] = None
    hottest_station_arrivals: Optional[int] = None
    hottest_station_exits: Optional[int] = None
    hottest_station_future_arrivals: Optional[int] = None
    hottest_station_low_arrivals_alert: bool = False
    
    # Hottest terminal (based on weighted score)
    hottest_terminal: Optional[str] = None
    hottest_terminal_count: int = 0
    hottest_terminal_lat: Optional[float] = None
    hottest_terminal_lng: Optional[float] = None
    hottest_terminal_score: Optional[float] = None
    hottest_terminal_avg_load_time: Optional[float] = None
    hottest_terminal_arrivals: Optional[int] = None
    hottest_terminal_exits: Optional[int] = None
    hottest_terminal_future_arrivals: Optional[int] = None
    hottest_terminal_low_arrivals_alert: bool = False
    
    # Taxi status for hottest locations
    hottest_station_taxi_status: Optional[str] = None
    hottest_station_taxi_time: Optional[str] = None
    hottest_station_taxi_reporter: Optional[str] = None
    hottest_terminal_taxi_status: Optional[str] = None
    hottest_terminal_taxi_time: Optional[str] = None
    hottest_terminal_taxi_reporter: Optional[str] = None
    
    recent_activities: List[StreetActivity]
    total_loads: int
    total_unloads: int
    total_station_entries: int = 0
    total_station_exits: int = 0
    total_terminal_entries: int = 0
    total_terminal_exits: int = 0
    last_update: str

# Check-in Models
class CheckInRequest(BaseModel):
    location_type: str  # 'station' or 'terminal'
    location_name: str  # e.g., 'Atocha', 'T4'
    action: str  # 'entry' or 'exit'
    latitude: float
    longitude: float
    taxi_status: Optional[str] = None  # 'poco', 'normal', 'mucho' - only for 'entry'

class TaxiStatusResponse(BaseModel):
    location_type: str
    location_name: str
    taxi_status: str  # 'poco', 'normal', 'mucho'
    reported_at: str
    reported_by: str

class CheckInStatus(BaseModel):
    is_checked_in: bool
    location_type: Optional[str] = None
    location_name: Optional[str] = None
    entry_time: Optional[str] = None

# Authentication Models
class UserInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    hashed_password: str
    phone: Optional[str] = None
    role: str = "user"  # "admin" or "user"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class UserCreate(BaseModel):
    username: str
    password: str
    phone: Optional[str] = None
    role: str = "user"

class UserUpdate(BaseModel):
    phone: Optional[str] = None
    role: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: Optional[str] = None  # Optional for admin changing others
    new_password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    phone: Optional[str] = None
    role: str
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# Authentication helper functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    if credentials is None:
        return None
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        user = await users_collection.find_one({"id": user_id})
        return user
    except JWTError:
        return None

async def get_current_user_required(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user_required(credentials)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    return user

async def create_default_admin():
    """Create default admin user if it doesn't exist."""
    existing_admin = await users_collection.find_one({"username": "admin"})
    if not existing_admin:
        admin_user = {
            "id": str(uuid.uuid4()),
            "username": "admin",
            "hashed_password": get_password_hash("admin"),
            "phone": None,
            "role": "admin",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await users_collection.insert_one(admin_user)
        logger.info("Default admin user created: admin/admin")

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

def normalize_time_string(time_str: str) -> str:
    """Normalize time string to HH:MM format.
    
    Sometimes ADIF returns concatenated times like '13:0513:25' (scheduled + actual).
    This function extracts only the first valid time.
    """
    if not time_str:
        return "00:00"
    
    # Try to extract the first HH:MM pattern
    match = re.match(r'(\d{1,2}:\d{2})', time_str)
    if match:
        return match.group(1)
    
    return time_str[:5] if len(time_str) >= 5 else time_str

async def fetch_adif_arrivals_api(station_id: str, max_global_retries: int = 5) -> List[Dict]:
    """Fetch train arrivals from ADIF API - ONLY media/larga distancia.
    
    Will retry up to max_global_retries times if no results are obtained.
    """
    
    for global_retry in range(max_global_retries):
        arrivals = await _fetch_adif_arrivals_single_attempt(station_id)
        
        if arrivals:
            if global_retry > 0:
                logger.info(f"Station {station_id}: Got {len(arrivals)} trains on attempt {global_retry + 1}")
            return arrivals
        
        # If no results, wait a bit and retry
        if global_retry < max_global_retries - 1:
            logger.info(f"Station {station_id}: No results on attempt {global_retry + 1}, retrying...")
            await asyncio.sleep(1)
    
    logger.warning(f"Station {station_id}: Failed to get results after {max_global_retries} attempts")
    return []

async def _fetch_adif_arrivals_single_attempt(station_id: str) -> List[Dict]:
    """Single attempt to fetch train arrivals from ADIF API."""
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
                                    
                                    # Get scheduled and real times
                                    scheduled_time = normalize_time_string(h.get("hora", "00:00"))
                                    hora_estado = h.get("horaEstado", "")
                                    
                                    # horaEstado contains the real arrival time when there's a delay
                                    if hora_estado and hora_estado.strip():
                                        real_time = normalize_time_string(hora_estado)
                                        # Calculate delay in minutes
                                        try:
                                            sched_parts = scheduled_time.split(":")
                                            real_parts = real_time.split(":")
                                            sched_mins = int(sched_parts[0]) * 60 + int(sched_parts[1])
                                            real_mins = int(real_parts[0]) * 60 + int(real_parts[1])
                                            delay = real_mins - sched_mins
                                            # Handle day rollover
                                            if delay < -120:
                                                delay += 24 * 60
                                            status = f"Retraso {delay} min" if delay > 0 else "Adelantado"
                                        except:
                                            delay = None
                                            status = "Retrasado"
                                    else:
                                        real_time = scheduled_time
                                        delay = None
                                        status = "En hora"
                                    
                                    arrivals.append({
                                        "time": real_time,  # Use real arrival time
                                        "scheduled_time": scheduled_time,
                                        "origin": h.get("estacion", "Unknown"),
                                        "train_type": train_type.upper(),
                                        "train_number": train_number,
                                        "platform": h.get("via", "-") or "-",
                                        "status": status,
                                        "delay_minutes": delay
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
                                            "time": normalize_time_string(time_text),
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
    
    # Calculate current time range and fetch relevant ranges
    now = datetime.now(MADRID_TZ)
    current_hour = now.hour
    
    # Generate time ranges based on current hour
    # Each range covers 3 hours: 0-3, 3-6, 6-9, 9-12, 12-15, 15-18, 18-21, 21-24
    all_ranges = ["0-3", "3-6", "6-9", "9-12", "12-15", "15-18", "18-21", "21-24"]
    
    # Find current range index
    current_range_idx = current_hour // 3
    
    # Fetch current range and next 2 ranges (to cover ~9 hours ahead)
    time_ranges = []
    for i in range(3):
        idx = (current_range_idx + i) % 8
        time_ranges.append(all_ranges[idx])
    
    logger.info(f"Fetching flight data for time ranges: {time_ranges}")
    
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
                                
                                # Get status and real arrival time if delayed
                                status_div = record.find('div', class_='flightListStatus')
                                real_time = None
                                if status_div:
                                    status_text = status_div.get_text(strip=True).lower()
                                    if "llegado" in status_text:
                                        status = "Aterrizado"
                                    elif "retrasado" in status_text:
                                        status = "Retrasado"
                                        # Try to get the real arrival time from the delayed link
                                        time_status_div = record.find('div', class_='flightListTimeStatus')
                                        if time_status_div:
                                            delayed_link = time_status_div.find('a', class_='flightDetailDelayed')
                                            if delayed_link:
                                                delayed_time_text = delayed_link.get_text(strip=True)
                                                delayed_time_match = re.match(r'(\d{1,2}:\d{2})', delayed_time_text)
                                                if delayed_time_match:
                                                    real_time = delayed_time_match.group(1)
                                    elif "cancelado" in status_text:
                                        status = "Cancelado"
                                    elif "adelantado" in status_text:
                                        status = "Adelantado"
                                        # Try to get the real arrival time from the advanced link
                                        time_status_div = record.find('div', class_='flightListTimeStatus')
                                        if time_status_div:
                                            advanced_link = time_status_div.find('a', class_='flightDetailAdvanced')
                                            if advanced_link:
                                                advanced_time_text = advanced_link.get_text(strip=True)
                                                advanced_time_match = re.match(r'(\d{1,2}:\d{2})', advanced_time_text)
                                                if advanced_time_match:
                                                    real_time = advanced_time_match.group(1)
                                    else:
                                        status = "En hora"
                                else:
                                    status = "En hora"
                                
                                # Use real time if available (for delayed/advanced flights)
                                final_time = real_time if real_time else arrival_time
                                
                                # Calculate delay in minutes
                                delay_minutes = None
                                if real_time and arrival_time and real_time != arrival_time:
                                    try:
                                        sched_parts = arrival_time.split(":")
                                        real_parts = real_time.split(":")
                                        sched_mins = int(sched_parts[0]) * 60 + int(sched_parts[1])
                                        real_mins = int(real_parts[0]) * 60 + int(real_parts[1])
                                        delay = real_mins - sched_mins
                                        # Handle day rollover
                                        if delay < -120:
                                            delay += 24 * 60
                                        delay_minutes = delay if delay > 0 else delay  # Negative for early
                                    except:
                                        pass
                                
                                # Avoid duplicates
                                existing = [f for f in terminal_arrivals[terminal] if f['flight_number'] == flight_number and f['time'] == final_time]
                                if not existing:
                                    terminal_arrivals[terminal].append({
                                        "time": final_time,
                                        "scheduled_time": arrival_time,
                                        "origin": origin,
                                        "flight_number": flight_number,
                                        "airline": airline,
                                        "terminal": terminal,
                                        "gate": "-",
                                        "status": status,
                                        "delay_minutes": delay_minutes
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
    """Count arrivals within the next X minutes using Madrid timezone."""
    now = datetime.now(MADRID_TZ)
    count = 0
    
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            # Parse time and set to today in Madrid timezone
            arrival_time = datetime.strptime(time_str, "%H:%M")
            arrival_time = MADRID_TZ.localize(arrival_time.replace(
                year=now.year, month=now.month, day=now.day
            ))
            
            # Handle day rollover
            if arrival_time < now - timedelta(hours=2):
                arrival_time += timedelta(days=1)
            
            time_diff = (arrival_time - now).total_seconds() / 60
            
            if 0 <= time_diff <= minutes:
                count += 1
        except Exception:
            pass
    
    return count

def count_arrivals_in_past_window(arrivals: List[Dict], minutes_start: int, minutes_end: int) -> int:
    """Count arrivals that happened between minutes_start and minutes_end ago.
    E.g., count_arrivals_in_past_window(arrivals, 60, 30) counts arrivals from -60 to -30 minutes ago.
    """
    now = datetime.now(MADRID_TZ)
    count = 0
    
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            # Parse time and set to today in Madrid timezone
            arrival_time = datetime.strptime(time_str, "%H:%M")
            arrival_time = MADRID_TZ.localize(arrival_time.replace(
                year=now.year, month=now.month, day=now.day
            ))
            
            # Handle day rollover (if arrival time is much later than now, it was yesterday)
            if arrival_time > now + timedelta(hours=12):
                arrival_time -= timedelta(days=1)
            
            time_diff = (now - arrival_time).total_seconds() / 60  # Positive = past
            
            # Check if arrival is within the past window
            if minutes_end <= time_diff <= minutes_start:
                count += 1
        except Exception:
            pass
    
    return count

def filter_future_flights(arrivals: List[Dict]) -> List[Dict]:
    """Filter flights to only include those that haven't arrived yet (excluding 'Aterrizado')."""
    now = datetime.now(MADRID_TZ)
    filtered = []
    
    for arrival in arrivals:
        try:
            # Skip flights that have already landed
            status = arrival.get("status", "").lower()
            if "aterrizado" in status or "llegado" in status:
                continue
            
            # Also check if the flight time is in the future
            time_str = arrival.get("time", "")
            arrival_time = datetime.strptime(time_str, "%H:%M")
            arrival_time = MADRID_TZ.localize(arrival_time.replace(
                year=now.year, month=now.month, day=now.day
            ))
            
            # Handle day rollover
            if arrival_time < now - timedelta(hours=2):
                arrival_time += timedelta(days=1)
            
            # Only include future flights (within next 4 hours buffer for delays)
            time_diff = (arrival_time - now).total_seconds() / 60
            if time_diff >= -30:  # Allow 30 min buffer for recently landed
                filtered.append(arrival)
        except:
            pass
    
    return filtered

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
    now = datetime.now(MADRID_TZ)
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
    now = datetime.now(MADRID_TZ)
    
    # Fetch real flight data from aeropuertomadrid-barajas.com
    all_arrivals = await fetch_aena_arrivals()
    
    terminal_data = {}
    max_30 = 0
    max_60 = 0
    winner_30 = "T4"
    winner_60 = "T4"
    
    for terminal in TERMINALS:
        raw_arrivals = all_arrivals.get(terminal, [])
        # Filter out flights that have already landed
        arrivals = filter_future_flights(raw_arrivals)
        
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

# ============== AUTHENTICATION ENDPOINTS ==============

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(login_data: UserLogin):
    """Login with username and password."""
    user = await users_collection.find_one({"username": login_data.username})
    if not user or not verify_password(login_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )
    
    access_token = create_access_token(data={"sub": user["id"]})
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            phone=user.get("phone"),
            role=user["role"],
            created_at=user["created_at"]
        )
    )

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user_required)):
    """Get current authenticated user."""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        phone=current_user.get("phone"),
        role=current_user["role"],
        created_at=current_user["created_at"]
    )

@api_router.put("/auth/password")
async def change_own_password(
    password_data: PasswordChange,
    current_user: dict = Depends(get_current_user_required)
):
    """Change own password (requires current password)."""
    if not password_data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña actual"
        )
    
    if not verify_password(password_data.current_password, current_user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )
    
    new_hash = get_password_hash(password_data.new_password)
    await users_collection.update_one(
        {"id": current_user["id"]},
        {"$set": {"hashed_password": new_hash, "updated_at": datetime.utcnow()}}
    )
    
    return {"message": "Contraseña actualizada correctamente"}

# ============== STREET WORK ENDPOINTS ==============

@api_router.post("/street/activity")
async def register_street_activity(
    activity: StreetActivityCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Register a load or unload activity at current location."""
    now = datetime.now(MADRID_TZ)
    
    activity_id = str(uuid.uuid4())
    new_activity = {
        "id": activity_id,
        "user_id": current_user["id"],
        "username": current_user["username"],
        "action": activity.action,
        "latitude": activity.latitude,
        "longitude": activity.longitude,
        "street_name": activity.street_name,
        "city": "Madrid",
        "created_at": now
    }
    
    await street_activities_collection.insert_one(new_activity)
    
    # Determine if there's now an active load
    has_active_load = activity.action == "load"
    
    # Return a clean response without MongoDB _id
    return {
        "message": f"Actividad '{activity.action}' registrada en {activity.street_name}",
        "activity": {
            "id": activity_id,
            "user_id": current_user["id"],
            "username": current_user["username"],
            "action": activity.action,
            "latitude": activity.latitude,
            "longitude": activity.longitude,
            "street_name": activity.street_name,
            "city": "Madrid",
            "created_at": now.isoformat()
        },
        "has_active_load": has_active_load
    }

@api_router.get("/street/load-status")
async def get_load_status(
    current_user: dict = Depends(get_current_user_required)
):
    """Check if user has an active load (load without subsequent unload)."""
    user_id = current_user["id"]
    now = datetime.now(MADRID_TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get the most recent load/unload activity for today
    last_activity = await street_activities_collection.find_one(
        {
            "user_id": user_id,
            "action": {"$in": ["load", "unload"]},
            "created_at": {"$gte": start_of_day}
        },
        sort=[("created_at", -1)]
    )
    
    has_active_load = last_activity is not None and last_activity.get("action") == "load"
    
    return {
        "has_active_load": has_active_load,
        "last_action": last_activity.get("action") if last_activity else None,
        "last_street": last_activity.get("street_name") if last_activity else None
    }

@api_router.get("/geocode/reverse")
async def reverse_geocode(
    lat: float,
    lng: float,
    current_user: dict = Depends(get_current_user_required)
):
    """Get street name from coordinates using Nominatim."""
    try:
        from geopy.geocoders import Nominatim
        from geopy.distance import geodesic
        
        geolocator = Nominatim(user_agent="transport_meter_app_v2")
        
        # Try to get the location
        location = geolocator.reverse(f"{lat}, {lng}", language="es", exactly_one=True)
        
        if location and location.raw:
            address = location.raw.get("address", {})
            
            # Try multiple fields to get the best street name
            street = (
                address.get("road") or 
                address.get("pedestrian") or 
                address.get("footway") or
                address.get("path") or
                address.get("cycleway") or
                address.get("neighbourhood") or
                address.get("suburb") or
                "Calle desconocida"
            )
            
            # Get house number if available
            house_number = address.get("house_number", "")
            
            # Calculate points 75m ahead and behind on the street
            # We use a simple approximation: 75m ≈ 0.000675 degrees latitude
            lat_offset = 0.000675  # ~75 meters
            
            return {
                "street": street,
                "house_number": house_number,
                "full_address": location.address,
                "lat": lat,
                "lng": lng,
                "range_start_lat": lat - lat_offset,
                "range_end_lat": lat + lat_offset,
                "range_meters": 150  # 75m ahead + 75m behind
            }
        
        return {
            "street": "Calle desconocida",
            "house_number": "",
            "full_address": "",
            "lat": lat,
            "lng": lng,
            "range_start_lat": lat - 0.000675,
            "range_end_lat": lat + 0.000675,
            "range_meters": 150
        }
    except Exception as e:
        logger.error(f"Reverse geocoding error: {e}")
        return {
            "street": "Calle desconocida",
            "error": str(e),
            "lat": lat,
            "lng": lng
        }

@api_router.get("/street/data", response_model=StreetWorkResponse)
async def get_street_work_data(
    minutes: int = 60,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    max_distance_km: float = 2.0,  # ~5 min by car
    current_user: dict = Depends(get_current_user_required)
):
    """Get street work data including hot streets for the time window.
    
    If user location is provided, filters and sorts by distance (max 5 min travel).
    """
    import math
    
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate distance in km between two points."""
        R = 6371  # Earth's radius in km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c
    
    now = datetime.now(MADRID_TZ)
    time_threshold = now - timedelta(minutes=minutes)
    
    # Get activities in the time window (exclude MongoDB _id field)
    cursor = street_activities_collection.find(
        {"created_at": {"$gte": time_threshold}},
        {"_id": 0}  # Exclude _id field
    ).sort("created_at", -1)
    activities = await cursor.to_list(1000)
    
    # Separate counters for streets, stations, and terminals
    street_counts = {}  # Only load/unload activities
    station_counts = {}  # Only station_exit activities
    terminal_counts = {}  # Only terminal_exit activities
    
    total_loads = 0
    total_unloads = 0
    total_station_entries = 0
    total_station_exits = 0
    total_terminal_entries = 0
    total_terminal_exits = 0
    
    for activity in activities:
        action = activity.get("action", "")
        
        if action == "load":
            total_loads += 1
            # Count for hot street
            street = activity.get("street_name", "Desconocida")
            if street not in street_counts:
                street_counts[street] = {
                    "count": 0,
                    "last_activity": activity["created_at"],
                    "latitude": activity["latitude"],
                    "longitude": activity["longitude"]
                }
            street_counts[street]["count"] += 1
            
        elif action == "unload":
            total_unloads += 1
            # Count for hot street
            street = activity.get("street_name", "Desconocida")
            if street not in street_counts:
                street_counts[street] = {
                    "count": 0,
                    "last_activity": activity["created_at"],
                    "latitude": activity["latitude"],
                    "longitude": activity["longitude"]
                }
            street_counts[street]["count"] += 1
            
        elif action == "station_entry":
            total_station_entries += 1
            
        elif action == "station_exit":
            total_station_exits += 1
            # Count for hot station (based on exits)
            location = activity.get("location_name", "Desconocida")
            if location not in station_counts:
                station_counts[location] = {
                    "count": 0,
                    "latitude": activity["latitude"],
                    "longitude": activity["longitude"]
                }
            station_counts[location]["count"] += 1
            
        elif action == "terminal_entry":
            total_terminal_entries += 1
            
        elif action == "terminal_exit":
            total_terminal_exits += 1
            # Count for hot terminal (based on exits)
            location = activity.get("location_name", "Desconocida")
            if location not in terminal_counts:
                terminal_counts[location] = {
                    "count": 0,
                    "latitude": activity["latitude"],
                    "longitude": activity["longitude"]
                }
            terminal_counts[location]["count"] += 1
    
    # Sort by count and get hot streets (only load/unload)
    hot_streets_raw = []
    for name, data in street_counts.items():
        distance = None
        if user_lat is not None and user_lng is not None:
            distance = haversine_distance(user_lat, user_lng, data["latitude"], data["longitude"])
        
        hot_streets_raw.append({
            "street_name": name,
            "count": data["count"],
            "last_activity": data["last_activity"],
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "distance_km": round(distance, 2) if distance else None
        })
    
    # If user location provided, filter by distance and sort by distance first, then by count
    if user_lat is not None and user_lng is not None:
        # Filter streets within max_distance_km (reachable in ~5 min)
        hot_streets_raw = [s for s in hot_streets_raw if s["distance_km"] and s["distance_km"] <= max_distance_km]
        # Sort by distance first, then by activity count
        hot_streets_raw.sort(key=lambda x: (x["distance_km"], -x["count"]))
    else:
        # Sort by count if no location
        hot_streets_raw.sort(key=lambda x: -x["count"])
    
    hot_streets = [
        HotStreet(
            street_name=s["street_name"],
            count=s["count"],
            last_activity=s["last_activity"],
            latitude=s["latitude"],
            longitude=s["longitude"],
            distance_km=s["distance_km"]
        )
        for s in hot_streets_raw[:10]  # Top 10
    ]
    
    # Determine hottest street based on percentage of total loads
    # Rules:
    # - If no data, show nothing
    # - If only one location, show it (100%)
    # - If multiple locations, show the one with highest percentage (if >= 10%)
    hottest_street = None
    hottest_count = 0
    hottest_lat = None
    hottest_lng = None
    hottest_distance = None
    hottest_percentage = None
    hottest_total_loads = total_loads  # Total "load" actions for context
    
    if hot_streets and total_loads > 0:
        # Calculate percentage for each street based on "load" actions only
        # We need to recalculate using only "load" actions (not unload)
        load_counts = {}
        for activity in activities:
            if activity.get("action") == "load":
                street = activity.get("street_name", "Desconocida")
                if street not in load_counts:
                    load_counts[street] = {
                        "count": 0,
                        "latitude": activity.get("latitude"),
                        "longitude": activity.get("longitude")
                    }
                load_counts[street]["count"] += 1
        
        if load_counts:
            # Calculate percentages
            street_percentages = []
            for street_name, data in load_counts.items():
                percentage = (data["count"] / total_loads) * 100
                distance = None
                if user_lat is not None and user_lng is not None:
                    distance = haversine_distance(user_lat, user_lng, data["latitude"], data["longitude"])
                street_percentages.append({
                    "name": street_name,
                    "count": data["count"],
                    "percentage": percentage,
                    "lat": data["latitude"],
                    "lng": data["longitude"],
                    "distance": distance
                })
            
            # Sort by percentage (highest first)
            street_percentages.sort(key=lambda x: -x["percentage"])
            
            # Get the highest percentage street
            best = street_percentages[0]
            
            # Show if it's the only one (100%) or if it has >= 10%
            if best["percentage"] >= 10 or len(street_percentages) == 1:
                hottest_street = best["name"]
                hottest_count = best["count"]
                hottest_lat = best["lat"]
                hottest_lng = best["lng"]
                hottest_distance = round(best["distance"], 2) if best["distance"] else None
                hottest_percentage = round(best["percentage"], 1)
    
    # ============== NEW HOTSPOT SCORING ALGORITHM (4 variables @ 25% each) ==============
    # Score = 25% previous_exits + 25% previous_arrivals + 25% previous_avg_load_time + 25% future_arrivals
    # Previous window: from (now - 2*minutes) to (now - minutes)
    # Future window: from now to (now + minutes)
    
    # Get activities from PREVIOUS time window for scoring
    previous_window_start = now - timedelta(minutes=minutes * 2)
    previous_window_end = now - timedelta(minutes=minutes)
    
    cursor_previous = street_activities_collection.find(
        {"created_at": {"$gte": previous_window_start, "$lt": previous_window_end}},
        {"_id": 0}
    ).sort("created_at", -1)
    previous_activities = await cursor_previous.to_list(1000)
    
    # Count previous window exits by station/terminal
    prev_station_exits = {}
    prev_terminal_exits = {}
    prev_load_times_by_station = {}
    prev_load_times_by_terminal = {}
    
    for activity in previous_activities:
        action = activity.get("action", "")
        
        if action == "station_exit":
            location = activity.get("location_name", "Desconocida")
            prev_station_exits[location] = prev_station_exits.get(location, 0) + 1
            
        elif action == "terminal_exit":
            location = activity.get("location_name", "Desconocida")
            grouped = TERMINAL_GROUPS.get(location, location)
            prev_terminal_exits[grouped] = prev_terminal_exits.get(grouped, 0) + 1
            
        elif action in ["load", "unload"] and activity.get("duration_minutes"):
            act_lat = activity.get("latitude", 0)
            act_lng = activity.get("longitude", 0)
            duration = activity["duration_minutes"]
            
            # Check proximity to stations
            for station_name, coords in STATION_COORDS.items():
                dist = haversine_distance(coords["lat"], coords["lng"], act_lat, act_lng)
                if dist <= 2.0:
                    if station_name not in prev_load_times_by_station:
                        prev_load_times_by_station[station_name] = []
                    prev_load_times_by_station[station_name].append(duration)
            
            # Check proximity to terminals
            for terminal_zone, coords in TERMINAL_COORDS.items():
                dist = haversine_distance(coords["lat"], coords["lng"], act_lat, act_lng)
                if dist <= 2.0:
                    if terminal_zone not in prev_load_times_by_terminal:
                        prev_load_times_by_terminal[terminal_zone] = []
                    prev_load_times_by_terminal[terminal_zone].append(duration)
    
    # ===== GET REAL TRAIN ARRIVALS DATA (WITH CACHE) =====
    now_ts = datetime.now()
    cache_valid_trains = (
        arrival_cache["trains"]["timestamp"] is not None and
        (now_ts - arrival_cache["trains"]["timestamp"]).total_seconds() < CACHE_TTL_SECONDS
    )
    
    if cache_valid_trains:
        atocha_arrivals_raw = arrival_cache["trains"]["data"].get("atocha", [])
        chamartin_arrivals_raw = arrival_cache["trains"]["data"].get("chamartin", [])
        logger.info("Using cached train data")
    else:
        try:
            atocha_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["atocha"])
            chamartin_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["chamartin"])
            arrival_cache["trains"]["data"] = {
                "atocha": atocha_arrivals_raw,
                "chamartin": chamartin_arrivals_raw
            }
            arrival_cache["trains"]["timestamp"] = now_ts
            logger.info("Fetched and cached new train data")
        except Exception as e:
            logger.error(f"Error fetching train data for hotspot: {e}")
            atocha_arrivals_raw = arrival_cache["trains"]["data"].get("atocha", [])
            chamartin_arrivals_raw = arrival_cache["trains"]["data"].get("chamartin", [])
    
    # Count PAST arrivals (previous window: from -2*minutes to -minutes)
    atocha_prev_arrivals = count_arrivals_in_past_window(atocha_arrivals_raw, minutes * 2, minutes)
    chamartin_prev_arrivals = count_arrivals_in_past_window(chamartin_arrivals_raw, minutes * 2, minutes)
    
    # Count FUTURE arrivals (next window: from now to +minutes)
    atocha_future_arrivals = count_arrivals_in_window(atocha_arrivals_raw, minutes)
    chamartin_future_arrivals = count_arrivals_in_window(chamartin_arrivals_raw, minutes)
    
    train_arrivals_data = {
        "Atocha": {"prev": atocha_prev_arrivals, "future": atocha_future_arrivals},
        "Chamartín": {"prev": chamartin_prev_arrivals, "future": chamartin_future_arrivals}
    }
    
    # ===== GET REAL FLIGHT ARRIVALS DATA (WITH CACHE) =====
    cache_valid_flights = (
        arrival_cache["flights"]["timestamp"] is not None and
        (now_ts - arrival_cache["flights"]["timestamp"]).total_seconds() < CACHE_TTL_SECONDS
    )
    
    if cache_valid_flights:
        flight_data = arrival_cache["flights"]["data"]
        logger.info("Using cached flight data")
    else:
        try:
            flight_data = await fetch_aena_arrivals()
            arrival_cache["flights"]["data"] = flight_data
            arrival_cache["flights"]["timestamp"] = now_ts
            logger.info("Fetched and cached new flight data")
        except Exception as e:
            logger.error(f"Error fetching flight data for hotspot: {e}")
            flight_data = arrival_cache["flights"]["data"] if arrival_cache["flights"]["data"] else {t: [] for t in TERMINALS}
    
    # Group flights by terminal zone and count arrivals
    flight_arrivals_data = {
        "T1": {"prev": 0, "future": 0},
        "T2-T3": {"prev": 0, "future": 0},
        "T4-T4S": {"prev": 0, "future": 0}
    }
    
    for terminal in TERMINALS:
        terminal_flights = flight_data.get(terminal, [])
        grouped = TERMINAL_GROUPS.get(terminal, terminal)
        
        prev_count = count_arrivals_in_past_window(terminal_flights, minutes * 2, minutes)
        future_count = count_arrivals_in_window(terminal_flights, minutes)
        
        flight_arrivals_data[grouped]["prev"] += prev_count
        flight_arrivals_data[grouped]["future"] += future_count
    
    # Calculate station scores with 4 variables @ 25% each
    station_scores = {}
    for station_name, coords in STATION_COORDS.items():
        # 1. Current exits (25%) - from CURRENT time window (station_counts)
        current_exits = station_counts.get(station_name, {}).get("count", 0)
        
        # 2. Previous arrivals (25%) - REAL DATA from API
        prev_arrivals = train_arrivals_data.get(station_name, {}).get("prev", 0)
        
        # 3. Previous avg load time (25%)
        load_times = prev_load_times_by_station.get(station_name, [])
        prev_avg_load_time = sum(load_times) / len(load_times) if load_times else 0
        
        # 4. Future arrivals (25%) - REAL DATA from API
        future_arrivals = train_arrivals_data.get(station_name, {}).get("future", 0)
        
        station_scores[station_name] = {
            "prev_exits": current_exits,  # Using current exits now
            "prev_arrivals": prev_arrivals,
            "prev_avg_load_time": prev_avg_load_time,
            "future_arrivals": future_arrivals,
            "coords": coords
        }
    
    # Calculate terminal scores with 4 variables @ 25% each
    terminal_scores = {}
    for terminal_zone, coords in TERMINAL_COORDS.items():
        # 1. Current exits (25%) - from CURRENT time window (terminal_counts grouped by zone)
        current_exits = 0
        for term_name, term_data in terminal_counts.items():
            grouped = TERMINAL_GROUPS.get(term_name, term_name)
            if grouped == terminal_zone:
                current_exits += term_data.get("count", 0)
        
        # 2. Previous arrivals (25%) - REAL DATA from API
        prev_arrivals = flight_arrivals_data.get(terminal_zone, {}).get("prev", 0)
        
        # 3. Previous avg load time (25%)
        load_times = prev_load_times_by_terminal.get(terminal_zone, [])
        prev_avg_load_time = sum(load_times) / len(load_times) if load_times else 0
        
        # 4. Future arrivals (25%) - REAL DATA from API
        future_arrivals = flight_arrivals_data.get(terminal_zone, {}).get("future", 0)
        
        terminal_scores[terminal_zone] = {
            "prev_exits": current_exits,  # Using current exits now
            "prev_arrivals": prev_arrivals,
            "prev_avg_load_time": prev_avg_load_time,
            "future_arrivals": future_arrivals,
            "coords": coords
        }
    
    # Normalize and calculate final scores (4 variables @ 25% each)
    def calculate_weighted_score_4vars(scores_dict):
        if not scores_dict:
            return {}
        
        # Find max values for normalization
        max_prev_exits = max((s["prev_exits"] for s in scores_dict.values()), default=1) or 1
        max_prev_arrivals = max((s["prev_arrivals"] for s in scores_dict.values()), default=1) or 1
        max_prev_load_time = max((s["prev_avg_load_time"] for s in scores_dict.values()), default=1) or 1
        max_future_arrivals = max((s["future_arrivals"] for s in scores_dict.values()), default=1) or 1
        
        result = {}
        for name, data in scores_dict.items():
            # Normalize to 0-100 scale
            norm_prev_exits = (data["prev_exits"] / max_prev_exits) * 100 if max_prev_exits > 0 else 0
            norm_prev_arrivals = (data["prev_arrivals"] / max_prev_arrivals) * 100 if max_prev_arrivals > 0 else 0
            norm_prev_load_time = (data["prev_avg_load_time"] / max_prev_load_time) * 100 if max_prev_load_time > 0 else 0
            norm_future_arrivals = (data["future_arrivals"] / max_future_arrivals) * 100 if max_future_arrivals > 0 else 0
            
            # Weighted score: 25% each
            final_score = (norm_prev_exits * 0.25) + (norm_prev_arrivals * 0.25) + (norm_prev_load_time * 0.25) + (norm_future_arrivals * 0.25)
            
            result[name] = {
                **data,
                "score": round(final_score, 2),
                # For backward compatibility, map to old field names
                "exits": data["prev_exits"],
                "arrivals": data["prev_arrivals"] + data["future_arrivals"],
                "avg_load_time": data["prev_avg_load_time"]
            }
        
        return result
    
    station_scores = calculate_weighted_score_4vars(station_scores)
    terminal_scores = calculate_weighted_score_4vars(terminal_scores)
    
    # Find hottest station
    hottest_station = None
    hottest_station_count = 0
    hottest_station_lat = None
    hottest_station_lng = None
    hottest_station_score = None
    hottest_station_avg_load_time = None
    hottest_station_arrivals = None
    hottest_station_exits = None
    hottest_station_future_arrivals = None
    hottest_station_low_arrivals_alert = False
    hottest_station_taxi_status = None
    hottest_station_taxi_time = None
    hottest_station_taxi_reporter = None
    
    if station_scores:
        best_station_name = max(station_scores.keys(), key=lambda x: station_scores[x]["score"])
        best_station = station_scores[best_station_name]
        hottest_station = best_station_name
        hottest_station_count = best_station["exits"]
        hottest_station_lat = best_station["coords"]["lat"]
        hottest_station_lng = best_station["coords"]["lng"]
        hottest_station_score = best_station["score"]
        hottest_station_avg_load_time = round(best_station["avg_load_time"], 1)
        hottest_station_arrivals = best_station["arrivals"]
        hottest_station_exits = best_station["exits"]
        hottest_station_future_arrivals = best_station["future_arrivals"]
        hottest_station_low_arrivals_alert = best_station["future_arrivals"] < 5
        
        # Get taxi status for hottest station
        taxi_doc = await taxi_status_collection.find_one(
            {"location_type": "station", "location_name": best_station_name},
            sort=[("reported_at", -1)]
        )
        if taxi_doc:
            hottest_station_taxi_status = taxi_doc.get("taxi_status")
            # Convert UTC to Madrid timezone for display
            reported_at = taxi_doc.get("reported_at")
            if reported_at:
                if reported_at.tzinfo is None:
                    reported_at = pytz.utc.localize(reported_at)
                hottest_station_taxi_time = reported_at.astimezone(MADRID_TZ).isoformat()
            else:
                hottest_station_taxi_time = None
            hottest_station_taxi_reporter = taxi_doc.get("reported_by")
    
    # Find hottest terminal
    hottest_terminal = None
    hottest_terminal_count = 0
    hottest_terminal_lat = None
    hottest_terminal_lng = None
    hottest_terminal_score = None
    hottest_terminal_avg_load_time = None
    hottest_terminal_arrivals = None
    hottest_terminal_exits = None
    hottest_terminal_future_arrivals = None
    hottest_terminal_low_arrivals_alert = False
    hottest_terminal_taxi_status = None
    hottest_terminal_taxi_time = None
    hottest_terminal_taxi_reporter = None
    
    if terminal_scores:
        best_terminal_name = max(terminal_scores.keys(), key=lambda x: terminal_scores[x]["score"])
        best_terminal = terminal_scores[best_terminal_name]
        hottest_terminal = best_terminal_name
        hottest_terminal_count = best_terminal["exits"]
        hottest_terminal_lat = best_terminal["coords"]["lat"]
        hottest_terminal_lng = best_terminal["coords"]["lng"]
        hottest_terminal_score = best_terminal["score"]
        hottest_terminal_avg_load_time = round(best_terminal["avg_load_time"], 1)
        hottest_terminal_arrivals = best_terminal["arrivals"]
        hottest_terminal_exits = best_terminal["exits"]
        hottest_terminal_future_arrivals = best_terminal["future_arrivals"]
        hottest_terminal_low_arrivals_alert = best_terminal["future_arrivals"] < 7
        
        # Get taxi status for hottest terminal (check all terminals in the group)
        terminal_taxi_query = {"location_type": "terminal", "location_name": {"$in": [best_terminal_name, best_terminal_name.replace("-", ""), *best_terminal_name.split("-")]}}
        taxi_doc = await taxi_status_collection.find_one(
            terminal_taxi_query,
            sort=[("reported_at", -1)]
        )
        if taxi_doc:
            hottest_terminal_taxi_status = taxi_doc.get("taxi_status")
            # Convert UTC to Madrid timezone for display
            reported_at = taxi_doc.get("reported_at")
            if reported_at:
                if reported_at.tzinfo is None:
                    reported_at = pytz.utc.localize(reported_at)
                hottest_terminal_taxi_time = reported_at.astimezone(MADRID_TZ).isoformat()
            else:
                hottest_terminal_taxi_time = None
            hottest_terminal_taxi_reporter = taxi_doc.get("reported_by")
    
    # Convert activities to response format
    recent_activities = [
        StreetActivity(
            id=a["id"],
            user_id=a["user_id"],
            username=a["username"],
            action=a["action"],
            latitude=a["latitude"],
            longitude=a["longitude"],
            street_name=a["street_name"],
            location_name=a.get("location_name"),
            city=a.get("city", "Madrid"),
            created_at=a["created_at"],
            duration_minutes=a.get("duration_minutes")
        )
        for a in activities[:20]  # Last 20 activities
    ]
    
    return StreetWorkResponse(
        hottest_street=hottest_street,
        hottest_street_lat=hottest_lat,
        hottest_street_lng=hottest_lng,
        hottest_count=hottest_count,
        hottest_percentage=hottest_percentage,
        hottest_total_loads=hottest_total_loads,
        hottest_distance_km=hottest_distance,
        hot_streets=hot_streets,
        hottest_station=hottest_station,
        hottest_station_count=hottest_station_count,
        hottest_station_lat=hottest_station_lat,
        hottest_station_lng=hottest_station_lng,
        hottest_station_score=hottest_station_score,
        hottest_station_avg_load_time=hottest_station_avg_load_time,
        hottest_station_arrivals=hottest_station_arrivals,
        hottest_station_exits=hottest_station_exits,
        hottest_station_future_arrivals=hottest_station_future_arrivals,
        hottest_station_low_arrivals_alert=hottest_station_low_arrivals_alert,
        hottest_terminal=hottest_terminal,
        hottest_terminal_count=hottest_terminal_count,
        hottest_terminal_lat=hottest_terminal_lat,
        hottest_terminal_lng=hottest_terminal_lng,
        hottest_terminal_score=hottest_terminal_score,
        hottest_terminal_avg_load_time=hottest_terminal_avg_load_time,
        hottest_terminal_arrivals=hottest_terminal_arrivals,
        hottest_terminal_exits=hottest_terminal_exits,
        hottest_terminal_future_arrivals=hottest_terminal_future_arrivals,
        hottest_terminal_low_arrivals_alert=hottest_terminal_low_arrivals_alert,
        hottest_station_taxi_status=hottest_station_taxi_status,
        hottest_station_taxi_time=hottest_station_taxi_time,
        hottest_station_taxi_reporter=hottest_station_taxi_reporter,
        hottest_terminal_taxi_status=hottest_terminal_taxi_status,
        hottest_terminal_taxi_time=hottest_terminal_taxi_time,
        hottest_terminal_taxi_reporter=hottest_terminal_taxi_reporter,
        recent_activities=recent_activities,
        total_loads=total_loads,
        total_unloads=total_unloads,
        total_station_entries=total_station_entries,
        total_station_exits=total_station_exits,
        total_terminal_entries=total_terminal_entries,
        total_terminal_exits=total_terminal_exits,
        last_update=now.isoformat()
    )

# ============== CHECK-IN/CHECK-OUT ENDPOINTS ==============

# Store for active check-ins (in production, use Redis or similar)
active_checkins = {}

@api_router.post("/checkin")
async def register_checkin(
    checkin: CheckInRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Register entry or exit at a station or terminal."""
    now = datetime.now(MADRID_TZ)
    user_id = current_user["id"]
    
    # Determine action type for street activity
    if checkin.action == "entry":
        action_type = f"{checkin.location_type}_entry"
        # Store active check-in
        active_checkins[user_id] = {
            "location_type": checkin.location_type,
            "location_name": checkin.location_name,
            "entry_time": now.isoformat()
        }
        duration_minutes = None
        
        # Save taxi status if provided
        if checkin.taxi_status:
            await taxi_status_collection.insert_one({
                "location_type": checkin.location_type,
                "location_name": checkin.location_name,
                "taxi_status": checkin.taxi_status,
                "reported_at": now,
                "reported_by": current_user.get("username", "unknown"),
                "user_id": user_id
            })
    else:  # exit
        action_type = f"{checkin.location_type}_exit"
        duration_minutes = None
        
        # Calculate duration if there was an entry
        if user_id in active_checkins:
            entry_time_str = active_checkins[user_id].get("entry_time")
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    duration = now - entry_time
                    duration_minutes = int(duration.total_seconds() / 60)
                except:
                    pass
            del active_checkins[user_id]
    
    # Get street name from coordinates
    street_name = f"{checkin.location_name}"
    try:
        geolocator = Nominatim(user_agent="transport_meter_app")
        location = geolocator.reverse(f"{checkin.latitude}, {checkin.longitude}", language="es")
        if location and location.raw.get('address'):
            addr = location.raw['address']
            street = addr.get('road') or addr.get('pedestrian') or addr.get('neighbourhood', '')
            if street:
                street_name = f"{checkin.location_name} - {street}"
    except Exception as e:
        logger.debug(f"Geocoding error: {e}")
    
    # Create activity record
    activity_id = str(uuid.uuid4())
    new_activity = {
        "id": activity_id,
        "user_id": user_id,
        "username": current_user["username"],
        "action": action_type,
        "latitude": checkin.latitude,
        "longitude": checkin.longitude,
        "street_name": street_name,
        "location_type": checkin.location_type,
        "location_name": checkin.location_name,
        "city": "Madrid",
        "created_at": now,
        "duration_minutes": duration_minutes
    }
    
    await street_activities_collection.insert_one(new_activity)
    
    action_label = "Entrada" if checkin.action == "entry" else "Salida"
    location_label = "estación" if checkin.location_type == "station" else "terminal"
    
    return {
        "message": f"{action_label} registrada en {location_label} {checkin.location_name}",
        "activity": {
            "id": activity_id,
            "action": action_type,
            "location_name": checkin.location_name,
            "street_name": street_name,
            "created_at": now.isoformat(),
            "duration_minutes": duration_minutes
        },
        "is_checked_in": checkin.action == "entry"
    }

@api_router.get("/checkin/status", response_model=CheckInStatus)
async def get_checkin_status(
    current_user: dict = Depends(get_current_user_required)
):
    """Get current check-in status for the user."""
    user_id = current_user["id"]
    
    # Check active check-ins in memory
    if user_id in active_checkins:
        checkin = active_checkins[user_id]
        return CheckInStatus(
            is_checked_in=True,
            location_type=checkin["location_type"],
            location_name=checkin["location_name"],
            entry_time=checkin["entry_time"]
        )
    
    # Also check if there's an entry without exit in DB (for persistence across restarts)
    now = datetime.now(MADRID_TZ)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get today's entries and exits for this user
    entries = await street_activities_collection.find({
        "user_id": user_id,
        "action": {"$regex": ".*_entry$"},
        "created_at": {"$gte": start_of_day}
    }).sort("created_at", -1).to_list(1)
    
    if entries:
        last_entry = entries[0]
        # Check if there's an exit after this entry
        exits = await street_activities_collection.find({
            "user_id": user_id,
            "action": {"$regex": ".*_exit$"},
            "created_at": {"$gt": last_entry["created_at"]}
        }).to_list(1)
        
        if not exits:
            # Still checked in
            active_checkins[user_id] = {
                "location_type": last_entry.get("location_type", "station"),
                "location_name": last_entry.get("location_name", "Unknown"),
                "entry_time": last_entry["created_at"].isoformat()
            }
            return CheckInStatus(
                is_checked_in=True,
                location_type=last_entry.get("location_type", "station"),
                location_name=last_entry.get("location_name", "Unknown"),
                entry_time=last_entry["created_at"].isoformat()
            )
    
    return CheckInStatus(is_checked_in=False)

@api_router.get("/taxi/status")
async def get_taxi_status(
    location_type: Optional[str] = None,
    location_name: Optional[str] = None,
    current_user: dict = Depends(get_current_user_required)
):
    """Get the latest taxi status for stations and terminals."""
    # Build query
    query = {}
    if location_type:
        query["location_type"] = location_type
    if location_name:
        query["location_name"] = location_name
    
    # Get the most recent taxi status for each location
    pipeline = [
        {"$match": query} if query else {"$match": {}},
        {"$sort": {"reported_at": -1}},
        {"$group": {
            "_id": {"location_type": "$location_type", "location_name": "$location_name"},
            "taxi_status": {"$first": "$taxi_status"},
            "reported_at": {"$first": "$reported_at"},
            "reported_by": {"$first": "$reported_by"}
        }}
    ]
    
    results = await taxi_status_collection.aggregate(pipeline).to_list(100)
    
    taxi_data = {}
    for r in results:
        key = f"{r['_id']['location_type']}_{r['_id']['location_name']}"
        # Convert UTC to Madrid timezone for display
        reported_at = r["reported_at"]
        if reported_at:
            if reported_at.tzinfo is None:
                reported_at = pytz.utc.localize(reported_at)
            reported_at_str = reported_at.astimezone(MADRID_TZ).isoformat()
        else:
            reported_at_str = None
        taxi_data[key] = {
            "location_type": r["_id"]["location_type"],
            "location_name": r["_id"]["location_name"],
            "taxi_status": r["taxi_status"],
            "reported_at": reported_at_str,
            "reported_by": r["reported_by"]
        }
    
    return taxi_data

# ============== ADMIN ENDPOINTS ==============

@api_router.get("/admin/users", response_model=List[UserResponse])
async def list_users(admin: dict = Depends(get_admin_user)):
    """List all users (admin only)."""
    users = await users_collection.find().to_list(1000)
    return [
        UserResponse(
            id=u["id"],
            username=u["username"],
            phone=u.get("phone"),
            role=u["role"],
            created_at=u["created_at"]
        )
        for u in users
    ]

@api_router.post("/admin/users", response_model=UserResponse)
async def create_user(user_data: UserCreate, admin: dict = Depends(get_admin_user)):
    """Create a new user (admin only)."""
    # Check if username already exists
    existing = await users_collection.find_one({"username": user_data.username})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya existe"
        )
    
    new_user = {
        "id": str(uuid.uuid4()),
        "username": user_data.username,
        "hashed_password": get_password_hash(user_data.password),
        "phone": user_data.phone,
        "role": user_data.role,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await users_collection.insert_one(new_user)
    
    return UserResponse(
        id=new_user["id"],
        username=new_user["username"],
        phone=new_user["phone"],
        role=new_user["role"],
        created_at=new_user["created_at"]
    )

@api_router.put("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    admin: dict = Depends(get_admin_user)
):
    """Update user details (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    update_data = {"updated_at": datetime.utcnow()}
    if user_data.phone is not None:
        update_data["phone"] = user_data.phone
    if user_data.role is not None:
        update_data["role"] = user_data.role
    
    await users_collection.update_one(
        {"id": user_id},
        {"$set": update_data}
    )
    
    return {"message": "Usuario actualizado correctamente"}

@api_router.put("/admin/users/{user_id}/password")
async def admin_change_password(
    user_id: str,
    password_data: PasswordChange,
    admin: dict = Depends(get_admin_user)
):
    """Change any user's password (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    new_hash = get_password_hash(password_data.new_password)
    await users_collection.update_one(
        {"id": user_id},
        {"$set": {"hashed_password": new_hash, "updated_at": datetime.utcnow()}}
    )
    
    return {"message": "Contraseña actualizada correctamente"}

@api_router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    """Delete a user (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Prevent deleting yourself
    if user["id"] == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta"
        )
    
    await users_collection.delete_one({"id": user_id})
    return {"message": "Usuario eliminado correctamente"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_client():
    """Create default admin user on startup."""
    await create_default_admin()

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
