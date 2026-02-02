"""
Shared dependencies, models, and utilities for all routers.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import uuid
import logging
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Configure logging
logger = logging.getLogger(__name__)

# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "transportmeter-secret-key-2025")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer(auto_error=False)

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collections
users_collection = db['users']
street_activities_collection = db['street_activities']
taxi_status_collection = db['taxi_status']
queue_status_collection = db['queue_status']
active_checkins_collection = db['active_checkins']
emergency_alerts_collection = db['emergency_alerts']
hottest_street_cache_collection = db['hottest_street_cache']
events_collection = db['events']
chat_messages_collection = db['chat_messages']
license_alerts_collection = db['license_alerts']
trains_history_collection = db['trains_history']
flights_history_collection = db['flights_history']
station_alerts_collection = db['station_alerts']  # For "sin taxis" and "barandilla" alerts
invitations_collection = db['invitations']  # For invitation codes
registration_requests_collection = db['registration_requests']  # For pending registrations
support_tickets_collection = db['support_tickets']
support_messages_collection = db['support_messages']

# ============== USER MODELS ==============

class UserInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    hashed_password: str
    phone: Optional[str] = None
    role: str = "user"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class UserCreate(BaseModel):
    username: str
    password: str
    phone: Optional[str] = None
    role: str = "user"

class UserRegister(BaseModel):
    """Model for public user registration"""
    username: str
    password: str
    full_name: str
    license_number: str
    phone: Optional[str] = None
    preferred_shift: Optional[str] = "all"

class UserUpdate(BaseModel):
    phone: Optional[str] = None
    role: Optional[str] = None

class UserProfileUpdate(BaseModel):
    """Model for user self-profile update"""
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    preferred_shift: Optional[str] = None

class PasswordChange(BaseModel):
    current_password: Optional[str] = None
    new_password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    full_name: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    role: str
    preferred_shift: Optional[str] = "all"
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# ============== AUTH HELPER FUNCTIONS ==============

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify a JWT token and return the payload. Raises JWTError if invalid."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[dict]:
    if credentials is None:
        return None
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
        user = await users_collection.find_one({"id": user_id})
        return user
    except JWTError:
        return None

async def get_current_user_required(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user_required(credentials)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    return user

async def get_moderator_or_admin_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    user = await get_current_user_required(credentials)
    if user.get("role") not in ["admin", "moderator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de moderador o administrador"
        )
    return user
