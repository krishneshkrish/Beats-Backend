from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.db.database import get_db, MoodLog
from app.models.schemas import MoodSetPayload, MoodSetResponse

router = APIRouter(prefix="/api/mood", tags=["mood"])

VALID_MOODS = {"Happy", "Chill", "Focus", "Workout", "Night", "Sad", "Party", "Travel"}


@router.post("/set", response_model=MoodSetResponse)
async def set_mood(payload: MoodSetPayload, db: AsyncSession = Depends(get_db)):
    """
    Called by useMoodStore every time the user picks a mood in Mood Hub.

    Logs the mood change with time context so the ML model can learn:
    'at 11PM on weekdays Krish always switches to Night mode'
    """
    if payload.mood not in VALID_MOODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mood. Must be one of: {', '.join(sorted(VALID_MOODS))}"
        )

    try:
        now = datetime.utcnow()
        try:
            ts = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
            hour = ts.hour
            dow = ts.weekday()
        except Exception:
            hour = now.hour
            dow = now.weekday()

        log = MoodLog(
            username=payload.username,
            mood=payload.mood,
            timestamp=payload.timestamp,
            hour_of_day=hour,
            day_of_week=dow,
        )
        db.add(log)
        await db.commit()

        return MoodSetResponse(status="success", mood=payload.mood)

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
