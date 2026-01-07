"""
Admin router for user management (admin only).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import uuid
import re

from shared import (
    users_collection,
    UserCreate, UserUpdate, PasswordChange, UserResponse,
    get_admin_user, get_password_hash
)

router = APIRouter(prefix="/admin", tags=["Admin"])


class UserStats(BaseModel):
    total_users: int
    active_last_month: int
    online_now: int


class UserSearchResult(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    role: str
    preferred_shift: str = "all"
    created_at: datetime
    last_seen: Optional[datetime] = None
    is_online: bool = False


@router.get("/stats", response_model=UserStats)
async def get_user_stats(admin: dict = Depends(get_admin_user)):
    """Get user statistics (admin only)."""
    now = datetime.utcnow()
    one_month_ago = now - timedelta(days=30)
    five_minutes_ago = now - timedelta(minutes=5)
    
    # Total users
    total_users = await users_collection.count_documents({})
    
    # Active last month (users who logged in or were seen in the last 30 days)
    active_last_month = await users_collection.count_documents({
        "$or": [
            {"last_seen": {"$gte": one_month_ago}},
            {"last_login": {"$gte": one_month_ago}}
        ]
    })
    
    # Online now (seen in the last 5 minutes)
    online_now = await users_collection.count_documents({
        "last_seen": {"$gte": five_minutes_ago}
    })
    
    return UserStats(
        total_users=total_users,
        active_last_month=active_last_month,
        online_now=online_now
    )


@router.get("/search", response_model=List[UserSearchResult])
async def search_users(
    q: str = Query(..., min_length=1, description="Search query (username, name, or license)"),
    admin: dict = Depends(get_admin_user)
):
    """Search users by username, full name, or license number (admin only)."""
    now = datetime.utcnow()
    five_minutes_ago = now - timedelta(minutes=5)
    
    # Create case-insensitive regex pattern
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    
    # Search in multiple fields
    users = await users_collection.find({
        "$or": [
            {"username": {"$regex": pattern}},
            {"full_name": {"$regex": pattern}},
            {"license_number": {"$regex": pattern}}
        ]
    }).limit(50).to_list(50)
    
    results = []
    for u in users:
        last_seen = u.get("last_seen")
        is_online = last_seen and last_seen >= five_minutes_ago if last_seen else False
        
        results.append(UserSearchResult(
            id=u["id"],
            username=u["username"],
            full_name=u.get("full_name"),
            license_number=u.get("license_number"),
            phone=u.get("phone"),
            role=u.get("role", "user"),
            preferred_shift=u.get("preferred_shift", "all"),
            created_at=u["created_at"],
            last_seen=last_seen,
            is_online=is_online
        ))
    
    return results


@router.get("/users", response_model=List[UserSearchResult])
async def list_users(admin: dict = Depends(get_admin_user)):
    """List all users (admin only)."""
    now = datetime.utcnow()
    five_minutes_ago = now - timedelta(minutes=5)
    
    users = await users_collection.find().to_list(1000)
    results = []
    for u in users:
        last_seen = u.get("last_seen")
        is_online = last_seen and last_seen >= five_minutes_ago if last_seen else False
        
        results.append(UserSearchResult(
            id=u["id"],
            username=u["username"],
            full_name=u.get("full_name"),
            license_number=u.get("license_number"),
            phone=u.get("phone"),
            role=u.get("role", "user"),
            preferred_shift=u.get("preferred_shift", "all"),
            created_at=u["created_at"],
            last_seen=last_seen,
            is_online=is_online
        ))
    
    return results


@router.post("/users", response_model=UserResponse)
async def create_user(user_data: UserCreate, admin: dict = Depends(get_admin_user)):
    """Create a new user (admin only)."""
    # Check if username already exists
    existing = await users_collection.find_one({"username": user_data.username})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya existe"
        )
    
    new_user = {
        "id": str(uuid.uuid4()),
        "username": user_data.username,
        "hashed_password": get_password_hash(user_data.password),
        "phone": user_data.phone,
        "role": user_data.role,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await users_collection.insert_one(new_user)
    
    return UserResponse(
        id=new_user["id"],
        username=new_user["username"],
        phone=new_user["phone"],
        role=new_user["role"],
        created_at=new_user["created_at"]
    )


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    admin: dict = Depends(get_admin_user)
):
    """Update user details (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    update_data = {"updated_at": datetime.utcnow()}
    if user_data.phone is not None:
        update_data["phone"] = user_data.phone
    if user_data.role is not None:
        update_data["role"] = user_data.role
    
    await users_collection.update_one(
        {"id": user_id},
        {"$set": update_data}
    )
    
    return {"message": "Usuario actualizado correctamente"}


@router.put("/users/{user_id}/password")
async def admin_change_password(
    user_id: str,
    password_data: PasswordChange,
    admin: dict = Depends(get_admin_user)
):
    """Change any user's password (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    new_hash = get_password_hash(password_data.new_password)
    await users_collection.update_one(
        {"id": user_id},
        {"$set": {"hashed_password": new_hash, "updated_at": datetime.utcnow()}}
    )
    
    return {"message": "Contraseña actualizada correctamente"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    """Delete a user (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Prevent deleting yourself
    if user["id"] == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta"
        )
    
    await users_collection.delete_one({"id": user_id})
    return {"message": "Usuario eliminado correctamente"}


# ============ BLOCKED USERS MANAGEMENT ============

class BlockedUserInfo(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    # Alert fraud info
    alert_fraud_count: int = 0
    alert_blocked_until: Optional[datetime] = None
    last_fraud_at: Optional[datetime] = None
    alert_block_status: str = "none"  # "temporary", "permanent", "expired", "none"
    alert_hours_remaining: Optional[int] = None
    # Chat abuse info
    chat_abuse_count: int = 0
    chat_blocked_until: Optional[datetime] = None
    last_chat_abuse_at: Optional[datetime] = None
    last_chat_abuse_message: Optional[str] = None
    chat_block_status: str = "none"  # "temporary", "permanent", "expired", "none"
    chat_hours_remaining: Optional[int] = None
    # Combined status
    block_reasons: List[str] = []  # ["avisos_fraudulentos", "mensajes_indebidos"]


class BlockedUsersStats(BaseModel):
    total_blocked: int
    alert_blocks: int
    chat_blocks: int
    permanent_blocks: int
    blocked_users: List[BlockedUserInfo]


def get_block_status(count: int, blocked_until: Optional[datetime], now: datetime) -> tuple[str, Optional[int]]:
    """Get block status and hours remaining."""
    if count > 20:
        return "permanent", None
    elif blocked_until:
        if blocked_until > now:
            hours_remaining = int((blocked_until - now).total_seconds() / 3600)
            return "temporary", hours_remaining
        else:
            return "expired", 0
    else:
        return "none", None


@router.get("/blocked-users", response_model=BlockedUsersStats)
async def get_blocked_users(admin: dict = Depends(get_admin_user)):
    """Get all users with any type of block (alerts or chat)."""
    now = datetime.utcnow()
    
    # Find users with any type of block or abuse count
    users_with_blocks = await users_collection.find({
        "$or": [
            {"alert_fraud_count": {"$gt": 0}},
            {"alert_blocked_until": {"$exists": True}},
            {"chat_abuse_count": {"$gt": 0}},
            {"chat_blocked_until": {"$exists": True}}
        ]
    }).to_list(1000)
    
    blocked_users = []
    alert_block_count = 0
    chat_block_count = 0
    permanent_count = 0
    active_blocks = set()
    
    for u in users_with_blocks:
        # Alert fraud info
        alert_fraud_count = u.get("alert_fraud_count", 0)
        alert_blocked_until = u.get("alert_blocked_until")
        alert_status, alert_hours = get_block_status(alert_fraud_count, alert_blocked_until, now)
        
        # Chat abuse info
        chat_abuse_count = u.get("chat_abuse_count", 0)
        chat_blocked_until = u.get("chat_blocked_until")
        chat_status, chat_hours = get_block_status(chat_abuse_count, chat_blocked_until, now)
        
        # Determine block reasons
        block_reasons = []
        if alert_status in ["temporary", "permanent"]:
            block_reasons.append("avisos_fraudulentos")
            if u["id"] not in active_blocks:
                alert_block_count += 1
                active_blocks.add(u["id"])
        if chat_status in ["temporary", "permanent"]:
            block_reasons.append("mensajes_indebidos")
            if u["id"] not in active_blocks:
                chat_block_count += 1
                active_blocks.add(u["id"])
        
        # Count permanent blocks
        if alert_status == "permanent" or chat_status == "permanent":
            permanent_count += 1
        
        blocked_users.append(BlockedUserInfo(
            id=u["id"],
            username=u["username"],
            full_name=u.get("full_name"),
            license_number=u.get("license_number"),
            # Alert info
            alert_fraud_count=alert_fraud_count,
            alert_blocked_until=alert_blocked_until,
            last_fraud_at=u.get("last_fraud_at"),
            alert_block_status=alert_status,
            alert_hours_remaining=alert_hours,
            # Chat info
            chat_abuse_count=chat_abuse_count,
            chat_blocked_until=chat_blocked_until,
            last_chat_abuse_at=u.get("last_chat_abuse_at"),
            last_chat_abuse_message=u.get("last_chat_abuse_message"),
            chat_block_status=chat_status,
            chat_hours_remaining=chat_hours,
            # Combined
            block_reasons=block_reasons
        ))
    
    # Sort: active blocks first (permanent, then temporary), then expired
    def sort_key(x):
        has_active = len(x.block_reasons) > 0
        is_permanent = x.alert_block_status == "permanent" or x.chat_block_status == "permanent"
        max_hours = max(x.alert_hours_remaining or 0, x.chat_hours_remaining or 0)
        return (0 if has_active else 1, 0 if is_permanent else 1, -max_hours)
    
    blocked_users.sort(key=sort_key)
    
    return BlockedUsersStats(
        total_blocked=len(active_blocks),
        alert_blocks=alert_block_count,
        chat_blocks=chat_block_count,
        permanent_blocks=permanent_count,
        blocked_users=blocked_users
    )
        
        blocked_users.append(BlockedUserInfo(
            id=u["id"],
            username=u["username"],
            full_name=u.get("full_name"),
            license_number=u.get("license_number"),
            alert_fraud_count=fraud_count,
            alert_blocked_until=blocked_until,
            last_fraud_at=u.get("last_fraud_at"),
            block_status=block_status,
            hours_remaining=hours_remaining
        ))
    
    # Sort: permanent first, then temporary by hours remaining, then expired
    blocked_users.sort(key=lambda x: (
        0 if x.block_status == "permanent" else (1 if x.block_status == "temporary" else 2),
        -(x.hours_remaining or 0)
    ))
    
    return BlockedUsersStats(
        total_blocked=temporary_count + permanent_count,
        temporary_blocks=temporary_count,
        permanent_blocks=permanent_count,
        blocked_users=blocked_users
    )


@router.post("/users/{user_id}/unblock")
async def unblock_user(user_id: str, admin: dict = Depends(get_admin_user)):
    """Remove alert block from a user (admin only). Does not reset fraud count."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Remove the block but keep the fraud count for history
    await users_collection.update_one(
        {"id": user_id},
        {"$unset": {"alert_blocked_until": ""}}
    )
    
    return {"message": f"Usuario {user['username']} desbloqueado correctamente"}


@router.post("/users/{user_id}/reset-fraud")
async def reset_fraud_count(user_id: str, admin: dict = Depends(get_admin_user)):
    """Reset a user's fraud count and remove block (admin only)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    # Reset fraud count and remove block
    await users_collection.update_one(
        {"id": user_id},
        {
            "$set": {"alert_fraud_count": 0},
            "$unset": {"alert_blocked_until": "", "last_fraud_at": ""}
        }
    )
    
    return {"message": f"Contador de fraudes de {user['username']} reseteado correctamente"}
