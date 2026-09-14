"""
Rides / Emisora — Uber-like extension for TaxiDash.

Introduces a "cliente" role separate from the existing driver/owner accounts:
- Cliente authenticates by phone + OTP (Twilio Verify, with DEV fallback when
  credentials are empty). No password.
- Cliente can request a ride ASAP or scheduled for a specific datetime.
- Driver can generate a QR code linked to their account. Clients registering
  through that QR are "associated" with the driver.
- Dispatcher rules:
    * ASAP → immediately open to all online drivers.
    * Scheduled → offered exclusively to the associated driver until 6 hours
      before service; then it falls into the open offers pool.

This module lives under /api/rides.
"""
from __future__ import annotations

import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field, validator

from shared import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    clients_collection,
    otp_codes_collection,
    rides_collection,
    driver_qrs_collection,
    users_collection,
    password_reset_tokens_collection,
    create_access_token,
    security,
    get_current_user_required,
    logger,
    get_password_hash,
    verify_password,
)
from email_service import send_email

router = APIRouter(prefix="/rides", tags=["rides"])


# ─────────────────────────── Twilio helper ────────────────────────────
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_VERIFY_SERVICE_SID = os.environ.get("TWILIO_VERIFY_SERVICE_SID", "").strip()

DEV_OTP_MODE = not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_VERIFY_SERVICE_SID)
DEV_OTP_CODE = "123456"


def _twilio_client():
    """Lazy import so the module still loads when the twilio package is missing."""
    from twilio.rest import Client  # type: ignore
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


async def _send_otp(phone: str) -> str:
    """Send an OTP to the phone. Returns 'sent' or 'dev'. Raises HTTPException on real errors."""
    if DEV_OTP_MODE:
        # Persist code so verify path finds it. Overwrite existing entry for same phone.
        await otp_codes_collection.update_one(
            {"phone": phone},
            {"$set": {
                "phone": phone,
                "code": DEV_OTP_CODE,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
                "mode": "dev",
            }},
            upsert=True,
        )
        logger.info(f"[rides/OTP-DEV] phone={phone} code={DEV_OTP_CODE}")
        return "dev"

    # Real Twilio Verify send
    try:
        client = _twilio_client()
        client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verifications.create(
            to=phone, channel="sms"
        )
        return "sent"
    except Exception as exc:  # pragma: no cover - external dependency
        logger.exception("[rides] Twilio send OTP failed")
        raise HTTPException(status_code=502, detail=f"No se pudo enviar el SMS: {exc}")


async def _verify_otp(phone: str, code: str) -> bool:
    """Return True if the code is valid for that phone."""
    if DEV_OTP_MODE:
        doc = await otp_codes_collection.find_one({"phone": phone})
        if not doc:
            return False
        if doc.get("code") != code:
            return False
        # Optional expiry check
        exp = doc.get("expires_at")
        if exp:
            if isinstance(exp, datetime):
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    return False
        # Burn code (dev mode) so it can't be reused
        await otp_codes_collection.delete_one({"phone": phone})
        return True

    try:
        client = _twilio_client()
        check = client.verify.v2.services(TWILIO_VERIFY_SERVICE_SID).verification_checks.create(
            to=phone, code=code
        )
        return check.status == "approved"
    except Exception:  # pragma: no cover
        logger.exception("[rides] Twilio verify OTP failed")
        return False


# ────────────────────────── Cliente auth models ────────────────────────
class SendOtpBody(BaseModel):
    phone: str  # E.164 format, e.g. +34611223344

    @validator("phone")
    def _norm_phone(cls, v: str) -> str:  # noqa: N805
        v = v.strip().replace(" ", "").replace("-", "")
        if not v.startswith("+"):
            raise ValueError("Teléfono debe ir en formato E.164 (ej. +34611223344)")
        if len(v) < 8 or len(v) > 16:
            raise ValueError("Teléfono con longitud inválida")
        return v


class VerifyOtpBody(BaseModel):
    phone: str
    code: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    associated_driver_qr: Optional[str] = None  # QR token from driver invite

    @validator("phone")
    def _norm_phone(cls, v: str) -> str:  # noqa: N805
        return SendOtpBody._norm_phone(v)


class ClientResponse(BaseModel):
    id: str
    phone: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    associated_driver_id: Optional[str] = None
    created_at: datetime


class ClientTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    client: ClientResponse


# ─────────────────────── Cliente authorization ─────────────────────────
async def get_current_client_required(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Auth guard for cliente-only endpoints. Cliente JWTs carry ct='client'."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="No autenticado")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    if payload.get("ct") != "client":
        raise HTTPException(status_code=403, detail="Solo clientes")
    cid = payload.get("sub")
    doc = await clients_collection.find_one({"id": cid})
    if not doc:
        raise HTTPException(status_code=401, detail="Cliente no encontrado")
    return doc


# ─────────────────────────── OTP endpoints ────────────────────────────
@router.post("/client/send-otp")
async def client_send_otp(body: SendOtpBody):
    status_ = await _send_otp(body.phone)
    return {"status": status_, "dev_mode": DEV_OTP_MODE}


@router.post("/client/verify-otp", response_model=ClientTokenResponse)
async def client_verify_otp(body: VerifyOtpBody):
    ok = await _verify_otp(body.phone, body.code)
    if not ok:
        raise HTTPException(status_code=400, detail="Código OTP incorrecto o caducado")

    doc = await clients_collection.find_one({"phone": body.phone})
    associated_driver_id: Optional[str] = None
    if body.associated_driver_qr:
        qr = await driver_qrs_collection.find_one({"token": body.associated_driver_qr})
        if qr:
            associated_driver_id = qr.get("driver_id")

    if doc:
        # Existing client — update names/associated driver if provided this time
        update: dict = {}
        if body.first_name and not doc.get("first_name"):
            update["first_name"] = body.first_name.strip()
        if body.last_name and not doc.get("last_name"):
            update["last_name"] = body.last_name.strip()
        if associated_driver_id and not doc.get("associated_driver_id"):
            update["associated_driver_id"] = associated_driver_id
        if update:
            update["updated_at"] = datetime.now(timezone.utc)
            await clients_collection.update_one({"id": doc["id"]}, {"$set": update})
            doc.update(update)
    else:
        # Registration path — require first & last name
        if not (body.first_name and body.last_name):
            raise HTTPException(
                status_code=400,
                detail="Para registrarte necesitamos tu nombre y apellido",
            )
        import uuid
        doc = {
            "id": str(uuid.uuid4()),
            "phone": body.phone,
            "first_name": body.first_name.strip(),
            "last_name": body.last_name.strip(),
            "associated_driver_id": associated_driver_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        await clients_collection.insert_one(doc)

    token = create_access_token(
        {"sub": doc["id"], "ct": "client"},
        expires_delta=timedelta(days=30),
    )
    return ClientTokenResponse(
        access_token=token,
        client=ClientResponse(
            id=doc["id"],
            phone=doc["phone"],
            first_name=doc.get("first_name", ""),
            last_name=doc.get("last_name", ""),
            email=doc.get("email"),
            associated_driver_id=doc.get("associated_driver_id"),
            created_at=doc["created_at"],
        ),
    )


@router.get("/client/me", response_model=ClientResponse)
async def client_me(current: dict = Depends(get_current_client_required)):
    return ClientResponse(
        id=current["id"],
        phone=current["phone"],
        first_name=current.get("first_name", ""),
        last_name=current.get("last_name", ""),
        email=current.get("email"),
        associated_driver_id=current.get("associated_driver_id"),
        created_at=current["created_at"],
    )


# ─────────────── Client auth via driver code (NO SMS) ─────────────────
class ClientAuthenticateBody(BaseModel):
    phone: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    qr_token: str
    verification_code: str  # 6-digit code shown on the driver's screen
    # Optional password the client can set during code-based signup so they
    # can log back in later without asking the taxista for a new code.
    password: Optional[str] = None
    # Optional email so the client can later use "olvidé mi contraseña".
    email: Optional[str] = None

    @validator("phone")
    def _norm_phone(cls, v: str) -> str:  # noqa: N805
        return SendOtpBody._norm_phone(v)

    @validator("verification_code")
    def _norm_code(cls, v: str) -> str:  # noqa: N805
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("El código debe tener 6 dígitos")
        return v

    @validator("password")
    def _norm_pw(cls, v: Optional[str]) -> Optional[str]:  # noqa: N805
        if v is None or v == "":
            return None
        if len(v) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres")
        return v

    @validator("email")
    def _norm_em(cls, v: Optional[str]) -> Optional[str]:  # noqa: N805
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Email no válido")
        return v


class ClientLoginBody(BaseModel):
    """Password-based login for returning clients (no QR/code needed)."""
    phone: str
    password: str

    @validator("phone")
    def _norm_phone(cls, v: str) -> str:  # noqa: N805
        return SendOtpBody._norm_phone(v)


class ClientSetPasswordBody(BaseModel):
    password: str

    @validator("password")
    def _norm(cls, v: str) -> str:  # noqa: N805
        if len(v) < 4:
            raise ValueError("La contraseña debe tener al menos 4 caracteres")
        return v


def _client_token(doc: dict) -> ClientTokenResponse:
    token = create_access_token({"sub": doc["id"], "ct": "client"}, expires_delta=timedelta(days=30))
    return ClientTokenResponse(
        access_token=token,
        client=ClientResponse(
            id=doc["id"],
            phone=doc["phone"],
            first_name=doc.get("first_name", ""),
            last_name=doc.get("last_name", ""),
            email=doc.get("email"),
            associated_driver_id=doc.get("associated_driver_id"),
            created_at=doc["created_at"],
        ),
    )


@router.post("/client/authenticate", response_model=ClientTokenResponse)
async def client_authenticate(body: ClientAuthenticateBody):
    """Register or log in a client using the code shown on the taxista's screen.
    Optionally sets a password so the client can log back in with phone+password
    later, without needing another code from the driver.
    """
    qr = await driver_qrs_collection.find_one({"token": body.qr_token})
    if not qr:
        raise HTTPException(status_code=404, detail="QR no válido")
    expected = qr.get("verification_code")
    if not expected or body.verification_code != expected:
        raise HTTPException(status_code=400, detail="Código incorrecto. Pídele el código al taxista.")

    associated_driver_id = qr["driver_id"]

    doc = await clients_collection.find_one({"phone": body.phone})
    now = datetime.now(timezone.utc)
    if doc:
        update: dict = {"updated_at": now}
        if body.first_name and not doc.get("first_name"):
            update["first_name"] = body.first_name.strip()
        if body.last_name and not doc.get("last_name"):
            update["last_name"] = body.last_name.strip()
        if body.password:
            update["password_hash"] = get_password_hash(body.password)
        if body.email and not doc.get("email"):
            update["email"] = body.email
        # Always update the last associated driver so newest QR wins
        update["associated_driver_id"] = associated_driver_id
        await clients_collection.update_one({"id": doc["id"]}, {"$set": update})
        doc.update(update)
    else:
        if not (body.first_name and body.last_name):
            raise HTTPException(
                status_code=400,
                detail="Para registrarte necesitamos tu nombre y apellido",
            )
        import uuid
        doc = {
            "id": str(uuid.uuid4()),
            "phone": body.phone,
            "first_name": body.first_name.strip(),
            "last_name": body.last_name.strip(),
            "email": body.email,
            "associated_driver_id": associated_driver_id,
            "password_hash": get_password_hash(body.password) if body.password else None,
            "created_at": now,
            "updated_at": now,
        }
        await clients_collection.insert_one(doc)

    return _client_token(doc)


@router.post("/client/login", response_model=ClientTokenResponse)
async def client_login(body: ClientLoginBody):
    """Log in an existing client using phone + password. No QR/code required."""
    doc = await clients_collection.find_one({"phone": body.phone})
    if not doc:
        raise HTTPException(status_code=404, detail="No hay cuenta con ese teléfono")
    pw_hash = doc.get("password_hash")
    if not pw_hash:
        raise HTTPException(
            status_code=400,
            detail="Esta cuenta no tiene contraseña. Pídele al taxista un código nuevo para acceder y esta vez fija tu contraseña.",
        )
    if not verify_password(body.password, pw_hash):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    return _client_token(doc)


@router.post("/client/set-password", status_code=204)
async def client_set_password(
    body: ClientSetPasswordBody,
    current: dict = Depends(get_current_client_required),
):
    """Allow a logged-in client to set/change their password."""
    await clients_collection.update_one(
        {"id": current["id"]},
        {"$set": {"password_hash": get_password_hash(body.password), "updated_at": datetime.now(timezone.utc)}},
    )
    return


class ClientSetEmailBody(BaseModel):
    email: str

    @validator("email")
    def _norm(cls, v: str) -> str:  # noqa: N805
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Email no válido")
        return v


@router.post("/client/set-email", status_code=204)
async def client_set_email(
    body: ClientSetEmailBody,
    current: dict = Depends(get_current_client_required),
):
    """Set or update the client's email so they can use password recovery."""
    # Uniqueness check across clients
    existing = await clients_collection.find_one({"email": body.email, "id": {"$ne": current["id"]}})
    if existing:
        raise HTTPException(status_code=400, detail="Ese email ya está en uso")
    await clients_collection.update_one(
        {"id": current["id"]},
        {"$set": {"email": body.email, "updated_at": datetime.now(timezone.utc)}},
    )
    return


# ─────────────────── Client password recovery (email) ─────────────────
class ClientForgotPasswordBody(BaseModel):
    email: str


class ClientResetPasswordBody(BaseModel):
    token: str
    new_password: str


def _client_reset_url(token: str) -> str:
    base = (os.environ.get("FRONTEND_PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}/?reset_token={token}&role=client" if base else f"/?reset_token={token}&role=client"


@router.post("/client/forgot-password")
async def client_forgot_password(body: ClientForgotPasswordBody):
    """Send a reset link to the client's email. Always returns 200 to
    prevent email enumeration. If the client has no email on file the
    response is still 200 but no email is sent — the frontend already
    tells the user to ask their taxista for a fresh code."""
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Email no válido")
    doc = await clients_collection.find_one({"email": email})
    if not doc:
        logger.info(f"[rides/client-forgot] Unknown email requested reset: {email}")
        return {"status": "ok"}

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    await password_reset_tokens_collection.insert_one({
        "token": token,
        "role": "client",
        "user_id": doc["id"],
        "email": email,
        "created_at": now,
        "expires_at": now + timedelta(hours=1),
        "used": False,
    })
    url = _client_reset_url(token)
    name = doc.get("first_name") or "cliente"
    text = (
        f"Hola {name},\n\n"
        "Recibimos una petición para restablecer tu contraseña en TaxiDash.\n\n"
        f"Abre este enlace (válido durante 1 hora):\n\n{url}\n\n"
        "Si no lo pediste tú, ignora este email."
    )
    html = (
        f"<p>Hola <strong>{name}</strong>,</p>"
        "<p>Recibimos una petición para restablecer tu contraseña en TaxiDash.</p>"
        f"<p><a href=\"{url}\" style=\"background:#F59E0B;color:#0F172A;"
        "padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:700\">"
        "Restablecer contraseña</a></p>"
        "<p style=\"font-size:12px;color:#666\">Este enlace caduca en 1 hora. "
        "Si no lo pediste tú, ignora este mensaje.</p>"
    )
    send_email(email, "TaxiDash — Restablecer contraseña", text, html)
    return {"status": "ok"}


@router.post("/client/reset-password")
async def client_reset_password(body: ClientResetPasswordBody):
    if not body.new_password or len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 4 caracteres")
    doc = await password_reset_tokens_collection.find_one({"token": body.token})
    if not doc or doc.get("used") or doc.get("role") != "client":
        raise HTTPException(status_code=400, detail="Enlace inválido o ya utilizado")
    exp = doc.get("expires_at")
    if isinstance(exp, datetime):
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="El enlace ha caducado. Solicita otro.")

    await clients_collection.update_one(
        {"id": doc["user_id"]},
        {"$set": {"password_hash": get_password_hash(body.new_password), "updated_at": datetime.now(timezone.utc)}},
    )
    await password_reset_tokens_collection.update_one(
        {"token": body.token},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
    )
    return {"status": "ok"}


# ───────────────────────── Driver QR endpoints ─────────────────────────
class DriverQrResponse(BaseModel):
    token: str
    url: str  # deep-link a la pantalla de registro cliente
    driver_id: str
    driver_name: str
    verification_code: str  # 6-digit code the driver shows the client


def _gen_code() -> str:
    return f"{random.randint(0, 999999):06d}"


@router.post("/driver/qr", response_model=DriverQrResponse)
async def driver_generate_qr(current: dict = Depends(get_current_user_required)):
    """A driver/owner generates a QR + verification code. The client
    scans the QR and enters the 6-digit code the taxista tells them
    to prove they're physically present. Idempotent: reuses existing
    token but rotates the code if older than 24h."""
    if current.get("role") not in ("conductor", "propietario", "user", "admin", "moderator"):
        raise HTTPException(status_code=403, detail="Solo taxistas pueden generar QR")

    now = datetime.now(timezone.utc)
    existing = await driver_qrs_collection.find_one({"driver_id": current["id"]})
    if existing:
        token = existing["token"]
        code = existing.get("verification_code")
        code_updated = existing.get("code_updated_at")
        # Rotate if missing or older than 24h
        needs_rotation = not code or not code_updated or (
            isinstance(code_updated, datetime)
            and (code_updated.tzinfo and code_updated < now - timedelta(hours=24)
                 or not code_updated.tzinfo and code_updated < now.replace(tzinfo=None) - timedelta(hours=24))
        )
        if needs_rotation:
            code = _gen_code()
            await driver_qrs_collection.update_one(
                {"driver_id": current["id"]},
                {"$set": {"verification_code": code, "code_updated_at": now}},
            )
    else:
        token = secrets.token_urlsafe(10)
        code = _gen_code()
        await driver_qrs_collection.insert_one({
            "token": token,
            "driver_id": current["id"],
            "driver_username": current.get("username"),
            "verification_code": code,
            "code_updated_at": now,
            "created_at": now,
        })

    frontend_base = os.environ.get("FRONTEND_PUBLIC_URL", "").rstrip("/")
    return DriverQrResponse(
        token=token,
        url=f"{frontend_base}/?cliente_qr={token}" if frontend_base else f"/?cliente_qr={token}",
        driver_id=current["id"],
        driver_name=current.get("full_name") or current.get("username") or "Taxista",
        verification_code=code,
    )


@router.post("/driver/qr/rotate", response_model=DriverQrResponse)
async def driver_rotate_qr_code(current: dict = Depends(get_current_user_required)):
    """Force-generate a fresh verification code for the driver's QR."""
    if current.get("role") not in ("conductor", "propietario", "user", "admin", "moderator"):
        raise HTTPException(status_code=403, detail="Solo taxistas pueden rotar el código")
    now = datetime.now(timezone.utc)
    doc = await driver_qrs_collection.find_one({"driver_id": current["id"]})
    if not doc:
        # Delegate to the generator, which will create both token and code
        return await driver_generate_qr(current)
    new_code = _gen_code()
    await driver_qrs_collection.update_one(
        {"driver_id": current["id"]},
        {"$set": {"verification_code": new_code, "code_updated_at": now}},
    )
    frontend_base = os.environ.get("FRONTEND_PUBLIC_URL", "").rstrip("/")
    return DriverQrResponse(
        token=doc["token"],
        url=f"{frontend_base}/?cliente_qr={doc['token']}" if frontend_base else f"/?cliente_qr={doc['token']}",
        driver_id=current["id"],
        driver_name=current.get("full_name") or current.get("username") or "Taxista",
        verification_code=new_code,
    )


@router.get("/qr/{token}/info")
async def qr_info(token: str):
    """Public endpoint the client's registration screen calls to display
    which driver they're being associated with."""
    qr = await driver_qrs_collection.find_one({"token": token})
    if not qr:
        raise HTTPException(status_code=404, detail="Código QR no válido")
    driver = await users_collection.find_one({"id": qr["driver_id"]})
    if not driver:
        raise HTTPException(status_code=404, detail="Taxista no encontrado")
    return {
        "token": token,
        "driver_id": driver["id"],
        "driver_name": driver.get("full_name") or driver.get("username"),
        "license_number": driver.get("license_number"),
    }


# ─────────────────────────── Ride models ───────────────────────────────
class RideCreateBody(BaseModel):
    origin: str
    destination: str
    ride_type: str  # "asap" | "scheduled"
    scheduled_at: Optional[datetime] = None  # required if ride_type == "scheduled"
    notes: Optional[str] = None
    passengers: Optional[int] = 1

    @validator("ride_type")
    def _rt(cls, v: str) -> str:  # noqa: N805
        if v not in ("asap", "scheduled"):
            raise ValueError("ride_type debe ser 'asap' o 'scheduled'")
        return v


class RideResponse(BaseModel):
    id: str
    origin: str
    destination: str
    ride_type: str
    scheduled_at: Optional[datetime]
    status: str  # pending, accepted, in_progress, completed, cancelled
    dispatch_scope: str  # "assigned" (exclusive to associated driver) | "open"
    client_id: str
    client_name: str
    client_phone: str
    associated_driver_id: Optional[str]
    accepted_by_driver_id: Optional[str]
    accepted_by_driver_name: Optional[str] = None
    notes: Optional[str]
    passengers: int
    created_at: datetime
    accepted_by_driver_phone: Optional[str] = None


def _ride_to_response(doc: dict) -> RideResponse:
    return RideResponse(
        id=doc["id"],
        origin=doc["origin"],
        destination=doc["destination"],
        ride_type=doc["ride_type"],
        scheduled_at=doc.get("scheduled_at"),
        status=doc["status"],
        dispatch_scope=doc["dispatch_scope"],
        client_id=doc["client_id"],
        client_name=doc.get("client_name", ""),
        client_phone=doc.get("client_phone", ""),
        associated_driver_id=doc.get("associated_driver_id"),
        accepted_by_driver_id=doc.get("accepted_by_driver_id"),
        accepted_by_driver_name=doc.get("accepted_by_driver_name"),
        accepted_by_driver_phone=doc.get("accepted_by_driver_phone"),
        notes=doc.get("notes"),
        passengers=doc.get("passengers", 1),
        created_at=doc["created_at"],
    )


# ────────────────────────── Ride endpoints (client) ────────────────────
@router.post("/rides", response_model=RideResponse)
async def create_ride(body: RideCreateBody, current: dict = Depends(get_current_client_required)):
    import uuid
    now = datetime.now(timezone.utc)

    if body.ride_type == "scheduled":
        if not body.scheduled_at:
            raise HTTPException(status_code=400, detail="Falta la fecha del servicio")
        sched = body.scheduled_at
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        if sched <= now + timedelta(minutes=10):
            raise HTTPException(status_code=400, detail="La reserva debe ser al menos 10 minutos en el futuro")
    else:
        sched = None

    associated_driver_id = current.get("associated_driver_id")

    # Dispatch scope:
    #   ASAP → always open to everyone
    #   Scheduled + associated_driver + >6h before service → exclusive
    #   Scheduled + no associated driver (or <6h) → open
    dispatch_scope = "open"
    if body.ride_type == "scheduled" and associated_driver_id and sched:
        hours_until = (sched - now).total_seconds() / 3600.0
        if hours_until > 6:
            dispatch_scope = "assigned"

    doc = {
        "id": str(uuid.uuid4()),
        "origin": body.origin.strip(),
        "destination": body.destination.strip(),
        "ride_type": body.ride_type,
        "scheduled_at": sched,
        "status": "pending",
        "dispatch_scope": dispatch_scope,
        "client_id": current["id"],
        "client_name": f"{current.get('first_name', '')} {current.get('last_name', '')}".strip(),
        "client_phone": current["phone"],
        "associated_driver_id": associated_driver_id if dispatch_scope == "assigned" else associated_driver_id,
        "accepted_by_driver_id": None,
        "accepted_by_driver_name": None,
        "notes": body.notes,
        "passengers": max(1, min(int(body.passengers or 1), 8)),
        "created_at": now,
        "updated_at": now,
    }
    await rides_collection.insert_one(doc)
    return _ride_to_response(doc)


@router.get("/rides/mine", response_model=List[RideResponse])
async def client_list_my_rides(current: dict = Depends(get_current_client_required)):
    cursor = rides_collection.find({"client_id": current["id"]}).sort("created_at", -1).limit(50)
    return [_ride_to_response(d) async for d in cursor]


@router.post("/rides/{ride_id}/cancel", response_model=RideResponse)
async def cancel_ride(ride_id: str, current: dict = Depends(get_current_client_required)):
    doc = await rides_collection.find_one({"id": ride_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if doc["client_id"] != current["id"]:
        raise HTTPException(status_code=403, detail="No puedes cancelar este servicio")
    # Solo se puede cancelar antes de que empiece el trayecto.
    # - pending: nadie lo ha aceptado todavía
    # - accepted: un taxista lo aceptó pero aún no ha empezado
    # - in_progress / completed / cancelled: ya no se puede cancelar
    if doc["status"] not in ("pending", "accepted"):
        if doc["status"] == "in_progress":
            raise HTTPException(status_code=400, detail="El servicio ya está en curso y no se puede cancelar")
        raise HTTPException(status_code=400, detail=f"El servicio ya está {doc['status']}")
    await rides_collection.update_one(
        {"id": ride_id},
        {"$set": {"status": "cancelled", "updated_at": datetime.now(timezone.utc)}},
    )
    doc["status"] = "cancelled"
    return _ride_to_response(doc)


# ────────────────────────── Ride endpoints (driver) ────────────────────
async def _promote_scheduled_rides_near_deadline():
    """Move any 'assigned' scheduled ride whose service time is within 6h to 'open'.
    Called opportunistically on every driver list query."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=6)
    await rides_collection.update_many(
        {
            "status": "pending",
            "dispatch_scope": "assigned",
            "ride_type": "scheduled",
            "scheduled_at": {"$lte": cutoff},
        },
        {"$set": {"dispatch_scope": "open", "updated_at": now}},
    )


@router.get("/driver/assigned", response_model=List[RideResponse])
async def driver_list_assigned(current: dict = Depends(get_current_user_required)):
    """Rides that are currently reserved for this driver (before the 6h cutoff)."""
    await _promote_scheduled_rides_near_deadline()
    cursor = rides_collection.find({
        "status": "pending",
        "dispatch_scope": "assigned",
        "associated_driver_id": current["id"],
    }).sort("scheduled_at", 1).limit(50)
    return [_ride_to_response(d) async for d in cursor]


@router.get("/driver/offers", response_model=List[RideResponse])
async def driver_list_offers(current: dict = Depends(get_current_user_required)):
    """Open-market rides available to any online driver."""
    await _promote_scheduled_rides_near_deadline()
    cursor = rides_collection.find({
        "status": "pending",
        "dispatch_scope": "open",
    }).sort("created_at", -1).limit(50)
    return [_ride_to_response(d) async for d in cursor]


@router.get("/driver/active", response_model=List[RideResponse])
async def driver_list_active(current: dict = Depends(get_current_user_required)):
    """Rides this driver has already accepted/started (not completed/cancelled)."""
    cursor = rides_collection.find({
        "accepted_by_driver_id": current["id"],
        "status": {"$in": ["accepted", "in_progress"]},
    }).sort("created_at", -1).limit(50)
    return [_ride_to_response(d) async for d in cursor]


@router.post("/rides/{ride_id}/accept", response_model=RideResponse)
async def driver_accept_ride(ride_id: str, current: dict = Depends(get_current_user_required)):
    doc = await rides_collection.find_one({"id": ride_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if doc["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"El servicio ya está {doc['status']}")

    # Assigned rides may only be accepted by the associated driver
    if doc["dispatch_scope"] == "assigned" and doc.get("associated_driver_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Este servicio no está en oferta abierta todavía")

    # Race-safe: only accept if still pending
    driver_name = current.get("full_name") or current.get("username")
    driver_phone = current.get("phone")
    upd = await rides_collection.update_one(
        {"id": ride_id, "status": "pending"},
        {"$set": {
            "status": "accepted",
            "accepted_by_driver_id": current["id"],
            "accepted_by_driver_name": driver_name,
            "accepted_by_driver_phone": driver_phone,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    if upd.modified_count == 0:
        raise HTTPException(status_code=409, detail="Otro taxista lo aceptó antes")
    doc = await rides_collection.find_one({"id": ride_id})
    return _ride_to_response(doc)


@router.post("/rides/{ride_id}/start", response_model=RideResponse)
async def driver_start_ride(ride_id: str, current: dict = Depends(get_current_user_required)):
    doc = await rides_collection.find_one({"id": ride_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if doc.get("accepted_by_driver_id") != current["id"]:
        raise HTTPException(status_code=403, detail="No eres el taxista asignado a este servicio")
    if doc["status"] != "accepted":
        raise HTTPException(status_code=400, detail=f"El servicio está en estado {doc['status']}")
    await rides_collection.update_one(
        {"id": ride_id},
        {"$set": {"status": "in_progress", "updated_at": datetime.now(timezone.utc)}},
    )
    doc["status"] = "in_progress"
    return _ride_to_response(doc)


@router.post("/rides/{ride_id}/complete", response_model=RideResponse)
async def driver_complete_ride(ride_id: str, current: dict = Depends(get_current_user_required)):
    doc = await rides_collection.find_one({"id": ride_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if doc.get("accepted_by_driver_id") != current["id"]:
        raise HTTPException(status_code=403, detail="No eres el taxista asignado")
    if doc["status"] not in ("accepted", "in_progress"):
        raise HTTPException(status_code=400, detail=f"El servicio está en estado {doc['status']}")
    await rides_collection.update_one(
        {"id": ride_id},
        {"$set": {"status": "completed", "updated_at": datetime.now(timezone.utc)}},
    )
    doc["status"] = "completed"
    return _ride_to_response(doc)


@router.post("/rides/{ride_id}/reject", response_model=RideResponse)
async def driver_reject_assigned(ride_id: str, current: dict = Depends(get_current_user_required)):
    """Assigned driver can push a ride to the open pool without waiting for the 6h cutoff."""
    doc = await rides_collection.find_one({"id": ride_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Servicio no encontrado")
    if doc["dispatch_scope"] != "assigned" or doc.get("associated_driver_id") != current["id"]:
        raise HTTPException(status_code=403, detail="No puedes liberar este servicio")
    if doc["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"El servicio está en estado {doc['status']}")
    await rides_collection.update_one(
        {"id": ride_id},
        {"$set": {"dispatch_scope": "open", "updated_at": datetime.now(timezone.utc)}},
    )
    doc["dispatch_scope"] = "open"
    return _ride_to_response(doc)
