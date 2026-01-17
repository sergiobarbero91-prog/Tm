from fastapi import FastAPI, APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
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

# =============================================================================
# RATE LIMITING CONFIGURATION
# =============================================================================
limiter = Limiter(key_func=get_remote_address)

# =============================================================================
# SENTRY ERROR MONITORING
# =============================================================================
# To enable Sentry, add SENTRY_DSN to your .env file
# Get your DSN from: https://sentry.io
# =============================================================================
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            StarletteIntegration(transaction_style="url"),
            FastApiIntegration(transaction_style="url"),
        ],
        # Set traces_sample_rate to 1.0 to capture 100% of transactions for performance monitoring.
        # Adjust this value in production (recommend 0.1 to 0.2)
        traces_sample_rate=0.1,
        # Set profiles_sample_rate to 1.0 to profile 100% of sampled transactions.
        profiles_sample_rate=0.1,
        # Environment tag
        environment=os.environ.get("ENVIRONMENT", "production"),
        # Release version (optional)
        release=os.environ.get("APP_VERSION", "1.0.0"),
        # Attach user info to events
        send_default_pii=False,
    )
    logging.info("Sentry error monitoring initialized")

# Import routers
from routers import auth as auth_router
from routers import chat as chat_router
from routers import alerts as alerts_router
from routers import admin as admin_router
from routers import events as events_router
from routers import emergency as emergency_router
from routers import checkin as checkin_router
from routers import status as status_router
from routers import geocoding as geocoding_router
from routers import station_alerts as station_alerts_router
from routers import radio as radio_router
from routers import games as games_router

# Import history collections from shared
from shared import (
    trains_history_collection, 
    flights_history_collection,
    station_alerts_collection,
    active_checkins_collection
)

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
    "trains": {"data": {}, "timestamp": None, "last_successful": None},
    "flights": {"data": {}, "timestamp": None, "last_successful": None}
}
CACHE_TTL_SECONDS = 30  # Cache data for 30 seconds for more real-time updates
CACHE_FALLBACK_TTL_SECONDS = 300  # Use stale data for up to 5 minutes if API fails

# Flag to prevent concurrent cache refreshes
cache_refresh_in_progress = {
    "trains": False,
    "flights": False
}

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
users_collection = db['users']
street_activities_collection = db['street_activities']
taxi_status_collection = db['taxi_status']
queue_status_collection = db['queue_status']  # People waiting at stations/terminals
active_checkins_collection = db['active_checkins']  # Persistent active check-ins
emergency_alerts_collection = db['emergency_alerts']  # Emergency SOS alerts
hottest_street_cache_collection = db['hottest_street_cache']  # Persistent hottest street cache
events_collection = db['events']  # User-created events
chat_messages_collection = db['chat_messages']  # Chat messages for all channels
license_alerts_collection = db['license_alerts']  # Alerts between taxi drivers by license number

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

# Helper function for distance calculation
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance in km between two points using Haversine formula."""
    R = 6371  # Earth's radius in km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

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
    # Weighted score fields
    score_30min: Optional[float] = None  # Weighted score for 30min window
    score_60min: Optional[float] = None  # Weighted score for 60min window
    past_30min: Optional[int] = None     # Arrivals in past 15 min (half of 30)
    past_60min: Optional[int] = None     # Arrivals in past 30 min (half of 60)

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
    # Weighted score fields
    score_30min: Optional[float] = None  # Weighted score for 30min window
    score_60min: Optional[float] = None  # Weighted score for 60min window
    past_30min: Optional[int] = None     # Arrivals in past 15 min
    past_60min: Optional[int] = None     # Arrivals in past 30 min

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
    duration_minutes: Optional[int] = None  # Duration for completed activities (unload)
    distance_km: Optional[float] = None  # Distance traveled (for unload - from load point)

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
    
    # Exits by location in previous window (for displaying in cards)
    exits_by_station: dict = {}  # {"Atocha": 5, "Chamartin": 3}
    exits_by_terminal: dict = {}  # {"T1": 2, "T4": 4}
    
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
    queue_status: Optional[str] = None  # 'poco', 'normal', 'mucho' - only for 'exit' (people waiting)

class TaxiStatusResponse(BaseModel):
    location_type: str
    location_name: str
    taxi_status: str  # 'poco', 'normal', 'mucho'
    reported_at: str
    reported_by: str

class QueueStatusResponse(BaseModel):
    location_type: str
    location_name: str
    queue_status: str  # 'poco', 'normal', 'mucho'
    reported_at: str
    reported_by: str

class CheckInStatus(BaseModel):
    is_checked_in: bool
    location_type: Optional[str] = None
    location_name: Optional[str] = None
    entry_time: Optional[str] = None

# Emergency Alert Models
class EmergencyAlertRequest(BaseModel):
    alert_type: str  # 'companions' or 'companions_police'
    latitude: float
    longitude: float

class EmergencyAlertResponse(BaseModel):
    id: str
    user_id: str
    username: str
    alert_type: str  # 'companions' or 'companions_police'
    latitude: float
    longitude: float
    created_at: str
    is_active: bool

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

class UserRegister(BaseModel):
    """Model for public user registration"""
    username: str
    password: str
    full_name: str
    license_number: str  # Numeric only
    phone: Optional[str] = None
    preferred_shift: Optional[str] = "all"  # 'all', 'day', 'night'

class UserUpdate(BaseModel):
    phone: Optional[str] = None
    role: Optional[str] = None

class UserProfileUpdate(BaseModel):
    """Model for user self-profile update"""
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    preferred_shift: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: Optional[str] = None  # Optional for admin changing others
    new_password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    role: str
    preferred_shift: Optional[str] = "all"
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
    """Create default admin user if it doesn't exist, or update existing if role is missing."""
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
    else:
        # Ensure admin user has admin role
        if existing_admin.get("role") != "admin":
            await users_collection.update_one(
                {"username": "admin"},
                {"$set": {"role": "admin", "updated_at": datetime.utcnow()}}
            )
            logger.info("Updated admin user to have admin role")
    
    # Ensure all users have a role field
    await users_collection.update_many(
        {"role": {"$exists": False}},
        {"$set": {"role": "user"}}
    )

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
                                        except (ValueError, TypeError):
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
                                    except (ValueError, TypeError):
                                        pass
                                
                                # Avoid duplicates and filter out cancelled/landed flights
                                # Only show flights that are still expected to arrive
                                if status in ["Cancelado", "Aterrizado"]:
                                    continue  # Skip cancelled and already landed flights
                                    
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


def calculate_weighted_score(arrivals: List[Dict], window_minutes: int) -> dict:
    """Calculate weighted arrival score combining future and past arrivals.
    
    Formula:
    - 50% weight: arrivals in the next [window_minutes] (future)
    - 50% weight: arrivals in the last [window_minutes / 2] (recent past)
    
    Returns dict with:
    - future_count: arrivals in future window
    - past_count: arrivals in past half-window
    - weighted_score: combined score (average of both)
    - total_raw: simple sum for display
    """
    future_count = count_arrivals_in_window(arrivals, window_minutes)
    half_window = window_minutes // 2
    past_count = count_arrivals_in_past_window(arrivals, half_window, 0)
    
    # Weighted score: 50% future + 50% past (normalized)
    weighted_score = (future_count * 0.5) + (past_count * 0.5)
    
    return {
        "future_count": future_count,
        "past_count": past_count,
        "weighted_score": round(weighted_score, 1),
        "total_raw": future_count + past_count
    }


def filter_future_arrivals(arrivals: List[Dict], arrival_type: str = "flight") -> List[Dict]:
    """Filter arrivals to only include those that haven't arrived yet and aren't cancelled.
    Works for both flights and trains.
    
    Flights/trains with delays are included but will be shown in their correct time window
    based on their REAL arrival time (with delay), not their scheduled time.
    
    Args:
        arrivals: List of arrival dicts
        arrival_type: "flight" or "train" to determine status keywords
    """
    now = datetime.now(MADRID_TZ)
    filtered = []
    
    # Status keywords to exclude
    if arrival_type == "flight":
        exclude_statuses = ["aterrizado", "llegado", "cancelado", "desviado"]
    else:  # train
        exclude_statuses = ["llegado", "cancelado", "suprimido"]
    
    for arrival in arrivals:
        try:
            # Skip arrivals that have already arrived or are cancelled
            status = arrival.get("status", "").lower()
            if any(excl in status for excl in exclude_statuses):
                continue
            
            # The "time" field contains the REAL arrival time (with delay included)
            # So flights with delay will naturally appear in the correct time window
            time_str = arrival.get("time", "")
            arrival_time = datetime.strptime(time_str, "%H:%M")
            arrival_time = MADRID_TZ.localize(arrival_time.replace(
                year=now.year, month=now.month, day=now.day
            ))
            
            # Handle day rollover
            if arrival_time < now - timedelta(hours=2):
                arrival_time += timedelta(days=1)
            
            # Only include future arrivals (within next 4 hours buffer for delays)
            time_diff = (arrival_time - now).total_seconds() / 60
            if time_diff >= -30:  # Allow 30 min buffer for recently arrived
                filtered.append(arrival)
        except (ValueError, TypeError, KeyError):
            pass
    
    return filtered

# Keep backward compatibility
def filter_future_flights(arrivals: List[Dict]) -> List[Dict]:
    """Filter flights to only include those that haven't arrived yet (excluding 'Aterrizado')."""
    return filter_future_arrivals(arrivals, "flight")

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
        except (ValueError, TypeError, KeyError):
            pass
    return filtered

def filter_arrivals_by_hour_window(arrivals: List[Dict], start_time: datetime, end_time: datetime) -> List[Dict]:
    """Filter arrivals to only include those with arrival times within the specified hour window.
    
    This filters based on the arrival TIME (hour:minute), not the fetch timestamp.
    Used for both past and future time windows.
    
    IMPORTANT: Train/flight times are in Madrid local time, so we must convert the
    input times to Madrid timezone before extracting hours.
    """
    filtered = []
    
    # Convert to Madrid timezone to get the correct local hours
    start_madrid = start_time.astimezone(MADRID_TZ)
    end_madrid = end_time.astimezone(MADRID_TZ)
    
    start_hour = start_madrid.hour
    start_minute = start_madrid.minute
    end_hour = end_madrid.hour
    end_minute = end_madrid.minute
    
    logger.info(f"[Filter] Filtering arrivals for hour window: {start_hour:02d}:{start_minute:02d} - {end_hour:02d}:{end_minute:02d} (Madrid time)")
    
    for arrival in arrivals:
        try:
            time_str = arrival.get("time", "")
            if not time_str or ":" not in time_str:
                continue
            
            parts = time_str.split(":")
            arr_hour = int(parts[0])
            arr_minute = int(parts[1]) if len(parts) > 1 else 0
            
            # Convert to minutes for easier comparison
            arr_minutes = arr_hour * 60 + arr_minute
            start_minutes = start_hour * 60 + start_minute
            end_minutes = end_hour * 60 + end_minute
            
            # Handle day boundary (e.g., 23:00 to 01:00)
            if end_minutes <= start_minutes:
                # Window crosses midnight (e.g., 23:00 - 00:00)
                if arr_minutes >= start_minutes or arr_minutes < end_minutes:
                    filtered.append(arrival)
            else:
                # Normal window
                if start_minutes <= arr_minutes < end_minutes:
                    filtered.append(arrival)
        except Exception as e:
            logger.debug(f"Error filtering arrival by hour: {e}")
            pass
    
    logger.info(f"[Filter] Filtered {len(filtered)} arrivals from {len(arrivals)} total")
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
        except (ValueError, TypeError, KeyError):
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
async def get_train_comparison(
    shift: str = "all",
    start_time: Optional[str] = None,  # ISO format: "2025-06-13T14:00:00"
    end_time: Optional[str] = None     # ISO format: "2025-06-13T15:00:00"
):
    """Get train arrivals comparison between Atocha and Chamartín - ONLY media/larga distancia.
    
    Parameters:
    - shift: 'all' (default), 'day' (05:00-16:59), or 'night' (17:00-04:59)
    - start_time: Optional start of time window (ISO format)
    - end_time: Optional end of time window (ISO format)
    
    If start_time and end_time are provided, returns historical data from that window.
    Otherwise, fetches real-time data and saves it to history.
    """
    now = datetime.now(MADRID_TZ)
    is_night_time = now.hour < 6
    
    # Validate shift parameter
    if shift not in ["all", "day", "night"]:
        shift = "all"
    
    logger.info(f"[Trains] Request params: shift={shift}, start_time={start_time}, end_time={end_time}")
    
    # Parse time range if provided
    time_start = None
    time_end = None
    is_future_window = False
    is_past_window = False
    custom_time_window = start_time is not None and end_time is not None
    
    if custom_time_window:
        try:
            time_start = date_parser.parse(start_time)
            time_end = date_parser.parse(end_time)
            
            # Ensure timezone awareness
            if time_start.tzinfo is None:
                time_start = MADRID_TZ.localize(time_start)
            if time_end.tzinfo is None:
                time_end = MADRID_TZ.localize(time_end)
            
            # Determine if this is a past or future window
            is_future_window = time_start >= now
            is_past_window = time_end <= now
            
            logger.info(f"[Trains] Time window: {time_start} to {time_end} (future={is_future_window}, past={is_past_window})")
            
        except Exception as e:
            logger.error(f"[Trains] Error parsing time range: {e}")
            custom_time_window = False
    
    # Always fetch fresh data from API
    atocha_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["atocha"])
    chamartin_arrivals_raw = await fetch_adif_arrivals_api(STATION_IDS["chamartin"])
    
    # Save to history for future queries (non-blocking)
    asyncio.create_task(save_train_history("atocha", atocha_arrivals_raw))
    asyncio.create_task(save_train_history("chamartin", chamartin_arrivals_raw))
    
    # If past window, also fetch historical data and merge
    if is_past_window and time_start and time_end:
        logger.info("[Trains] Fetching historical data for past window")
        atocha_history = await trains_history_collection.find({
            "station": "atocha",
            "fetched_at": {"$gte": time_start, "$lte": time_end}
        }).sort("fetched_at", -1).to_list(100)
        
        chamartin_history = await trains_history_collection.find({
            "station": "chamartin",
            "fetched_at": {"$gte": time_start, "$lte": time_end}
        }).sort("fetched_at", -1).to_list(100)
        
        # Use historical data if available
        if atocha_history:
            seen = set()
            atocha_arrivals_raw = []
            for record in atocha_history:
                for arr in record.get("arrivals", []):
                    key = f"{arr.get('train_number', '')}-{arr.get('time', '')}"
                    if key not in seen:
                        seen.add(key)
                        atocha_arrivals_raw.append(arr)
        
        if chamartin_history:
            seen = set()
            chamartin_arrivals_raw = []
            for record in chamartin_history:
                for arr in record.get("arrivals", []):
                    key = f"{arr.get('train_number', '')}-{arr.get('time', '')}"
                    if key not in seen:
                        seen.add(key)
                        chamartin_arrivals_raw.append(arr)
    
    # Filter arrivals by shift
    atocha_arrivals_shift = filter_arrivals_by_shift(atocha_arrivals_raw, shift)
    chamartin_arrivals_shift = filter_arrivals_by_shift(chamartin_arrivals_raw, shift)
    
    # Filter arrivals based on time window
    if custom_time_window and time_start and time_end:
        # Filter arrivals to only those within the specified hour window
        atocha_arrivals = filter_arrivals_by_hour_window(atocha_arrivals_shift, time_start, time_end)
        chamartin_arrivals = filter_arrivals_by_hour_window(chamartin_arrivals_shift, time_start, time_end)
        logger.info(f"[Trains] After hour filter: Atocha={len(atocha_arrivals)}, Chamartín={len(chamartin_arrivals)}")
    else:
        # No time window - filter out arrived and cancelled trains
        atocha_arrivals = filter_future_arrivals(atocha_arrivals_shift, "train")
        chamartin_arrivals = filter_future_arrivals(chamartin_arrivals_shift, "train")
    
    # Calculate weighted scores (50% future + 50% recent past)
    atocha_score_30 = calculate_weighted_score(atocha_arrivals_shift, 30)
    atocha_score_60 = calculate_weighted_score(atocha_arrivals_shift, 60)
    chamartin_score_30 = calculate_weighted_score(chamartin_arrivals_shift, 30)
    chamartin_score_60 = calculate_weighted_score(chamartin_arrivals_shift, 60)
    
    # Count arrivals
    if custom_time_window:
        # For custom time window, count all arrivals in the window
        atocha_30 = len(atocha_arrivals)
        atocha_60 = atocha_30
        chamartin_30 = len(chamartin_arrivals)
        chamartin_60 = chamartin_30
    else:
        # For real-time, use future counts
        atocha_30 = atocha_score_30["future_count"]
        atocha_60 = atocha_score_60["future_count"]
        chamartin_30 = chamartin_score_30["future_count"]
        chamartin_60 = chamartin_score_60["future_count"]
    
    # Calculate peak hours (within the selected shift)
    atocha_peak = calculate_peak_hour(atocha_arrivals_raw, shift)
    chamartin_peak = calculate_peak_hour(chamartin_arrivals_raw, shift)
    
    # Determine winner based on WEIGHTED SCORE (not just future count)
    atocha_weighted_30 = atocha_score_30["weighted_score"]
    atocha_weighted_60 = atocha_score_60["weighted_score"]
    chamartin_weighted_30 = chamartin_score_30["weighted_score"]
    chamartin_weighted_60 = chamartin_score_60["weighted_score"]
    
    winner_30 = "atocha" if atocha_weighted_30 >= chamartin_weighted_30 else "chamartin"
    winner_60 = "atocha" if atocha_weighted_60 >= chamartin_weighted_60 else "chamartin"
    
    logger.info(f"[Trains] Weighted scores - Atocha 30m: {atocha_weighted_30} (fut:{atocha_score_30['future_count']}, past:{atocha_score_30['past_count']}), Chamartín 30m: {chamartin_weighted_30} (fut:{chamartin_score_30['future_count']}, past:{chamartin_score_30['past_count']})")
    
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
        peak_hour=PeakHourInfo(**atocha_peak) if atocha_peak else None,
        score_30min=atocha_weighted_30,
        score_60min=atocha_weighted_60,
        past_30min=atocha_score_30["past_count"],
        past_60min=atocha_score_60["past_count"]
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
        peak_hour=PeakHourInfo(**chamartin_peak) if chamartin_peak else None,
        score_30min=chamartin_weighted_30,
        score_60min=chamartin_weighted_60,
        past_30min=chamartin_score_30["past_count"],
        past_60min=chamartin_score_60["past_count"]
    )
    
    message = None
    if custom_time_window:
        if is_future_window:
            message = "Trenes previstos para la franja horaria seleccionada"
        elif is_past_window:
            message = "Datos históricos del período seleccionado"
        else:
            message = "Trenes para la franja horaria seleccionada"
    elif is_night_time and atocha_30 == 0 and chamartin_30 == 0:
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


async def save_train_history(station: str, arrivals: List[Dict]):
    """Save train arrivals to history collection for time-window queries."""
    try:
        now = datetime.now(MADRID_TZ)
        history_record = {
            "station": station,
            "arrivals": arrivals,
            "fetched_at": now
        }
        await trains_history_collection.insert_one(history_record)
        logger.info(f"[Trains] Saved {len(arrivals)} arrivals to history for {station}")
    except Exception as e:
        logger.error(f"[Trains] Error saving history for {station}: {e}")

@api_router.get("/flights", response_model=FlightComparisonResponse)
async def get_flight_comparison(
    start_time: Optional[str] = None,  # ISO format: "2025-06-13T14:00:00"
    end_time: Optional[str] = None     # ISO format: "2025-06-13T15:00:00"
):
    """Get REAL flight arrivals comparison between terminals at Madrid-Barajas.
    
    Parameters:
    - start_time: Optional start of time window (ISO format)
    - end_time: Optional end of time window (ISO format)
    
    If start_time and end_time are provided, filters flights to that hour window.
    Otherwise, returns real-time data.
    """
    now = datetime.now(MADRID_TZ)
    
    logger.info(f"[Flights] Request params: start_time={start_time}, end_time={end_time}")
    
    # Parse time range if provided
    time_start = None
    time_end = None
    is_future_window = False
    is_past_window = False
    custom_time_window = start_time is not None and end_time is not None
    
    if custom_time_window:
        try:
            time_start = date_parser.parse(start_time)
            time_end = date_parser.parse(end_time)
            
            # Ensure timezone awareness
            if time_start.tzinfo is None:
                time_start = MADRID_TZ.localize(time_start)
            if time_end.tzinfo is None:
                time_end = MADRID_TZ.localize(time_end)
            
            # Determine if this is a past or future window
            is_future_window = time_start >= now
            is_past_window = time_end <= now
            
            logger.info(f"[Flights] Time window: {time_start} to {time_end} (future={is_future_window}, past={is_past_window})")
            
        except Exception as e:
            logger.error(f"[Flights] Error parsing time range: {e}")
            custom_time_window = False
    
    # Always fetch fresh data first
    all_arrivals = await fetch_aena_arrivals()
    
    # Save to history for future queries (non-blocking)
    for terminal in TERMINALS:
        asyncio.create_task(save_flight_history(terminal, all_arrivals.get(terminal, [])))
    
    terminal_data = {}
    max_score_30 = 0.0
    max_score_60 = 0.0
    winner_30 = "T4"
    winner_60 = "T4"
    
    for terminal in TERMINALS:
        raw_arrivals = all_arrivals.get(terminal, [])
        
        # Calculate weighted scores for this terminal (50% future + 50% past)
        score_30 = calculate_weighted_score(raw_arrivals, 30)
        score_60 = calculate_weighted_score(raw_arrivals, 60)
        
        # Filter arrivals based on time window
        if custom_time_window and time_start and time_end:
            # Filter arrivals to only those within the specified hour window
            arrivals = filter_arrivals_by_hour_window(raw_arrivals, time_start, time_end)
            
            # If no arrivals from fresh data and this is a past window, try historical data
            if len(arrivals) == 0 and is_past_window:
                logger.info(f"[Flights] No fresh data for {terminal} in time window, checking history...")
                terminal_history = await flights_history_collection.find({
                    "terminal": terminal,
                    "fetched_at": {"$gte": time_start - timedelta(hours=2), "$lte": time_end + timedelta(hours=2)}
                }).sort("fetched_at", -1).to_list(50)
                
                if terminal_history:
                    historical_arrivals = []
                    seen = set()
                    for record in terminal_history:
                        for arr in record.get("arrivals", []):
                            key = f"{arr.get('flight_number', '')}-{arr.get('time', '')}"
                            if key not in seen:
                                seen.add(key)
                                historical_arrivals.append(arr)
                    
                    # Filter historical data by hour window
                    arrivals = filter_arrivals_by_hour_window(historical_arrivals, time_start, time_end)
                    logger.info(f"[Flights] Found {len(arrivals)} historical arrivals for {terminal}")
        else:
            # No time window - filter out arrived flights
            arrivals = filter_future_flights(raw_arrivals)
        
        # Count arrivals
        if custom_time_window:
            count_30 = len(arrivals)
            count_60 = count_30
        else:
            count_30 = score_30["future_count"]
            count_60 = score_60["future_count"]
        
        # Determine winner based on weighted score
        weighted_30 = score_30["weighted_score"]
        weighted_60 = score_60["weighted_score"]
        
        if weighted_30 > max_score_30:
            max_score_30 = weighted_30
            winner_30 = terminal
        if weighted_60 > max_score_60:
            max_score_60 = weighted_60
            winner_60 = terminal
        
        terminal_data[terminal] = TerminalData(
            terminal=terminal,
            arrivals=[FlightArrival(**a) for a in arrivals[:15]],
            total_next_30min=count_30,
            total_next_60min=count_60,
            score_30min=weighted_30,
            score_60min=weighted_60,
            past_30min=score_30["past_count"],
            past_60min=score_60["past_count"]
        )
    
    logger.info(f"[Flights] Winner 30m: {winner_30} (score: {max_score_30}), Winner 60m: {winner_60} (score: {max_score_60})")
    
    # Set winners
    for terminal in TERMINALS:
        terminal_data[terminal].is_winner_30min = (terminal == winner_30)
        terminal_data[terminal].is_winner_60min = (terminal == winner_60)
    
    # Determine message
    message = None
    if custom_time_window:
        if is_future_window:
            message = "Vuelos previstos para la franja horaria seleccionada"
        elif is_past_window:
            message = "Datos históricos del período seleccionado"
        else:
            message = "Vuelos para la franja horaria seleccionada"
    
    return FlightComparisonResponse(
        terminals=terminal_data,
        winner_30min=winner_30,
        winner_60min=winner_60,
        last_update=now.isoformat(),
        message=message
    )


async def save_flight_history(terminal: str, arrivals: List[Dict]):
    """Save flight arrivals to history collection for time-window queries."""
    try:
        now = datetime.now(MADRID_TZ)
        history_record = {
            "terminal": terminal,
            "arrivals": arrivals,
            "fetched_at": now
        }
        await flights_history_collection.insert_one(history_record)
        logger.info(f"[Flights] Saved {len(arrivals)} arrivals to history for {terminal}")
    except Exception as e:
        logger.error(f"[Flights] Error saving history for {terminal}: {e}")

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

@api_router.get("/health/detailed")
async def health_check_detailed():
    """Detailed health check with system metrics."""
    import psutil
    
    # Get system metrics
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Check MongoDB connection
    mongo_status = "healthy"
    try:
        await db.command('ping')
    except Exception as e:
        mongo_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if mongo_status == "healthy" else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
        },
        "services": {
            "mongodb": mongo_status,
            "sentry": "enabled" if SENTRY_DSN else "disabled",
        },
        "cache": {
            "trains_cached": arrival_cache["trains"]["data"] is not None,
            "trains_last_update": arrival_cache["trains"]["timestamp"].isoformat() if arrival_cache["trains"]["timestamp"] else None,
            "flights_cached": arrival_cache["flights"]["data"] is not None,
            "flights_last_update": arrival_cache["flights"]["timestamp"].isoformat() if arrival_cache["flights"]["timestamp"] else None,
        },
        "rate_limiting": "enabled",
        "gzip_compression": "enabled"
    }

@api_router.get("/debug/sentry-test")
async def sentry_test():
    """
    Test endpoint to trigger a Sentry error.
    Only works if SENTRY_DSN is configured.
    """
    if not SENTRY_DSN:
        return {"message": "Sentry not configured. Add SENTRY_DSN to .env file."}
    
    try:
        # This will trigger an error that Sentry will capture
        _ = 1 / 0  # noqa: F841 - intentional division by zero for testing
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return {"message": "Test error sent to Sentry!", "error": str(e)}

# ============== AUTHENTICATION ENDPOINTS ==============
# NOTE: Auth endpoints have been moved to routers/auth.py

# ============== GEOCODING & FARE ENDPOINTS ==============

# Approximate polygon for M30 Madrid (simplified)
# These coordinates form a rough polygon around the M30 ring road
M30_POLYGON = [
    (40.4752, -3.7223),  # North
    (40.4699, -3.6899),  # Northeast
    (40.4542, -3.6677),  # East
    (40.4319, -3.6653),  # Southeast
    (40.4067, -3.6764),  # South-Southeast
    (40.3933, -3.6936),  # South
    (40.3892, -3.7132),  # South-Southwest
    (40.3969, -3.7377),  # Southwest
    (40.4142, -3.7511),  # West
    (40.4367, -3.7529),  # Northwest
    (40.4584, -3.7423),  # North-Northwest
    (40.4752, -3.7223),  # Close polygon
]

def point_in_polygon(lat: float, lng: float, polygon: list) -> bool:
    """Check if a point is inside a polygon using ray casting algorithm."""
    n = len(polygon)
    inside = False
    
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        
        if ((yi > lng) != (yj > lng)) and (lat < (xj - xi) * (lng - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    
    return inside

# ============== GEOCODING & FARE ENDPOINTS ==============
# NOTE: Geocoding endpoints have been moved to routers/geocoding.py


# ============== STREET WORK ENDPOINTS ==============

@api_router.post("/street/activity")
async def register_street_activity(
    activity: StreetActivityCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Register a load or unload activity at current location."""
    now = datetime.now(MADRID_TZ)
    user_id = current_user["id"]
    
    activity_id = str(uuid.uuid4())
    duration_minutes = None
    distance_km = None
    
    # If this is an unload, calculate duration and distance from last load
    if activity.action == "unload":
        # Find the most recent load for this user
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_load = await street_activities_collection.find_one(
            {
                "user_id": user_id,
                "action": "load",
                "created_at": {"$gte": start_of_day}
            },
            sort=[("created_at", -1)]
        )
        
        if last_load:
            # Calculate duration
            load_time = last_load.get("created_at")
            if load_time:
                if load_time.tzinfo is None:
                    load_time = MADRID_TZ.localize(load_time)
                duration = now - load_time
                duration_minutes = int(duration.total_seconds() / 60)
            
            # Calculate distance using haversine
            load_lat = last_load.get("latitude", 0)
            load_lng = last_load.get("longitude", 0)
            if load_lat and load_lng:
                distance_km = round(haversine_distance(
                    load_lat, load_lng,
                    activity.latitude, activity.longitude
                ), 2)
    
    new_activity = {
        "id": activity_id,
        "user_id": user_id,
        "username": current_user["username"],
        "action": activity.action,
        "latitude": activity.latitude,
        "longitude": activity.longitude,
        "street_name": activity.street_name,
        "city": "Madrid",
        "created_at": now,
        "duration_minutes": duration_minutes,
        "distance_km": distance_km
    }
    
    await street_activities_collection.insert_one(new_activity)
    
    # Determine if there's now an active load
    has_active_load = activity.action == "load"
    
    # Return a clean response without MongoDB _id
    return {
        "message": f"Actividad '{activity.action}' registrada en {activity.street_name}",
        "activity": {
            "id": activity_id,
            "user_id": user_id,
            "username": current_user["username"],
            "action": activity.action,
            "latitude": activity.latitude,
            "longitude": activity.longitude,
            "street_name": activity.street_name,
            "city": "Madrid",
            "created_at": now.isoformat(),
            "duration_minutes": duration_minutes,
            "distance_km": distance_km
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


# ============== ROUTE DISTANCE CALCULATION ==============

class RouteDistanceRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float


@api_router.post("/calculate-route-distance")
async def calculate_route_distance(
    request: RouteDistanceRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """
    Calculate real driving distance between two points using OSRM (Open Source Routing Machine).
    This gives the actual route distance, not the straight-line distance.
    
    Returns distance in km and estimated duration in minutes.
    """
    try:
        # Use OSRM demo server (free, but rate-limited for production use)
        # For production, consider hosting your own OSRM instance or using a paid service
        osrm_url = f"http://router.project-osrm.org/route/v1/driving/{request.origin_lng},{request.origin_lat};{request.dest_lng},{request.dest_lat}"
        
        params = {
            "overview": "false",  # Don't need the polyline
            "alternatives": "false"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(osrm_url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get("code") == "Ok" and data.get("routes"):
                        route = data["routes"][0]
                        distance_meters = route.get("distance", 0)
                        duration_seconds = route.get("duration", 0)
                        
                        distance_km = round(distance_meters / 1000, 2)
                        duration_minutes = round(duration_seconds / 60, 1)
                        
                        # Also calculate straight-line distance for comparison
                        straight_line_km = round(haversine_distance(
                            request.origin_lat, request.origin_lng,
                            request.dest_lat, request.dest_lng
                        ), 2)
                        
                        # Calculate the route factor (how much longer the real route is)
                        route_factor = round(distance_km / straight_line_km, 2) if straight_line_km > 0 else 1.0
                        
                        logger.info(f"Route calculated: {distance_km}km (straight: {straight_line_km}km, factor: {route_factor}x)")
                        
                        return {
                            "success": True,
                            "distance_km": distance_km,
                            "duration_minutes": duration_minutes,
                            "straight_line_km": straight_line_km,
                            "route_factor": route_factor,
                            "source": "osrm"
                        }
                    else:
                        # OSRM couldn't find a route, fall back to Haversine with factor
                        raise Exception(f"OSRM error: {data.get('code', 'Unknown')}")
                else:
                    raise Exception(f"OSRM HTTP error: {response.status}")
                    
    except Exception as e:
        logger.warning(f"OSRM routing failed: {e}, using Haversine fallback with 1.3x factor")
        
        # Fallback: Use Haversine distance with a typical urban route factor of 1.3
        # This accounts for the fact that roads aren't straight
        straight_line_km = round(haversine_distance(
            request.origin_lat, request.origin_lng,
            request.dest_lat, request.dest_lng
        ), 2)
        
        # Apply urban route factor (typically routes are 1.2-1.4x longer than straight line in cities)
        estimated_km = round(straight_line_km * 1.3, 2)
        
        # Estimate duration: ~30 km/h average in Madrid traffic
        estimated_duration = round((estimated_km / 30) * 60, 1)
        
        return {
            "success": True,
            "distance_km": estimated_km,
            "duration_minutes": estimated_duration,
            "straight_line_km": straight_line_km,
            "route_factor": 1.3,
            "source": "haversine_estimated",
            "note": "Estimación basada en factor urbano típico (1.3x)"
        }

# NOTE: /geocode/reverse endpoint has been moved to routers/geocoding.py

@api_router.get("/street/data", response_model=StreetWorkResponse)
async def get_street_work_data(
    minutes: int = 60,
    user_lat: Optional[float] = None,
    user_lng: Optional[float] = None,
    max_distance_km: float = 2.0,  # ~5 min by car
    start_time: Optional[str] = None,  # ISO format: "2025-06-13T14:00:00"
    end_time: Optional[str] = None,    # ISO format: "2025-06-13T15:00:00"
    current_user: dict = Depends(get_current_user_required)
):
    """Get street work data including hot streets for the time window.
    
    If user location is provided, filters and sorts by distance (max 5 min travel).
    
    Time range selection:
    - If start_time and end_time are provided, uses that specific time range.
    - Otherwise, uses the last `minutes` from now.
    """
    logger.info(f"[Street Data] Request params: minutes={minutes}, start_time={start_time}, end_time={end_time}")
    now = datetime.now(MADRID_TZ)
    
    # Determine time range
    if start_time and end_time:
        try:
            # Parse ISO format strings
            time_start = date_parser.parse(start_time)
            time_end = date_parser.parse(end_time)
            
            # Ensure timezone awareness
            if time_start.tzinfo is None:
                time_start = MADRID_TZ.localize(time_start)
            if time_end.tzinfo is None:
                time_end = MADRID_TZ.localize(time_end)
            
            time_threshold = time_start
            time_limit = time_end
            logger.info(f"Using custom time range: {time_start} to {time_end}")
        except Exception as e:
            logger.error(f"Error parsing time range: {e}")
            time_threshold = now - timedelta(minutes=minutes)
            time_limit = now
    else:
        time_threshold = now - timedelta(minutes=minutes)
        time_limit = now
    
    # Get activities in the time window (exclude MongoDB _id field)
    cursor = street_activities_collection.find(
        {"created_at": {"$gte": time_threshold, "$lte": time_limit}},
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
    
    # Try to use cached hottest street data first (if no user location provided)
    # This provides persistence across server restarts
    if user_lat is None and user_lng is None and minutes == 60:
        cached_hottest = await get_cached_hottest_street(minutes=60)
        if cached_hottest:
            hottest_street = cached_hottest.get("hottest_street")
            hottest_count = cached_hottest.get("hottest_count", 0)
            hottest_lat = cached_hottest.get("hottest_lat")
            hottest_lng = cached_hottest.get("hottest_lng")
            hottest_percentage = cached_hottest.get("hottest_percentage")
            hottest_total_loads = cached_hottest.get("hottest_total_loads", total_loads)
            logger.info(f"Using cached hottest street: {hottest_street}")
    
    # If no cache hit, calculate on-the-fly
    if hottest_street is None and hot_streets and total_loads > 0:
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
    # Previous window: from (selected_start - duration) to selected_start
    # Future window: from selected_end to (selected_end + duration)
    
    # Calculate duration of selected window for previous/future windows
    selected_duration_minutes = int((time_limit - time_threshold).total_seconds() / 60)
    if selected_duration_minutes <= 0:
        selected_duration_minutes = minutes  # Fallback to default
    
    # Get activities from PREVIOUS time window for scoring
    previous_window_start = time_threshold - timedelta(minutes=selected_duration_minutes)
    previous_window_end = time_threshold
    
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
    
    # Filter out arrived and cancelled trains
    atocha_arrivals_filtered = filter_future_arrivals(atocha_arrivals_raw, "train")
    chamartin_arrivals_filtered = filter_future_arrivals(chamartin_arrivals_raw, "train")
    
    # Count PAST arrivals (previous window: from -2*minutes to -minutes)
    # Use raw data for past arrivals since we want to count what already arrived
    atocha_prev_arrivals = count_arrivals_in_past_window(atocha_arrivals_raw, minutes * 2, minutes)
    chamartin_prev_arrivals = count_arrivals_in_past_window(chamartin_arrivals_raw, minutes * 2, minutes)
    
    # Count FUTURE arrivals (next window: from now to +minutes) - use filtered data
    atocha_future_arrivals = count_arrivals_in_window(atocha_arrivals_filtered, minutes)
    chamartin_future_arrivals = count_arrivals_in_window(chamartin_arrivals_filtered, minutes)
    
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
        
        # Use raw data for past arrivals
        prev_count = count_arrivals_in_past_window(terminal_flights, minutes * 2, minutes)
        # Filter for future arrivals (exclude cancelled and landed)
        filtered_flights = filter_future_arrivals(terminal_flights, "flight")
        future_count = count_arrivals_in_window(filtered_flights, minutes)
        
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
        
        # Get taxi status for hottest station (only from last 24 hours)
        taxi_time_limit = now - timedelta(hours=24)
        taxi_doc = await taxi_status_collection.find_one(
            {
                "location_type": "station", 
                "location_name": best_station_name,
                "reported_at": {"$gte": taxi_time_limit}
            },
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
        
        # Get taxi status for hottest terminal (only from last 24 hours)
        # Check all terminals in the group
        taxi_time_limit = now - timedelta(hours=24)
        terminal_taxi_query = {
            "location_type": "terminal", 
            "location_name": {"$in": [best_terminal_name, best_terminal_name.replace("-", ""), *best_terminal_name.split("-")]},
            "reported_at": {"$gte": taxi_time_limit}
        }
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
            duration_minutes=a.get("duration_minutes"),
            distance_km=a.get("distance_km")
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
        exits_by_station=prev_station_exits,
        exits_by_terminal=prev_terminal_exits,
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
# NOTE: Checkin endpoints have been moved to routers/checkin.py

# NOTE: Taxi and Queue status endpoints have been moved to routers/status.py

# ============== EMERGENCY ALERT ENDPOINTS ==============
# NOTE: Emergency endpoints have been moved to routers/emergency.py


# ============== EVENTS ENDPOINTS ==============
# NOTE: Events endpoints have been moved to routers/events.py


# ============== CHAT ENDPOINTS ==============


# ============== CHAT ENDPOINTS ==============
# NOTE: Chat endpoints have been moved to routers/chat.py


# ============== LICENSE ALERTS ENDPOINTS ==============
# NOTE: License alerts endpoints have been moved to routers/alerts.py


# ============== ADMIN ENDPOINTS ==============
# NOTE: Admin endpoints have been moved to routers/admin.py


# Include modular routers BEFORE adding to app
api_router.include_router(auth_router.router)
api_router.include_router(chat_router.router)
api_router.include_router(alerts_router.router)
api_router.include_router(admin_router.router)
api_router.include_router(events_router.router)
api_router.include_router(emergency_router.router)
api_router.include_router(checkin_router.router)
api_router.include_router(status_router.router)
api_router.include_router(geocoding_router.router)
api_router.include_router(station_alerts_router.router)
api_router.include_router(radio_router.router)
api_router.include_router(games_router.router)

# Include the router in the main app
app.include_router(api_router)

# Add rate limiting to the app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# GZIP compression middleware for faster responses
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)  # Compress responses > 500 bytes

# CORS configuration - use environment variable for production domains
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============== HOTTEST STREET CACHE FUNCTIONS ==============

async def calculate_and_cache_hottest_street(minutes: int = 60):
    """Calculate hottest street data and save to MongoDB for persistence."""
    try:
        # Use UTC for MongoDB comparisons since MongoDB stores dates in UTC
        now_utc = datetime.utcnow()
        time_threshold = now_utc - timedelta(minutes=minutes)
        
        # Get activities in the time window
        cursor = street_activities_collection.find(
            {"created_at": {"$gte": time_threshold}},
            {"_id": 0}
        ).sort("created_at", -1)
        activities = await cursor.to_list(1000)
        
        logger.info(f"Hottest street calc: Found {len(activities)} activities in last {minutes} minutes")
        
        # Count loads per street
        load_counts = {}
        total_loads = 0
        
        for activity in activities:
            if activity.get("action") == "load":
                total_loads += 1
                street = activity.get("street_name", "Desconocida")
                if street not in load_counts:
                    load_counts[street] = {
                        "count": 0,
                        "latitude": activity.get("latitude"),
                        "longitude": activity.get("longitude")
                    }
                load_counts[street]["count"] += 1
        
        # Calculate hottest street
        hottest_street_data = {
            "hottest_street": None,
            "hottest_count": 0,
            "hottest_lat": None,
            "hottest_lng": None,
            "hottest_percentage": None,
            "hottest_total_loads": total_loads,
            "calculated_at": now_utc,
            "minutes_window": minutes
        }
        
        if load_counts and total_loads > 0:
            street_percentages = []
            for street_name, data in load_counts.items():
                percentage = (data["count"] / total_loads) * 100
                street_percentages.append({
                    "name": street_name,
                    "count": data["count"],
                    "percentage": percentage,
                    "lat": data["latitude"],
                    "lng": data["longitude"]
                })
            
            street_percentages.sort(key=lambda x: -x["percentage"])
            best = street_percentages[0]
            
            if best["percentage"] >= 10 or len(street_percentages) == 1:
                hottest_street_data["hottest_street"] = best["name"]
                hottest_street_data["hottest_count"] = best["count"]
                hottest_street_data["hottest_lat"] = best["lat"]
                hottest_street_data["hottest_lng"] = best["lng"]
                hottest_street_data["hottest_percentage"] = round(best["percentage"], 1)
        
        # Save to MongoDB (upsert based on minutes_window)
        await hottest_street_cache_collection.update_one(
            {"minutes_window": minutes},
            {"$set": hottest_street_data},
            upsert=True
        )
        
        logger.info(f"Hottest street cache updated: {hottest_street_data['hottest_street']} ({hottest_street_data['hottest_percentage']}%)")
        return hottest_street_data
        
    except Exception as e:
        logger.error(f"Error calculating hottest street cache: {e}")
        return None


async def get_cached_hottest_street(minutes: int = 60):
    """Get cached hottest street data from MongoDB."""
    try:
        cached = await hottest_street_cache_collection.find_one({"minutes_window": minutes})
        if cached:
            # Check if cache is still fresh (less than 60 seconds old)
            calc_time = cached.get("calculated_at")
            if calc_time:
                # Handle both datetime and string formats
                if isinstance(calc_time, str):
                    calc_time = date_parser.parse(calc_time)
                # Use UTC for comparison since MongoDB stores in UTC
                now_utc = datetime.utcnow()
                if calc_time.tzinfo:
                    calc_time = calc_time.replace(tzinfo=None)  # Remove timezone for UTC comparison
                age = (now_utc - calc_time).total_seconds()
                if age < 60:  # Use cache if less than 60 seconds old
                    return cached
        return None
    except Exception as e:
        logger.error(f"Error getting cached hottest street: {e}")
        return None


# Background task for cache refresh
async def refresh_cache_periodically():
    """Background task to refresh cache every 30 seconds."""
    while True:
        try:
            await asyncio.sleep(CACHE_TTL_SECONDS)
            logger.info("Background cache refresh starting...")
            
            # Refresh train data
            if not cache_refresh_in_progress["trains"]:
                cache_refresh_in_progress["trains"] = True
                try:
                    atocha_arrivals = await fetch_adif_arrivals_api(STATION_IDS["atocha"])
                    chamartin_arrivals = await fetch_adif_arrivals_api(STATION_IDS["chamartin"])
                    
                    if atocha_arrivals or chamartin_arrivals:
                        arrival_cache["trains"]["data"] = {
                            "atocha": atocha_arrivals,
                            "chamartin": chamartin_arrivals
                        }
                        arrival_cache["trains"]["timestamp"] = datetime.now()
                        arrival_cache["trains"]["last_successful"] = datetime.now()
                        logger.info(f"Background: Train cache refreshed - Atocha: {len(atocha_arrivals)}, Chamartin: {len(chamartin_arrivals)}")
                except Exception as e:
                    logger.error(f"Background: Error refreshing train cache: {e}")
                finally:
                    cache_refresh_in_progress["trains"] = False
            
            # Refresh flight data
            if not cache_refresh_in_progress["flights"]:
                cache_refresh_in_progress["flights"] = True
                try:
                    flight_data = await fetch_aena_arrivals()
                    if flight_data:
                        arrival_cache["flights"]["data"] = flight_data
                        arrival_cache["flights"]["timestamp"] = datetime.now()
                        arrival_cache["flights"]["last_successful"] = datetime.now()
                        total_flights = sum(len(v) for v in flight_data.values())
                        logger.info(f"Background: Flight cache refreshed - {total_flights} flights")
                except Exception as e:
                    logger.error(f"Background: Error refreshing flight cache: {e}")
                finally:
                    cache_refresh_in_progress["flights"] = False
            
            # Refresh hottest street cache (every 30 seconds)
            try:
                await calculate_and_cache_hottest_street(minutes=60)
            except Exception as e:
                logger.error(f"Background: Error refreshing hottest street cache: {e}")
                    
        except Exception as e:
            logger.error(f"Background cache refresh error: {e}")
            await asyncio.sleep(10)  # Wait a bit before retrying

@app.on_event("startup")
async def startup_db_client():
    """Create default admin user and preload cache on startup."""
    await create_default_admin()
    
    # Create indexes for faster queries
    logger.info("Setting up database indexes...")
    try:
        # Index for street_activities by created_at (speeds up time-based queries)
        await street_activities_collection.create_index(
            "created_at",
            background=True
        )
        logger.info("Created index on street_activities.created_at")
        
        # Compound index for street activities queries
        await street_activities_collection.create_index(
            [("created_at", -1), ("action", 1)],
            background=True
        )
        logger.info("Created compound index on street_activities")
        
        # Index for taxi_status by created_at
        await taxi_status_collection.create_index(
            "created_at",
            background=True
        )
        logger.info("Created index on taxi_status.created_at")
        
        # Index for queue_status by created_at
        await queue_status_collection.create_index(
            "created_at",
            background=True
        )
        logger.info("Created index on queue_status.created_at")
        
    except Exception as e:
        logger.info(f"Index setup: {e}")
    
    # Create additional indexes for other collections
    logger.info("Setting up additional indexes...")
    try:
        # Index for users by username (unique lookups)
        await users_collection.create_index("username", unique=True, background=True)
        logger.info("Created unique index on users.username")
        
        # Index for users by license_number (unique lookups)
        await users_collection.create_index("license_number", unique=True, sparse=True, background=True)
        logger.info("Created unique index on users.license_number")
        
        # Index for station_alerts by expires_at (for cleanup queries)
        await station_alerts_collection.create_index("expires_at", background=True)
        logger.info("Created index on station_alerts.expires_at")
        
        # Compound index for station_alerts by location
        await station_alerts_collection.create_index(
            [("location_type", 1), ("location_name", 1), ("expires_at", -1)],
            background=True
        )
        logger.info("Created compound index on station_alerts")
        
        # Index for chat_messages by channel and created_at
        await chat_messages_collection.create_index(
            [("channel", 1), ("created_at", -1)],
            background=True
        )
        logger.info("Created compound index on chat_messages")
        
        # Index for checkins by user_id and location
        await active_checkins_collection.create_index(
            [("user_id", 1), ("status", 1)],
            background=True
        )
        logger.info("Created compound index on checkins")
        
    except Exception as e:
        logger.info(f"Additional indexes setup: {e}")
    
    # Create TTL indexes for history collections (12 hours = 43200 seconds)
    logger.info("Setting up TTL indexes for history collections...")
    try:
        # Create TTL index for trains_history (12 hours retention)
        await trains_history_collection.create_index(
            "fetched_at",
            expireAfterSeconds=43200,  # 12 hours
            background=True
        )
        logger.info("Created TTL index for trains_history (12 hour retention)")
        
        # Create TTL index for flights_history (12 hours retention)
        await flights_history_collection.create_index(
            "fetched_at",
            expireAfterSeconds=43200,  # 12 hours
            background=True
        )
        logger.info("Created TTL index for flights_history (12 hour retention)")
    except Exception as e:
        # Index may already exist, which is fine
        logger.info(f"TTL indexes setup: {e}")
    
    # Preload cache on startup
    logger.info("Preloading arrival cache on startup...")
    try:
        # Fetch train data
        atocha_arrivals = await fetch_adif_arrivals_api(STATION_IDS["atocha"])
        chamartin_arrivals = await fetch_adif_arrivals_api(STATION_IDS["chamartin"])
        arrival_cache["trains"]["data"] = {
            "atocha": atocha_arrivals,
            "chamartin": chamartin_arrivals
        }
        arrival_cache["trains"]["timestamp"] = datetime.now()
        arrival_cache["trains"]["last_successful"] = datetime.now()
        logger.info(f"Preloaded train cache - Atocha: {len(atocha_arrivals)}, Chamartin: {len(chamartin_arrivals)}")
        
        # Save initial data to history
        await save_train_history("atocha", atocha_arrivals)
        await save_train_history("chamartin", chamartin_arrivals)
        
        # Fetch flight data
        flight_data = await fetch_aena_arrivals()
        arrival_cache["flights"]["data"] = flight_data
        arrival_cache["flights"]["timestamp"] = datetime.now()
        arrival_cache["flights"]["last_successful"] = datetime.now()
        total_flights = sum(len(v) for v in flight_data.values())
        logger.info(f"Preloaded flight cache - {total_flights} flights")
        
        # Save initial flight data to history
        for terminal in TERMINALS:
            await save_flight_history(terminal, flight_data.get(terminal, []))
            
    except Exception as e:
        logger.error(f"Error preloading cache: {e}")
    
    # Preload hottest street cache on startup
    try:
        await calculate_and_cache_hottest_street(minutes=60)
        logger.info("Preloaded hottest street cache")
    except Exception as e:
        logger.error(f"Error preloading hottest street cache: {e}")
    
    # Start background refresh task
    asyncio.create_task(refresh_cache_periodically())
    logger.info("Background cache refresh task started")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
