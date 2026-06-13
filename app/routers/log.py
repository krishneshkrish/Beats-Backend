"""
Play logging router.
Every song play from the frontend hits POST /api/log/play.
This is the most important data collection endpoint —
every row here becomes a training sample for the ML model.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.db.database import get_db, PlayEvent, UserSession
from app.models.schemas import PlayLogPayload, PlayLogResponse

router = APIRouter(prefix="/api/log", tags=["logging"])


@router.post("/play", response_model=PlayLogResponse)
async def log_play(payload: PlayLogPayload, db: AsyncSession = Depends(get_db)):
    """
    Called by usePlayerStore every time a track starts playing.

    Payload (from frontend):
      song_id    — song identifier
      mood_tag   — active mood at time of play (from useMoodStore)
      timestamp  — ISO string from frontend
      session_id — browser session ID (random per tab)

    Server enriches with:
      hour_of_day  — for time-of-day ML features
      day_of_week  — for weekly pattern ML features
    """
    try:
        now = datetime.utcnow()

        # Parse frontend timestamp for hour/dow features
        try:
            ts = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
            hour = ts.hour
            dow = ts.weekday()
        except Exception:
            hour = now.hour
            dow = now.weekday()

        # Write play event
        event = PlayEvent(
            song_id=payload.song_id,
            mood_tag=payload.mood_tag,
            session_id=payload.session_id,
            timestamp=payload.timestamp,
            hour_of_day=hour,
            day_of_week=dow,
        )
        db.add(event)

        # Upsert session
        from sqlalchemy import select
        result = await db.execute(
            select(UserSession).where(UserSession.id == payload.session_id)
        )
        session = result.scalars().first()
        if session:
            session.last_active = now
            session.songs_played += 1
        else:
            db.add(UserSession(
                id=payload.session_id,
                started_at=now,
                last_active=now,
                mood_at_start=payload.mood_tag,
                songs_played=1,
            ))

        await db.commit()
        return PlayLogResponse(status="success")

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
