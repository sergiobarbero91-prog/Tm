"""
Support/Help Center Router
Handles support tickets and chat messages between users and admins
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime
import uuid

from shared import get_current_user_required, db

router = APIRouter(prefix="/support", tags=["support"])


# Models
class CreateTicketRequest(BaseModel):
    subject: str = Field(..., min_length=3, max_length=100)
    message: str = Field(..., min_length=10, max_length=2000)


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class TicketResponse(BaseModel):
    id: str
    user_id: str
    username: str
    subject: str
    status: Literal["open", "closed"]
    created_at: datetime
    updated_at: datetime
    last_message: Optional[str] = None
    unread_by_user: bool = False
    unread_by_admin: bool = False


class MessageResponse(BaseModel):
    id: str
    ticket_id: str
    sender_id: str
    sender_username: str
    sender_role: str
    message: str
    created_at: datetime


# Helper to check if user is admin
async def require_admin(current_user: dict = Depends(get_current_user_required)):
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden realizar esta acción"
        )
    return current_user


@router.post("/tickets", response_model=TicketResponse)
async def create_ticket(
    request: CreateTicketRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Create a new support ticket with initial message"""
    # Check if user already has an open ticket
    existing_ticket = await db.support_tickets.find_one({
        "user_id": current_user["id"],
        "status": "open"
    })
    
    if existing_ticket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya tienes un ticket abierto. Por favor, usa ese ticket o espera a que sea cerrado."
        )
    
    now = datetime.utcnow()
    ticket_id = str(uuid.uuid4())
    
    # Create ticket
    ticket = {
        "id": ticket_id,
        "user_id": current_user["id"],
        "username": current_user["username"],
        "subject": request.subject,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "last_message": request.message[:100] + "..." if len(request.message) > 100 else request.message,
        "unread_by_user": False,
        "unread_by_admin": True
    }
    
    await db.support_tickets.insert_one(ticket)
    
    # Create initial message
    message = {
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "sender_id": current_user["id"],
        "sender_username": current_user["username"],
        "sender_role": current_user.get("role", "user"),
        "message": request.message,
        "created_at": now
    }
    
    await db.support_messages.insert_one(message)
    
    return TicketResponse(**ticket)


@router.get("/tickets", response_model=List[TicketResponse])
async def get_tickets(
    status_filter: Optional[str] = None,
    current_user: dict = Depends(get_current_user_required)
):
    """Get tickets - admins see all, users see only their own"""
    query = {}
    
    # Non-admins can only see their own tickets
    if current_user.get("role") != "admin":
        query["user_id"] = current_user["id"]
    
    # Apply status filter if provided
    if status_filter in ["open", "closed"]:
        query["status"] = status_filter
    
    cursor = db.support_tickets.find(query).sort("updated_at", -1)
    tickets = await cursor.to_list(length=100)
    
    return [TicketResponse(**t) for t in tickets]


@router.get("/tickets/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user_required)
):
    """Get count of unread tickets for admin or unread responses for user"""
    if current_user.get("role") == "admin":
        # Admin sees count of tickets with unread messages from users
        count = await db.support_tickets.count_documents({
            "status": "open",
            "unread_by_admin": True
        })
    else:
        # User sees count of tickets with unread admin responses
        count = await db.support_tickets.count_documents({
            "user_id": current_user["id"],
            "unread_by_user": True
        })
    
    return {"unread_count": count}


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get a specific ticket"""
    ticket = await db.support_tickets.find_one({"id": ticket_id})
    
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket no encontrado"
        )
    
    # Check permissions
    if current_user.get("role") != "admin" and ticket["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este ticket"
        )
    
    return TicketResponse(**ticket)


@router.get("/tickets/{ticket_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    ticket_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get all messages for a ticket"""
    # First check ticket exists and user has access
    ticket = await db.support_tickets.find_one({"id": ticket_id})
    
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket no encontrado"
        )
    
    # Check permissions
    is_admin = current_user.get("role") == "admin"
    if not is_admin and ticket["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este ticket"
        )
    
    # Mark as read
    if is_admin:
        await db.support_tickets.update_one(
            {"id": ticket_id},
            {"$set": {"unread_by_admin": False}}
        )
    else:
        await db.support_tickets.update_one(
            {"id": ticket_id},
            {"$set": {"unread_by_user": False}}
        )
    
    cursor = db.support_messages.find({"ticket_id": ticket_id}).sort("created_at", 1)
    messages = await cursor.to_list(length=500)
    
    return [MessageResponse(**m) for m in messages]


@router.post("/tickets/{ticket_id}/messages", response_model=MessageResponse)
async def send_message(
    ticket_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user_required)
):
    """Send a message to a ticket"""
    # Check ticket exists and is open
    ticket = await db.support_tickets.find_one({"id": ticket_id})
    
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket no encontrado"
        )
    
    if ticket["status"] == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este ticket está cerrado. No se pueden enviar más mensajes."
        )
    
    # Check permissions
    is_admin = current_user.get("role") == "admin"
    if not is_admin and ticket["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para enviar mensajes a este ticket"
        )
    
    now = datetime.utcnow()
    
    # Create message
    message = {
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "sender_id": current_user["id"],
        "sender_username": current_user["username"],
        "sender_role": current_user.get("role", "user"),
        "message": request.message,
        "created_at": now
    }
    
    await db.support_messages.insert_one(message)
    
    # Update ticket
    update_data = {
        "updated_at": now,
        "last_message": request.message[:100] + "..." if len(request.message) > 100 else request.message
    }
    
    # Set unread flags based on who sent the message
    if is_admin:
        update_data["unread_by_user"] = True
        update_data["unread_by_admin"] = False
    else:
        update_data["unread_by_admin"] = True
        update_data["unread_by_user"] = False
    
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$set": update_data}
    )
    
    return MessageResponse(**message)


@router.put("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    current_user: dict = Depends(require_admin)
):
    """Close a ticket (admin only)"""
    ticket = await db.support_tickets.find_one({"id": ticket_id})
    
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket no encontrado"
        )
    
    if ticket["status"] == "closed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este ticket ya está cerrado"
        )
    
    now = datetime.utcnow()
    
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "closed",
            "updated_at": now,
            "unread_by_user": True,
            "unread_by_admin": False
        }}
    )
    
    # Add system message about closure
    closure_message = {
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "sender_id": current_user["id"],
        "sender_username": "Sistema",
        "sender_role": "system",
        "message": f"Ticket cerrado por {current_user['username']}. Si necesitas más ayuda, puedes crear un nuevo ticket.",
        "created_at": now
    }
    
    await db.support_messages.insert_one(closure_message)
    
    return {"message": "Ticket cerrado correctamente"}


@router.put("/tickets/{ticket_id}/reopen")
async def reopen_ticket(
    ticket_id: str,
    current_user: dict = Depends(require_admin)
):
    """Reopen a closed ticket (admin only)"""
    ticket = await db.support_tickets.find_one({"id": ticket_id})
    
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket no encontrado"
        )
    
    if ticket["status"] == "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este ticket ya está abierto"
        )
    
    now = datetime.utcnow()
    
    await db.support_tickets.update_one(
        {"id": ticket_id},
        {"$set": {
            "status": "open",
            "updated_at": now
        }}
    )
    
    return {"message": "Ticket reabierto correctamente"}
