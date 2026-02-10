"""
WhatsApp Bot Router - Controls the WhatsApp bot service
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import aiohttp
import os
import logging
from datetime import datetime
import asyncio

from shared import get_current_user, UserInDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# WhatsApp bot service URL
WHATSAPP_BOT_URL = os.environ.get("WHATSAPP_BOT_URL", "http://localhost:3001")

# ==================== Models ====================

class GroupInfo(BaseModel):
    id: str
    name: str
    participantsCount: int = 0

class SetGroupRequest(BaseModel):
    groupId: str

class SendMessageRequest(BaseModel):
    message: str
    groupId: Optional[str] = None

class BotStatus(BaseModel):
    isReady: bool
    isAuthenticated: bool
    hasQR: bool
    groupId: Optional[str]
    groupName: Optional[str]
    lastMessageSent: Optional[str]
    messagesCount: int
    error: Optional[str]

class ScheduleConfig(BaseModel):
    enabled: bool = True
    intervalMinutes: int = 60
    startHour: int = 6  # Start at 6 AM
    endHour: int = 23   # End at 11 PM

# ==================== Helper Functions ====================

async def call_bot_api(method: str, endpoint: str, data: dict = None) -> dict:
    """Call the WhatsApp bot API"""
    url = f"{WHATSAPP_BOT_URL}{endpoint}"
    
    try:
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    return await response.json()
            elif method == "POST":
                async with session.post(url, json=data, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"Error calling bot API: {e}")
        raise HTTPException(status_code=503, detail=f"Bot service unavailable: {str(e)}")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Bot service timeout")

# ==================== Endpoints ====================

@router.get("/status")
async def get_bot_status(current_user: UserInDB = Depends(get_current_user)):
    """Get WhatsApp bot status"""
    try:
        result = await call_bot_api("GET", "/status")
        return result
    except HTTPException:
        return {
            "success": False,
            "data": {
                "isReady": False,
                "isAuthenticated": False,
                "hasQR": False,
                "groupId": None,
                "groupName": None,
                "lastMessageSent": None,
                "messagesCount": 0,
                "error": "Bot service not running"
            }
        }

@router.get("/qr")
async def get_qr_code(current_user: UserInDB = Depends(get_current_user)):
    """Get QR code for WhatsApp authentication"""
    # Only admin can get QR code
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden autenticar el bot")
    
    result = await call_bot_api("GET", "/qr")
    return result

@router.get("/groups")
async def list_groups(current_user: UserInDB = Depends(get_current_user)):
    """List available WhatsApp groups"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden ver los grupos")
    
    result = await call_bot_api("GET", "/groups")
    return result

@router.post("/set-group")
async def set_target_group(
    request: SetGroupRequest,
    current_user: UserInDB = Depends(get_current_user)
):
    """Set the target group for messages"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden configurar el grupo")
    
    result = await call_bot_api("POST", "/set-group", {"groupId": request.groupId})
    return result

@router.post("/send")
async def send_message(
    request: SendMessageRequest,
    current_user: UserInDB = Depends(get_current_user)
):
    """Send a custom message to the configured group"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden enviar mensajes")
    
    result = await call_bot_api("POST", "/send", {
        "message": request.message,
        "groupId": request.groupId
    })
    return result

@router.post("/send-hourly-update")
async def trigger_hourly_update(current_user: UserInDB = Depends(get_current_user)):
    """Manually trigger an hourly update"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden enviar actualizaciones")
    
    result = await call_bot_api("POST", "/send-hourly-update")
    return result

@router.post("/logout")
async def logout_bot(current_user: UserInDB = Depends(get_current_user)):
    """Logout from WhatsApp and clear session"""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden cerrar sesión")
    
    result = await call_bot_api("POST", "/logout")
    return result

@router.get("/health")
async def bot_health():
    """Check if bot service is running (no auth required)"""
    try:
        result = await call_bot_api("GET", "/health")
        return {"success": True, "bot_status": result}
    except HTTPException as e:
        return {"success": False, "error": str(e.detail)}
