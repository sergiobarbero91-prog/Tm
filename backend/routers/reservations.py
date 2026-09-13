"""
Reservation management system for taxi drivers.
Allows creating, offering, accepting, and cancelling reservations.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import uuid
import os
from pymongo import MongoClient, DESCENDING

router = APIRouter(prefix="/reservations", tags=["reservations"])

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME", "taximeter_madrid")
mongo_client = MongoClient(MONGO_URL)
db = mongo_client[DB_NAME]
reservations_col = db["reservations"]
reservation_logs_col = db["reservation_logs"]

# Ensure indexes
reservations_col.create_index("creator_id")
reservations_col.create_index("status")
reservations_col.create_index("date")
reservations_col.create_index("accepted_by_id")
reservation_logs_col.create_index("reservation_id")


# ============================================================
# Models
# ============================================================

class CreateReservation(BaseModel):
    date: str  # YYYY-MM-DD
    time: str  # HH:MM
    pickup_address: str
    destination: str
    passenger_name: str
    passenger_phone: str


class CancelReservation(BaseModel):
    reason: str  # "cliente_cancelo" | "yo_me_encargo"


# ============================================================
# Auth dependency (reuse from server.py pattern)
# ============================================================

from fastapi import Request

async def get_current_user(request: Request):
    """Extract current user from auth header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autorizado")

    token = auth_header.split(" ")[1]
    import jwt
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise HTTPException(status_code=500, detail="Server config error")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")

        users_col = db["users"]
        user = users_col.find_one({"id": user_id}, {"_id": 0, "password": 0})
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")


def _log_action(reservation_id: str, action: str, actor_id: str, actor_name: str, details: str = ""):
    """Log a reservation action for audit trail."""
    reservation_logs_col.insert_one({
        "reservation_id": reservation_id,
        "action": action,
        "actor_id": actor_id,
        "actor_name": actor_name,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


def _serialize_reservation(r: dict) -> dict:
    """Remove MongoDB _id and return clean dict."""
    r.pop("_id", None)
    return r


# ============================================================
# Endpoints
# ============================================================

@router.post("")
async def create_reservation(data: CreateReservation, user=Depends(get_current_user)):
    """Create a new reservation."""
    reservation = {
        "id": str(uuid.uuid4()),
        "creator_id": user["id"],
        "creator_name": user.get("name", user.get("username", "Desconocido")),
        "date": data.date,
        "time": data.time,
        "pickup_address": data.pickup_address,
        "destination": data.destination,
        "passenger_name": data.passenger_name,
        "passenger_phone": data.passenger_phone,
        "status": "pendiente",
        "offered_at": None,
        "accepted_by_id": None,
        "accepted_by_name": None,
        "accepted_at": None,
        "cancel_reason": None,
        "cancelled_by_id": None,
        "cancelled_by_name": None,
        "cancelled_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    reservations_col.insert_one(reservation)
    _log_action(reservation["id"], "created", user["id"], reservation["creator_name"], f"Reserva creada para {data.date} {data.time}")

    return _serialize_reservation(reservation)


@router.get("")
async def get_my_reservations(user=Depends(get_current_user)):
    """Get all reservations created by the current user."""
    results = list(reservations_col.find(
        {"creator_id": user["id"]},
        {"_id": 0}
    ).sort("date", DESCENDING))
    return {"reservations": results}


@router.get("/offered")
async def get_offered_reservations(user=Depends(get_current_user)):
    """Get all reservations that are currently offered (available to accept)."""
    results = list(reservations_col.find(
        {"status": "ofertada", "creator_id": {"$ne": user["id"]}},
        {"_id": 0}
    ).sort([("date", 1), ("time", 1)]))
    return {"reservations": results}


@router.get("/accepted")
async def get_accepted_reservations(user=Depends(get_current_user)):
    """Get reservations accepted by the current user."""
    results = list(reservations_col.find(
        {"accepted_by_id": user["id"]},
        {"_id": 0}
    ).sort("date", DESCENDING))
    return {"reservations": results}


@router.get("/logs")
async def get_reservation_logs(user=Depends(get_current_user)):
    """Get acceptance logs (who accepted which reservations)."""
    logs = list(reservation_logs_col.find(
        {"action": {"$in": ["accepted", "cancelled"]}},
        {"_id": 0}
    ).sort("timestamp", DESCENDING).limit(50))
    return {"logs": logs}


@router.get("/calendar/{year}/{month}")
async def get_calendar_reservations(year: int, month: int, user=Depends(get_current_user)):
    """Get reservations for a specific month (user's own + accepted)."""
    date_prefix = f"{year:04d}-{month:02d}"
    results = list(reservations_col.find(
        {
            "date": {"$regex": f"^{date_prefix}"},
            "$or": [
                {"creator_id": user["id"]},
                {"accepted_by_id": user["id"]}
            ]
        },
        {"_id": 0}
    ).sort([("date", 1), ("time", 1)]))
    return {"reservations": results}


@router.put("/{reservation_id}/offer")
async def offer_reservation(reservation_id: str, user=Depends(get_current_user)):
    """Offer a reservation so other drivers can accept it."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if reservation["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Solo el creador puede ofertar esta reserva")
    if reservation["status"] != "pendiente":
        raise HTTPException(status_code=400, detail=f"No se puede ofertar una reserva en estado '{reservation['status']}'")

    now = datetime.now(timezone.utc).isoformat()
    reservations_col.update_one(
        {"id": reservation_id},
        {"$set": {"status": "ofertada", "offered_at": now, "updated_at": now}}
    )
    _log_action(reservation_id, "offered", user["id"], reservation["creator_name"],
                f"Reserva ofertada: {reservation['date']} {reservation['time']} - {reservation['pickup_address']}")

    return {"success": True, "message": "Reserva ofertada correctamente"}


@router.put("/{reservation_id}/accept")
async def accept_reservation(reservation_id: str, user=Depends(get_current_user)):
    """Accept an offered reservation."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if reservation["status"] != "ofertada":
        raise HTTPException(status_code=400, detail="Esta reserva ya no está disponible")
    if reservation["creator_id"] == user["id"]:
        raise HTTPException(status_code=400, detail="No puedes aceptar tu propia reserva")

    acceptor_name = user.get("name", user.get("username", "Desconocido"))
    now = datetime.now(timezone.utc).isoformat()

    reservations_col.update_one(
        {"id": reservation_id},
        {"$set": {
            "status": "aceptada",
            "accepted_by_id": user["id"],
            "accepted_by_name": acceptor_name,
            "accepted_at": now,
            "updated_at": now
        }}
    )
    _log_action(reservation_id, "accepted", user["id"], acceptor_name,
                f"Reserva aceptada de {reservation['creator_name']}: {reservation['date']} {reservation['time']} - {reservation['pickup_address']}")

    return {
        "success": True,
        "message": "Reserva aceptada correctamente",
        "notification": {
            "to": reservation["creator_id"],
            "creator_name": reservation["creator_name"],
            "acceptor_name": acceptor_name,
            "reservation_date": reservation["date"],
            "reservation_time": reservation["time"]
        }
    }


@router.put("/{reservation_id}/cancel")
async def cancel_reservation(reservation_id: str, data: CancelReservation, user=Depends(get_current_user)):
    """Cancel an accepted reservation. Only the creator can cancel, and only up to 1 hour before."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if reservation["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Solo el creador puede cancelar esta reserva")
    if reservation["status"] not in ("ofertada", "aceptada"):
        raise HTTPException(status_code=400, detail=f"No se puede cancelar una reserva en estado '{reservation['status']}'")

    # Check 1-hour rule for accepted reservations
    if reservation["status"] == "aceptada":
        try:
            import pytz
            madrid_tz = pytz.timezone("Europe/Madrid")
            reservation_dt = datetime.strptime(f"{reservation['date']} {reservation['time']}", "%Y-%m-%d %H:%M")
            reservation_dt = madrid_tz.localize(reservation_dt)
            now_madrid = datetime.now(madrid_tz)
            if (reservation_dt - now_madrid) < timedelta(hours=1):
                raise HTTPException(status_code=400, detail="No se puede cancelar menos de 1 hora antes de la reserva")
        except (ValueError, HTTPException) as e:
            if isinstance(e, HTTPException):
                raise
            pass

    reason_text = "Cliente canceló" if data.reason == "cliente_cancelo" else "El conductor se encarga"
    now = datetime.now(timezone.utc).isoformat()
    creator_name = user.get("name", user.get("username", "Desconocido"))

    reservations_col.update_one(
        {"id": reservation_id},
        {"$set": {
            "status": "cancelada",
            "cancel_reason": data.reason,
            "cancelled_by_id": user["id"],
            "cancelled_by_name": creator_name,
            "cancelled_at": now,
            "updated_at": now
        }}
    )
    _log_action(reservation_id, "cancelled", user["id"], creator_name,
                f"Reserva cancelada ({reason_text}): {reservation['date']} {reservation['time']}")

    response = {
        "success": True,
        "message": f"Reserva cancelada: {reason_text}"
    }

    # Include notification info if it was accepted by someone
    if reservation.get("accepted_by_id"):
        response["notification"] = {
            "to": reservation["accepted_by_id"],
            "acceptor_name": reservation["accepted_by_name"],
            "creator_name": creator_name,
            "reason": reason_text,
            "reservation_date": reservation["date"],
            "reservation_time": reservation["time"]
        }

    return response


@router.put("/{reservation_id}/complete")
async def complete_reservation(reservation_id: str, user=Depends(get_current_user)):
    """Mark a reservation as completed."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")

    # Both creator and acceptor can mark as completed
    if reservation["creator_id"] != user["id"] and reservation.get("accepted_by_id") != user["id"]:
        raise HTTPException(status_code=403, detail="No tienes permiso para completar esta reserva")

    if reservation["status"] not in ("pendiente", "aceptada"):
        raise HTTPException(status_code=400, detail=f"No se puede completar una reserva en estado '{reservation['status']}'")

    now = datetime.now(timezone.utc).isoformat()
    actor_name = user.get("name", user.get("username", "Desconocido"))

    reservations_col.update_one(
        {"id": reservation_id},
        {"$set": {"status": "completada", "updated_at": now}}
    )
    _log_action(reservation_id, "completed", user["id"], actor_name,
                f"Reserva completada: {reservation['date']} {reservation['time']}")

    return {"success": True, "message": "Reserva marcada como completada"}


@router.put("/{reservation_id}/unoffer")
async def unoffer_reservation(reservation_id: str, user=Depends(get_current_user)):
    """Remove a reservation from offered status back to pending."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if reservation["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Solo el creador puede retirar la oferta")
    if reservation["status"] != "ofertada":
        raise HTTPException(status_code=400, detail="La reserva no está en estado ofertada")

    now = datetime.now(timezone.utc).isoformat()
    reservations_col.update_one(
        {"id": reservation_id},
        {"$set": {"status": "pendiente", "offered_at": None, "updated_at": now}}
    )

    return {"success": True, "message": "Oferta retirada"}


@router.delete("/{reservation_id}")
async def delete_reservation(reservation_id: str, user=Depends(get_current_user)):
    """Delete a reservation. Only the creator can delete, and only if status is pendiente or ofertada."""
    reservation = reservations_col.find_one({"id": reservation_id}, {"_id": 0})
    if not reservation:
        raise HTTPException(status_code=404, detail="Reserva no encontrada")
    if reservation["creator_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Solo el creador puede eliminar esta reserva")
    if reservation["status"] not in ("pendiente", "ofertada"):
        raise HTTPException(status_code=400, detail=f"No se puede eliminar una reserva en estado '{reservation['status']}'")

    reservations_col.delete_one({"id": reservation_id})
    _log_action(reservation_id, "deleted", user["id"],
                user.get("name", user.get("username", "Desconocido")),
                f"Reserva eliminada: {reservation['date']} {reservation['time']} - {reservation['pickup_address']}")

    return {"success": True, "message": "Reserva eliminada correctamente"}
