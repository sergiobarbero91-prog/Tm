"""
Renfe Open Data GTFS Integration
Downloads and parses GTFS static data + real-time delays for train arrivals.
Used as fallback when ADIF API fails.
"""
import os
import csv
import json
import zipfile
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from io import BytesIO, StringIO
import pytz

logger = logging.getLogger(__name__)

MADRID_TZ = pytz.timezone('Europe/Madrid')

# GTFS URLs
GTFS_STATIC_URL = "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"
GTFS_REALTIME_URL = "https://gtfsrt.renfe.com/trip_updates_LD.json"

# Station IDs
CHAMARTIN_ID = "17000"
ATOCHA_ID = "60000"

# Cache for GTFS data
gtfs_cache = {
    "routes": {},       # route_id -> route_short_name (train type)
    "trips": {},        # trip_id -> {route_id, train_number}
    "stops": {},        # stop_id -> stop_name
    "stop_times": {},   # stop_id -> [{trip_id, arrival_time, stop_sequence}]
    "trip_origins": {}, # trip_id -> origin_stop_id
    "last_update": None,
    "update_interval_hours": 24  # Update GTFS static data daily
}


async def download_gtfs_static() -> bool:
    """Download and parse GTFS static data from Renfe."""
    try:
        logger.info("Downloading Renfe GTFS static data...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(GTFS_STATIC_URL, timeout=aiohttp.ClientTimeout(total=60)) as response:
                if response.status != 200:
                    logger.error(f"Failed to download GTFS: HTTP {response.status}")
                    return False
                
                zip_data = await response.read()
        
        # Parse ZIP in memory
        with zipfile.ZipFile(BytesIO(zip_data)) as zf:
            # Parse routes.txt
            with zf.open('routes.txt') as f:
                content = f.read().decode('utf-8')
                reader = csv.DictReader(StringIO(content))
                gtfs_cache["routes"] = {}
                for row in reader:
                    route_id = row['route_id'].strip()
                    gtfs_cache["routes"][route_id] = row.get('route_short_name', '').strip()
            
            # Parse trips.txt
            with zf.open('trips.txt') as f:
                content = f.read().decode('utf-8')
                reader = csv.DictReader(StringIO(content))
                gtfs_cache["trips"] = {}
                for row in reader:
                    trip_id = row['trip_id'].strip()
                    gtfs_cache["trips"][trip_id] = {
                        'route_id': row['route_id'].strip(),
                        'train_number': row.get('trip_short_name', '').strip()
                    }
            
            # Parse stops.txt
            with zf.open('stops.txt') as f:
                content = f.read().decode('utf-8')
                reader = csv.DictReader(StringIO(content))
                gtfs_cache["stops"] = {}
                for row in reader:
                    stop_id = row['stop_id'].strip()
                    gtfs_cache["stops"][stop_id] = row.get('stop_name', '').strip()
            
            # Parse stop_times.txt and index by stop_id
            with zf.open('stop_times.txt') as f:
                content = f.read().decode('utf-8')
                reader = csv.DictReader(StringIO(content))
                gtfs_cache["stop_times"] = {}
                gtfs_cache["trip_origins"] = {}
                
                for row in reader:
                    trip_id = row['trip_id'].strip()
                    stop_id = row['stop_id'].strip()
                    seq = int(row.get('stop_sequence', 0))
                    
                    # Track first stop (origin) of each trip
                    if seq == 1:
                        gtfs_cache["trip_origins"][trip_id] = stop_id
                    
                    # Index by stop_id for quick lookups
                    if stop_id not in gtfs_cache["stop_times"]:
                        gtfs_cache["stop_times"][stop_id] = []
                    
                    gtfs_cache["stop_times"][stop_id].append({
                        'trip_id': trip_id,
                        'arrival_time': row['arrival_time'].strip(),
                        'stop_sequence': seq
                    })
        
        gtfs_cache["last_update"] = datetime.now()
        
        logger.info(f"GTFS loaded: {len(gtfs_cache['routes'])} routes, "
                   f"{len(gtfs_cache['trips'])} trips, "
                   f"{len(gtfs_cache['stops'])} stops")
        
        return True
        
    except Exception as e:
        logger.error(f"Error downloading GTFS: {e}")
        return False


async def get_realtime_delays() -> Dict[str, int]:
    """Fetch real-time delays from Renfe GTFS-RT feed."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(GTFS_REALTIME_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {}
                
                data = await response.json()
                delays = {}
                
                for entity in data.get('entity', []):
                    tu = entity.get('tripUpdate', {})
                    trip_id = tu.get('trip', {}).get('tripId', '')
                    delay = tu.get('delay', 0)
                    if trip_id:
                        delays[trip_id] = delay
                
                return delays
                
    except Exception as e:
        logger.debug(f"Error fetching realtime delays: {e}")
        return {}


async def ensure_gtfs_loaded():
    """Ensure GTFS data is loaded and up to date."""
    if gtfs_cache["last_update"] is None:
        await download_gtfs_static()
    elif (datetime.now() - gtfs_cache["last_update"]).total_seconds() > gtfs_cache["update_interval_hours"] * 3600:
        await download_gtfs_static()


async def get_arrivals_from_renfe(station_id: str, hours_ahead: int = 3) -> List[Dict]:
    """
    Get train arrivals from Renfe Open Data GTFS.
    
    Args:
        station_id: Station ID (17000 for Chamartín, 60000 for Atocha)
        hours_ahead: How many hours ahead to look
        
    Returns:
        List of arrival dicts with time, train_type, train_number, origin, etc.
    """
    await ensure_gtfs_loaded()
    
    if not gtfs_cache["stop_times"]:
        logger.warning("GTFS data not available")
        return []
    
    now = datetime.now(MADRID_TZ)
    today = now.strftime('%Y-%m-%d')
    current_minutes = now.hour * 60 + now.minute
    max_minutes = current_minutes + (hours_ahead * 60)
    
    # Get realtime delays
    delays = await get_realtime_delays()
    
    arrivals = []
    stop_times = gtfs_cache["stop_times"].get(station_id, [])
    
    for st in stop_times:
        trip_id = st['trip_id']
        
        # Only today's trips
        if today not in trip_id:
            continue
        
        # Only arrivals (not the origin station)
        origin_stop = gtfs_cache["trip_origins"].get(trip_id, '')
        if origin_stop == station_id:
            continue  # This train departs from here, not arrives
        
        # Parse arrival time
        try:
            parts = st['arrival_time'].split(':')
            arr_hour = int(parts[0])
            arr_min = int(parts[1])
            
            # Handle times > 24 (next day service)
            if arr_hour >= 24:
                continue  # Skip next-day arrivals
            
            arr_minutes = arr_hour * 60 + arr_min
            
            # Only future arrivals within range
            if arr_minutes < current_minutes or arr_minutes > max_minutes:
                continue
                
        except (ValueError, IndexError):
            continue
        
        # Get train info
        trip_info = gtfs_cache["trips"].get(trip_id, {})
        route_id = trip_info.get('route_id', '')
        train_type = gtfs_cache["routes"].get(route_id, 'TREN')
        train_number = trip_info.get('train_number', '')
        origin_name = gtfs_cache["stops"].get(origin_stop, origin_stop)
        
        # Apply realtime delay
        delay_seconds = delays.get(trip_id, 0)
        delay_minutes = delay_seconds // 60 if delay_seconds else 0
        
        # Calculate real arrival time
        real_minutes = arr_minutes + delay_minutes
        real_hour = (real_minutes // 60) % 24
        real_min = real_minutes % 60
        
        arrivals.append({
            'time': f"{real_hour:02d}:{real_min:02d}",
            'scheduled_time': f"{arr_hour:02d}:{arr_min:02d}",
            'train_type': train_type.upper(),
            'train_number': train_number,
            'origin': origin_name,
            'delay_minutes': delay_minutes if delay_minutes != 0 else None,
            'status': 'Retraso' if delay_minutes > 0 else 'En hora',
            'platform': '-',
            'source': 'Renfe GTFS'
        })
    
    # Sort by time and remove duplicates
    arrivals.sort(key=lambda x: x['time'])
    
    seen = set()
    unique = []
    for arr in arrivals:
        key = f"{arr['scheduled_time']}_{arr['train_number']}"
        if key not in seen:
            seen.add(key)
            unique.append(arr)
    
    return unique[:30]
