"""
Authentication router for login, registration, and profile management.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
import uuid

from shared import (
    users_collection,
    UserLogin, UserRegister, UserProfileUpdate, PasswordChange,
    UserResponse, TokenResponse,
    verify_password, get_password_hash, create_access_token,
    get_current_user_required, logger
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(login_data: UserLogin):
    """Login with username and password."""
    user = await users_collection.find_one({"username": login_data.username})
    if not user or not verify_password(login_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos"
        )
    
    # Update last_login and last_seen
    now = datetime.utcnow()
    await users_collection.update_one(
        {"id": user["id"]},
        {"$set": {"last_login": now, "last_seen": now}}
    )
    
    access_token = create_access_token(data={"sub": user["id"]})
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            full_name=user.get("full_name"),
            license_number=user.get("license_number"),
            phone=user.get("phone"),
            role=user.get("role", "user"),
            preferred_shift=user.get("preferred_shift", "all"),
            created_at=user["created_at"]
        )
    )


@router.post("/register", response_model=TokenResponse)
async def register(register_data: UserRegister):
    """Public registration endpoint for new users."""
    # Check if username already exists
    existing_user = await users_collection.find_one({"username": register_data.username})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya existe"
        )
    
    # Check if license number already exists
    existing_license = await users_collection.find_one({"license_number": register_data.license_number})
    if existing_license:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El número de licencia ya está registrado"
        )
    
    # Validate license number is numeric
    if not register_data.license_number.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El número de licencia debe contener solo dígitos"
        )
    
    # Validate preferred_shift
    valid_shifts = ["all", "day", "night"]
    if register_data.preferred_shift and register_data.preferred_shift not in valid_shifts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Turno de preferencia inválido"
        )
    
    # Create new user
    new_user = {
        "id": str(uuid.uuid4()),
        "username": register_data.username,
        "hashed_password": get_password_hash(register_data.password),
        "full_name": register_data.full_name,
        "license_number": register_data.license_number,
        "phone": register_data.phone,
        "role": "user",
        "preferred_shift": register_data.preferred_shift or "all",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await users_collection.insert_one(new_user)
    
    # Generate token and login immediately
    access_token = create_access_token(data={"sub": new_user["id"]})
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=new_user["id"],
            username=new_user["username"],
            full_name=new_user["full_name"],
            license_number=new_user["license_number"],
            phone=new_user.get("phone"),
            role=new_user["role"],
            preferred_shift=new_user["preferred_shift"],
            created_at=new_user["created_at"]
        )
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user_required)):
    """Get current authenticated user."""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        full_name=current_user.get("full_name"),
        license_number=current_user.get("license_number"),
        phone=current_user.get("phone"),
        role=current_user.get("role", "user"),
        preferred_shift=current_user.get("preferred_shift", "all"),
        created_at=current_user["created_at"]
    )


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    profile_data: UserProfileUpdate,
    current_user: dict = Depends(get_current_user_required)
):
    """Update own profile data."""
    update_fields = {}
    
    if profile_data.full_name is not None:
        update_fields["full_name"] = profile_data.full_name
    
    if profile_data.license_number is not None:
        # Validate numeric
        if not profile_data.license_number.isdigit():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de licencia debe contener solo dígitos"
            )
        # Check uniqueness (excluding current user)
        existing = await users_collection.find_one({
            "license_number": profile_data.license_number,
            "id": {"$ne": current_user["id"]}
        })
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El número de licencia ya está registrado"
            )
        update_fields["license_number"] = profile_data.license_number
    
    if profile_data.phone is not None:
        update_fields["phone"] = profile_data.phone
    
    if profile_data.preferred_shift is not None:
        valid_shifts = ["all", "day", "night"]
        if profile_data.preferred_shift not in valid_shifts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Turno de preferencia inválido"
            )
        update_fields["preferred_shift"] = profile_data.preferred_shift
    
    if update_fields:
        update_fields["updated_at"] = datetime.utcnow()
        await users_collection.update_one(
            {"id": current_user["id"]},
            {"$set": update_fields}
        )
    
    # Fetch updated user
    updated_user = await users_collection.find_one({"id": current_user["id"]})
    
    return UserResponse(
        id=updated_user["id"],
        username=updated_user["username"],
        full_name=updated_user.get("full_name"),
        license_number=updated_user.get("license_number"),
        phone=updated_user.get("phone"),
        role=updated_user.get("role", "user"),
        preferred_shift=updated_user.get("preferred_shift", "all"),
        created_at=updated_user["created_at"]
    )


@router.put("/password")
async def change_own_password(
    password_data: PasswordChange,
    current_user: dict = Depends(get_current_user_required)
):
    """Change own password (requires current password)."""
    if not password_data.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se requiere la contraseña actual"
        )
    
    if not verify_password(password_data.current_password, current_user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña actual incorrecta"
        )
    
    new_hash = get_password_hash(password_data.new_password)
    await users_collection.update_one(
        {"id": current_user["id"]},
        {"$set": {"hashed_password": new_hash, "updated_at": datetime.utcnow()}}
    )
    
    return {"message": "Contraseña actualizada correctamente"}


@router.post("/heartbeat")
async def heartbeat(current_user: dict = Depends(get_current_user_required)):
    """Update user's last_seen timestamp (call periodically to show as online)."""
    now = datetime.utcnow()
    await users_collection.update_one(
        {"id": current_user["id"]},
        {"$set": {"last_seen": now}}
    )
    return {"status": "ok", "timestamp": now.isoformat()}
