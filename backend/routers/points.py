"""
Points System Router - Gamification for taxi drivers
Tracks points for various activities and provides ranking
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import List, Optional
import uuid

from shared import (
    users_collection, points_history_collection,
    POINTS_CONFIG, get_user_level,
    get_current_user_required, logger
)

router = APIRouter(prefix="/points", tags=["Points System"])


# ============== HELPER FUNCTIONS ==============

async def add_points(user_id: str, action: str, points: int, description: str = None):
    """Add points to a user and record the transaction"""
    try:
        # Record the transaction
        transaction = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "action": action,
            "points": points,
            "description": description or action,
            "created_at": datetime.utcnow()
        }
        await points_history_collection.insert_one(transaction)
        
        # Update user's total points
        result = await users_collection.find_one_and_update(
            {"id": user_id},
            {"$inc": {"total_points": points}},
            return_document=True
        )
        
        if result:
            new_total = result.get("total_points", 0)
            logger.info(f"Points added: {points} to user {user_id} for {action}. New total: {new_total}")
            
            # Check for promotion eligibility
            await check_and_create_promotion_request(user_id, new_total, result.get("role", "user"))
        
        return True
    except Exception as e:
        logger.error(f"Error adding points: {e}")
        return False


async def check_and_create_promotion_request(user_id: str, total_points: int, current_role: str):
    """Check if user qualifies for promotion and create request if needed"""
    try:
        # Import here to avoid circular imports
        from motor.motor_asyncio import AsyncIOMotorClient
        import os
        from dotenv import load_dotenv
        from pathlib import Path
        
        ROOT_DIR = Path(__file__).parent.parent
        load_dotenv(ROOT_DIR / '.env')
        
        mongo_url = os.environ['MONGO_URL']
        client = AsyncIOMotorClient(mongo_url)
        db = client[os.environ['DB_NAME']]
        promotion_requests_collection = db['promotion_requests']
        
        user = await users_collection.find_one({"id": user_id})
        if not user:
            return
        
        # Check for moderator promotion (1500+ points, current role is user)
        if total_points >= 1500 and current_role == "user":
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
                logger.info(f"Created moderator promotion request for user {user_id} with {total_points} points")
        
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
                logger.info(f"Created admin promotion request for user {user_id} with {total_points} points")
    except Exception as e:
        logger.error(f"Error checking promotion eligibility: {e}")


async def get_user_points(user_id: str) -> int:
    """Get total points for a user"""
    user = await users_collection.find_one({"id": user_id})
    if user:
        return user.get("total_points", 0)
    return 0


# ============== ENDPOINTS ==============

@router.get("/my-points")
async def get_my_points(current_user: dict = Depends(get_current_user_required)):
    """Get current user's points, level, and recent history"""
    total_points = current_user.get("total_points", 0)
    level_name, level_badge = get_user_level(total_points)
    
    # Get recent transactions (last 20)
    history = await points_history_collection.find(
        {"user_id": current_user["id"]}
    ).sort("created_at", -1).limit(20).to_list(20)
    
    # Calculate points to next level
    next_level_points = 0
    next_level_name = None
    from shared import LEVEL_THRESHOLDS
    for threshold, name, badge in LEVEL_THRESHOLDS:
        if threshold > total_points:
            next_level_points = threshold - total_points
            next_level_name = name
            break
    
    return {
        "total_points": total_points,
        "level_name": level_name,
        "level_badge": level_badge,
        "next_level_name": next_level_name,
        "points_to_next_level": next_level_points,
        "history": [
            {
                "id": h["id"],
                "action": h["action"],
                "points": h["points"],
                "description": h.get("description", h["action"]),
                "created_at": h["created_at"].isoformat() if h.get("created_at") else None
            }
            for h in history
        ]
    }


@router.get("/ranking")
async def get_ranking(
    limit: int = 50,
    current_user: dict = Depends(get_current_user_required)
):
    """Get the leaderboard/ranking of all users"""
    # Get top users by points
    top_users = await users_collection.find(
        {"total_points": {"$exists": True, "$gt": 0}}
    ).sort("total_points", -1).limit(limit).to_list(limit)
    
    ranking = []
    for i, user in enumerate(top_users, 1):
        points = user.get("total_points", 0)
        level_name, level_badge = get_user_level(points)
        ranking.append({
            "position": i,
            "user_id": user["id"],
            "username": user["username"],
            "full_name": user.get("full_name"),
            "license_number": user.get("license_number"),
            "total_points": points,
            "level_name": level_name,
            "level_badge": level_badge,
            "is_me": user["id"] == current_user["id"]
        })
    
    # Get current user's position if not in top
    current_user_in_ranking = any(r["is_me"] for r in ranking)
    my_position = None
    
    if not current_user_in_ranking:
        my_points = current_user.get("total_points", 0)
        # Count users with more points
        users_above = await users_collection.count_documents(
            {"total_points": {"$gt": my_points}}
        )
        my_position = users_above + 1
    
    return {
        "ranking": ranking,
        "my_position": my_position,
        "total_users": await users_collection.count_documents({"total_points": {"$exists": True}})
    }


@router.get("/user/{user_id}")
async def get_user_points_info(
    user_id: str,
    current_user: dict = Depends(get_current_user_required)
):
    """Get points info for a specific user"""
    user = await users_collection.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    total_points = user.get("total_points", 0)
    level_name, level_badge = get_user_level(total_points)
    
    return {
        "user_id": user["id"],
        "username": user["username"],
        "full_name": user.get("full_name"),
        "total_points": total_points,
        "level_name": level_name,
        "level_badge": level_badge
    }


@router.get("/config")
async def get_points_config(current_user: dict = Depends(get_current_user_required)):
    """Get the points configuration"""
    from shared import LEVEL_THRESHOLDS
    return {
        "actions": POINTS_CONFIG,
        "levels": [
            {"threshold": t, "name": n, "badge": b}
            for t, n, b in LEVEL_THRESHOLDS
        ]
    }
