"""
License Alerts router for driver-to-driver messaging.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import uuid

from shared import (
    users_collection,
    license_alerts_collection,
    get_current_user_required,
    logger
)

router = APIRouter(prefix="/alerts/license", tags=["License Alerts"])

# Models
class CreateLicenseAlertRequest(BaseModel):
    target_license: str  # License number of recipient
    alert_type: str  # "lost_item" or "general"
    message: str

VALID_ALERT_TYPES = ["lost_item", "general"]


@router.get("/search")
async def search_licenses(
    q: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Search for users by license number for autocomplete."""
    if not q or len(q) < 1:
        return {"results": []}
    
    try:
        # Search for licenses that start with the query
        # Exclude current user
        cursor = users_collection.find({
            "license_number": {"$regex": f"^{q}", "$options": "i"},
            "id": {"$ne": current_user["id"]}
        }).limit(10)
        
        users = await cursor.to_list(10)
        
        results = [
            {
                "license_number": user["license_number"],
                "full_name": user.get("full_name") or user["username"],
                "username": user["username"]
            }
            for user in users
            if user.get("license_number")
        ]
        
        return {"results": results}
    except Exception as e:
        logger.error(f"Error searching licenses: {e}")
        return {"results": []}


@router.post("")
async def create_license_alert(
    request: CreateLicenseAlertRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Create an alert for another taxi driver by license number."""
    # Validate alert type
    if request.alert_type not in VALID_ALERT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de alerta inválido")
    
    # Validate message
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    # Check sender has a license number
    sender_license = current_user.get("license_number")
    if not sender_license:
        raise HTTPException(status_code=400, detail="Debes tener un número de licencia registrado para enviar alertas")
    
    # Find recipient by license number
    recipient = await users_collection.find_one({"license_number": request.target_license})
    if not recipient:
        raise HTTPException(status_code=404, detail="No se encontró ningún taxista con ese número de licencia")
    
    # Can't send alert to yourself
    if recipient["id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="No puedes enviarte alertas a ti mismo")
    
    try:
        alert_doc = {
            "id": str(uuid.uuid4()),
            "sender_id": current_user["id"],
            "sender_username": current_user["username"],
            "sender_full_name": current_user.get("full_name"),
            "sender_license": sender_license,
            "recipient_id": recipient["id"],
            "recipient_license": request.target_license,
            "alert_type": request.alert_type,
            "message": request.message.strip()[:500],
            "is_read": False,
            "created_at": datetime.utcnow()
        }
        
        await license_alerts_collection.insert_one(alert_doc)
        
        return {
            "success": True,
            "alert_id": alert_doc["id"],
            "message": "Alerta enviada correctamente"
        }
    except Exception as e:
        logger.error(f"Error creating license alert: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar alerta")


@router.get("/received")
async def get_received_alerts(
    current_user: dict = Depends(get_current_user_required)
):
    """Get alerts received by current user."""
    try:
        cursor = license_alerts_collection.find({
            "recipient_id": current_user["id"]
        }).sort("created_at", -1).limit(50)
        
        alerts = await cursor.to_list(50)
        
        # Count unread
        unread_count = sum(1 for a in alerts if not a.get("is_read", False))
        
        return {
            "alerts": [
                {
                    "id": alert["id"],
                    "sender_full_name": alert.get("sender_full_name") or alert["sender_username"],
                    "sender_license": alert["sender_license"],
                    "alert_type": alert["alert_type"],
                    "message": alert["message"],
                    "is_read": alert.get("is_read", False),
                    "created_at": alert["created_at"].isoformat()
                }
                for alert in alerts
            ],
            "unread_count": unread_count
        }
    except Exception as e:
        logger.error(f"Error getting received alerts: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener alertas")


@router.get("/unread-count")
async def get_unread_alerts_count(
    current_user: dict = Depends(get_current_user_required)
):
    """Get count of unread alerts for current user."""
    try:
        count = await license_alerts_collection.count_documents({
            "recipient_id": current_user["id"],
            "is_read": False
        })
        return {"unread_count": count}
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener conteo")


@router.put("/{alert_id}/read")
async def mark_alert_read(
    alert_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Mark an alert as read."""
    try:
        result = await license_alerts_collection.update_one(
            {"id": alert_id, "recipient_id": current_user["id"]},
            {"$set": {"is_read": True}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Alerta no encontrada")
        
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking alert read: {e}")
        raise HTTPException(status_code=500, detail="Error al actualizar alerta")


@router.put("/read-all")
async def mark_all_alerts_read(
    current_user: dict = Depends(get_current_user_required)
):
    """Mark all alerts as read for current user."""
    try:
        await license_alerts_collection.update_many(
            {"recipient_id": current_user["id"], "is_read": False},
            {"$set": {"is_read": True}}
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Error marking all alerts read: {e}")
        raise HTTPException(status_code=500, detail="Error al actualizar alertas")


@router.delete("/{alert_id}")
async def delete_license_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Delete an alert (recipient can delete their received alerts)."""
    try:
        result = await license_alerts_collection.delete_one({
            "id": alert_id,
            "recipient_id": current_user["id"]
        })
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Alerta no encontrada")
        
        return {"success": True, "message": "Alerta eliminada"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting alert: {e}")
        raise HTTPException(status_code=500, detail="Error al eliminar alerta")
