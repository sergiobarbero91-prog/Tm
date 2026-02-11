"""
WhatsApp Bot Router - Controls the WhatsApp bot service
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import aiohttp
import os
import logging
from datetime import datetime
import asyncio

from shared import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# WhatsApp bot service URL
WHATSAPP_BOT_URL = os.environ.get("WHATSAPP_BOT_URL", "http://localhost:3001")

# Monitor configuration
MONITOR_ENABLED = os.environ.get("WHATSAPP_MONITOR_ENABLED", "true").lower() == "true"
MONITOR_INTERVAL_SECONDS = int(os.environ.get("WHATSAPP_MONITOR_INTERVAL", "300"))  # 5 minutes
MAX_RESTART_ATTEMPTS = int(os.environ.get("WHATSAPP_MAX_RESTART_ATTEMPTS", "3"))

# Monitor state
monitor_state = {
    "last_check": None,
    "last_status": None,
    "restart_attempts": 0,
    "last_restart": None,
    "errors": []
}

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
async def get_bot_status(current_user: dict = Depends(get_current_user)):
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
async def get_qr_code(current_user: dict = Depends(get_current_user)):
    """Get QR code for WhatsApp authentication"""
    # Only admin can get QR code
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden autenticar el bot")
    
    result = await call_bot_api("GET", "/qr")
    return result

@router.get("/groups")
async def list_groups(current_user: dict = Depends(get_current_user)):
    """List available WhatsApp groups"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden ver los grupos")
    
    result = await call_bot_api("GET", "/groups")
    return result

@router.post("/set-group")
async def set_target_group(
    request: SetGroupRequest,
    current_user: dict = Depends(get_current_user)
):
    """Set the target group for messages"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden configurar el grupo")
    
    result = await call_bot_api("POST", "/set-group", {"groupId": request.groupId})
    return result

@router.post("/send")
async def send_message(
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """Send a custom message to the configured group"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden enviar mensajes")
    
    result = await call_bot_api("POST", "/send", {
        "message": request.message,
        "groupId": request.groupId
    })
    return result

@router.post("/send-hourly-update")
async def trigger_hourly_update(current_user: dict = Depends(get_current_user)):
    """Manually trigger an hourly update"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden enviar actualizaciones")
    
    result = await call_bot_api("POST", "/send-hourly-update")
    return result

@router.post("/logout")
async def logout_bot(current_user: dict = Depends(get_current_user)):
    """Logout from WhatsApp and clear session"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden cerrar sesión")
    
    result = await call_bot_api("POST", "/logout")
    return result


@router.post("/restart")
async def restart_bot(current_user: dict = Depends(get_current_user)):
    """Restart the WhatsApp bot client"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden reiniciar el bot")
    
    try:
        result = await call_bot_api("POST", "/restart")
        return result
    except HTTPException as e:
        # If bot is not responding, return a helpful message
        return {
            "success": False,
            "message": "El bot no responde. Puede que necesite reiniciarse manualmente en el servidor.",
            "error": str(e.detail)
        }


@router.get("/health")
async def bot_health():
    """Check if bot service is running (no auth required)"""
    try:
        result = await call_bot_api("GET", "/health")
        return {"success": True, "bot_status": result}
    except HTTPException as e:
        return {"success": False, "error": str(e.detail)}


# ==================== Bot Monitor ====================

async def check_bot_health_internal() -> dict:
    """Internal function to check bot health without raising exceptions"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{WHATSAPP_BOT_URL}/status", 
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "reachable": True,
                        "status": data.get("data", {}),
                        "error": None
                    }
                else:
                    return {
                        "reachable": False,
                        "status": None,
                        "error": f"HTTP {response.status}"
                    }
    except Exception as e:
        return {
            "reachable": False,
            "status": None,
            "error": str(e)
        }


async def restart_bot_internal() -> bool:
    """Internal function to restart the bot"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WHATSAPP_BOT_URL}/restart",
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get("success", False)
                return False
    except Exception as e:
        logger.error(f"[Bot Monitor] Error restarting bot: {e}")
        return False


async def bot_monitor_task():
    """Background task that monitors the bot and restarts it if needed"""
    global monitor_state
    
    logger.info("[Bot Monitor] Monitor task started")
    
    while True:
        try:
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
            
            if not MONITOR_ENABLED:
                continue
            
            # Check bot health
            health = await check_bot_health_internal()
            monitor_state["last_check"] = datetime.now().isoformat()
            monitor_state["last_status"] = health
            
            # Determine if bot needs restart
            needs_restart = False
            reason = ""
            
            if not health["reachable"]:
                needs_restart = True
                reason = f"Bot not reachable: {health['error']}"
            elif health["status"]:
                status = health["status"]
                if not status.get("isReady", False):
                    needs_restart = True
                    reason = "Bot not ready"
                elif not status.get("isAuthenticated", False):
                    # Don't restart if just not authenticated - needs QR scan
                    logger.warning("[Bot Monitor] Bot not authenticated - needs QR scan")
            
            if needs_restart:
                logger.warning(f"[Bot Monitor] Bot needs restart: {reason}")
                
                # Check if we've exceeded max restart attempts
                if monitor_state["restart_attempts"] >= MAX_RESTART_ATTEMPTS:
                    logger.error("[Bot Monitor] Max restart attempts exceeded. Manual intervention required.")
                    monitor_state["errors"].append({
                        "time": datetime.now().isoformat(),
                        "error": "Max restart attempts exceeded"
                    })
                    # Reset counter after some time (1 hour)
                    if monitor_state["last_restart"]:
                        last_restart = datetime.fromisoformat(monitor_state["last_restart"])
                        if (datetime.now() - last_restart).total_seconds() > 3600:
                            monitor_state["restart_attempts"] = 0
                            logger.info("[Bot Monitor] Reset restart counter after 1 hour")
                    continue
                
                # Attempt restart
                logger.info("[Bot Monitor] Attempting to restart bot...")
                success = await restart_bot_internal()
                
                if success:
                    logger.info("[Bot Monitor] Bot restart initiated successfully")
                    monitor_state["restart_attempts"] += 1
                    monitor_state["last_restart"] = datetime.now().isoformat()
                    # Wait a bit for bot to initialize
                    await asyncio.sleep(30)
                else:
                    logger.error("[Bot Monitor] Failed to restart bot")
                    monitor_state["errors"].append({
                        "time": datetime.now().isoformat(),
                        "error": f"Restart failed: {reason}"
                    })
            else:
                # Bot is healthy, reset restart counter
                if monitor_state["restart_attempts"] > 0:
                    logger.info("[Bot Monitor] Bot is healthy, resetting restart counter")
                    monitor_state["restart_attempts"] = 0
                    
        except Exception as e:
            logger.error(f"[Bot Monitor] Error in monitor task: {e}")
            monitor_state["errors"].append({
                "time": datetime.now().isoformat(),
                "error": str(e)
            })
    
    # Keep only last 10 errors
    monitor_state["errors"] = monitor_state["errors"][-10:]


@router.get("/monitor/status")
async def get_monitor_status(current_user: dict = Depends(get_current_user)):
    """Get the bot monitor status"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden ver el estado del monitor")
    
    return {
        "success": True,
        "monitor_enabled": MONITOR_ENABLED,
        "check_interval_seconds": MONITOR_INTERVAL_SECONDS,
        "max_restart_attempts": MAX_RESTART_ATTEMPTS,
        "state": monitor_state
    }


@router.post("/monitor/reset")
async def reset_monitor(current_user: dict = Depends(get_current_user)):
    """Reset the monitor state (clear errors and restart counter)"""
    global monitor_state
    
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden resetear el monitor")
    
    monitor_state = {
        "last_check": None,
        "last_status": None,
        "restart_attempts": 0,
        "last_restart": None,
        "errors": []
    }
    
    return {"success": True, "message": "Monitor state reset"}


def start_bot_monitor():
    """Start the bot monitor background task"""
    if MONITOR_ENABLED:
        asyncio.create_task(bot_monitor_task())
        logger.info(f"[Bot Monitor] Started with {MONITOR_INTERVAL_SECONDS}s interval")
    else:
        logger.info("[Bot Monitor] Disabled via configuration")
