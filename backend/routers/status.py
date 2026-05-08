"""
Status router for taxi and queue status reporting.
"""
from fastapi import APIRouter, Depends
from typing import Optional
from datetime import datetime, timedelta
import pytz

from shared import (
    taxi_status_collection,
    queue_status_collection,
    get_current_user_required
)

router = APIRouter(tags=["Status"])

MADRID_TZ = pytz.timezone('Europe/Madrid')


@router.get("/taxi/status")
async def get_taxi_status(
    location_type: Optional[str] = None,
    location_name: Optional[str] = None,
    minutes: int = 60,  # Time window to filter
    current_user: dict = Depends(get_current_user_required)
):
    """Get the latest taxi status for stations and terminals within the time window (max 24 hours)."""
    now = datetime.now(MADRID_TZ)
    
    # Time window: from (now - minutes) to now
    # But limit to maximum 24 hours to avoid showing very old data
    max_window = timedelta(hours=24)
    requested_window = timedelta(minutes=minutes)
    actual_window = min(requested_window, max_window)
    
    window_start = now - actual_window
    
    # Build query: data within the time window (can span midnight)
    query = {"reported_at": {"$gte": window_start, "$lte": now}}
    if location_type:
        query["location_type"] = location_type
    if location_name:
        query["location_name"] = location_name
    
    # Get the most recent taxi status for each location within time window
    pipeline = [
        {"$match": query},
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


@router.get("/queue/status")
async def get_queue_status(
    location_type: Optional[str] = None,
    location_name: Optional[str] = None,
    minutes: int = 60,  # Time window to filter
    current_user: dict = Depends(get_current_user_required)
):
    """Get the latest queue status (people waiting) within the time window (max 24 hours)."""
    now = datetime.now(MADRID_TZ)
    
    # Time window: from (now - minutes) to now
    # But limit to maximum 24 hours to avoid showing very old data
    max_window = timedelta(hours=24)
    requested_window = timedelta(minutes=minutes)
    actual_window = min(requested_window, max_window)
    
    window_start = now - actual_window
    
    # Build query: data within the time window (can span midnight)
    query = {"reported_at": {"$gte": window_start, "$lte": now}}
    if location_type:
        query["location_type"] = location_type
    if location_name:
        query["location_name"] = location_name
    
    # Get the most recent queue status for each location within time window
    pipeline = [
        {"$match": query},
        {"$sort": {"reported_at": -1}},
        {"$group": {
            "_id": {"location_type": "$location_type", "location_name": "$location_name"},
            "queue_status": {"$first": "$queue_status"},
            "reported_at": {"$first": "$reported_at"},
            "reported_by": {"$first": "$reported_by"}
        }}
    ]
    
    results = await queue_status_collection.aggregate(pipeline).to_list(100)
    
    queue_data = {}
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
        queue_data[key] = {
            "location_type": r["_id"]["location_type"],
            "location_name": r["_id"]["location_name"],
            "queue_status": r["queue_status"],
            "reported_at": reported_at_str,
            "reported_by": r["reported_by"]
        }
    
    return queue_data
