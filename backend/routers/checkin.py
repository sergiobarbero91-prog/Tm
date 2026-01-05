"""
Check-in router for station/terminal entry and exit tracking.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid
import pytz

from shared import (
    street_activities_collection,
    taxi_status_collection,
    queue_status_collection,
    active_checkins_collection,
    get_current_user_required,
    logger
)

router = APIRouter(tags=["Check-in"])

MADRID_TZ = pytz.timezone('Europe/Madrid')

# Models
class CheckInRequest(BaseModel):
    location_type: str  # 'station' or 'terminal'
    location_name: str  # e.g., 'Atocha', 'T4'
    action: str  # 'entry' or 'exit'
    latitude: float
    longitude: float
    taxi_status: Optional[str] = None  # 'poco', 'normal', 'mucho' - only for 'entry'
    queue_status: Optional[str] = None  # 'poco', 'normal', 'mucho' - only for 'exit' (people waiting)

class CheckInStatus(BaseModel):
    is_checked_in: bool
    location_type: Optional[str] = None
    location_name: Optional[str] = None
    entry_time: Optional[str] = None


# Helper functions for active check-ins (using MongoDB for persistence)
async def get_active_checkin(user_id: str):
    """Get active check-in from MongoDB."""
    return await active_checkins_collection.find_one({"user_id": user_id})

async def set_active_checkin(user_id: str, location_type: str, location_name: str, entry_time: str):
    """Set or update active check-in in MongoDB."""
    await active_checkins_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "location_type": location_type,
            "location_name": location_name,
            "entry_time": entry_time
        }},
        upsert=True
    )

async def delete_active_checkin(user_id: str):
    """Delete active check-in from MongoDB."""
    await active_checkins_collection.delete_one({"user_id": user_id})


@router.post("/checkin")
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
        # Store active check-in in MongoDB
        await set_active_checkin(
            user_id=user_id,
            location_type=checkin.location_type,
            location_name=checkin.location_name,
            entry_time=now.isoformat()
        )
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
        
        # Calculate duration if there was an entry (from MongoDB)
        active_checkin = await get_active_checkin(user_id)
        if active_checkin:
            entry_time_str = active_checkin.get("entry_time")
            if entry_time_str:
                try:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    duration = now - entry_time
                    duration_minutes = int(duration.total_seconds() / 60)
                except:
                    pass
            await delete_active_checkin(user_id)
        
        # Save queue status if provided (people waiting)
        if checkin.queue_status:
            await queue_status_collection.insert_one({
                "location_type": checkin.location_type,
                "location_name": checkin.location_name,
                "queue_status": checkin.queue_status,
                "reported_at": now,
                "reported_by": current_user.get("username", "unknown"),
                "user_id": user_id
            })
    
    # Get street name from coordinates
    street_name = f"{checkin.location_name}"
    try:
        from geopy.geocoders import Nominatim
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


@router.get("/checkin/status", response_model=CheckInStatus)
async def get_checkin_status(
    current_user: dict = Depends(get_current_user_required)
):
    """Get current check-in status for the user."""
    user_id = current_user["id"]
    
    # Check active check-ins in MongoDB (persistent storage)
    active_checkin = await get_active_checkin(user_id)
    if active_checkin:
        return CheckInStatus(
            is_checked_in=True,
            location_type=active_checkin["location_type"],
            location_name=active_checkin["location_name"],
            entry_time=active_checkin["entry_time"]
        )
    
    # Also check if there's an entry without exit in street activities (backup check)
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
            # Still checked in - restore to active_checkins collection
            location_type = last_entry.get("location_type", "station")
            location_name = last_entry.get("location_name", "Unknown")
            entry_time = last_entry["created_at"].isoformat()
            
            await set_active_checkin(user_id, location_type, location_name, entry_time)
            
            return CheckInStatus(
                is_checked_in=True,
                location_type=location_type,
                location_name=location_name,
                entry_time=entry_time
            )
    
    return CheckInStatus(is_checked_in=False)
