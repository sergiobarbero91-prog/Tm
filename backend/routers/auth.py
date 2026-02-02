"""
Authentication router for login, registration, and profile management.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from datetime import datetime, timedelta
import uuid
import secrets
import string
from typing import List
from slowapi import Limiter
from slowapi.util import get_remote_address

from shared import (
    users_collection, invitations_collection, registration_requests_collection,
    UserLogin, UserRegister, UserProfileUpdate, PasswordChange,
    UserResponse, TokenResponse,
    InvitationCreate, InvitationResponse, 
    RegistrationRequestCreate, RegistrationRequestResponse,
    RegisterWithInvitation, SponsorInfo, ReferralInfo,
    verify_password, get_password_hash, create_access_token,
    get_current_user_required, logger
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
limiter = Limiter(key_func=get_remote_address)

# Invitation code expiration
INVITATION_EXPIRY_DAYS = 7

def generate_invitation_code(length=8):
    """Generate a random invitation code"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")  # Rate limit: 10 login attempts per minute
async def login(request: Request, login_data: UserLogin):
    """Login with username and password."""
    user = await users_collection.find_one({"username": login_data.username})
    logger.info(f"Login attempt for user: {login_data.username}, found: {user is not None}")
    if user:
        pwd_check = verify_password(login_data.password, user["hashed_password"])
        logger.info(f"Password check result: {pwd_check}")
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


@router.get("/check-username/{username}")
async def check_username(username: str):
    """Check if a username is available."""
    existing_user = await users_collection.find_one({"username": username})
    return {"available": existing_user is None}


@router.post("/register", response_model=TokenResponse)
@limiter.limit("5/minute")  # Rate limit: 5 registrations per minute
async def register(request: Request, register_data: UserRegister):
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


@router.post("/refresh-token", response_model=TokenResponse)
async def refresh_token(current_user: dict = Depends(get_current_user_required)):
    """Refresh the access token if the user is still authenticated.
    Call this periodically to prevent session expiration during active use.
    """
    # Update last_seen
    now = datetime.utcnow()
    await users_collection.update_one(
        {"id": current_user["id"]},
        {"$set": {"last_seen": now}}
    )
    
    # Generate a new token with fresh expiration
    access_token = create_access_token(data={"sub": current_user["id"]})
    
    logger.info(f"Token refreshed for user {current_user['username']}")
    
    return TokenResponse(
        access_token=access_token,
        user=UserResponse(
            id=current_user["id"],
            username=current_user["username"],
            full_name=current_user.get("full_name"),
            license_number=current_user.get("license_number"),
            phone=current_user.get("phone"),
            role=current_user.get("role", "user"),
            preferred_shift=current_user.get("preferred_shift", "all"),
            created_at=current_user["created_at"]
        )
    )


# ============== INVITATION SYSTEM ==============

@router.post("/invitations", response_model=InvitationResponse)
async def create_invitation(
    invitation_data: InvitationCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Create an invitation code for a new user."""
    code = generate_invitation_code()
    now = datetime.utcnow()
    
    invitation = {
        "id": str(uuid.uuid4()),
        "code": code,
        "created_by_id": current_user["id"],
        "created_by_username": current_user["username"],
        "created_by_license": current_user.get("license_number", ""),
        "note": invitation_data.note,
        "used": False,
        "used_by_id": None,
        "used_by_username": None,
        "created_at": now,
        "expires_at": now + timedelta(days=INVITATION_EXPIRY_DAYS)
    }
    
    await invitations_collection.insert_one(invitation)
    logger.info(f"User {current_user['username']} created invitation {code}")
    
    return InvitationResponse(**invitation)


@router.get("/invitations", response_model=List[InvitationResponse])
async def get_my_invitations(current_user: dict = Depends(get_current_user_required)):
    """Get all invitations created by the current user."""
    invitations = await invitations_collection.find({
        "created_by_id": current_user["id"]
    }).sort("created_at", -1).to_list(100)
    
    return [InvitationResponse(**inv) for inv in invitations]


@router.delete("/invitations/{invitation_id}")
async def delete_invitation(
    invitation_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Delete an unused invitation."""
    invitation = await invitations_collection.find_one({
        "id": invitation_id,
        "created_by_id": current_user["id"]
    })
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    
    if invitation.get("used"):
        raise HTTPException(status_code=400, detail="No se puede eliminar una invitación ya utilizada")
    
    await invitations_collection.delete_one({"id": invitation_id})
    return {"message": "Invitación eliminada"}


@router.post("/register-with-invitation", response_model=TokenResponse)
@limiter.limit("5/minute")
async def register_with_invitation(request: Request, register_data: RegisterWithInvitation):
    """Register a new user using an invitation code."""
    # Find and validate invitation
    invitation = await invitations_collection.find_one({
        "code": register_data.invitation_code.upper(),
        "used": False
    })
    
    if not invitation:
        raise HTTPException(status_code=400, detail="Código de invitación inválido o ya utilizado")
    
    # Check expiration
    if invitation["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="El código de invitación ha expirado")
    
    # Check if username already exists
    existing_user = await users_collection.find_one({"username": register_data.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    
    # Check if license number already exists
    existing_license = await users_collection.find_one({"license_number": register_data.license_number})
    if existing_license:
        raise HTTPException(status_code=400, detail="El número de licencia ya está registrado")
    
    # Validate license number is numeric
    if not register_data.license_number.isdigit():
        raise HTTPException(status_code=400, detail="El número de licencia debe contener solo dígitos")
    
    now = datetime.utcnow()
    
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
        "created_at": now,
        "updated_at": now,
        "invited_by_id": invitation["created_by_id"],
        "invited_by_username": invitation["created_by_username"],
        "registration_method": "invitation"
    }
    
    await users_collection.insert_one(new_user)
    
    # Mark invitation as used
    await invitations_collection.update_one(
        {"id": invitation["id"]},
        {"$set": {
            "used": True,
            "used_by_id": new_user["id"],
            "used_by_username": new_user["username"],
            "used_at": now
        }}
    )
    
    logger.info(f"User {register_data.username} registered via invitation from {invitation['created_by_username']}")
    
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


# ============== REGISTRATION REQUEST SYSTEM ==============

@router.post("/registration-requests", response_model=RegistrationRequestResponse)
@limiter.limit("5/minute")
async def create_registration_request(request: Request, request_data: RegistrationRequestCreate):
    """Create a registration request that needs approval from an existing user."""
    # Find sponsor by license number
    sponsor = await users_collection.find_one({"license_number": request_data.sponsor_license})
    if not sponsor:
        raise HTTPException(status_code=400, detail="No existe ningún usuario con esa licencia de referencia")
    
    # Check if username already exists
    existing_user = await users_collection.find_one({"username": request_data.username})
    if existing_user:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    
    # Check if license number already exists
    existing_license = await users_collection.find_one({"license_number": request_data.license_number})
    if existing_license:
        raise HTTPException(status_code=400, detail="El número de licencia ya está registrado")
    
    # Check if there's already a pending request with this username or license
    existing_request = await registration_requests_collection.find_one({
        "$or": [
            {"username": request_data.username, "status": "pending"},
            {"license_number": request_data.license_number, "status": "pending"}
        ]
    })
    if existing_request:
        raise HTTPException(status_code=400, detail="Ya existe una solicitud pendiente con este usuario o licencia")
    
    # Validate license number is numeric
    if not request_data.license_number.isdigit():
        raise HTTPException(status_code=400, detail="El número de licencia debe contener solo dígitos")
    
    now = datetime.utcnow()
    
    registration_request = {
        "id": str(uuid.uuid4()),
        "username": request_data.username,
        "hashed_password": get_password_hash(request_data.password),
        "full_name": request_data.full_name,
        "license_number": request_data.license_number,
        "phone": request_data.phone,
        "preferred_shift": request_data.preferred_shift or "all",
        "sponsor_license": request_data.sponsor_license,
        "sponsor_id": sponsor["id"],
        "sponsor_username": sponsor["username"],
        "sponsor_full_name": sponsor.get("full_name"),
        "status": "pending",
        "created_at": now,
        "resolved_at": None
    }
    
    await registration_requests_collection.insert_one(registration_request)
    logger.info(f"Registration request created for {request_data.username}, awaiting approval from {sponsor['username']}")
    
    return RegistrationRequestResponse(
        id=registration_request["id"],
        username=registration_request["username"],
        full_name=registration_request["full_name"],
        license_number=registration_request["license_number"],
        phone=registration_request.get("phone"),
        sponsor_license=registration_request["sponsor_license"],
        sponsor_username=registration_request["sponsor_username"],
        sponsor_full_name=registration_request["sponsor_full_name"],
        status=registration_request["status"],
        created_at=registration_request["created_at"],
        resolved_at=registration_request.get("resolved_at")
    )


@router.get("/registration-requests/pending", response_model=List[RegistrationRequestResponse])
async def get_pending_requests(current_user: dict = Depends(get_current_user_required)):
    """Get all pending registration requests where current user is the sponsor."""
    requests = await registration_requests_collection.find({
        "sponsor_id": current_user["id"],
        "status": "pending"
    }).sort("created_at", -1).to_list(100)
    
    return [RegistrationRequestResponse(
        id=req["id"],
        username=req["username"],
        full_name=req["full_name"],
        license_number=req["license_number"],
        phone=req.get("phone"),
        sponsor_license=req["sponsor_license"],
        sponsor_username=req.get("sponsor_username"),
        sponsor_full_name=req.get("sponsor_full_name"),
        status=req["status"],
        created_at=req["created_at"],
        resolved_at=req.get("resolved_at")
    ) for req in requests]


@router.get("/registration-requests/pending/count")
async def get_pending_requests_count(current_user: dict = Depends(get_current_user_required)):
    """Get count of pending registration requests for current user."""
    count = await registration_requests_collection.count_documents({
        "sponsor_id": current_user["id"],
        "status": "pending"
    })
    return {"count": count}


@router.post("/registration-requests/{request_id}/approve", response_model=dict)
async def approve_registration_request(
    request_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Approve a registration request and create the user account."""
    reg_request = await registration_requests_collection.find_one({
        "id": request_id,
        "sponsor_id": current_user["id"],
        "status": "pending"
    })
    
    if not reg_request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada o ya procesada")
    
    # Double-check username and license aren't taken
    existing_user = await users_collection.find_one({"username": reg_request["username"]})
    if existing_user:
        await registration_requests_collection.update_one(
            {"id": request_id},
            {"$set": {"status": "rejected", "resolved_at": datetime.utcnow(), "reject_reason": "Username taken"}}
        )
        raise HTTPException(status_code=400, detail="El nombre de usuario ya fue registrado")
    
    existing_license = await users_collection.find_one({"license_number": reg_request["license_number"]})
    if existing_license:
        await registration_requests_collection.update_one(
            {"id": request_id},
            {"$set": {"status": "rejected", "resolved_at": datetime.utcnow(), "reject_reason": "License taken"}}
        )
        raise HTTPException(status_code=400, detail="El número de licencia ya fue registrado")
    
    now = datetime.utcnow()
    
    # Create the user
    new_user = {
        "id": str(uuid.uuid4()),
        "username": reg_request["username"],
        "hashed_password": reg_request["hashed_password"],
        "full_name": reg_request["full_name"],
        "license_number": reg_request["license_number"],
        "phone": reg_request.get("phone"),
        "role": "user",
        "preferred_shift": reg_request.get("preferred_shift", "all"),
        "created_at": now,
        "updated_at": now,
        "approved_by_id": current_user["id"],
        "approved_by_username": current_user["username"],
        "registration_method": "approval"
    }
    
    await users_collection.insert_one(new_user)
    
    # Update request status
    await registration_requests_collection.update_one(
        {"id": request_id},
        {"$set": {"status": "approved", "resolved_at": now, "created_user_id": new_user["id"]}}
    )
    
    logger.info(f"User {reg_request['username']} approved by {current_user['username']}")
    
    return {"message": f"Usuario {reg_request['username']} aprobado correctamente", "user_id": new_user["id"]}


@router.post("/registration-requests/{request_id}/reject")
async def reject_registration_request(
    request_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Reject a registration request."""
    reg_request = await registration_requests_collection.find_one({
        "id": request_id,
        "sponsor_id": current_user["id"],
        "status": "pending"
    })
    
    if not reg_request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada o ya procesada")
    
    await registration_requests_collection.update_one(
        {"id": request_id},
        {"$set": {"status": "rejected", "resolved_at": datetime.utcnow()}}
    )
    
    logger.info(f"Registration request for {reg_request['username']} rejected by {current_user['username']}")
    
    return {"message": "Solicitud rechazada"}


# ============== SPONSOR & REFERRAL INFO ==============

@router.get("/my-sponsor", response_model=SponsorInfo | None)
async def get_my_sponsor(current_user: dict = Depends(get_current_user_required)):
    """Get info about the user who invited/approved the current user."""
    invited_by_id = current_user.get("invited_by_id")
    approved_by_id = current_user.get("approved_by_id")
    registration_method = current_user.get("registration_method")
    
    if invited_by_id:
        sponsor = await users_collection.find_one({"id": invited_by_id})
        if sponsor:
            return SponsorInfo(
                id=sponsor["id"],
                username=sponsor["username"],
                full_name=sponsor.get("full_name"),
                license_number=sponsor.get("license_number"),
                registration_method="invitation"
            )
    
    if approved_by_id:
        sponsor = await users_collection.find_one({"id": approved_by_id})
        if sponsor:
            return SponsorInfo(
                id=sponsor["id"],
                username=sponsor["username"],
                full_name=sponsor.get("full_name"),
                license_number=sponsor.get("license_number"),
                registration_method="approval"
            )
    
    return None


@router.get("/my-referrals", response_model=List[ReferralInfo])
async def get_my_referrals(current_user: dict = Depends(get_current_user_required)):
    """Get all users invited or approved by the current user."""
    # Get users invited by current user
    invited_users = await users_collection.find({
        "invited_by_id": current_user["id"]
    }).to_list(100)
    
    # Get users approved by current user
    approved_users = await users_collection.find({
        "approved_by_id": current_user["id"]
    }).to_list(100)
    
    referrals = []
    
    for user in invited_users:
        referrals.append(ReferralInfo(
            id=user["id"],
            username=user["username"],
            full_name=user.get("full_name"),
            license_number=user.get("license_number"),
            registration_method="invitation",
            created_at=user["created_at"]
        ))
    
    for user in approved_users:
        referrals.append(ReferralInfo(
            id=user["id"],
            username=user["username"],
            full_name=user.get("full_name"),
            license_number=user.get("license_number"),
            registration_method="approval",
            created_at=user["created_at"]
        ))
    
    # Sort by created_at descending
    referrals.sort(key=lambda x: x.created_at, reverse=True)
    
    return referrals
