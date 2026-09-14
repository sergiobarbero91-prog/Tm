"""
Admin router for user management (admin only).
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, validator
import uuid
import re

from shared import (
    users_collection,
    clients_collection,
    rides_collection,
    UserCreate, UserUpdate, PasswordChange, UserResponse,
    LicenciaInput,
    get_admin_user, get_password_hash
)

router = APIRouter(prefix="/admin", tags=["Admin"])


VALID_ROLES = {"user", "conductor", "propietario", "moderator", "admin"}
VALID_SHIFTS = {"all", "day", "night"}


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
    email: Optional[str] = None
    role: str
    preferred_shift: str = "all"
    licencias: Optional[List[dict]] = None
    created_at: datetime
    last_seen: Optional[datetime] = None
    is_online: bool = False


class AdminUserUpdate(BaseModel):
    """Extended fields an admin can edit on any user."""
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    preferred_shift: Optional[str] = None
    licencias: Optional[List[LicenciaInput]] = None

    @validator("role")
    def _v_role(cls, v):  # noqa: N805
        if v is None:
            return v
        if v not in VALID_ROLES:
            raise ValueError(f"Rol invalido. Validos: {sorted(VALID_ROLES)}")
        return v

    @validator("preferred_shift")
    def _v_shift(cls, v):  # noqa: N805
        if v is None:
            return v
        if v not in VALID_SHIFTS:
            raise ValueError(f"Turno invalido. Validos: {sorted(VALID_SHIFTS)}")
        return v

    @validator("email")
    def _v_email(cls, v):  # noqa: N805
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Email no valido")
        return v

    @validator("license_number")
    def _v_lic(cls, v):  # noqa: N805
        if v is None or v == "":
            return v
        if not v.isdigit():
            raise ValueError("El numero de licencia debe contener solo digitos")
        return v


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
            email=u.get("email"),
            role=u.get("role", "user"),
            preferred_shift=u.get("preferred_shift", "all"),
            licencias=u.get("licencias"),
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
            email=u.get("email"),
            role=u.get("role", "user"),
            preferred_shift=u.get("preferred_shift", "all"),
            licencias=u.get("licencias"),
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
    user_data: AdminUserUpdate,
    admin: dict = Depends(get_admin_user)
):
    """Update user details (admin only). Supports all editable fields + licencias."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    update_data: dict = {"updated_at": datetime.utcnow()}

    if user_data.full_name is not None:
        update_data["full_name"] = user_data.full_name.strip() or None

    if user_data.phone is not None:
        update_data["phone"] = user_data.phone.strip() or None

    if user_data.email is not None:
        # Uniqueness across users
        if user_data.email:
            clash = await users_collection.find_one({
                "email": user_data.email,
                "id": {"$ne": user_id},
            })
            if clash:
                raise HTTPException(status_code=400, detail="Ese email ya esta en uso")
        update_data["email"] = user_data.email

    if user_data.preferred_shift is not None:
        update_data["preferred_shift"] = user_data.preferred_shift

    if user_data.role is not None:
        update_data["role"] = user_data.role

    if user_data.license_number is not None:
        if user_data.license_number:
            clash = await users_collection.find_one({
                "$or": [
                    {"license_number": user_data.license_number},
                    {"licencias.numero": user_data.license_number},
                ],
                "id": {"$ne": user_id},
            })
            if clash:
                raise HTTPException(status_code=400, detail="Esa licencia ya esta registrada")
        update_data["license_number"] = user_data.license_number or None

    # Manage licencias list (owners) — replace whole list atomically
    if user_data.licencias is not None:
        licencias_out = []
        seen = set()
        for lic in user_data.licencias:
            numero = (lic.numero or "").strip()
            if not numero.isdigit():
                raise HTTPException(status_code=400, detail=f"La licencia '{numero}' debe contener solo digitos")
            if numero in seen:
                raise HTTPException(status_code=400, detail=f"La licencia '{numero}' esta duplicada")
            seen.add(numero)
            clash = await users_collection.find_one({
                "$or": [
                    {"license_number": numero},
                    {"licencias.numero": numero},
                ],
                "id": {"$ne": user_id},
            })
            if clash:
                raise HTTPException(status_code=400, detail=f"La licencia {numero} ya esta registrada en otro usuario")
            licencias_out.append({"numero": numero, "alias": (lic.alias or "").strip() or None})
        update_data["licencias"] = licencias_out
        # For owners, canonical license_number tracks first licencia
        if update_data.get("role", user.get("role")) == "propietario" and licencias_out:
            update_data.setdefault("license_number", licencias_out[0]["numero"])

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


@router.post("/users/{user_id}/unblock")
async def unblock_user(user_id: str, block_type: str = "all", admin: dict = Depends(get_admin_user)):
    """Remove block from a user. block_type can be 'alert', 'chat', or 'all'."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    unset_fields = {}
    if block_type in ["alert", "all"]:
        unset_fields["alert_blocked_until"] = ""
    if block_type in ["chat", "all"]:
        unset_fields["chat_blocked_until"] = ""
    
    if unset_fields:
        await users_collection.update_one(
            {"id": user_id},
            {"$unset": unset_fields}
        )
    
    return {"message": f"Usuario {user['username']} desbloqueado correctamente"}


@router.post("/users/{user_id}/reset-fraud")
async def reset_fraud_count(user_id: str, block_type: str = "all", admin: dict = Depends(get_admin_user)):
    """Reset a user's abuse count and remove block. block_type can be 'alert', 'chat', or 'all'."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )
    
    set_fields = {}
    unset_fields = {}
    
    if block_type in ["alert", "all"]:
        set_fields["alert_fraud_count"] = 0
        unset_fields["alert_blocked_until"] = ""
        unset_fields["last_fraud_at"] = ""
    
    if block_type in ["chat", "all"]:
        set_fields["chat_abuse_count"] = 0
        unset_fields["chat_blocked_until"] = ""
        unset_fields["last_chat_abuse_at"] = ""
        unset_fields["last_chat_abuse_message"] = ""
        unset_fields["last_chat_abuse_blocked_by"] = ""
    
    update_ops = {}
    if set_fields:
        update_ops["$set"] = set_fields
    if unset_fields:
        update_ops["$unset"] = unset_fields
    
    if update_ops:
        await users_collection.update_one({"id": user_id}, update_ops)
    
    return {"message": f"Contador de {user['username']} reseteado correctamente"}


# ============ CLIENT MANAGEMENT (ADMIN) ============

_PHONE_RE = re.compile(r"^\+\d{8,15}$")


def _norm_phone(v: str) -> str:
    v = (v or "").strip().replace(" ", "").replace("-", "")
    if not _PHONE_RE.match(v):
        raise HTTPException(status_code=400, detail="Telefono debe ir en formato E.164 (ej. +34611223344)")
    return v


def _norm_email(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    v = v.strip().lower()
    if "@" not in v or "." not in v.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Email no valido")
    return v


class ClientResult(BaseModel):
    id: str
    phone: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    associated_driver_id: Optional[str] = None
    associated_driver_name: Optional[str] = None
    has_password: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None


class ClientCreateBody(BaseModel):
    phone: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    password: Optional[str] = None
    associated_driver_id: Optional[str] = None


class ClientUpdateBody(BaseModel):
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    associated_driver_id: Optional[str] = None


class ClientPasswordBody(BaseModel):
    new_password: str


async def _client_to_result(doc: dict) -> ClientResult:
    driver_name = None
    if doc.get("associated_driver_id"):
        drv = await users_collection.find_one({"id": doc["associated_driver_id"]}, {"full_name": 1, "username": 1})
        if drv:
            driver_name = drv.get("full_name") or drv.get("username")
    return ClientResult(
        id=doc["id"],
        phone=doc.get("phone", ""),
        first_name=doc.get("first_name", ""),
        last_name=doc.get("last_name", ""),
        email=doc.get("email"),
        associated_driver_id=doc.get("associated_driver_id"),
        associated_driver_name=driver_name,
        has_password=bool(doc.get("password_hash")),
        created_at=doc.get("created_at", datetime.utcnow()),
        updated_at=doc.get("updated_at"),
    )


@router.get("/clients", response_model=List[ClientResult])
async def list_clients(admin: dict = Depends(get_admin_user)):
    """List all clients (admin only)."""
    docs = await clients_collection.find().sort("created_at", -1).to_list(1000)
    return [await _client_to_result(d) for d in docs]


@router.get("/clients/search", response_model=List[ClientResult])
async def search_clients(
    q: str = Query(..., min_length=1),
    admin: dict = Depends(get_admin_user),
):
    """Search clients by phone / name / email (admin only)."""
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    docs = await clients_collection.find({
        "$or": [
            {"phone": {"$regex": pattern}},
            {"first_name": {"$regex": pattern}},
            {"last_name": {"$regex": pattern}},
            {"email": {"$regex": pattern}},
        ]
    }).limit(100).to_list(100)
    return [await _client_to_result(d) for d in docs]


@router.post("/clients", response_model=ClientResult)
async def create_client(body: ClientCreateBody, admin: dict = Depends(get_admin_user)):
    """Create a new client account (admin only)."""
    phone = _norm_phone(body.phone)
    if await clients_collection.find_one({"phone": phone}):
        raise HTTPException(status_code=400, detail="Ya existe un cliente con ese telefono")
    email = _norm_email(body.email)
    if email:
        clash = await clients_collection.find_one({"email": email})
        if clash:
            raise HTTPException(status_code=400, detail="Ya existe un cliente con ese email")
    if body.associated_driver_id:
        drv = await users_collection.find_one({"id": body.associated_driver_id})
        if not drv:
            raise HTTPException(status_code=400, detail="Taxista asociado no encontrado")

    fn = (body.first_name or "").strip()
    ln = (body.last_name or "").strip()
    if not fn or not ln:
        raise HTTPException(status_code=400, detail="Nombre y apellido son obligatorios")

    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "phone": phone,
        "first_name": fn,
        "last_name": ln,
        "email": email,
        "associated_driver_id": body.associated_driver_id,
        "password_hash": get_password_hash(body.password) if body.password else None,
        "created_at": now,
        "updated_at": now,
    }
    await clients_collection.insert_one(doc)
    return await _client_to_result(doc)


@router.put("/clients/{client_id}", response_model=ClientResult)
async def update_client(client_id: str, body: ClientUpdateBody, admin: dict = Depends(get_admin_user)):
    """Update client fields (admin only)."""
    doc = await clients_collection.find_one({"id": client_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    update: dict = {"updated_at": datetime.now(timezone.utc)}
    if body.phone is not None:
        phone = _norm_phone(body.phone)
        if phone != doc.get("phone"):
            clash = await clients_collection.find_one({"phone": phone, "id": {"$ne": client_id}})
            if clash:
                raise HTTPException(status_code=400, detail="Ese telefono ya esta en uso")
        update["phone"] = phone
    if body.first_name is not None:
        update["first_name"] = body.first_name.strip()
    if body.last_name is not None:
        update["last_name"] = body.last_name.strip()
    if body.email is not None:
        email = _norm_email(body.email)
        if email and email != doc.get("email"):
            clash = await clients_collection.find_one({"email": email, "id": {"$ne": client_id}})
            if clash:
                raise HTTPException(status_code=400, detail="Ese email ya esta en uso")
        update["email"] = email
    if body.associated_driver_id is not None:
        if body.associated_driver_id:
            drv = await users_collection.find_one({"id": body.associated_driver_id})
            if not drv:
                raise HTTPException(status_code=400, detail="Taxista asociado no encontrado")
        update["associated_driver_id"] = body.associated_driver_id or None

    await clients_collection.update_one({"id": client_id}, {"$set": update})
    doc = await clients_collection.find_one({"id": client_id})
    return await _client_to_result(doc)


@router.put("/clients/{client_id}/password")
async def change_client_password(
    client_id: str, body: ClientPasswordBody, admin: dict = Depends(get_admin_user)
):
    """Reset a client's password (admin only)."""
    if not body.new_password or len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="La contrasena debe tener al menos 4 caracteres")
    doc = await clients_collection.find_one({"id": client_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    await clients_collection.update_one(
        {"id": client_id},
        {"$set": {
            "password_hash": get_password_hash(body.new_password),
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    return {"message": "Contrasena actualizada correctamente"}


@router.delete("/clients/{client_id}")
async def delete_client(client_id: str, admin: dict = Depends(get_admin_user)):
    """Delete a client (admin only)."""
    doc = await clients_collection.find_one({"id": client_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    await clients_collection.delete_one({"id": client_id})
    return {"message": "Cliente eliminado correctamente"}



# ============ SERVICE HISTORY (ADMIN) ============

class RideHistoryItem(BaseModel):
    id: str
    origin: str
    destination: str
    ride_type: str
    scheduled_at: Optional[datetime] = None
    status: str
    dispatch_scope: str
    client_id: str
    client_name: str
    client_phone: str
    associated_driver_id: Optional[str] = None
    accepted_by_driver_id: Optional[str] = None
    accepted_by_driver_name: Optional[str] = None
    notes: Optional[str] = None
    passengers: int = 1
    created_at: datetime
    updated_at: Optional[datetime] = None


def _ride_history(doc: dict) -> RideHistoryItem:
    return RideHistoryItem(
        id=doc["id"],
        origin=doc.get("origin", ""),
        destination=doc.get("destination", ""),
        ride_type=doc.get("ride_type", "asap"),
        scheduled_at=doc.get("scheduled_at"),
        status=doc.get("status", "pending"),
        dispatch_scope=doc.get("dispatch_scope", "open"),
        client_id=doc.get("client_id", ""),
        client_name=doc.get("client_name", ""),
        client_phone=doc.get("client_phone", ""),
        associated_driver_id=doc.get("associated_driver_id"),
        accepted_by_driver_id=doc.get("accepted_by_driver_id"),
        accepted_by_driver_name=doc.get("accepted_by_driver_name"),
        notes=doc.get("notes"),
        passengers=doc.get("passengers", 1),
        created_at=doc.get("created_at", datetime.utcnow()),
        updated_at=doc.get("updated_at"),
    )


@router.get("/users/{user_id}/rides", response_model=List[RideHistoryItem])
async def admin_user_ride_history(user_id: str, admin: dict = Depends(get_admin_user)):
    """History of rides the driver has accepted (or been assigned)."""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    cursor = rides_collection.find({
        "$or": [
            {"accepted_by_driver_id": user_id},
            {"associated_driver_id": user_id},
        ]
    }).sort("created_at", -1).limit(200)
    return [_ride_history(d) async for d in cursor]


@router.get("/clients/{client_id}/rides", response_model=List[RideHistoryItem])
async def admin_client_ride_history(client_id: str, admin: dict = Depends(get_admin_user)):
    """History of rides requested by the client."""
    client = await clients_collection.find_one({"id": client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cursor = rides_collection.find({"client_id": client_id}).sort("created_at", -1).limit(200)
    return [_ride_history(d) async for d in cursor]

