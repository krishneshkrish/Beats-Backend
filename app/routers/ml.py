"""
ML management router.
Exposes endpoints to trigger training, check model status,
and view raw play event counts — user-scoped ML ops panel.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.db.database import get_db, PlayEvent, MoodLog
from app.ml.recommender import trigger_training, get_recommender, MIN_EVENTS_FOR_ML

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.post("/train")
async def train_model(
    username: str = Query(default="default_user"),  # ✅ Profile identifier hook
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger ML model training for a specific testing account profile.
    """
    report = await trigger_training(db, username)
    return report


@router.get("/status")
async def model_status(
    username: str = Query(default="default_user"),  # ✅ Profile identifier hook
    db: AsyncSession = Depends(get_db)
):
    """
    Check current recommender matrix state for an isolated user query profile.
    """
    count_result = await db.execute(select(func.count(PlayEvent.id)).where(PlayEvent.username == username))
    event_count = count_result.scalar() or 0

    mood_result = await db.execute(select(func.count(MoodLog.id)).where(MoodLog.username == username))
    mood_count = mood_result.scalar() or 0

    recommender = get_recommender()
    user_model = recommender.models.get(username)
    user_songs = recommender.song_ids_map.get(username, [])
    ml_active = user_model is not None and event_count >= MIN_EVENTS_FOR_ML

    return {
        "username": username,
        "play_events": event_count,
        "mood_logs": mood_count,
        "events_needed_for_ml": MIN_EVENTS_FOR_ML,
        "ml_model_active": ml_active,
        "ml_model_loaded": user_model is not None,
        "songs_in_model": len(user_songs),
        "current_mode": "ml" if ml_active else "rule-based",
        "message": (
            f"ML active — model trained on {len(user_songs)} songs for profile '{username}'."
            if ml_active
            else f"Rule-based mode. Need {MIN_EVENTS_FOR_ML - event_count} more play events to unlock ML tracking for '{username}'."
        ),
    }


@router.get("/events")
async def recent_events(
    username: Optional[str] = Query(default=None),  # ✅ Filter queries by user if provided
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    View recent play events — useful for debugging and verifying multi-tenant data logs.
    """
    stmt = select(PlayEvent)
    if username:
        stmt = stmt.where(PlayEvent.username == username)
    
    stmt = stmt.order_by(PlayEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    return [
        {
            "id": e.id,
            "username": e.username,
            "song_id": e.song_id,
            "mood_tag": e.mood_tag,
            "session_id": e.session_id,
            "hour_of_day": e.hour_of_day,
            "day_of_week": e.day_of_week,
            "was_skipped": e.was_skipped,
            "was_replayed": e.was_replayed,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]