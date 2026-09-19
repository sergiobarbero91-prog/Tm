"""Activity heartbeats — track per-user minutes of usage.

Each authenticated request writes at most one document per user per minute
into `activity_heartbeats` (idempotent via a unique (user_id, kind, bucket)
index). Summing distinct buckets over a period yields the real minutes of
usage, which we expose per period (today, week, month) on:

- `GET /api/admin/activity/stats`          — aggregate for the whole app.
- `GET /api/admin/users/{id}/activity`     — one driver (hours + rides).
- `GET /api/admin/clients/{id}/activity`   — one client (hours + rides).

Historical data older than 90 days is discarded via a TTL Mongo index.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from shared import (
    ALGORITHM,
    SECRET_KEY,
    clients_collection,
    db,
    get_admin_user,
    logger,
    rides_collection,
    users_collection,
)

activity_heartbeats_collection = db.activity_heartbeats

router = APIRouter(prefix="/admin/activity", tags=["Admin activity"])


# ─────────────────────── Bookkeeping ───────────────────────
async def ensure_indexes():
    """Create the compound uniqueness index + TTL on `created_at`.

    TTL guarantees the collection stays bounded (90 days). Idempotent — safe
    to call on every startup.
    """
    try:
        await activity_heartbeats_collection.create_index(
            [("user_id", 1), ("kind", 1), ("bucket_minute", 1)],
            unique=True,
        )
        await activity_heartbeats_collection.create_index(
            "created_at", expireAfterSeconds=90 * 24 * 3600
        )
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning(f"[activity] index setup failed: {e}")


async def record_heartbeat(user_id: str, kind: Literal["user", "client"]) -> None:
    """Upsert the minute-bucket for the given user/client."""
    if not user_id:
        return
    now = datetime.now(timezone.utc)
    bucket = now.replace(second=0, microsecond=0)
    try:
        await activity_heartbeats_collection.update_one(
            {"user_id": user_id, "kind": kind, "bucket_minute": bucket},
            {"$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    except Exception:
        # Duplicate key when two requests race is fine — silent swallow.
        pass


class ActivityHeartbeatMiddleware(BaseHTTPMiddleware):
    """Fire a heartbeat when the incoming request carries a valid Bearer JWT.

    Written after the response is produced so it never delays the client.
    Decode uses `verify_exp=False`: we want to count activity even on the
    borderline second where the token expires — auth guards run separately.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        auth = request.headers.get("authorization") or ""
        if auth.startswith("Bearer "):
            token = auth[7:]
            try:
                payload = jwt.decode(
                    token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False}
                )
                uid = payload.get("sub")
                # Client tokens include `client_id`; drivers/admins/mod use `sub`.
                cid = payload.get("client_id")
                if cid:
                    await record_heartbeat(cid, "client")
                elif uid:
                    await record_heartbeat(uid, "user")
            except Exception:
                pass
        return response


# ─────────────────────── Query helpers ───────────────────────
def _period_bounds() -> dict:
    now = datetime.now(timezone.utc)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_week = start_day - timedelta(days=6)   # last 7 days including today
    start_month = start_day - timedelta(days=29)  # last 30 days including today
    return {"day": start_day, "week": start_week, "month": start_month}


async def _aggregate(match: dict) -> dict:
    """Count distinct users and total minutes matching a filter."""
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "distinct_users": {"$addToSet": "$user_id"},
            "total_minutes": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0,
            "active_users": {"$size": "$distinct_users"},
            "total_minutes": 1,
        }},
    ]
    async for row in activity_heartbeats_collection.aggregate(pipeline):
        return {
            "active_users": row.get("active_users", 0),
            "total_hours": round(row.get("total_minutes", 0) / 60.0, 2),
        }
    return {"active_users": 0, "total_hours": 0.0}


# ─────────────────────── Endpoints ───────────────────────
@router.get("/stats")
async def activity_stats(_admin: dict = Depends(get_admin_user)) -> dict:
    """Global usage stats per role (users vs clients) and per period."""
    bounds = _period_bounds()
    out: dict = {"periods": {}, "roles": {}}
    for period, start in bounds.items():
        out["periods"][period] = {
            "users": await _aggregate({"kind": "user", "bucket_minute": {"$gte": start}}),
            "clients": await _aggregate({"kind": "client", "bucket_minute": {"$gte": start}}),
        }
    # Role breakdown for MONTH — useful in the admin dashboard tiles.
    role_pipeline = [
        {"$match": {"kind": "user", "bucket_minute": {"$gte": bounds["month"]}}},
        {"$lookup": {
            "from": "users",
            "localField": "user_id",
            "foreignField": "id",
            "as": "u",
        }},
        {"$unwind": "$u"},
        {"$group": {
            "_id": "$u.role",
            "distinct": {"$addToSet": "$user_id"},
            "minutes": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0,
            "role": "$_id",
            "active_users": {"$size": "$distinct"},
            "total_hours": {"$round": [{"$divide": ["$minutes", 60]}, 2]},
        }},
    ]
    async for row in activity_heartbeats_collection.aggregate(role_pipeline):
        out["roles"][row["role"]] = {
            "active_users": row["active_users"],
            "total_hours": row["total_hours"],
        }
    return out


async def _user_kind_or_404(uid: str) -> str:
    if await users_collection.find_one({"id": uid}, {"_id": 0, "id": 1}):
        return "user"
    if await clients_collection.find_one({"id": uid}, {"_id": 0, "id": 1}):
        return "client"
    raise HTTPException(status_code=404, detail="Usuario o cliente no encontrado")


@router.get("/user/{uid}")
async def user_activity(uid: str, _admin: dict = Depends(get_admin_user)) -> dict:
    """Per-user usage hours and last activity."""
    kind = await _user_kind_or_404(uid)
    bounds = _period_bounds()
    periods = {}
    for period, start in bounds.items():
        periods[period] = await _aggregate({
            "kind": kind,
            "user_id": uid,
            "bucket_minute": {"$gte": start},
        })
    last = await activity_heartbeats_collection.find_one(
        {"kind": kind, "user_id": uid},
        sort=[("bucket_minute", -1)],
    )
    # Ride counts
    if kind == "user":
        rides_count = await rides_collection.count_documents({"accepted_by_driver_id": uid})
    else:
        rides_count = await rides_collection.count_documents({"client_id": uid})
    return {
        "kind": kind,
        "periods": periods,
        "last_seen": last.get("bucket_minute").isoformat() if last else None,
        "rides_count": rides_count,
    }


@router.get("/user/{uid}/rides")
async def user_rides(uid: str, _admin: dict = Depends(get_admin_user), limit: int = 100) -> list:
    """List a user's rides for the admin drill-down."""
    kind = await _user_kind_or_404(uid)
    q = {"accepted_by_driver_id": uid} if kind == "user" else {"client_id": uid}
    cursor = rides_collection.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 500))
    return [
        {
            "id": d.get("id"),
            "origin": d.get("origin"),
            "destination": d.get("destination"),
            "status": d.get("status"),
            "ride_type": d.get("ride_type"),
            "scheduled_at": d.get("scheduled_at").isoformat() if d.get("scheduled_at") else None,
            "created_at": d.get("created_at").isoformat() if d.get("created_at") else None,
            "client_name": d.get("client_name"),
            "accepted_by_driver_name": d.get("accepted_by_driver_name"),
            "passengers": d.get("passengers", 1),
        }
        async for d in cursor
    ]
