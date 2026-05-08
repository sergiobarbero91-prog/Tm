"""
Release Notes Router - Sistema de notas de actualización
Muestra las novedades a los usuarios después de una actualización
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId

from shared import get_current_user, db

router = APIRouter(prefix="/release-notes", tags=["release-notes"])

# Colecciones
release_notes_collection = db['release_notes']
user_seen_notes_collection = db['user_seen_notes']


class ReleaseNoteCreate(BaseModel):
    version: str
    title: str
    description: str
    features: List[str] = []
    fixes: List[str] = []
    improvements: List[str] = []


class ReleaseNoteResponse(BaseModel):
    id: str
    version: str
    title: str
    description: str
    features: List[str]
    fixes: List[str]
    improvements: List[str]
    created_at: str


@router.post("/create")
async def create_release_note(
    note: ReleaseNoteCreate,
    current_user: dict = Depends(get_current_user)
):
    """Crear una nueva nota de actualización (solo admin)"""
    # Verificar si es admin
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Solo administradores pueden crear notas")
    
    release_note = {
        "version": note.version,
        "title": note.title,
        "description": note.description,
        "features": note.features,
        "fixes": note.fixes,
        "improvements": note.improvements,
        "created_at": datetime.now(timezone.utc),
        "created_by": current_user["id"]
    }
    
    result = await release_notes_collection.insert_one(release_note)
    
    return {
        "success": True,
        "message": "Nota de actualización creada",
        "id": str(result.inserted_id)
    }


@router.get("/latest")
async def get_latest_release_notes(
    current_user: dict = Depends(get_current_user)
):
    """Obtener las notas de actualización que el usuario no ha visto"""
    user_id = current_user["id"]
    
    # Obtener IDs de notas ya vistas por el usuario
    seen_record = await user_seen_notes_collection.find_one({"user_id": user_id})
    seen_note_ids = seen_record.get("seen_notes", []) if seen_record else []
    
    # Buscar notas no vistas
    query = {}
    if seen_note_ids:
        query["_id"] = {"$nin": [ObjectId(nid) for nid in seen_note_ids if ObjectId.is_valid(nid)]}
    
    unseen_notes = await release_notes_collection.find(query).sort("created_at", -1).limit(5).to_list(length=5)
    
    notes = []
    for note in unseen_notes:
        notes.append({
            "id": str(note["_id"]),
            "version": note["version"],
            "title": note["title"],
            "description": note["description"],
            "features": note.get("features", []),
            "fixes": note.get("fixes", []),
            "improvements": note.get("improvements", []),
            "created_at": note["created_at"].isoformat()
        })
    
    return {
        "has_unread": len(notes) > 0,
        "notes": notes
    }


@router.post("/mark-seen/{note_id}")
async def mark_note_as_seen(
    note_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Marcar una nota como vista por el usuario"""
    user_id = current_user["id"]
    
    # Agregar el ID de la nota a la lista de vistas
    await user_seen_notes_collection.update_one(
        {"user_id": user_id},
        {"$addToSet": {"seen_notes": note_id}},
        upsert=True
    )
    
    return {"success": True, "message": "Nota marcada como vista"}


@router.post("/mark-all-seen")
async def mark_all_notes_as_seen(
    current_user: dict = Depends(get_current_user)
):
    """Marcar todas las notas como vistas"""
    user_id = current_user["id"]
    
    # Obtener todos los IDs de notas
    all_notes = await release_notes_collection.find({}, {"_id": 1}).to_list(length=100)
    all_note_ids = [str(note["_id"]) for note in all_notes]
    
    # Actualizar registro del usuario
    await user_seen_notes_collection.update_one(
        {"user_id": user_id},
        {"$set": {"seen_notes": all_note_ids}},
        upsert=True
    )
    
    return {"success": True, "message": "Todas las notas marcadas como vistas"}


@router.get("/all")
async def get_all_release_notes():
    """Obtener todas las notas de actualización (público)"""
    notes = await release_notes_collection.find({}).sort("created_at", -1).limit(20).to_list(length=20)
    
    result = []
    for note in notes:
        result.append({
            "id": str(note["_id"]),
            "version": note["version"],
            "title": note["title"],
            "description": note["description"],
            "features": note.get("features", []),
            "fixes": note.get("fixes", []),
            "improvements": note.get("improvements", []),
            "created_at": note["created_at"].isoformat()
        })
    
    return {"notes": result}
