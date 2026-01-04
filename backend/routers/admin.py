"""
Admin router for user management (admin only).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from datetime import datetime
import uuid

from shared import (
    users_collection,
    UserCreate, UserUpdate, PasswordChange, UserResponse,
    get_admin_user, get_password_hash
)

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=List[UserResponse])
async def list_users(admin: dict = Depends(get_admin_user)):
    """List all users (admin only)."""
    users = await users_collection.find().to_list(1000)
    return [
        UserResponse(
            id=u["id"],
            username=u["username"],
            full_name=u.get("full_name"),
            license_number=u.get("license_number"),
            phone=u.get("phone"),
            role=u.get("role", "user"),
            preferred_shift=u.get("preferred_shift", "all"),
            created_at=u["created_at"]
        )
        for u in users
    ]


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
