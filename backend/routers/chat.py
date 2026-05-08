"""
Chat router for multi-channel messaging system.
Includes chat abuse blocking system.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import uuid
import bleach
from slowapi import Limiter
from slowapi.util import get_remote_address

from shared import (
    chat_messages_collection,
    users_collection,
    get_current_user_required,
    logger
)

router = APIRouter(prefix="/chat", tags=["Chat"])
limiter = Limiter(key_func=get_remote_address)

# Blocking configuration - same pattern as alert fraud
CHAT_ABUSE_THRESHOLD = 60  # Seconds - not used for chat, immediate block
CHAT_PENALTIES = {
    5: 6,      # 1-5 abuses: 6 hours
    10: 12,    # 6-10 abuses: 12 hours
    20: 48,    # 11-20 abuses: 48 hours
    float('inf'): None  # 21+ abuses: permanent ban
}

# XSS prevention - sanitize all user input
def sanitize_message(text: str) -> str:
    """Sanitize user input to prevent XSS attacks."""
    # Allow no HTML tags - strip everything
    return bleach.clean(text, tags=[], strip=True)


def get_chat_penalty_hours(abuse_count: int) -> Optional[int]:
    """Get the penalty hours based on chat abuse count."""
    if abuse_count <= 5:
        return 6
    elif abuse_count <= 10:
        return 12
    elif abuse_count <= 20:
        return 48
    else:
        return None  # Permanent ban


async def check_chat_blocked(user_id: str) -> tuple[bool, Optional[str]]:
    """Check if user is blocked from sending chat messages."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        return False, None
    
    abuse_count = user.get("chat_abuse_count", 0)
    blocked_until = user.get("chat_blocked_until")
    
    # Check for permanent ban
    if abuse_count > 20:
        return True, "Has sido bloqueado permanentemente del chat debido a múltiples mensajes indebidos."
    
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
            
            return True, f"No puedes enviar mensajes durante {time_str} debido a mensajes indebidos previos."
    
    return False, None


async def apply_chat_abuse_penalty(user_id: str, message_content: str, blocked_by: str) -> dict:
    """Apply chat abuse penalty to a user."""
    user = await users_collection.find_one({"id": user_id})
    current_abuse_count = user.get("chat_abuse_count", 0) if user else 0
    new_abuse_count = current_abuse_count + 1
    
    penalty_hours = get_chat_penalty_hours(new_abuse_count)
    
    now = datetime.utcnow()
    update_data = {
        "chat_abuse_count": new_abuse_count,
        "last_chat_abuse_at": now,
        "last_chat_abuse_message": message_content[:200],  # Store snippet of offending message
        "last_chat_abuse_blocked_by": blocked_by
    }
    
    if penalty_hours is not None:
        blocked_until = now + timedelta(hours=penalty_hours)
        update_data["chat_blocked_until"] = blocked_until
    else:
        # Permanent ban
        update_data["chat_blocked_until"] = now + timedelta(days=36500)
    
    await users_collection.update_one(
        {"id": user_id},
        {"$set": update_data}
    )
    
    return {
        "abuse_count": new_abuse_count,
        "penalty_hours": penalty_hours,
        "is_permanent": penalty_hours is None
    }


# Models
class SendMessageRequest(BaseModel):
    message: str

class ChatMessage(BaseModel):
    id: str
    channel: str
    user_id: str
    username: str
    full_name: Optional[str]
    message: str
    created_at: datetime

# Channel configuration
VALID_CHANNELS = ["global", "avisos", "admin"]

def can_read_channel(channel: str, role: str) -> bool:
    """Check if user role can read from channel."""
    if channel == "global":
        return True
    elif channel == "avisos":
        return True  # Everyone can read avisos
    elif channel == "admin":
        return role == "admin"
    return False

def can_write_channel(channel: str, role: str) -> bool:
    """Check if user role can write to channel."""
    if channel == "global":
        return True  # Everyone can write to global
    elif channel == "avisos":
        return role in ["admin", "moderator"]  # Only mods and admins
    elif channel == "admin":
        return role == "admin"  # Only admins
    return False


@router.get("/{channel}/messages")
async def get_chat_messages(
    channel: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user_required)
):
    """Get messages from a chat channel."""
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Canal inválido")
    
    user_role = current_user.get("role", "user")
    
    if not can_read_channel(channel, user_role):
        raise HTTPException(status_code=403, detail="No tienes acceso a este canal")
    
    try:
        cursor = chat_messages_collection.find(
            {"channel": channel}
        ).sort("created_at", -1).limit(limit)
        
        messages = await cursor.to_list(limit)
        
        # Reverse to get chronological order
        messages.reverse()
        
        return {
            "channel": channel,
            "messages": [
                {
                    "id": msg["id"],
                    "user_id": msg["user_id"],
                    "username": msg["username"],
                    "full_name": msg.get("full_name"),
                    "message": msg["message"],
                    "created_at": msg["created_at"].isoformat()
                }
                for msg in messages
            ],
            "can_write": can_write_channel(channel, user_role)
        }
    except Exception as e:
        logger.error(f"Error getting chat messages: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener mensajes")


@router.post("/{channel}/messages")
@limiter.limit("30/minute")  # Rate limit: 30 messages per minute
async def send_chat_message(
    channel: str,
    request_body: SendMessageRequest,
    request: Request,
    current_user: dict = Depends(get_current_user_required)
):
    """Send a message to a chat channel."""
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Canal inválido")
    
    user_role = current_user.get("role", "user")
    
    if not can_write_channel(channel, user_role):
        raise HTTPException(status_code=403, detail="No tienes permiso para escribir en este canal")
    
    # Check if user is blocked from chat
    is_blocked, block_message = await check_chat_blocked(current_user["id"])
    if is_blocked:
        raise HTTPException(status_code=403, detail=block_message)
    
    if not request_body.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    # Sanitize message to prevent XSS
    sanitized_message = sanitize_message(request_body.message.strip()[:1000])
    
    try:
        message_doc = {
            "id": str(uuid.uuid4()),
            "channel": channel,
            "user_id": current_user["id"],
            "username": current_user["username"],
            "full_name": current_user.get("full_name"),
            "message": sanitized_message,  # Use sanitized message
            "created_at": datetime.utcnow()
        }
        
        await chat_messages_collection.insert_one(message_doc)
        
        return {
            "success": True,
            "message": {
                "id": message_doc["id"],
                "user_id": message_doc["user_id"],
                "username": message_doc["username"],
                "full_name": message_doc.get("full_name"),
                "message": message_doc["message"],
                "created_at": message_doc["created_at"].isoformat()
            }
        }
    except Exception as e:
        logger.error(f"Error sending chat message: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar mensaje")


@router.delete("/{channel}/messages/{message_id}")
async def delete_chat_message(
    channel: str,
    message_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Delete a chat message (moderators and admins can delete any message)."""
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail="Canal inválido")
    
    user_role = current_user.get("role", "user")
    
    # Check if user can access this channel
    if not can_read_channel(channel, user_role):
        raise HTTPException(status_code=403, detail="No tienes acceso a este canal")
    
    try:
        # Find the message
        message = await chat_messages_collection.find_one({
            "id": message_id,
            "channel": channel
        })
        
        if not message:
            raise HTTPException(status_code=404, detail="Mensaje no encontrado")
        
        # Check permissions: owner can delete their own, mods/admins can delete any
        is_owner = message["user_id"] == current_user["id"]
        is_mod_or_admin = user_role in ["admin", "moderator"]
        
        if not is_owner and not is_mod_or_admin:
            raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este mensaje")
        
        # Delete the message
        await chat_messages_collection.delete_one({"id": message_id})
        
        return {"success": True, "message": "Mensaje eliminado"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting chat message: {e}")
        raise HTTPException(status_code=500, detail="Error al eliminar mensaje")


@router.get("/channels")
async def get_available_channels(
    current_user: dict = Depends(get_current_user_required)
):
    """Get list of channels available to the user."""
    user_role = current_user.get("role", "user")
    
    channels = []
    
    # Global chat - available to everyone
    channels.append({
        "id": "global",
        "name": "Chat Global",
        "icon": "chatbubbles",
        "description": "Chat abierto para todos",
        "can_write": True
    })
    
    # Avisos - everyone can read, only mods/admins can write
    channels.append({
        "id": "avisos",
        "name": "Avisos",
        "icon": "megaphone",
        "description": "Avisos oficiales",
        "can_write": can_write_channel("avisos", user_role)
    })
    
    # Admin - only visible to admins
    if user_role == "admin":
        channels.append({
            "id": "admin",
            "name": "Admin",
            "icon": "shield",
            "description": "Chat de administradores",
            "can_write": True
        })
    
    return {"channels": channels}


# ============ CHAT MODERATION ENDPOINTS ============

class BlockUserRequest(BaseModel):
    message_id: str
    reason: Optional[str] = None


@router.post("/{channel}/messages/{message_id}/block-user")
async def block_user_for_message(
    channel: str,
    message_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Block a user for an inappropriate message (moderators and admins only)."""
    user_role = current_user.get("role", "user")
    
    # Only moderators and admins can block users
    if user_role not in ["admin", "moderator"]:
        raise HTTPException(
            status_code=403, 
            detail="Solo moderadores y administradores pueden bloquear usuarios"
        )
    
    # Find the message
    message = await chat_messages_collection.find_one({
        "id": message_id,
        "channel": channel
    })
    
    if not message:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    
    # Can't block yourself
    if message["user_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="No puedes bloquearte a ti mismo")
    
    # Get the user being blocked
    blocked_user = await users_collection.find_one({"id": message["user_id"]})
    if not blocked_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Can't block admins or moderators
    if blocked_user.get("role") in ["admin", "moderator"]:
        raise HTTPException(status_code=403, detail="No puedes bloquear a administradores o moderadores")
    
    # Apply penalty
    penalty_info = await apply_chat_abuse_penalty(
        user_id=message["user_id"],
        message_content=message["message"],
        blocked_by=current_user["username"]
    )
    
    # Delete the offending message
    await chat_messages_collection.delete_one({"id": message_id})
    
    # Build response message
    if penalty_info["is_permanent"]:
        penalty_msg = "El usuario ha sido bloqueado PERMANENTEMENTE del chat."
    else:
        penalty_msg = f"El usuario ha sido bloqueado del chat por {penalty_info['penalty_hours']} horas."
    
    return {
        "success": True,
        "message": f"Usuario @{blocked_user['username']} bloqueado por mensaje indebido.",
        "penalty_info": {
            "username": blocked_user["username"],
            "abuse_count": penalty_info["abuse_count"],
            "penalty_hours": penalty_info["penalty_hours"],
            "is_permanent": penalty_info["is_permanent"],
            "penalty_message": penalty_msg
        }
    }
