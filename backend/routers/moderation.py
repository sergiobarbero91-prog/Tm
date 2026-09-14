"""
Moderation System Router - Reports and Promotion Requests
Handles user reports, moderator reviews, and promotion petitions
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel
import uuid

from shared import (
    users_collection, get_current_user_required, 
    get_moderator_or_admin_user, get_admin_user, logger,
    POINTS_CONFIG, get_user_level
)
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection for new collections
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Collections
reports_collection = db['reports']
report_messages_collection = db['report_messages']
promotion_requests_collection = db['promotion_requests']

router = APIRouter(prefix="/moderation", tags=["Moderation"])

# ============== MODELS ==============

class ReportCreate(BaseModel):
    """Model for creating a report"""
    reported_user_id: Optional[str] = None  # Can be null for general reports
    reported_username: Optional[str] = None
    report_type: str  # inappropriate, spam, false_info, harassment, other
    description: str
    context: Optional[str] = None  # e.g., "chat message", "false alert", "event"
    context_id: Optional[str] = None  # ID of the related item
    media_base64: Optional[str] = None  # Base64 encoded image or video
    media_type: Optional[str] = None  # "image" or "video"

class ModeratorReview(BaseModel):
    """Model for moderator review"""
    approved: bool  # True = pass to admin, False = reject
    moderator_notes: Optional[str] = None

class AdminDecision(BaseModel):
    """Model for admin final decision"""
    approved: bool  # True = valid report, False = invalid
    admin_notes: Optional[str] = None
    ban_duration: Optional[str] = None  # "6h", "12h", "48h", "permanent", or null


class ReportMessageCreate(BaseModel):
    """Payload to post a new message in a report thread."""
    body: str


class ReportStatusUpdate(BaseModel):
    """Payload for flexible status changes (staff only)."""
    status: str  # 'in_progress' | 'awaiting_reporter' | 'resolved'
    note: Optional[str] = None

class PromotionDecision(BaseModel):
    """Model for promotion decision"""
    approved: bool
    notes: Optional[str] = None

# ============== REPORT TYPES ==============

REPORT_TYPES = {
    "inappropriate": "Comportamiento inapropiado",
    "spam": "Spam",
    "false_info": "Información falsa",
    "harassment": "Acoso",
    "other": "Otro"
}

# ============== HELPER FUNCTIONS ==============

async def check_and_create_promotion_request(user_id: str, total_points: int):
    """Check if user qualifies for promotion and create request if needed"""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        return
    
    current_role = user.get("role", "user")
    
    # Check for moderator promotion (1500+ points, current role is user)
    if total_points >= 1500 and current_role == "user":
        # Check if request already exists
        existing = await promotion_requests_collection.find_one({
            "user_id": user_id,
            "target_role": "moderator",
            "status": "pending"
        })
        if not existing:
            await promotion_requests_collection.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "username": user.get("username"),
                "full_name": user.get("full_name"),
                "current_role": current_role,
                "target_role": "moderator",
                "total_points": total_points,
                "status": "pending",
                "created_at": datetime.utcnow(),
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": None
            })
            logger.info(f"Created moderator promotion request for user {user_id}")
    
    # Check for admin promotion (3000+ points, current role is moderator)
    if total_points >= 3000 and current_role == "moderator":
        existing = await promotion_requests_collection.find_one({
            "user_id": user_id,
            "target_role": "admin",
            "status": "pending"
        })
        if not existing:
            await promotion_requests_collection.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "username": user.get("username"),
                "full_name": user.get("full_name"),
                "current_role": current_role,
                "target_role": "admin",
                "total_points": total_points,
                "status": "pending",
                "created_at": datetime.utcnow(),
                "reviewed_by": None,
                "reviewed_at": None,
                "notes": None
            })
            logger.info(f"Created admin promotion request for user {user_id}")


def calculate_ban_until(duration: str) -> Optional[datetime]:
    """Calculate ban end time based on duration string"""
    if not duration:
        return None
    
    now = datetime.utcnow()
    if duration == "6h":
        return now + timedelta(hours=6)
    elif duration == "12h":
        return now + timedelta(hours=12)
    elif duration == "48h":
        return now + timedelta(hours=48)
    elif duration == "permanent":
        return datetime(2099, 12, 31)  # Far future date for permanent ban
    return None


# ============== REPORT ENDPOINTS ==============

@router.post("/reports")
async def create_report(
    report: ReportCreate,
    current_user: dict = Depends(get_current_user_required)
):
    """Create a new report (any user can create)"""
    if report.report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de reporte inválido")
    
    if not report.description or len(report.description.strip()) < 10:
        raise HTTPException(status_code=400, detail="La descripción debe tener al menos 10 caracteres")
    
    # Can't report yourself
    if report.reported_user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="No puedes reportarte a ti mismo")
    
    report_id = str(uuid.uuid4())
    report_doc = {
        "id": report_id,
        "reporter_id": current_user["id"],
        "reporter_username": current_user["username"],
        "reported_user_id": report.reported_user_id,
        "reported_username": report.reported_username,
        "report_type": report.report_type,
        "report_type_name": REPORT_TYPES.get(report.report_type, "Otro"),
        "description": report.description.strip(),
        "context": report.context,
        "context_id": report.context_id,
        "media_base64": report.media_base64,
        "media_type": report.media_type,
        "status": "pending_mod",  # pending_mod, pending_admin, approved, rejected
        "created_at": datetime.utcnow(),
        # Moderator review
        "moderator_id": None,
        "moderator_username": None,
        "moderator_approved": None,
        "moderator_notes": None,
        "moderated_at": None,
        # Admin decision
        "admin_id": None,
        "admin_username": None,
        "admin_approved": None,
        "admin_notes": None,
        "admin_decided_at": None,
        "ban_applied": None,
        # Threaded conversation counters
        "message_count": 0,
        "unread_by_reporter": 0,
        "unread_by_staff": 0,
        "last_message_at": None,
    }
    
    await reports_collection.insert_one(report_doc)
    
    return {
        "success": True,
        "report_id": report_id,
        "message": "Reporte creado correctamente. Será revisado por los moderadores."
    }


@router.get("/reports/types")
async def get_report_types(current_user: dict = Depends(get_current_user_required)):
    """Get available report types"""
    return {
        "types": [
            {"id": k, "name": v} for k, v in REPORT_TYPES.items()
        ]
    }


@router.get("/reports/pending-moderator")
async def get_pending_reports_for_moderator(
    current_user: dict = Depends(get_moderator_or_admin_user)
):
    """Get reports pending moderator review"""
    reports = await reports_collection.find(
        {"status": "pending_mod"}
    ).sort("created_at", -1).to_list(100)
    
    return {
        "reports": [
            {
                "id": r["id"],
                "reporter_username": r["reporter_username"],
                "reported_username": r.get("reported_username"),
                "report_type": r["report_type"],
                "report_type_name": r["report_type_name"],
                "description": r["description"],
                "context": r.get("context"),
                "media_base64": r.get("media_base64"),
                "media_type": r.get("media_type"),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "message_count": r.get("message_count", 0),
                "unread_for_viewer": r.get("unread_by_staff", 0),
                "last_message_at": r.get("last_message_at").isoformat() if r.get("last_message_at") else None
            }
            for r in reports
        ],
        "total": len(reports)
    }


@router.get("/reports/pending-admin")
async def get_pending_reports_for_admin(
    current_user: dict = Depends(get_admin_user)
):
    """Get reports pending admin decision (already reviewed by moderator)"""
    reports = await reports_collection.find(
        {"status": "pending_admin"}
    ).sort("moderated_at", -1).to_list(100)
    
    return {
        "reports": [
            {
                "id": r["id"],
                "reporter_username": r["reporter_username"],
                "reported_user_id": r.get("reported_user_id"),
                "reported_username": r.get("reported_username"),
                "report_type": r["report_type"],
                "report_type_name": r["report_type_name"],
                "description": r["description"],
                "context": r.get("context"),
                "media_base64": r.get("media_base64"),
                "media_type": r.get("media_type"),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "moderator_username": r.get("moderator_username"),
                "moderator_notes": r.get("moderator_notes"),
                "moderated_at": r["moderated_at"].isoformat() if r.get("moderated_at") else None,
                "message_count": r.get("message_count", 0),
                "unread_for_viewer": r.get("unread_by_staff", 0),
                "last_message_at": r.get("last_message_at").isoformat() if r.get("last_message_at") else None
            }
            for r in reports
        ],
        "total": len(reports)
    }


@router.get("/reports/active")
async def get_all_active_reports(current_user: dict = Depends(get_moderator_or_admin_user)):
    """All non-final reports (for the staff inbox). Sorted by unread + recency."""
    active_statuses = ["pending_mod", "pending_admin", "in_progress", "awaiting_reporter"]
    reports = await reports_collection.find(
        {"status": {"$in": active_statuses}}
    ).sort([("unread_by_staff", -1), ("last_message_at", -1), ("created_at", -1)]).to_list(200)
    return {
        "reports": [await _serialize_report(r, current_user) for r in reports],
        "total": len(reports),
    }


@router.put("/reports/{report_id}/moderate")
async def moderate_report(
    report_id: str,
    review: ModeratorReview,
    current_user: dict = Depends(get_moderator_or_admin_user)
):
    """Moderator reviews a report"""
    report = await reports_collection.find_one({"id": report_id})
    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    
    if report["status"] != "pending_mod":
        raise HTTPException(status_code=400, detail="Este reporte ya fue revisado")
    
    new_status = "pending_admin" if review.approved else "rejected"
    
    await reports_collection.update_one(
        {"id": report_id},
        {"$set": {
            "status": new_status,
            "moderator_id": current_user["id"],
            "moderator_username": current_user["username"],
            "moderator_approved": review.approved,
            "moderator_notes": review.moderator_notes,
            "moderated_at": datetime.utcnow()
        }}
    )

    # Notify reporter through the thread
    if review.approved:
        sys_body = "Un moderador ha revisado el reporte y lo ha pasado a administracion."
    else:
        sys_body = "Un moderador ha rechazado el reporte."
    if review.moderator_notes:
        sys_body += f"\nNota: {review.moderator_notes.strip()}"
    await _push_system_message(report_id, sys_body, current_user)

    return {
        "success": True,
        "message": "Reporte pasado a administración" if review.approved else "Reporte rechazado"
    }


@router.put("/reports/{report_id}/admin-decision")
async def admin_decide_report(
    report_id: str,
    decision: AdminDecision,
    current_user: dict = Depends(get_admin_user)
):
    """Admin makes final decision on a report"""
    report = await reports_collection.find_one({"id": report_id})
    if not report:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    
    if report["status"] != "pending_admin":
        raise HTTPException(status_code=400, detail="Este reporte no está pendiente de decisión admin")
    
    new_status = "approved" if decision.approved else "rejected"
    ban_until = None
    
    # Apply ban if approved and ban_duration specified
    if decision.approved and decision.ban_duration and report.get("reported_user_id"):
        ban_until = calculate_ban_until(decision.ban_duration)
        if ban_until:
            await users_collection.update_one(
                {"id": report["reported_user_id"]},
                {"$set": {
                    "banned_until": ban_until,
                    "ban_reason": f"Reporte aprobado: {report['report_type_name']}",
                    "banned_by": current_user["id"]
                }}
            )
            logger.info(f"User {report['reported_user_id']} banned until {ban_until}")
    
    await reports_collection.update_one(
        {"id": report_id},
        {"$set": {
            "status": new_status,
            "admin_id": current_user["id"],
            "admin_username": current_user["username"],
            "admin_approved": decision.approved,
            "admin_notes": decision.admin_notes,
            "admin_decided_at": datetime.utcnow(),
            "ban_applied": decision.ban_duration if ban_until else None
        }}
    )

    # Notify reporter through the thread
    if decision.approved:
        sys_body = "Administracion ha aprobado el reporte."
        if ban_until and decision.ban_duration:
            sys_body += f" Se ha aplicado una sancion: {decision.ban_duration}."
    else:
        sys_body = "Administracion ha rechazado el reporte."
    if decision.admin_notes:
        sys_body += f"\nNota: {decision.admin_notes.strip()}"
    await _push_system_message(report_id, sys_body, current_user)

    return {
        "success": True,
        "message": "Decisión aplicada correctamente",
        "ban_applied": decision.ban_duration if ban_until else None
    }


@router.get("/reports/my-reports")
async def get_my_reports(current_user: dict = Depends(get_current_user_required)):
    """Get reports created by current user"""
    reports = await reports_collection.find(
        {"reporter_id": current_user["id"]}
    ).sort("created_at", -1).to_list(50)
    
    status_names = {
        "pending_mod": "Pendiente de revisión",
        "pending_admin": "En revisión por administración",
        "approved": "Aprobado",
        "rejected": "Rechazado"
    }
    
    return {
        "reports": [
            {
                "id": r["id"],
                "reported_username": r.get("reported_username"),
                "report_type_name": r["report_type_name"],
                "description": r["description"][:100] + "..." if len(r["description"]) > 100 else r["description"],
                "status": r["status"],
                "status_name": status_names.get(r["status"], r["status"]),
                "message_count": r.get("message_count", 0),
                "unread_for_viewer": r.get("unread_by_reporter", 0),
                "last_message_at": r.get("last_message_at").isoformat() if r.get("last_message_at") else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
            }
            for r in reports
        ]
    }


# ============== PROMOTION ENDPOINTS ==============

@router.get("/promotions/pending-moderator")
async def get_pending_moderator_promotions(
    current_user: dict = Depends(get_moderator_or_admin_user)
):
    """Get pending requests for users to become moderators (reviewed by moderators)"""
    requests = await promotion_requests_collection.find(
        {"target_role": "moderator", "status": "pending"}
    ).sort("created_at", -1).to_list(50)
    
    return {
        "requests": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "full_name": r.get("full_name"),
                "current_role": r["current_role"],
                "target_role": r["target_role"],
                "total_points": r["total_points"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
            }
            for r in requests
        ],
        "total": len(requests)
    }


@router.get("/promotions/pending-admin")
async def get_pending_admin_promotions(
    current_user: dict = Depends(get_admin_user)
):
    """Get pending requests for moderators to become admins (reviewed by admins)"""
    requests = await promotion_requests_collection.find(
        {"target_role": "admin", "status": "pending"}
    ).sort("created_at", -1).to_list(50)
    
    return {
        "requests": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "full_name": r.get("full_name"),
                "current_role": r["current_role"],
                "target_role": r["target_role"],
                "total_points": r["total_points"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
            }
            for r in requests
        ],
        "total": len(requests)
    }


@router.put("/promotions/{request_id}/decide")
async def decide_promotion(
    request_id: str,
    decision: PromotionDecision,
    current_user: dict = Depends(get_moderator_or_admin_user)
):
    """Decide on a promotion request"""
    request = await promotion_requests_collection.find_one({"id": request_id})
    if not request:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    if request["status"] != "pending":
        raise HTTPException(status_code=400, detail="Esta solicitud ya fue procesada")
    
    # Only admins can approve admin promotions
    if request["target_role"] == "admin" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden aprobar promociones a admin")
    
    # Update request
    new_status = "approved" if decision.approved else "rejected"
    await promotion_requests_collection.update_one(
        {"id": request_id},
        {"$set": {
            "status": new_status,
            "reviewed_by": current_user["id"],
            "reviewed_at": datetime.utcnow(),
            "notes": decision.notes
        }}
    )
    
    # If approved, update user role
    if decision.approved:
        await users_collection.update_one(
            {"id": request["user_id"]},
            {"$set": {
                "role": request["target_role"],
                "promoted_at": datetime.utcnow(),
                "promoted_by": current_user["id"]
            }}
        )
        logger.info(f"User {request['user_id']} promoted to {request['target_role']}")
    
    return {
        "success": True,
        "message": f"Usuario {'promovido a ' + request['target_role'] if decision.approved else 'solicitud rechazada'}"
    }


# ============== STATS ENDPOINTS ==============

@router.get("/stats/moderator")
async def get_moderator_stats(
    current_user: dict = Depends(get_moderator_or_admin_user)
):
    """Get moderation statistics for moderators"""
    pending_reports = await reports_collection.count_documents({"status": "pending_mod"})
    pending_promotions = await promotion_requests_collection.count_documents({
        "target_role": "moderator", 
        "status": "pending"
    })
    
    return {
        "pending_reports": pending_reports,
        "pending_promotions": pending_promotions
    }


@router.get("/stats/admin")
async def get_admin_moderation_stats(
    current_user: dict = Depends(get_admin_user)
):
    """Get moderation statistics for admins"""
    pending_reports = await reports_collection.count_documents({"status": "pending_admin"})
    pending_promotions = await promotion_requests_collection.count_documents({
        "target_role": "admin",
        "status": "pending"
    })
    total_reports_today = await reports_collection.count_documents({
        "created_at": {"$gte": datetime.utcnow().replace(hour=0, minute=0, second=0)}
    })
    
    return {
        "pending_reports": pending_reports,
        "pending_promotions": pending_promotions,
        "total_reports_today": total_reports_today
    }


# ============== REPORT THREAD / MESSAGING ==============

FINAL_REPORT_STATUSES = {"approved", "rejected", "resolved"}


def _is_staff(user: dict) -> bool:
    return user.get("role") in ("moderator", "admin")


async def _serialize_report(r: dict, viewer: dict) -> dict:
    """Return the full report with role-aware unread counter for the viewer."""
    is_reporter = r["reporter_id"] == viewer["id"]
    is_staff = _is_staff(viewer)
    status_names = {
        "pending_mod": "Pendiente de revisión",
        "pending_admin": "En revisión por administración",
        "in_progress": "En curso",
        "awaiting_reporter": "Esperando al usuario",
        "resolved": "Resuelto",
        "approved": "Aprobado",
        "rejected": "Rechazado",
    }
    return {
        "id": r["id"],
        "reporter_id": r["reporter_id"],
        "reporter_username": r["reporter_username"],
        "reported_user_id": r.get("reported_user_id"),
        "reported_username": r.get("reported_username"),
        "report_type": r.get("report_type"),
        "report_type_name": r.get("report_type_name"),
        "description": r.get("description"),
        "context": r.get("context"),
        "context_id": r.get("context_id"),
        "media_base64": r.get("media_base64"),
        "media_type": r.get("media_type"),
        "status": r["status"],
        "status_name": status_names.get(r["status"], r["status"]),
        "created_at": r.get("created_at"),
        "message_count": r.get("message_count", 0),
        "unread_for_viewer": (
            r.get("unread_by_reporter", 0) if is_reporter
            else r.get("unread_by_staff", 0) if is_staff
            else 0
        ),
        "last_message_at": r.get("last_message_at"),
        "moderator_username": r.get("moderator_username"),
        "admin_username": r.get("admin_username"),
        "moderator_notes": r.get("moderator_notes"),
        "admin_notes": r.get("admin_notes"),
    }


async def _load_report_for_viewer(report_id: str, viewer: dict) -> dict:
    r = await reports_collection.find_one({"id": report_id})
    if not r:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    if not (_is_staff(viewer) or r["reporter_id"] == viewer["id"]):
        raise HTTPException(status_code=403, detail="No tienes acceso a este reporte")
    return r


async def _push_system_message(report_id: str, body: str, actor: dict) -> None:
    """Insert a system message (used when staff changes status)."""
    doc = {
        "id": str(uuid.uuid4()),
        "report_id": report_id,
        "sender_id": actor["id"],
        "sender_username": actor["username"],
        "sender_role": actor.get("role"),
        "body": body,
        "is_system": True,
        "created_at": datetime.utcnow(),
    }
    await report_messages_collection.insert_one(doc)
    await reports_collection.update_one(
        {"id": report_id},
        {
            "$inc": {"message_count": 1, "unread_by_reporter": 1},
            "$set": {"last_message_at": doc["created_at"]},
        },
    )


@router.get("/reports/{report_id}")
async def get_report_detail(
    report_id: str,
    current_user: dict = Depends(get_current_user_required),
):
    """Return a single report (accessible to its reporter or staff)."""
    r = await _load_report_for_viewer(report_id, current_user)
    return await _serialize_report(r, current_user)


@router.get("/reports/{report_id}/messages")
async def list_report_messages(
    report_id: str,
    current_user: dict = Depends(get_current_user_required),
):
    """List all messages of a report thread. Marks unread as read for the viewer."""
    r = await _load_report_for_viewer(report_id, current_user)
    docs = await report_messages_collection.find({"report_id": report_id}).sort("created_at", 1).to_list(500)

    # Mark unread as read for the viewer
    is_reporter = r["reporter_id"] == current_user["id"]
    if is_reporter and r.get("unread_by_reporter", 0) > 0:
        await reports_collection.update_one({"id": report_id}, {"$set": {"unread_by_reporter": 0}})
    if _is_staff(current_user) and r.get("unread_by_staff", 0) > 0:
        await reports_collection.update_one({"id": report_id}, {"$set": {"unread_by_staff": 0}})

    return {
        "messages": [
            {
                "id": m["id"],
                "sender_id": m["sender_id"],
                "sender_username": m["sender_username"],
                "sender_role": m.get("sender_role"),
                "body": m["body"],
                "is_system": bool(m.get("is_system", False)),
                "created_at": m["created_at"].isoformat() if m.get("created_at") else None,
            }
            for m in docs
        ]
    }


@router.post("/reports/{report_id}/messages")
async def send_report_message(
    report_id: str,
    payload: ReportMessageCreate,
    current_user: dict = Depends(get_current_user_required),
):
    """Reporter, moderator or admin can post a message. Resolved reports are read-only."""
    r = await _load_report_for_viewer(report_id, current_user)
    if r["status"] in FINAL_REPORT_STATUSES:
        raise HTTPException(status_code=400, detail="El reporte esta cerrado, no se pueden enviar mensajes")
    body = (payload.body or "").strip()
    if len(body) < 1:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacio")
    if len(body) > 2000:
        raise HTTPException(status_code=400, detail="El mensaje es demasiado largo (max 2000 caracteres)")

    is_reporter = r["reporter_id"] == current_user["id"]
    is_staff = _is_staff(current_user)

    doc = {
        "id": str(uuid.uuid4()),
        "report_id": report_id,
        "sender_id": current_user["id"],
        "sender_username": current_user["username"],
        "sender_role": current_user.get("role"),
        "body": body,
        "is_system": False,
        "created_at": datetime.utcnow(),
    }
    await report_messages_collection.insert_one(doc)

    inc = {"message_count": 1}
    # If reporter posts -> staff has unread; if staff -> reporter has unread
    if is_reporter:
        inc["unread_by_staff"] = 1
    elif is_staff:
        inc["unread_by_reporter"] = 1

    set_fields = {"last_message_at": doc["created_at"]}
    # First staff response bumps status out of "awaiting_reporter"
    if is_staff and r["status"] == "awaiting_reporter":
        set_fields["status"] = "in_progress"
    # First reporter reply after "awaiting_reporter" -> back to in_progress
    if is_reporter and r["status"] == "awaiting_reporter":
        set_fields["status"] = "in_progress"

    await reports_collection.update_one({"id": report_id}, {"$inc": inc, "$set": set_fields})

    return {
        "message": {
            "id": doc["id"],
            "sender_username": doc["sender_username"],
            "sender_role": doc["sender_role"],
            "body": doc["body"],
            "is_system": False,
            "created_at": doc["created_at"].isoformat(),
        }
    }


@router.put("/reports/{report_id}/status")
async def change_report_status(
    report_id: str,
    payload: ReportStatusUpdate,
    current_user: dict = Depends(get_moderator_or_admin_user),
):
    """Staff-only flexible status transitions with an optional system note."""
    allowed = {"in_progress", "awaiting_reporter", "resolved"}
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Estado invalido. Validos: {sorted(allowed)}")
    if payload.status == "resolved" and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede resolver un reporte")

    r = await reports_collection.find_one({"id": report_id})
    if not r:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    if r["status"] in FINAL_REPORT_STATUSES:
        raise HTTPException(status_code=400, detail="El reporte ya esta cerrado")

    await reports_collection.update_one(
        {"id": report_id},
        {"$set": {
            "status": payload.status,
            "last_message_at": datetime.utcnow(),
        }},
    )
    labels = {
        "in_progress": "La conversacion esta en curso",
        "awaiting_reporter": "Los moderadores necesitan mas informacion",
        "resolved": "Reporte marcado como resuelto",
    }
    system_body = labels[payload.status]
    if payload.note:
        system_body += f"\nNota: {payload.note.strip()}"
    await _push_system_message(report_id, system_body, current_user)

    return {"success": True, "status": payload.status}

