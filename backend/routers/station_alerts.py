"""
Station alerts router for "sin taxis" and "barandilla" alerts.
Includes fraud detection and user blocking system.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import pytz

from shared import (
    station_alerts_collection,
    users_collection,
    get_current_user_required
)

router = APIRouter(prefix="/station-alerts", tags=["Station Alerts"])

MADRID_TZ = pytz.timezone('Europe/Madrid')
ALERT_DURATION_MINUTES = 5  # Alerts expire after 5 minutes
FRAUD_THRESHOLD_SECONDS = 60  # If cancelled within 60 seconds by another user, it's fraud

# Fraud penalty durations
FRAUD_PENALTIES = {
    5: 6,      # 1-5 frauds: 6 hours
    10: 12,    # 6-10 frauds: 12 hours
    20: 48,    # 11-20 frauds: 48 hours
    float('inf'): None  # 21+ frauds: permanent ban
}


def get_penalty_hours(fraud_count: int) -> Optional[int]:
    """Get the penalty hours based on fraud count."""
    if fraud_count <= 5:
        return 6
    elif fraud_count <= 10:
        return 12
    elif fraud_count <= 20:
        return 48
    else:
        return None  # Permanent ban


async def check_user_blocked(user_id: str) -> tuple[bool, Optional[str]]:
    """Check if user is blocked from creating alerts. Returns (is_blocked, message)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        return False, None
    
    fraud_count = user.get("alert_fraud_count", 0)
    blocked_until = user.get("alert_blocked_until")
    
    # Check for permanent ban
    if fraud_count > 20:
        return True, "Has sido bloqueado permanentemente para enviar avisos debido a múltiples reportes fraudulentos."
    
    # Check for temporary block
    if blocked_until:
        now = datetime.utcnow()
        if isinstance(blocked_until, str):
            blocked_until = datetime.fromisoformat(blocked_until.replace('Z', '+00:00'))
        
        if now < blocked_until:
            remaining = blocked_until - now
            hours_remaining = int(remaining.total_seconds() / 3600)
            mins_remaining = int((remaining.total_seconds() % 3600) / 60)
            
            if hours_remaining > 0:
                time_str = f"{hours_remaining}h {mins_remaining}min"
            else:
                time_str = f"{mins_remaining} minutos"
            
            return True, f"No puedes enviar avisos durante {time_str} debido a avisos incorrectos previos."
    
    return False, None


async def apply_fraud_penalty(reporter_user_id: str) -> dict:
    """Apply fraud penalty to a user. Returns info about the penalty."""
    # Get current fraud count
    user = await users_collection.find_one({"id": reporter_user_id})
    current_fraud_count = user.get("alert_fraud_count", 0) if user else 0
    new_fraud_count = current_fraud_count + 1
    
    # Calculate penalty
    penalty_hours = get_penalty_hours(new_fraud_count)
    
    now = datetime.utcnow()
    update_data = {
        "alert_fraud_count": new_fraud_count,
        "last_fraud_at": now
    }
    
    if penalty_hours is not None:
        blocked_until = now + timedelta(hours=penalty_hours)
        update_data["alert_blocked_until"] = blocked_until
    else:
        # Permanent ban - set to far future
        update_data["alert_blocked_until"] = now + timedelta(days=36500)  # ~100 years
    
    await users_collection.update_one(
        {"id": reporter_user_id},
        {"$set": update_data}
    )
    
    return {
        "fraud_count": new_fraud_count,
        "penalty_hours": penalty_hours,
        "is_permanent": penalty_hours is None
    }


class StationAlertCreate(BaseModel):
    location_type: str  # "station" or "terminal"
    location_name: str  # "atocha", "chamartin", "T1", "T2", "T4", "T4S", "T123"
    alert_type: str  # "sin_taxis" or "barandilla"


class StationAlertResponse(BaseModel):
    id: str
    location_type: str
    location_name: str
    alert_type: str
    reported_by: str
    reported_by_name: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    seconds_ago: int
    is_active: bool


class ActiveAlertsResponse(BaseModel):
    alerts: List[StationAlertResponse]
    stations_with_alerts: List[str]
    terminals_with_alerts: List[str]


@router.post("/report", response_model=StationAlertResponse)
async def report_station_alert(
    alert_data: StationAlertCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Report a 'sin taxis' or 'barandilla' alert for a station or terminal."""
    
    # Validate location_type
    if alert_data.location_type not in ["station", "terminal"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="location_type debe ser 'station' o 'terminal'"
        )
    
    # Validate alert_type
    if alert_data.alert_type not in ["sin_taxis", "barandilla"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="alert_type debe ser 'sin_taxis' o 'barandilla'"
        )
    
    # Validate location_name based on type
    valid_stations = ["atocha", "chamartin"]
    valid_terminals = ["T1", "T2", "T4", "T4S", "T123"]
    
    if alert_data.location_type == "station" and alert_data.location_name.lower() not in valid_stations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estación inválida. Debe ser: {', '.join(valid_stations)}"
        )
    
    if alert_data.location_type == "terminal" and alert_data.location_name not in valid_terminals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Terminal inválida. Debe ser: {', '.join(valid_terminals)}"
        )
    
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=ALERT_DURATION_MINUTES)
    
    # Check if there's already an active alert of the same type for this location
    existing = await station_alerts_collection.find_one({
        "location_type": alert_data.location_type,
        "location_name": alert_data.location_name.lower() if alert_data.location_type == "station" else alert_data.location_name,
        "alert_type": alert_data.alert_type,
        "expires_at": {"$gt": now}
    })
    
    if existing:
        # Update the existing alert to extend its duration
        await station_alerts_collection.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "created_at": now,
                    "expires_at": expires_at,
                    "reported_by": current_user["id"],
                    "reported_by_name": current_user.get("full_name") or current_user["username"]
                }
            }
        )
        alert_id = str(existing["_id"])
    else:
        # Create new alert
        import uuid
        alert_id = str(uuid.uuid4())
        new_alert = {
            "id": alert_id,
            "location_type": alert_data.location_type,
            "location_name": alert_data.location_name.lower() if alert_data.location_type == "station" else alert_data.location_name,
            "alert_type": alert_data.alert_type,
            "reported_by": current_user["id"],
            "reported_by_name": current_user.get("full_name") or current_user["username"],
            "created_at": now,
            "expires_at": expires_at
        }
        await station_alerts_collection.insert_one(new_alert)
    
    return StationAlertResponse(
        id=alert_id,
        location_type=alert_data.location_type,
        location_name=alert_data.location_name.lower() if alert_data.location_type == "station" else alert_data.location_name,
        alert_type=alert_data.alert_type,
        reported_by=current_user["id"],
        reported_by_name=current_user.get("full_name") or current_user["username"],
        created_at=now,
        expires_at=expires_at,
        seconds_ago=0,
        is_active=True
    )


@router.get("/active", response_model=ActiveAlertsResponse)
async def get_active_alerts():
    """Get all active station/terminal alerts (not expired)."""
    now = datetime.utcnow()
    
    # Get all non-expired alerts
    alerts_cursor = station_alerts_collection.find({
        "expires_at": {"$gt": now}
    }).sort("created_at", -1)
    
    alerts = await alerts_cursor.to_list(100)
    
    stations_with_alerts = set()
    terminals_with_alerts = set()
    
    response_alerts = []
    for alert in alerts:
        seconds_ago = int((now - alert["created_at"]).total_seconds())
        
        response_alerts.append(StationAlertResponse(
            id=alert.get("id", str(alert["_id"])),
            location_type=alert["location_type"],
            location_name=alert["location_name"],
            alert_type=alert["alert_type"],
            reported_by=alert["reported_by"],
            reported_by_name=alert.get("reported_by_name"),
            created_at=alert["created_at"],
            expires_at=alert["expires_at"],
            seconds_ago=seconds_ago,
            is_active=True
        ))
        
        if alert["location_type"] == "station":
            stations_with_alerts.add(alert["location_name"])
        else:
            terminals_with_alerts.add(alert["location_name"])
    
    return ActiveAlertsResponse(
        alerts=response_alerts,
        stations_with_alerts=list(stations_with_alerts),
        terminals_with_alerts=list(terminals_with_alerts)
    )


@router.delete("/{alert_id}")
async def cancel_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Cancel an alert. The original reporter cannot cancel within the first minute."""
    alert = await station_alerts_collection.find_one({"id": alert_id})
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada"
        )
    
    now = datetime.utcnow()
    seconds_since_created = int((now - alert["created_at"]).total_seconds())
    
    # If the user is the one who reported the alert and less than 1 minute has passed, block
    if alert["reported_by"] == current_user["id"] and seconds_since_created < 60:
        remaining_seconds = 60 - seconds_since_created
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Debes esperar {remaining_seconds} segundos para cerrar tu propia alerta"
        )
    
    await station_alerts_collection.delete_one({"id": alert_id})
    
    return {"message": "Alerta cancelada correctamente"}


class CancelAlertByLocationRequest(BaseModel):
    location_type: str  # "station" or "terminal"
    location_name: str  # "atocha", "chamartin", "T1", etc.
    alert_type: str  # "sin_taxis" or "barandilla"


@router.post("/cancel-by-location")
async def cancel_alert_by_location(
    data: CancelAlertByLocationRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Cancel an alert by location. The original reporter cannot cancel within the first minute."""
    now = datetime.utcnow()
    
    location_name = data.location_name.lower() if data.location_type == "station" else data.location_name
    
    # Find the active alert
    alert = await station_alerts_collection.find_one({
        "location_type": data.location_type,
        "location_name": location_name,
        "alert_type": data.alert_type,
        "expires_at": {"$gt": now}
    })
    
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alerta no encontrada"
        )
    
    seconds_since_created = int((now - alert["created_at"]).total_seconds())
    
    # If the user is the one who reported the alert and less than 1 minute has passed, block
    if alert["reported_by"] == current_user["id"] and seconds_since_created < 60:
        remaining_seconds = 60 - seconds_since_created
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Debes esperar {remaining_seconds} segundos para cerrar tu propia alerta"
        )
    
    await station_alerts_collection.delete_one({"_id": alert["_id"]})
    
    return {"message": "Alerta cancelada correctamente"}
