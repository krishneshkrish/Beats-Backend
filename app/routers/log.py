"""
Beats — Play Logging & History Router
─────────────────────────────────────
Captures track playback telemetry events from the frontend,
enriches them with server-side time dimensions, and provides
history retrieval routes to sync data profiles across screens.
"""

import json
from datetime import datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db, PlayEvent, SongCatalog
from app.models.schemas import PlayLogPayload, PlayLogResponse, Song

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
        try:
            clean_ts = payload.timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
        except Exception:
            dt = datetime.utcnow()

        new_event = PlayEvent(
            username=payload.username,
            song_id=payload.song_id,
            mood_tag=payload.mood_tag,
            session_id=payload.session_id,
            timestamp=payload.timestamp,
            hour_of_day=dt.hour,
            day_of_week=dt.weekday(),
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


@router.get("/history", response_model=list[Song])
async def get_user_history(
    username: str = Query(default="default_user"),
    limit: int = Query(default=10, ge=1, le=20),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the unique recently played track history for a specific username context.
    Resolves track metadata against the SongCatalog to populate the frontend layout on reload.
    """
    try:
        # Fetch recent events for this specific user profile
        stmt = (
            select(PlayEvent)
            .where(PlayEvent.username == username)
            .order_by(PlayEvent.created_at.desc())
            .limit(limit * 3)  # Pull extra rows to filter out duplicate plays cleanly in Python
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

        # Extract unique song IDs while preserving the exact chronological sequence
        seen_songs = set()
        unique_song_ids = []
        for e in events:
            if e.song_id not in seen_songs:
                seen_songs.add(e.song_id)
                unique_song_ids.append(e.song_id)
            if len(unique_song_ids) >= limit:
                break

        if not unique_song_ids:
            return []

        # Hydrate full metadata details from the catalog store
        catalog_stmt = select(SongCatalog).where(SongCatalog.id.in_(unique_song_ids))
        catalog_result = await db.execute(catalog_stmt)
        rows = catalog_result.scalars().all()
        id_to_row = {r.id: r for r in rows}

        # Map rows back to standard schemas matching the chronological timeline sequence
        songs = []
        for sid in unique_song_ids:
            row = id_to_row.get(sid)
            if row:
                songs.append(Song(
                    id=row.id,
                    title=row.title,
                    artist=row.artist,
                    album=row.album,
                    artwork=row.artwork,
                    duration=row.duration,
                    url=row.url,
                    lyrics=json.loads(row.lyrics) if row.lyrics else None
                ))
        return songs

    except Exception as e:
        logger.error(f"[History Retrieval Error] Failed to query user timeline: {str(e)}")
        return []