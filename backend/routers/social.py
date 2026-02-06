"""
Social Network Router - Friends, Direct Messages, and Group Chats
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
import uuid

from shared import (
    users_collection, get_current_user_required, logger, get_user_level
)
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collections
friend_requests_collection = db['friend_requests']
friends_collection = db['friends']
direct_messages_collection = db['direct_messages']
conversations_collection = db['conversations']
chat_groups_collection = db['chat_groups']
group_messages_collection = db['group_messages']
posts_collection = db['posts']
post_likes_collection = db['post_likes']
post_comments_collection = db['post_comments']

router = APIRouter(prefix="/social", tags=["Social"])

# Post categories
POST_CATEGORIES = [
    {"id": "news", "name": "📰 Noticias", "color": "#3B82F6"},
    {"id": "humor", "name": "😂 Humor", "color": "#F59E0B"},
    {"id": "tips", "name": "💡 Consejos", "color": "#10B981"},
    {"id": "stories", "name": "📖 Historias", "color": "#8B5CF6"},
    {"id": "events", "name": "🎉 Eventos", "color": "#EC4899"},
]

# ============== MODELS ==============

class ProfileVisibilityUpdate(BaseModel):
    is_public: bool

class FriendRequestCreate(BaseModel):
    to_user_id: str

class FriendRequestResponse(BaseModel):
    accepted: bool

class DirectMessageCreate(BaseModel):
    to_user_id: str
    content: str

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class GroupMemberAction(BaseModel):
    user_id: str

class GroupMessageCreate(BaseModel):
    content: str

# Post models
class PostCreate(BaseModel):
    content: str
    category: str  # hot_zone, warning, general, good_news
    visibility: str = "public"  # public or friends_only
    image_base64: Optional[str] = None
    location_name: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None

class CommentCreate(BaseModel):
    content: str

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    profile_photo: Optional[str] = None  # Base64
    cover_photo: Optional[str] = None    # Base64

# ============== PROFILE VISIBILITY ==============

@router.put("/profile/visibility")
async def update_profile_visibility(
    data: ProfileVisibilityUpdate,
    current_user: dict = Depends(get_current_user_required)
):
    """Update profile visibility (public/private)"""
    await users_collection.update_one(
        {"id": current_user["id"]},
        {"$set": {"is_profile_public": data.is_public}}
    )
    return {
        "success": True,
        "is_public": data.is_public,
        "message": "Perfil actualizado a " + ("público" if data.is_public else "privado")
    }

@router.get("/profile/visibility")
async def get_profile_visibility(current_user: dict = Depends(get_current_user_required)):
    """Get current profile visibility setting"""
    user = await users_collection.find_one({"id": current_user["id"]})
    return {
        "is_public": user.get("is_profile_public", True)  # Default to public
    }

@router.get("/profile/{user_id}")
async def get_user_profile(
    user_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get another user's profile (respects privacy settings)"""
    target_user = await users_collection.find_one({"id": user_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Check if they are friends
    are_friends = await friends_collection.find_one({
        "$or": [
            {"user_id": current_user["id"], "friend_id": user_id},
            {"user_id": user_id, "friend_id": current_user["id"]}
        ]
    })
    
    # Get levels
    current_user_points = current_user.get("total_points", 0)
    target_user_points = target_user.get("total_points", 0)
    current_level_info = get_user_level(current_user_points)
    target_level_info = get_user_level(target_user_points)
    
    is_public = target_user.get("is_profile_public", True)
    is_same_or_higher_level = current_user_points >= target_user_points
    can_view_full = is_public or are_friends or is_same_or_higher_level or current_user["id"] == user_id
    
    # Basic info always visible
    profile = {
        "id": target_user["id"],
        "username": target_user["username"],
        "full_name": target_user.get("full_name"),
        "level_name": target_level_info[0],
        "level_badge": target_level_info[1],
        "total_points": target_user_points,
        "is_friend": bool(are_friends),
        "is_own_profile": current_user["id"] == user_id,
        "can_view_full": can_view_full
    }
    
    # Add sensitive info only if allowed
    if can_view_full:
        profile.update({
            "phone": target_user.get("phone"),
            "license_number": target_user.get("license_number"),
            "shift": target_user.get("shift"),
            "role": target_user.get("role", "user"),
            "created_at": target_user.get("created_at").isoformat() if target_user.get("created_at") else None
        })
    
    return profile

# ============== FRIEND REQUESTS ==============

@router.post("/friends/request")
async def send_friend_request(
    data: FriendRequestCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Send a friend request to another user"""
    if data.to_user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="No puedes enviarte una solicitud a ti mismo")
    
    # Check if target user exists
    target_user = await users_collection.find_one({"id": data.to_user_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Check if already friends
    existing_friendship = await friends_collection.find_one({
        "$or": [
            {"user_id": current_user["id"], "friend_id": data.to_user_id},
            {"user_id": data.to_user_id, "friend_id": current_user["id"]}
        ]
    })
    if existing_friendship:
        raise HTTPException(status_code=400, detail="Ya sois amigos")
    
    # Check if request already exists
    existing_request = await friend_requests_collection.find_one({
        "$or": [
            {"from_user_id": current_user["id"], "to_user_id": data.to_user_id, "status": "pending"},
            {"from_user_id": data.to_user_id, "to_user_id": current_user["id"], "status": "pending"}
        ]
    })
    if existing_request:
        raise HTTPException(status_code=400, detail="Ya existe una solicitud pendiente")
    
    request_id = str(uuid.uuid4())
    await friend_requests_collection.insert_one({
        "id": request_id,
        "from_user_id": current_user["id"],
        "from_username": current_user["username"],
        "from_full_name": current_user.get("full_name"),
        "to_user_id": data.to_user_id,
        "to_username": target_user["username"],
        "status": "pending",
        "created_at": datetime.utcnow()
    })
    
    return {
        "success": True,
        "request_id": request_id,
        "message": f"Solicitud enviada a {target_user['username']}"
    }

@router.get("/friends/requests/pending")
async def get_pending_friend_requests(current_user: dict = Depends(get_current_user_required)):
    """Get pending friend requests received"""
    requests = await friend_requests_collection.find({
        "to_user_id": current_user["id"],
        "status": "pending"
    }).sort("created_at", -1).to_list(50)
    
    return {
        "requests": [
            {
                "id": r["id"],
                "from_user_id": r["from_user_id"],
                "from_username": r["from_username"],
                "from_full_name": r.get("from_full_name"),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
            }
            for r in requests
        ],
        "total": len(requests)
    }

@router.get("/friends/requests/sent")
async def get_sent_friend_requests(current_user: dict = Depends(get_current_user_required)):
    """Get friend requests sent by current user"""
    requests = await friend_requests_collection.find({
        "from_user_id": current_user["id"],
        "status": "pending"
    }).sort("created_at", -1).to_list(50)
    
    return {
        "requests": [
            {
                "id": r["id"],
                "to_user_id": r["to_user_id"],
                "to_username": r["to_username"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
            }
            for r in requests
        ]
    }

@router.put("/friends/requests/{request_id}")
async def respond_to_friend_request(
    request_id: str,
    response: FriendRequestResponse,
    current_user: dict = Depends(get_current_user_required)
):
    """Accept or reject a friend request"""
    request = await friend_requests_collection.find_one({
        "id": request_id,
        "to_user_id": current_user["id"],
        "status": "pending"
    })
    
    if not request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    new_status = "accepted" if response.accepted else "rejected"
    
    await friend_requests_collection.update_one(
        {"id": request_id},
        {"$set": {"status": new_status, "responded_at": datetime.utcnow()}}
    )
    
    if response.accepted:
        # Create friendship (bidirectional entry)
        friendship_id = str(uuid.uuid4())
        await friends_collection.insert_one({
            "id": friendship_id,
            "user_id": current_user["id"],
            "friend_id": request["from_user_id"],
            "created_at": datetime.utcnow()
        })
    
    return {
        "success": True,
        "message": "Solicitud aceptada" if response.accepted else "Solicitud rechazada"
    }

@router.delete("/friends/requests/{request_id}")
async def cancel_friend_request(
    request_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Cancel a sent friend request"""
    result = await friend_requests_collection.delete_one({
        "id": request_id,
        "from_user_id": current_user["id"],
        "status": "pending"
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    return {"success": True, "message": "Solicitud cancelada"}

# ============== FRIENDS LIST ==============

@router.get("/friends")
async def get_friends_list(current_user: dict = Depends(get_current_user_required)):
    """Get list of friends"""
    # Find all friendships where current user is involved
    friendships = await friends_collection.find({
        "$or": [
            {"user_id": current_user["id"]},
            {"friend_id": current_user["id"]}
        ]
    }).to_list(200)
    
    # Get friend IDs
    friend_ids = []
    for f in friendships:
        if f["user_id"] == current_user["id"]:
            friend_ids.append(f["friend_id"])
        else:
            friend_ids.append(f["user_id"])
    
    # Get friend details
    friends = []
    for friend_id in friend_ids:
        user = await users_collection.find_one({"id": friend_id})
        if user:
            level_info = get_user_level(user.get("total_points", 0))
            friends.append({
                "id": user["id"],
                "username": user["username"],
                "full_name": user.get("full_name"),
                "level_name": level_info[0],
                "level_badge": level_info[1],
                "total_points": user.get("total_points", 0)
            })
    
    return {"friends": friends, "total": len(friends)}

@router.delete("/friends/{friend_id}")
async def remove_friend(
    friend_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Remove a friend"""
    result = await friends_collection.delete_one({
        "$or": [
            {"user_id": current_user["id"], "friend_id": friend_id},
            {"user_id": friend_id, "friend_id": current_user["id"]}
        ]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Amistad no encontrada")
    
    return {"success": True, "message": "Amigo eliminado"}

# ============== DIRECT MESSAGES ==============

@router.post("/messages/direct")
async def send_direct_message(
    data: DirectMessageCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Send a direct message to another user"""
    if data.to_user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="No puedes enviarte mensajes a ti mismo")
    
    target_user = await users_collection.find_one({"id": data.to_user_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    # Get or create conversation
    conversation = await conversations_collection.find_one({
        "$or": [
            {"user1_id": current_user["id"], "user2_id": data.to_user_id},
            {"user1_id": data.to_user_id, "user2_id": current_user["id"]}
        ]
    })
    
    if not conversation:
        conversation_id = str(uuid.uuid4())
        conversation = {
            "id": conversation_id,
            "user1_id": current_user["id"],
            "user1_username": current_user["username"],
            "user2_id": data.to_user_id,
            "user2_username": target_user["username"],
            "created_at": datetime.utcnow(),
            "last_message_at": datetime.utcnow(),
            "last_message_preview": data.content[:50]
        }
        await conversations_collection.insert_one(conversation)
    else:
        conversation_id = conversation["id"]
        await conversations_collection.update_one(
            {"id": conversation_id},
            {"$set": {
                "last_message_at": datetime.utcnow(),
                "last_message_preview": data.content[:50]
            }}
        )
    
    # Create message
    message_id = str(uuid.uuid4())
    await direct_messages_collection.insert_one({
        "id": message_id,
        "conversation_id": conversation_id,
        "from_user_id": current_user["id"],
        "from_username": current_user["username"],
        "to_user_id": data.to_user_id,
        "content": data.content.strip(),
        "created_at": datetime.utcnow(),
        "read": False
    })
    
    return {
        "success": True,
        "message_id": message_id,
        "conversation_id": conversation_id
    }

@router.get("/messages/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user_required)):
    """Get list of direct message conversations"""
    conversations = await conversations_collection.find({
        "$or": [
            {"user1_id": current_user["id"]},
            {"user2_id": current_user["id"]}
        ]
    }).sort("last_message_at", -1).to_list(50)
    
    result = []
    for conv in conversations:
        # Get the other user
        other_user_id = conv["user2_id"] if conv["user1_id"] == current_user["id"] else conv["user1_id"]
        other_user = await users_collection.find_one({"id": other_user_id})
        
        # Count unread messages
        unread_count = await direct_messages_collection.count_documents({
            "conversation_id": conv["id"],
            "to_user_id": current_user["id"],
            "read": False
        })
        
        if other_user:
            level_info = get_user_level(other_user.get("total_points", 0))
            result.append({
                "id": conv["id"],
                "other_user_id": other_user_id,
                "other_username": other_user["username"],
                "other_full_name": other_user.get("full_name"),
                "other_level_badge": level_info[1],
                "last_message_preview": conv.get("last_message_preview"),
                "last_message_at": conv["last_message_at"].isoformat() if conv.get("last_message_at") else None,
                "unread_count": unread_count
            })
    
    return {"conversations": result}

@router.get("/messages/conversation/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get messages in a conversation"""
    # Verify user is part of conversation
    conversation = await conversations_collection.find_one({
        "id": conversation_id,
        "$or": [
            {"user1_id": current_user["id"]},
            {"user2_id": current_user["id"]}
        ]
    })
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    
    # Mark messages as read
    await direct_messages_collection.update_many(
        {"conversation_id": conversation_id, "to_user_id": current_user["id"]},
        {"$set": {"read": True}}
    )
    
    # Get messages
    messages = await direct_messages_collection.find({
        "conversation_id": conversation_id
    }).sort("created_at", 1).to_list(200)
    
    return {
        "messages": [
            {
                "id": m["id"],
                "from_user_id": m["from_user_id"],
                "from_username": m["from_username"],
                "content": m["content"],
                "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
                "is_mine": m["from_user_id"] == current_user["id"]
            }
            for m in messages
        ]
    }

@router.get("/messages/unread-count")
async def get_unread_messages_count(current_user: dict = Depends(get_current_user_required)):
    """Get total unread direct messages count"""
    count = await direct_messages_collection.count_documents({
        "to_user_id": current_user["id"],
        "read": False
    })
    return {"unread_count": count}

# ============== GROUP CHATS ==============

@router.post("/groups")
async def create_group(
    data: GroupCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Create a new chat group"""
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="El nombre del grupo no puede estar vacío")
    
    group_id = str(uuid.uuid4())
    await chat_groups_collection.insert_one({
        "id": group_id,
        "name": data.name.strip(),
        "description": data.description,
        "created_by": current_user["id"],
        "admin_ids": [current_user["id"]],
        "member_ids": [current_user["id"]],
        "created_at": datetime.utcnow(),
        "last_message_at": datetime.utcnow()
    })
    
    return {
        "success": True,
        "group_id": group_id,
        "message": f"Grupo '{data.name}' creado"
    }

@router.get("/groups")
async def get_my_groups(current_user: dict = Depends(get_current_user_required)):
    """Get groups the user is a member of"""
    groups = await chat_groups_collection.find({
        "member_ids": current_user["id"]
    }).sort("last_message_at", -1).to_list(50)
    
    result = []
    for g in groups:
        # Count unread messages in group
        last_read = g.get(f"last_read_{current_user['id']}")
        unread_query = {"group_id": g["id"]}
        if last_read:
            unread_query["created_at"] = {"$gt": last_read}
        unread_count = await group_messages_collection.count_documents(unread_query) if last_read else 0
        
        result.append({
            "id": g["id"],
            "name": g["name"],
            "description": g.get("description"),
            "member_count": len(g["member_ids"]),
            "is_admin": current_user["id"] in g.get("admin_ids", []),
            "last_message_at": g["last_message_at"].isoformat() if g.get("last_message_at") else None,
            "unread_count": unread_count
        })
    
    return {"groups": result}

@router.get("/groups/{group_id}")
async def get_group_details(
    group_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get group details including members"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "member_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    # Get member details
    members = []
    for member_id in group["member_ids"]:
        user = await users_collection.find_one({"id": member_id})
        if user:
            level_info = get_user_level(user.get("total_points", 0))
            members.append({
                "id": user["id"],
                "username": user["username"],
                "full_name": user.get("full_name"),
                "level_badge": level_info[1],
                "is_admin": member_id in group.get("admin_ids", [])
            })
    
    return {
        "id": group["id"],
        "name": group["name"],
        "description": group.get("description"),
        "created_by": group["created_by"],
        "is_admin": current_user["id"] in group.get("admin_ids", []),
        "members": members,
        "member_count": len(members)
    }

@router.put("/groups/{group_id}")
async def update_group(
    group_id: str,
    data: GroupUpdate,
    current_user: dict = Depends(get_current_user_required)
):
    """Update group details (admin only)"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "admin_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado o no tienes permisos")
    
    update_data = {}
    if data.name:
        update_data["name"] = data.name.strip()
    if data.description is not None:
        update_data["description"] = data.description
    
    if update_data:
        await chat_groups_collection.update_one(
            {"id": group_id},
            {"$set": update_data}
        )
    
    return {"success": True, "message": "Grupo actualizado"}

@router.post("/groups/{group_id}/members")
async def add_group_member(
    group_id: str,
    data: GroupMemberAction,
    current_user: dict = Depends(get_current_user_required)
):
    """Add a member to the group (admin only)"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "admin_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado o no tienes permisos")
    
    # Check if user exists
    target_user = await users_collection.find_one({"id": data.user_id})
    if not target_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Check if already a member
    if data.user_id in group["member_ids"]:
        raise HTTPException(status_code=400, detail="El usuario ya es miembro del grupo")
    
    await chat_groups_collection.update_one(
        {"id": group_id},
        {"$push": {"member_ids": data.user_id}}
    )
    
    return {"success": True, "message": f"{target_user['username']} añadido al grupo"}

@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_group_member(
    group_id: str,
    user_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Remove a member from the group (admin only, or self-leave)"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "member_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    is_admin = current_user["id"] in group.get("admin_ids", [])
    is_self = user_id == current_user["id"]
    
    if not is_admin and not is_self:
        raise HTTPException(status_code=403, detail="No tienes permisos para eliminar miembros")
    
    # Can't remove the last admin unless leaving
    if user_id in group.get("admin_ids", []) and len(group["admin_ids"]) == 1 and not is_self:
        raise HTTPException(status_code=400, detail="No puedes eliminar al único administrador")
    
    await chat_groups_collection.update_one(
        {"id": group_id},
        {
            "$pull": {
                "member_ids": user_id,
                "admin_ids": user_id
            }
        }
    )
    
    return {"success": True, "message": "Has salido del grupo" if is_self else "Miembro eliminado"}

@router.post("/groups/{group_id}/messages")
async def send_group_message(
    group_id: str,
    data: GroupMessageCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Send a message to a group"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "member_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    
    message_id = str(uuid.uuid4())
    await group_messages_collection.insert_one({
        "id": message_id,
        "group_id": group_id,
        "from_user_id": current_user["id"],
        "from_username": current_user["username"],
        "content": data.content.strip(),
        "created_at": datetime.utcnow()
    })
    
    # Update group last message time
    await chat_groups_collection.update_one(
        {"id": group_id},
        {"$set": {"last_message_at": datetime.utcnow()}}
    )
    
    return {"success": True, "message_id": message_id}

@router.get("/groups/{group_id}/messages")
async def get_group_messages(
    group_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get messages in a group"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "member_ids": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    # Update last read time
    await chat_groups_collection.update_one(
        {"id": group_id},
        {"$set": {f"last_read_{current_user['id']}": datetime.utcnow()}}
    )
    
    messages = await group_messages_collection.find({
        "group_id": group_id
    }).sort("created_at", 1).to_list(200)
    
    return {
        "messages": [
            {
                "id": m["id"],
                "from_user_id": m["from_user_id"],
                "from_username": m["from_username"],
                "content": m["content"],
                "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
                "is_mine": m["from_user_id"] == current_user["id"]
            }
            for m in messages
        ]
    }

@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Delete a group (creator/admin only)"""
    group = await chat_groups_collection.find_one({
        "id": group_id,
        "created_by": current_user["id"]
    })
    
    if not group:
        raise HTTPException(status_code=404, detail="Grupo no encontrado o no tienes permisos")
    
    # Delete all messages
    await group_messages_collection.delete_many({"group_id": group_id})
    # Delete group
    await chat_groups_collection.delete_one({"id": group_id})
    
    return {"success": True, "message": "Grupo eliminado"}

# ============== SEARCH USERS ==============

@router.get("/search/users")
async def search_users(
    q: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Search users by username or name"""
    if len(q) < 2:
        return {"users": []}
    
    users = await users_collection.find({
        "$and": [
            {"id": {"$ne": current_user["id"]}},
            {"$or": [
                {"username": {"$regex": q, "$options": "i"}},
                {"full_name": {"$regex": q, "$options": "i"}}
            ]}
        ]
    }).limit(20).to_list(20)
    
    result = []
    for user in users:
        level_info = get_user_level(user.get("total_points", 0))
        
        # Check if already friends
        friendship = await friends_collection.find_one({
            "$or": [
                {"user_id": current_user["id"], "friend_id": user["id"]},
                {"user_id": user["id"], "friend_id": current_user["id"]}
            ]
        })
        
        # Check if pending request
        pending_request = await friend_requests_collection.find_one({
            "$or": [
                {"from_user_id": current_user["id"], "to_user_id": user["id"], "status": "pending"},
                {"from_user_id": user["id"], "to_user_id": current_user["id"], "status": "pending"}
            ]
        })
        
        result.append({
            "id": user["id"],
            "username": user["username"],
            "full_name": user.get("full_name"),
            "level_name": level_info[0],
            "level_badge": level_info[1],
            "is_friend": bool(friendship),
            "has_pending_request": bool(pending_request)
        })
    
    return {"users": result}



# ============== POSTS / TABLÓN ENDPOINTS ==============

@router.get("/posts/categories")
async def get_post_categories():
    """Get available post categories"""
    return {"categories": POST_CATEGORIES}

@router.post("/posts")
async def create_post(post_data: PostCreate, current_user: dict = Depends(get_current_user_required)):
    """Create a new post"""
    # Validate category
    valid_categories = [c["id"] for c in POST_CATEGORIES]
    if post_data.category not in valid_categories:
        raise HTTPException(status_code=400, detail="Categoría inválida")
    
    # Validate visibility
    if post_data.visibility not in ["public", "friends_only"]:
        raise HTTPException(status_code=400, detail="Visibilidad inválida")
    
    post_id = str(uuid.uuid4())
    level_info = get_user_level(current_user.get("points", 0))
    
    post = {
        "id": post_id,
        "user_id": current_user["id"],
        "username": current_user["username"],
        "user_full_name": current_user.get("full_name"),
        "user_level_name": level_info[0],
        "user_level_badge": level_info[1],
        "content": post_data.content,
        "category": post_data.category,
        "visibility": post_data.visibility,
        "image_base64": post_data.image_base64,
        "location_name": post_data.location_name,
        "location_lat": post_data.location_lat,
        "location_lng": post_data.location_lng,
        "likes_count": 0,
        "comments_count": 0,
        "created_at": datetime.utcnow()
    }
    
    await posts_collection.insert_one(post)
    
    logger.info(f"User {current_user['username']} created post {post_id}")
    
    return {"id": post_id, "message": "Publicación creada correctamente"}

@router.get("/posts")
async def get_posts(
    page: int = 0, 
    limit: int = 20, 
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user_required)
):
    """Get posts feed"""
    # Get user's friends for filtering friends_only posts
    friendships = await friends_collection.find({
        "$or": [
            {"user_id_1": current_user["id"]},
            {"user_id_2": current_user["id"]}
        ]
    }).to_list(1000)
    
    friend_ids = set()
    for f in friendships:
        if f["user_id_1"] == current_user["id"]:
            friend_ids.add(f["user_id_2"])
        else:
            friend_ids.add(f["user_id_1"])
    
    # Build query: show public posts OR friends_only posts from friends OR own posts
    query = {
        "$or": [
            {"visibility": "public"},
            {"visibility": "friends_only", "user_id": {"$in": list(friend_ids)}},
            {"user_id": current_user["id"]}
        ]
    }
    
    if category:
        query["category"] = category
    
    posts = await posts_collection.find(query).sort("created_at", -1).skip(page * limit).limit(limit).to_list(limit)
    
    result = []
    for post in posts:
        # Check if current user liked this post
        liked = await post_likes_collection.find_one({
            "post_id": post["id"],
            "user_id": current_user["id"]
        })
        
        # Get category info
        category_info = next((c for c in POST_CATEGORIES if c["id"] == post["category"]), None)
        
        result.append({
            "id": post["id"],
            "user_id": post["user_id"],
            "username": post["username"],
            "user_full_name": post.get("user_full_name"),
            "user_level_name": post.get("user_level_name"),
            "user_level_badge": post.get("user_level_badge"),
            "content": post["content"],
            "category": post["category"],
            "category_name": category_info["name"] if category_info else "",
            "category_color": category_info["color"] if category_info else "#6366F1",
            "visibility": post["visibility"],
            "image_base64": post.get("image_base64"),
            "location_name": post.get("location_name"),
            "location_lat": post.get("location_lat"),
            "location_lng": post.get("location_lng"),
            "likes_count": post.get("likes_count", 0),
            "comments_count": post.get("comments_count", 0),
            "is_liked": bool(liked),
            "is_own": post["user_id"] == current_user["id"],
            "created_at": post["created_at"].isoformat() if post.get("created_at") else None
        })
    
    return {"posts": result}

@router.post("/posts/{post_id}/like")
async def toggle_like_post(post_id: str, current_user: dict = Depends(get_current_user_required)):
    """Like or unlike a post"""
    post = await posts_collection.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    # Check if already liked
    existing_like = await post_likes_collection.find_one({
        "post_id": post_id,
        "user_id": current_user["id"]
    })
    
    if existing_like:
        # Unlike
        await post_likes_collection.delete_one({"_id": existing_like["_id"]})
        await posts_collection.update_one(
            {"id": post_id},
            {"$inc": {"likes_count": -1}}
        )
        return {"liked": False, "message": "Like eliminado"}
    else:
        # Like
        await post_likes_collection.insert_one({
            "post_id": post_id,
            "user_id": current_user["id"],
            "created_at": datetime.utcnow()
        })
        await posts_collection.update_one(
            {"id": post_id},
            {"$inc": {"likes_count": 1}}
        )
        return {"liked": True, "message": "Like añadido"}

@router.get("/posts/{post_id}/comments")
async def get_post_comments(post_id: str, current_user: dict = Depends(get_current_user_required)):
    """Get comments for a post"""
    post = await posts_collection.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    comments = await post_comments_collection.find({"post_id": post_id}).sort("created_at", 1).to_list(100)
    
    result = []
    for comment in comments:
        result.append({
            "id": comment["id"],
            "user_id": comment["user_id"],
            "username": comment["username"],
            "user_level_badge": comment.get("user_level_badge"),
            "content": comment["content"],
            "is_own": comment["user_id"] == current_user["id"],
            "created_at": comment["created_at"].isoformat() if comment.get("created_at") else None
        })
    
    return {"comments": result}

@router.post("/posts/{post_id}/comments")
async def add_comment(post_id: str, comment_data: CommentCreate, current_user: dict = Depends(get_current_user_required)):
    """Add a comment to a post"""
    post = await posts_collection.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    comment_id = str(uuid.uuid4())
    level_info = get_user_level(current_user.get("points", 0))
    
    comment = {
        "id": comment_id,
        "post_id": post_id,
        "user_id": current_user["id"],
        "username": current_user["username"],
        "user_level_badge": level_info[1],
        "content": comment_data.content,
        "created_at": datetime.utcnow()
    }
    
    await post_comments_collection.insert_one(comment)
    await posts_collection.update_one(
        {"id": post_id},
        {"$inc": {"comments_count": 1}}
    )
    
    return {"id": comment_id, "message": "Comentario añadido"}

@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, current_user: dict = Depends(get_current_user_required)):
    """Delete own post"""
    post = await posts_collection.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    # Only owner or admin can delete
    if post["user_id"] != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar esta publicación")
    
    # Delete post and all related data
    await posts_collection.delete_one({"id": post_id})
    await post_likes_collection.delete_many({"post_id": post_id})
    await post_comments_collection.delete_many({"post_id": post_id})
    
    return {"message": "Publicación eliminada"}

@router.delete("/posts/{post_id}/comments/{comment_id}")
async def delete_comment(post_id: str, comment_id: str, current_user: dict = Depends(get_current_user_required)):
    """Delete own comment"""
    comment = await post_comments_collection.find_one({"id": comment_id, "post_id": post_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comentario no encontrado")
    
    # Only owner or admin can delete
    if comment["user_id"] != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este comentario")
    
    await post_comments_collection.delete_one({"id": comment_id})
    await posts_collection.update_one(
        {"id": post_id},
        {"$inc": {"comments_count": -1}}
    )
    
    return {"message": "Comentario eliminado"}

# ============== USER ACTIVITY ENDPOINTS ==============

@router.get("/profile/{user_id}/posts")
async def get_user_posts(user_id: str, current_user: dict = Depends(get_current_user_required)):
    """Get posts by a specific user"""
    # Check if user exists
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Check friendship for private posts
    is_friend = False
    is_own = user_id == current_user["id"]
    
    if not is_own:
        friendship = await friends_collection.find_one({
            "$or": [
                {"user_id_1": current_user["id"], "user_id_2": user_id},
                {"user_id_1": user_id, "user_id_2": current_user["id"]}
            ]
        })
        is_friend = bool(friendship)
    
    # Build query based on access
    if is_own:
        query = {"user_id": user_id}
    elif is_friend:
        query = {"user_id": user_id}  # Can see all posts if friends
    else:
        query = {"user_id": user_id, "visibility": "public"}
    
    posts = await posts_collection.find(query).sort("created_at", -1).limit(20).to_list(20)
    
    result = []
    for post in posts:
        category_info = next((c for c in POST_CATEGORIES if c["id"] == post["category"]), None)
        liked = await post_likes_collection.find_one({
            "post_id": post["id"],
            "user_id": current_user["id"]
        })
        
        result.append({
            "id": post["id"],
            "content": post["content"],
            "category": post["category"],
            "category_name": category_info["name"] if category_info else "",
            "category_color": category_info["color"] if category_info else "#6366F1",
            "visibility": post["visibility"],
            "image_base64": post.get("image_base64"),
            "location_name": post.get("location_name"),
            "likes_count": post.get("likes_count", 0),
            "comments_count": post.get("comments_count", 0),
            "is_liked": bool(liked),
            "created_at": post["created_at"].isoformat() if post.get("created_at") else None
        })
    
    return {"posts": result}

@router.get("/profile/{user_id}/activity")
async def get_user_activity(user_id: str, current_user: dict = Depends(get_current_user_required)):
    """Get taxi activity for a specific user"""
    # Check if user exists
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    # Check privacy settings and friendship
    is_own = user_id == current_user["id"]
    
    if not is_own:
        # Check profile privacy
        is_public = user.get("is_profile_public", True)
        if not is_public:
            friendship = await friends_collection.find_one({
                "$or": [
                    {"user_id_1": current_user["id"], "user_id_2": user_id},
                    {"user_id_1": user_id, "user_id_2": current_user["id"]}
                ]
            })
            if not friendship:
                return {"activity": [], "restricted": True}
    
    # Get checkins from the checkin collection
    checkins_collection = db['checkins']
    services_collection = db['services']
    
    activities = []
    
    # Get recent checkins (station waits)
    checkins = await checkins_collection.find({
        "user_id": user_id
    }).sort("created_at", -1).limit(10).to_list(10)
    
    for checkin in checkins:
        activities.append({
            "type": "checkin",
            "icon": "time-outline",
            "color": "#3B82F6",
            "title": f"Espera en {checkin.get('location_name', 'estación')}",
            "description": f"Tiempo estimado: {checkin.get('wait_time', 'N/A')} min",
            "location": checkin.get('location_name'),
            "created_at": checkin["created_at"].isoformat() if checkin.get("created_at") else None
        })
    
    # Get recent services (rides)
    services = await services_collection.find({
        "user_id": user_id
    }).sort("created_at", -1).limit(10).to_list(10)
    
    for service in services:
        distance = service.get('distance_km', 0)
        activities.append({
            "type": "service",
            "icon": "car-outline",
            "color": "#10B981",
            "title": f"Servicio completado",
            "description": f"Distancia: {distance:.1f} km" if distance else "Servicio realizado",
            "location": service.get('destination'),
            "created_at": service["created_at"].isoformat() if service.get("created_at") else None
        })
    
    # Sort by date
    activities.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    
    return {"activity": activities[:15], "restricted": False}
