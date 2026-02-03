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
        "ban_applied": None
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
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None
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
                "moderated_at": r["moderated_at"].isoformat() if r.get("moderated_at") else None
            }
            for r in reports
        ],
        "total": len(reports)
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
