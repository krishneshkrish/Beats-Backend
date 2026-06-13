"""
ML management router.
Exposes endpoints to trigger training, check model status,
and view raw play event counts — your ML ops panel.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db, PlayEvent, MoodLog
from app.ml.recommender import trigger_training, get_recommender, MIN_EVENTS_FOR_ML

router = APIRouter(prefix="/api/ml", tags=["ml"])


@router.post("/train")
async def train_model(db: AsyncSession = Depends(get_db)):
    """
    Manually trigger ML model training.
    Call this after you've accumulated enough play events.
    Returns training report with accuracy score.
    """
    report = await trigger_training(db)
    return report


@router.get("/status")
async def model_status(db: AsyncSession = Depends(get_db)):
    """
    Check current recommender status.
    Shows: event count, whether ML model is active, model info.
    """
    count_result = await db.execute(select(func.count(PlayEvent.id)))
    event_count = count_result.scalar() or 0

    mood_result = await db.execute(select(func.count(MoodLog.id)))
    mood_count = mood_result.scalar() or 0

    recommender = get_recommender()
    ml_active = recommender.model is not None and event_count >= MIN_EVENTS_FOR_ML

    return {
        "play_events": event_count,
        "mood_logs": mood_count,
        "events_needed_for_ml": MIN_EVENTS_FOR_ML,
        "ml_model_active": ml_active,
        "ml_model_loaded": recommender.model is not None,
        "songs_in_model": len(recommender.song_ids),
        "current_mode": "ml" if ml_active else "rule-based",
        "message": (
            f"ML active — model trained on {len(recommender.song_ids)} songs."
            if ml_active
            else f"Rule-based mode. Need {MIN_EVENTS_FOR_ML - event_count} more play events to unlock ML."
        ),
    }


@router.get("/events")
async def recent_events(
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    View recent play events — useful for debugging and verifying data collection.
    """
    result = await db.execute(
        select(PlayEvent).order_by(PlayEvent.created_at.desc()).limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id,
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
