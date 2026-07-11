"""
Beats — Play Logging & Dynamic Catalog Hydration Router
────────────────────────────────────────────────────────
Captures track playback telemetries, dynamically caches new
external streaming catalog parameters, and serves fleet timeline syncs.
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
    Logs track execution events under user profiles.
    Dynamically caches missing stream properties directly into the Catalog table.
    """
    try:
        # 1. Safe date parsing for temporal ML tracking arrays
        try:
            clean_ts = payload.timestamp.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_ts)
        except Exception:
            dt = datetime.utcnow()

        # 2. Dynamic Catalog Cache Check
        catalog_check = await db.execute(select(SongCatalog).where(SongCatalog.id == payload.song_id))
        existing_song = catalog_check.scalar_one_or_none()

        if not existing_song and payload.title:
            logger.info(f"[Catalog Cache] Caching new track definition to DB: {payload.title} ({payload.song_id})")
            new_catalog_entry = SongCatalog(
                id=payload.song_id,
                title=payload.title,
                artist=payload.artist or "Unknown Artist",
                album=payload.album or "YouTube Stream",
                artwork=payload.artwork or "",
                duration=payload.duration or 0,
                url=payload.url or "",
                lyrics=json.dumps([]),
                genre="Unknown",
                mood_tags=json.dumps([payload.mood_tag])
            )
            db.add(new_catalog_entry)
            await db.flush()  # Flushes buffer state to ensure ID presence for dependencies

        # 3. Create the user-scoped play event logging record
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
        await db.rollback()
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
    """
    try:
        stmt = (
            select(PlayEvent)
            .where(PlayEvent.username == username)
            .order_by(PlayEvent.created_at.desc())
            .limit(limit * 3)
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

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

        catalog_stmt = select(SongCatalog).where(SongCatalog.id.in_(unique_song_ids))
        catalog_result = await db.execute(catalog_stmt)
        rows = catalog_result.scalars().all()
        id_to_row = {r.id: r for r in rows}

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