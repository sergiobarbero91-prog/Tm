"""
Radio walkie-talkie system with 10 channels.
Uses WebSockets for real-time audio communication.
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import Dict, List, Set, Optional
from datetime import datetime
from pydantic import BaseModel
import json
import asyncio
import base64

from shared import users_collection, get_current_user_required, logger

router = APIRouter(prefix="/radio", tags=["Radio"])

# Radio channel configuration
NUM_CHANNELS = 10
CHANNEL_NAMES = {
    1: "Canal 1 - General",
    2: "Canal 2 - Aeropuerto",
    3: "Canal 3 - Atocha",
    4: "Canal 4 - Chamartín",
    5: "Canal 5 - Centro",
    6: "Canal 6 - Norte",
    7: "Canal 7 - Sur",
    8: "Canal 8 - Este",
    9: "Canal 9 - Oeste",
    10: "Canal 10 - Emergencias"
}

# Connection manager for radio channels
class RadioConnectionManager:
    def __init__(self):
        # channel_id -> set of WebSocket connections
        self.active_connections: Dict[int, Dict[str, WebSocket]] = {i: {} for i in range(1, NUM_CHANNELS + 1)}
        # user_id -> channel_id (to track which channel each user is on)
        self.user_channels: Dict[str, int] = {}
        # user_id -> user info
        self.user_info: Dict[str, dict] = {}
        # channel_id -> currently transmitting user_id
        self.transmitting: Dict[int, Optional[str]] = {i: None for i in range(1, NUM_CHANNELS + 1)}
    
    async def connect(self, websocket: WebSocket, channel: int, user_id: str, user_info: dict):
        """Connect a user to a radio channel."""
        await websocket.accept()
        
        # Disconnect from previous channel if any
        if user_id in self.user_channels:
            old_channel = self.user_channels[user_id]
            if user_id in self.active_connections[old_channel]:
                del self.active_connections[old_channel][user_id]
                await self.broadcast_status(old_channel)
        
        # Connect to new channel
        self.active_connections[channel][user_id] = websocket
        self.user_channels[user_id] = channel
        self.user_info[user_id] = user_info
        
        # Notify channel about new user
        await self.broadcast_status(channel)
        
        logger.info(f"Radio: User {user_info.get('username')} connected to channel {channel}")
    
    def disconnect(self, user_id: str):
        """Disconnect a user from their current channel."""
        if user_id in self.user_channels:
            channel = self.user_channels[user_id]
            if user_id in self.active_connections[channel]:
                del self.active_connections[channel][user_id]
            
            # If user was transmitting, stop transmission
            if self.transmitting[channel] == user_id:
                self.transmitting[channel] = None
            
            del self.user_channels[user_id]
            if user_id in self.user_info:
                del self.user_info[user_id]
            
            # Schedule status broadcast
            asyncio.create_task(self.broadcast_status(channel))
            
            logger.info(f"Radio: User {user_id} disconnected from channel {channel}")
    
    async def broadcast_status(self, channel: int):
        """Broadcast channel status to all connected users."""
        users_in_channel = []
        for uid in self.active_connections[channel]:
            info = self.user_info.get(uid, {})
            users_in_channel.append({
                "user_id": uid,
                "username": info.get("username", "Unknown"),
                "full_name": info.get("full_name"),
                "is_transmitting": self.transmitting[channel] == uid
            })
        
        status_message = json.dumps({
            "type": "channel_status",
            "channel": channel,
            "channel_name": CHANNEL_NAMES.get(channel, f"Canal {channel}"),
            "users": users_in_channel,
            "user_count": len(users_in_channel),
            "transmitting_user": self.transmitting[channel]
        })
        
        for uid, ws in list(self.active_connections[channel].items()):
            try:
                await ws.send_text(status_message)
            except:
                pass
    
    async def start_transmission(self, channel: int, user_id: str) -> bool:
        """Start audio transmission if channel is free."""
        if self.transmitting[channel] is not None:
            return False  # Channel is busy
        
        self.transmitting[channel] = user_id
        await self.broadcast_status(channel)
        
        user_info = self.user_info.get(user_id, {})
        logger.info(f"Radio: {user_info.get('username')} started transmitting on channel {channel}")
        return True
    
    async def stop_transmission(self, channel: int, user_id: str):
        """Stop audio transmission."""
        if self.transmitting[channel] == user_id:
            self.transmitting[channel] = None
            await self.broadcast_status(channel)
            
            user_info = self.user_info.get(user_id, {})
            logger.info(f"Radio: {user_info.get('username')} stopped transmitting on channel {channel}")
    
    async def broadcast_audio(self, channel: int, user_id: str, audio_data: str, mime_type: str = None):
        """Broadcast audio data to all users in the channel except sender."""
        if self.transmitting[channel] != user_id:
            return  # User is not the current transmitter
        
        user_info = self.user_info.get(user_id, {})
        audio_message = json.dumps({
            "type": "audio",
            "channel": channel,
            "sender_id": user_id,
            "sender_name": user_info.get("full_name") or user_info.get("username", "Unknown"),
            "audio_data": audio_data,
            "mime_type": mime_type or "audio/mp4",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Radio: Broadcasting audio from {user_info.get('username')} to channel {channel}, size: {len(audio_data)}")
        
        for uid, ws in list(self.active_connections[channel].items()):
            if uid != user_id:  # Don't send back to sender
                try:
                    await ws.send_text(audio_message)
                except:
                    pass
    
    def get_channel_info(self, channel: int) -> dict:
        """Get information about a channel."""
        users_in_channel = []
        for uid in self.active_connections[channel]:
            info = self.user_info.get(uid, {})
            users_in_channel.append({
                "user_id": uid,
                "username": info.get("username", "Unknown"),
                "full_name": info.get("full_name"),
                "is_transmitting": self.transmitting[channel] == uid
            })
        
        return {
            "channel": channel,
            "channel_name": CHANNEL_NAMES.get(channel, f"Canal {channel}"),
            "users": users_in_channel,
            "user_count": len(users_in_channel),
            "is_busy": self.transmitting[channel] is not None,
            "transmitting_user": self.transmitting[channel]
        }
    
    def get_all_channels_info(self) -> List[dict]:
        """Get information about all channels."""
        return [self.get_channel_info(i) for i in range(1, NUM_CHANNELS + 1)]


# Global connection manager
radio_manager = RadioConnectionManager()


# REST endpoints
class ChannelInfo(BaseModel):
    channel: int
    channel_name: str
    user_count: int
    is_busy: bool


@router.get("/channels")
async def get_channels(current_user: dict = Depends(get_current_user_required)):
    """Get list of all radio channels with their status."""
    channels = []
    for i in range(1, NUM_CHANNELS + 1):
        info = radio_manager.get_channel_info(i)
        channels.append({
            "channel": i,
            "channel_name": CHANNEL_NAMES.get(i, f"Canal {i}"),
            "user_count": info["user_count"],
            "is_busy": info["is_busy"]
        })
    return {"channels": channels}


@router.get("/channels/{channel}")
async def get_channel_status(channel: int, current_user: dict = Depends(get_current_user_required)):
    """Get detailed status of a specific channel."""
    if channel < 1 or channel > NUM_CHANNELS:
        raise HTTPException(status_code=400, detail="Canal inválido")
    
    return radio_manager.get_channel_info(channel)


# WebSocket endpoint
@router.websocket("/ws/{channel}")
async def radio_websocket(websocket: WebSocket, channel: int, token: str):
    """WebSocket endpoint for radio channel communication."""
    if channel < 1 or channel > NUM_CHANNELS:
        await websocket.close(code=4000, reason="Canal inválido")
        return
    
    # Verify token and get user
    try:
        from shared import verify_token
        payload = verify_token(token)
        user_id = payload.get("sub")
        
        user = await users_collection.find_one({"id": user_id})
        if not user:
            await websocket.close(code=4001, reason="Usuario no encontrado")
            return
        
        user_info = {
            "user_id": user_id,
            "username": user["username"],
            "full_name": user.get("full_name")
        }
    except Exception as e:
        logger.error(f"Radio WebSocket auth error: {e}")
        await websocket.close(code=4001, reason="Token inválido")
        return
    
    # Connect to channel
    await radio_manager.connect(websocket, channel, user_id, user_info)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            msg_type = message.get("type")
            
            if msg_type == "start_transmission":
                success = await radio_manager.start_transmission(channel, user_id)
                await websocket.send_text(json.dumps({
                    "type": "transmission_status",
                    "success": success,
                    "message": "Transmitiendo..." if success else "Canal ocupado"
                }))
            
            elif msg_type == "stop_transmission":
                await radio_manager.stop_transmission(channel, user_id)
                await websocket.send_text(json.dumps({
                    "type": "transmission_status",
                    "success": True,
                    "message": "Transmisión finalizada"
                }))
            
            elif msg_type == "audio":
                audio_data = message.get("audio_data")
                mime_type = message.get("mime_type", "audio/mp4")
                if audio_data:
                    logger.info(f"Radio: Received audio from user, size: {len(audio_data)}, mime: {mime_type}")
                    await radio_manager.broadcast_audio(channel, user_id, audio_data, mime_type)
            
            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    
    except WebSocketDisconnect:
        radio_manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"Radio WebSocket error: {e}")
        radio_manager.disconnect(user_id)
