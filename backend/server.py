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

class StationData(BaseModel):
    station_id: str
    station_name: str
    arrivals: List[TrainArrival]
    total_next_30min: int
    total_next_60min: int
    is_winner_30min: bool = False
    is_winner_60min: bool = False
    morning_arrivals: int = 0

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
    # Reject MD (Media Distancia regional) - only keep high-speed
    if train_type_upper == "MD":
        return False
    return False

async def fetch_adif_arrivals(station_id: str) -> List[Dict]:
    """Fetch train arrivals from ADIF website - ONLY media/larga distancia."""
    arrivals = []
    url = f"https://www.adif.es/-/{station_id}-madrid-pta-de-atocha" if station_id == "60000" else f"https://www.adif.es/-/{station_id}-madrid-chamart%C3%ADn"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=30) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')
                    
                    # Find the arrivals table
                    arrivals_section = soup.find('div', {'id': 'tab-llegadas'})
                    if arrivals_section:
                        table = arrivals_section.find('table')
                        if table:
                            rows = table.find_all('tr')[1:]  # Skip header
                            for row in rows:
                                cols = row.find_all('td')
                                if len(cols) >= 3:
                                    time_text = cols[0].get_text(strip=True)
                                    origin = cols[1].get_text(strip=True)
                                    train_info = cols[2].get_text(strip=True)
                                    platform = cols[3].get_text(strip=True) if len(cols) > 3 else None
                                    
                                    # Parse train type and number
                                    # Format: "RF - AVE03063" or "IL - IRYO06261" or "RI - OUIGO06476"
                                    train_match = re.search(r'([A-Z]+)\s*[-]?\s*([A-Z]+)(\d+)', train_info)
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
                                            "origin": origin.split('\n')[0].strip(),
                                            "train_type": train_type.upper(),
                                            "train_number": train_number,
                                            "platform": platform if platform else "-",
                                            "status": "En hora"
                                        })
    except Exception as e:
        logger.error(f"Error fetching ADIF data for station {station_id}: {e}")
    
    logger.info(f"Station {station_id}: Found {len(arrivals)} media/larga distancia trains")
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
                            
                            # Extract time
                            time_elem = row.find('td', class_='scheduled') or row.find('td')
                            if not time_elem:
                                continue
                            time_text = time_elem.get_text(strip=True)
                            
                            # Try to extract time from text like "00:15 - Milan (MXP)"
                            time_match = re.search(r'(\d{1,2}:\d{2})', time_text)
                            if not time_match:
                                continue
                            arrival_time = time_match.group(1)
                            
                            # Get terminal
                            terminal_elem = row.find('span', class_=re.compile(r'T\d'))
                            if terminal_elem:
                                terminal = terminal_elem.get_text(strip=True)
                            else:
                                # Try to find T1, T2, T3, T4, T4S in the row text
                                row_text = row.get_text()
                                terminal = None
                                for t in ["T4S", "T4", "T3", "T2", "T1"]:
                                    if t in row_text:
                                        terminal = t
                                        break
                                if not terminal:
                                    continue
                            
                            # Normalize terminal
                            if terminal == "T4-S":
                                terminal = "T4S"
                            
                            # Get origin
                            origin_match = re.search(r'-\s*([^(]+)\s*\(', time_text)
                            if origin_match:
                                origin = origin_match.group(1).strip()
                            else:
                                origin = "Unknown"
                            
                            # Get airline and flight number
                            airline_links = row.find_all('a', href=re.compile(r'aerolineas'))
                            flight_links = row.find_all('a', href=re.compile(r'llegada-vuelo'))
                            
                            airline = airline_links[0].get_text(strip=True) if airline_links else "Unknown"
                            flight_number = flight_links[0].get_text(strip=True) if flight_links else "Unknown"
                            
                            # Get status
                            status_elem = row.find('td', class_=re.compile(r'status|estado'))
                            status = status_elem.get_text(strip=True) if status_elem else "En hora"
                            
                            # Translate status
                            if "llegado" in status.lower() or "arrived" in status.lower():
                                status = "Aterrizado"
                            elif "retrasado" in status.lower() or "delayed" in status.lower():
                                status = "Retrasado"
                            elif "cancelado" in status.lower() or "cancelled" in status.lower():
                                status = "Cancelado"
                            else:
                                status = "En hora"
                            
                            if terminal in terminal_arrivals:
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
                            continue
                    
    except Exception as e:
        logger.error(f"Error fetching AENA data: {e}")
    
    # Count total flights found
    total = sum(len(v) for v in terminal_arrivals.values())
    logger.info(f"Flights fetched: {total} total")
    
    # If no data was scraped, return empty but valid structure
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
            except:
                pass
        return count, morning_count
    
    return count, 0

# API Endpoints
@api_router.get("/")
async def root():
    return {"message": "TransportMeter API - Frecuencia de Trenes y Aviones en Madrid"}

@api_router.get("/trains", response_model=TrainComparisonResponse)
async def get_train_comparison():
    """Get train arrivals comparison between Atocha and Chamartín - ONLY media/larga distancia."""
    now = datetime.now()
    is_night_time = now.hour < 6
    
    # Fetch data for both stations
    atocha_arrivals = await fetch_adif_arrivals(STATION_IDS["atocha"])
    chamartin_arrivals = await fetch_adif_arrivals(STATION_IDS["chamartin"])
    
    # Count arrivals with extended info for night time
    atocha_30, atocha_morning = count_arrivals_extended(atocha_arrivals, 30)
    atocha_60, _ = count_arrivals_extended(atocha_arrivals, 60)
    chamartin_30, chamartin_morning = count_arrivals_extended(chamartin_arrivals, 30)
    chamartin_60, _ = count_arrivals_extended(chamartin_arrivals, 60)
    
    # For night time, use morning counts to determine winner
    if is_night_time:
        winner_30 = "atocha" if atocha_morning >= chamartin_morning else "chamartin"
        winner_60 = "atocha" if atocha_morning >= chamartin_morning else "chamartin"
    else:
        winner_30 = "atocha" if atocha_30 >= chamartin_30 else "chamartin"
        winner_60 = "atocha" if atocha_60 >= chamartin_60 else "chamartin"
    
    # Build response
    atocha_data = StationData(
        station_id=STATION_IDS["atocha"],
        station_name=STATION_NAMES["atocha"],
        arrivals=[TrainArrival(**a) for a in atocha_arrivals[:20]],
        total_next_30min=atocha_30 if not is_night_time else atocha_morning,
        total_next_60min=atocha_60 if not is_night_time else atocha_morning,
        is_winner_30min=(winner_30 == "atocha"),
        is_winner_60min=(winner_60 == "atocha"),
        morning_arrivals=atocha_morning
    )
    
    chamartin_data = StationData(
        station_id=STATION_IDS["chamartin"],
        station_name=STATION_NAMES["chamartin"],
        arrivals=[TrainArrival(**a) for a in chamartin_arrivals[:20]],
        total_next_30min=chamartin_30 if not is_night_time else chamartin_morning,
        total_next_60min=chamartin_60 if not is_night_time else chamartin_morning,
        is_winner_30min=(winner_30 == "chamartin"),
        is_winner_60min=(winner_60 == "chamartin"),
        morning_arrivals=chamartin_morning
    )
    
    message = None
    if is_night_time:
        message = "Horario nocturno - Mostrando llegadas de AVE/AVANT/ALVIA/IRYO programadas para la mañana (6:00-10:00)"
    
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
