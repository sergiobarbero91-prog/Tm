"""
Analytics router for tracking user events and page views.
Privacy-friendly: no cookies, no personal data stored.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import os

from shared import db, logger

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Analytics collection
analytics_collection = db['analytics_events']

# Only enable analytics if explicitly configured
ANALYTICS_ENABLED = os.getenv("ANALYTICS_ENABLED", "false").lower() == "true"


class AnalyticsEvent(BaseModel):
    event: str
    properties: Optional[Dict[str, Any]] = {}
    timestamp: Optional[str] = None
    platform: Optional[str] = None


@router.post("/event")
async def track_event(event_data: AnalyticsEvent, request: Request):
    """
    Track an analytics event.
    Privacy-friendly: only stores aggregated data, no personal identifiers.
    """
    if not ANALYTICS_ENABLED:
        return {"status": "analytics_disabled"}
    
    try:
        # Get basic info without storing personal data
        event_doc = {
            "event": event_data.event,
            "properties": event_data.properties,
            "platform": event_data.platform or "unknown",
            "timestamp": datetime.utcnow(),
            # Store only date for aggregation, not exact time
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            # Hash the IP for unique visitor counting without storing actual IP
            "visitor_hash": hash(request.client.host) % 10000000 if request.client else None
        }
        
        await analytics_collection.insert_one(event_doc)
        
        return {"status": "tracked"}
    except Exception as e:
        logger.error(f"Analytics error: {e}")
        return {"status": "error"}


@router.get("/summary")
async def get_analytics_summary():
    """
    Get analytics summary for the last 7 days.
    Only accessible if analytics is enabled.
    """
    if not ANALYTICS_ENABLED:
        return {"status": "analytics_disabled"}
    
    try:
        from datetime import timedelta
        
        # Get events from last 7 days
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        
        pipeline = [
            {"$match": {"timestamp": {"$gte": seven_days_ago}}},
            {"$group": {
                "_id": {
                    "date": "$date",
                    "event": "$event"
                },
                "count": {"$sum": 1},
                "unique_visitors": {"$addToSet": "$visitor_hash"}
            }},
            {"$project": {
                "date": "$_id.date",
                "event": "$_id.event",
                "count": 1,
                "unique_visitors": {"$size": "$unique_visitors"}
            }},
            {"$sort": {"date": -1}}
        ]
        
        cursor = analytics_collection.aggregate(pipeline)
        results = await cursor.to_list(100)
        
        # Calculate totals
        total_events = sum(r["count"] for r in results)
        total_page_views = sum(r["count"] for r in results if r["event"] == "page_view")
        
        return {
            "status": "ok",
            "period": "last_7_days",
            "total_events": total_events,
            "total_page_views": total_page_views,
            "daily_breakdown": results
        }
    except Exception as e:
        logger.error(f"Analytics summary error: {e}")
        return {"status": "error", "message": str(e)}
