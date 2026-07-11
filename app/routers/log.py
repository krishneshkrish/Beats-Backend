"""
Beats — Play Logging Router
───────────────────────────
Captures track playback telemetry events from the frontend,
enriches them with server-side time dimensions, and records
them persistently under the active username profile context.
"""

from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db, PlayEvent
from app.models.schemas import PlayLogPayload, PlayLogResponse

logger = logging.getLogger("beats.log")
router = APIRouter(prefix="/api/log", tags=["log"])

@router.post("", response_model=PlayLogResponse)
async def log_play_event(
    payload: PlayLogPayload,
    db: AsyncSession = Depends(get_db)
):
    """
    Logs an active playback event under a specific user profile context.
    Enriches temporal features (hour, day of week) for the ML model matrix.
    """
    try:
        # Parse frontend timestamp safely to calculate temporal ML vectors
        try:
            # Handle standard Javascript ISO strings (e.g., trailing 'Z')
            clean_ts = payload.timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
        except Exception:
            dt = datetime.utcnow()

        # Build the user-scoped database record
        new_event = PlayEvent(
            username=payload.username,
            song_id=payload.song_id,
            mood_tag=payload.mood_tag,
            session_id=payload.session_id,
            timestamp=payload.timestamp,
            hour_of_day=dt.hour,
            day_of_week=dt.weekday(),  # 0 = Monday, 6 = Sunday
        )

        db.add(new_event)
        await db.commit()
        await db.refresh(new_event)

        logger.info(f"[Logger] Logged play event for user '{payload.username}' -> Song ID: {payload.song_id}")
        return PlayLogResponse(status="success")

    except Exception as e:
        logger.error(f"[Logger Error] Failed to write event to database: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database logging failure: {str(e)}"
        )