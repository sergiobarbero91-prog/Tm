"""
Emergency alerts router for SOS functionality.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import uuid
import pytz

from shared import (
    emergency_alerts_collection,
    get_current_user_required,
    logger
)

router = APIRouter(prefix="/emergency", tags=["Emergency"])

MADRID_TZ = pytz.timezone('Europe/Madrid')

# Models
class EmergencyAlertRequest(BaseModel):
    alert_type: str  # 'companions' or 'companions_police'
    latitude: float
    longitude: float


@router.post("/alert")
async def create_emergency_alert(
    alert: EmergencyAlertRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Create an emergency alert to notify other users."""
    now = datetime.now(MADRID_TZ)
    user_id = current_user["id"]
    username = current_user.get("username", "Unknown")
    
    # Check if user already has an active alert
    existing_alert = await emergency_alerts_collection.find_one({
        "user_id": user_id,
        "is_active": True
    })
    
    if existing_alert:
        return {
            "message": "Ya tienes una alerta activa",
            "alert_id": existing_alert["alert_id"],
            "is_new": False
        }
    
    alert_id = str(uuid.uuid4())
    
    alert_doc = {
        "alert_id": alert_id,
        "user_id": user_id,
        "username": username,
        "alert_type": alert.alert_type,  # 'companions' or 'companions_police'
        "latitude": alert.latitude,
        "longitude": alert.longitude,
        "created_at": now,
        "is_active": True
    }
    
    await emergency_alerts_collection.insert_one(alert_doc)
    
    logger.info(f"Emergency alert created by {username}: {alert.alert_type} at ({alert.latitude}, {alert.longitude})")
    
    return {
        "message": "Alerta de emergencia enviada",
        "alert_id": alert_id,
        "is_new": True
    }


@router.post("/resolve/{alert_id}")
async def resolve_emergency_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Resolve/cancel an emergency alert."""
    user_id = current_user["id"]
    
    # Find the alert
    alert = await emergency_alerts_collection.find_one({
        "alert_id": alert_id,
        "user_id": user_id,
        "is_active": True
    })
    
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada o ya resuelta")
    
    # Mark as resolved
    await emergency_alerts_collection.update_one(
        {"alert_id": alert_id},
        {"$set": {"is_active": False, "resolved_at": datetime.now(MADRID_TZ)}}
    )
    
    logger.info(f"Emergency alert {alert_id} resolved by {current_user.get('username', 'Unknown')}")
    
    return {"message": "Alerta resuelta", "alert_id": alert_id}


@router.get("/alerts")
async def get_active_emergency_alerts(
    current_user: dict = Depends(get_current_user_required)
):
    """Get all active emergency alerts (for other users to see)."""
    user_id = current_user["id"]
    
    # Get all active alerts
    alerts = await emergency_alerts_collection.find({
        "is_active": True
    }).sort("created_at", -1).to_list(100)
    
    result = []
    for alert in alerts:
        # Convert datetime to string
        created_at = alert["created_at"]
        if created_at.tzinfo is None:
            created_at = MADRID_TZ.localize(created_at)
        
        result.append({
            "alert_id": alert["alert_id"],
            "user_id": alert["user_id"],
            "username": alert["username"],
            "alert_type": alert["alert_type"],
            "latitude": alert["latitude"],
            "longitude": alert["longitude"],
            "created_at": created_at.isoformat(),
            "is_own": alert["user_id"] == user_id  # Flag if this is user's own alert
        })
    
    return {"alerts": result}


@router.get("/my-alert")
async def get_my_active_alert(
    current_user: dict = Depends(get_current_user_required)
):
    """Get the current user's active alert if any."""
    user_id = current_user["id"]
    
    alert = await emergency_alerts_collection.find_one({
        "user_id": user_id,
        "is_active": True
    })
    
    if not alert:
        return {"has_active_alert": False, "alert": None}
    
    created_at = alert["created_at"]
    if created_at.tzinfo is None:
        created_at = MADRID_TZ.localize(created_at)
    
    return {
        "has_active_alert": True,
        "alert": {
            "alert_id": alert["alert_id"],
            "alert_type": alert["alert_type"],
            "latitude": alert["latitude"],
            "longitude": alert["longitude"],
            "created_at": created_at.isoformat()
        }
    }
