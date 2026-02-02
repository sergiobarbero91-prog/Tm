"""
Events router for community events (traffic jams, police controls, etc.)
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import uuid
import pytz

from shared import (
    events_collection,
    get_current_user_required,
    logger,
    POINTS_CONFIG
)

# Import add_points function
from routers.points import add_points

router = APIRouter(prefix="/events", tags=["Events"])

MADRID_TZ = pytz.timezone('Europe/Madrid')

# Models
class CreateEventRequest(BaseModel):
    location: str
    description: str
    event_time: str  # Format: "HH:MM"

class VoteEventRequest(BaseModel):
    vote_type: str  # "like" or "dislike"


@router.post("")
async def create_event(
    request: CreateEventRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Create a new event."""
    try:
        now = datetime.now(MADRID_TZ)
        
        # Parse event time
        try:
            event_hour, event_minute = map(int, request.event_time.split(':'))
            event_datetime = now.replace(hour=event_hour, minute=event_minute, second=0, microsecond=0)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de hora inválido. Use HH:MM")
        
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "user_id": current_user["id"],
            "username": current_user["username"],
            "location": request.location,
            "description": request.description,
            "event_time": request.event_time,
            "event_datetime": event_datetime,
            "likes": 0,
            "dislikes": 0,
            "liked_by": [],
            "disliked_by": [],
            "created_at": now,
            "date": now.strftime("%Y-%m-%d")
        }
        
        await events_collection.insert_one(event)
        
        return {
            "success": True,
            "event_id": event_id,
            "message": "Evento creado correctamente"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating event: {e}")
        raise HTTPException(status_code=500, detail="Error al crear el evento")


@router.get("")
async def get_events(
    shift: str = "all",  # "morning", "afternoon", "night", "all"
    current_user: dict = Depends(get_current_user_required)
):
    """Get events for today filtered by shift."""
    try:
        now = datetime.now(MADRID_TZ)
        today = now.strftime("%Y-%m-%d")
        
        # Build query for today's events
        query = {"date": today}
        
        # Filter by shift (time ranges)
        if shift == "morning":
            # 6:00 - 14:00
            query["event_time"] = {"$gte": "06:00", "$lt": "14:00"}
        elif shift == "afternoon":
            # 14:00 - 22:00
            query["event_time"] = {"$gte": "14:00", "$lt": "22:00"}
        elif shift == "night":
            # 22:00 - 06:00 (need special handling for overnight)
            query["$or"] = [
                {"event_time": {"$gte": "22:00"}},
                {"event_time": {"$lt": "06:00"}}
            ]
        
        # Get events sorted by event_time descending and likes descending
        cursor = events_collection.find(query).sort([
            ("event_time", -1),
            ("likes", -1)
        ])
        events = await cursor.to_list(100)
        
        # Get user role for permission checks
        user_role = current_user.get("role", "user")
        can_moderate = user_role in ["admin", "moderator"]
        
        # Format response
        result = []
        for event in events:
            is_owner = event["user_id"] == current_user["id"]
            result.append({
                "event_id": event["event_id"],
                "username": event["username"],
                "location": event["location"],
                "description": event["description"],
                "event_time": event["event_time"],
                "likes": event.get("likes", 0),
                "dislikes": event.get("dislikes", 0),
                "user_vote": "like" if current_user["id"] in event.get("liked_by", []) else 
                            "dislike" if current_user["id"] in event.get("disliked_by", []) else None,
                "is_owner": is_owner,
                "can_delete": is_owner or can_moderate,
                "created_at": event["created_at"].isoformat() if event.get("created_at") else None
            })
        
        return {"events": result}
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener eventos")


@router.post("/{event_id}/vote")
async def vote_event(
    event_id: str,
    request: VoteEventRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Vote on an event (like or dislike)."""
    try:
        if request.vote_type not in ["like", "dislike"]:
            raise HTTPException(status_code=400, detail="Tipo de voto inválido")
        
        # Find the event
        event = await events_collection.find_one({"event_id": event_id})
        if not event:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        
        user_id = current_user["id"]
        event_owner_id = event.get("user_id")
        liked_by = event.get("liked_by", [])
        disliked_by = event.get("disliked_by", [])
        likes = event.get("likes", 0)
        dislikes = event.get("dislikes", 0)
        
        # Track if this is a NEW like (not removing previous like or changing vote)
        was_liked = user_id in liked_by
        is_new_like = request.vote_type == "like" and not was_liked
        
        # Remove previous vote if exists
        if user_id in liked_by:
            liked_by.remove(user_id)
            likes -= 1
        if user_id in disliked_by:
            disliked_by.remove(user_id)
            dislikes -= 1
        
        # Add new vote
        if request.vote_type == "like":
            liked_by.append(user_id)
            likes += 1
        else:
            disliked_by.append(user_id)
            dislikes += 1
        
        # Update event
        await events_collection.update_one(
            {"event_id": event_id},
            {"$set": {
                "liked_by": liked_by,
                "disliked_by": disliked_by,
                "likes": likes,
                "dislikes": dislikes
            }}
        )
        
        # Award points to event owner for receiving a NEW like (not self-like)
        if is_new_like and event_owner_id and event_owner_id != user_id:
            await add_points(
                event_owner_id,
                "receive_like",
                POINTS_CONFIG["receive_like"],
                f"Like recibido en evento: {event.get('description', '')[:30]}"
            )
        
        return {
            "success": True,
            "likes": likes,
            "dislikes": dislikes,
            "user_vote": request.vote_type
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error voting event: {e}")
        raise HTTPException(status_code=500, detail="Error al votar")


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Delete an event (owner, moderator or admin can delete)."""
    try:
        event = await events_collection.find_one({"event_id": event_id})
        if not event:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        
        user_role = current_user.get("role", "user")
        is_owner = event["user_id"] == current_user["id"]
        can_delete = is_owner or user_role in ["admin", "moderator"]
        
        if not can_delete:
            raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este evento")
        
        await events_collection.delete_one({"event_id": event_id})
        
        return {"success": True, "message": "Evento eliminado"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        raise HTTPException(status_code=500, detail="Error al eliminar evento")
