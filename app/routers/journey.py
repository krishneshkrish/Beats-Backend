"""
Journey timeline router.
Converts raw play events into the Music Journey storytelling format —
grouped by time-of-day, with milestone detection.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Literal

from app.db.database import get_db, PlayEvent, SongCatalog
from app.db.mock_data import MOCK_JOURNEY, MOCK_SONGS
from app.models.schemas import TimelineItem, Song

router = APIRouter(prefix="/api/journey", tags=["journey"])

# Build a quick lookup from mock songs
SONG_MAP = {s.id: s for s in MOCK_SONGS}


def _time_label(hour: int) -> str:
    if 5 <= hour < 12:
        return "Morning Sessions"
    elif 12 <= hour < 17:
        return "Afternoon Focus"
    elif 17 <= hour < 22:
        return "Evening Vibes"
    else:
        return "Late Night"


def _detect_milestone(
    song_id: str,
    play_count: int,
    new_artists: set[str],
    song_artist: str,
) -> tuple[bool, str | None]:
    """
    Milestone triggers:
    - First time hearing an artist
    - Every 50th play
    - Round play counts (100, 200, ...)
    """
    if play_count in {100, 200, 500}:
        return True, f"🎉 {play_count} songs played on Beats!"

    if song_artist in new_artists:
        return True, f"New artist discovered: {song_artist} 🌟"

    return False, None


@router.get("/timeline", response_model=list[TimelineItem])
async def journey_timeline(
    request: Request,
    username: str = Query(default="default_user"),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(PlayEvent)
        .where(PlayEvent.username == username)
        .order_by(PlayEvent.created_at.desc())
        .limit(50)
    )
    events = result.scalars().all()

    base_url = str(request.base_url)

    if len(events) < 3:
        mock_copies = []
        for item in MOCK_JOURNEY:
            song_copy = Song(
                id=item.song.id,
                title=item.song.title,
                artist=item.song.artist,
                album=item.song.album,
                artwork=item.song.artwork,
                duration=item.song.duration,
                url=item.song.url,
                lyrics=item.song.lyrics
            )
            song_copy.resolve_url(base_url)
            mock_copies.append(TimelineItem(
                id=item.id,
                timestamp=item.timestamp,
                song=song_copy,
                moodTag=item.moodTag,
                timeLabel=item.timeLabel,
                isMilestone=item.isMilestone,
                milestoneText=item.milestoneText
            ))
        return mock_copies

    # Pre-fetch dynamic song catalog mapping
    song_ids = [e.song_id for e in events]
    catalog_result = await db.execute(
        select(SongCatalog).where(SongCatalog.id.in_(song_ids))
    )
    catalog_rows = catalog_result.scalars().all()
    
    import json
    catalog_map = {}
    for r in catalog_rows:
        try:
            lyrics_parsed = json.loads(r.lyrics) if r.lyrics else None
        except Exception:
            lyrics_parsed = None
        catalog_map[r.id] = Song(
            id=r.id,
            title=r.title,
            artist=r.artist,
            album=r.album,
            artwork=r.artwork,
            duration=r.duration,
            url=r.url,
            lyrics=lyrics_parsed
        )

    # Process events chronologically (oldest to newest) to detect true historical milestones
    chrono_events = list(reversed(events))
    chrono_items: list[TimelineItem] = []
    seen_artists: set[str] = set()
    play_count = 0

    for event in chrono_events:
        song = catalog_map.get(event.song_id) or SONG_MAP.get(event.song_id)
        if not song:
            continue

        play_count += 1
        is_new_artist = song.artist not in seen_artists
        if is_new_artist:
            seen_artists.add(song.artist)

        is_milestone, milestone_text = _detect_milestone(
            event.song_id,
            play_count,
            {song.artist} if is_new_artist else set(),
            song.artist,
        )

        hour = event.hour_of_day if event.hour_of_day is not None else 12
        label = _time_label(hour)

        # Use created_at for timestamp, fallback to stored timestamp
        ts = (
            event.created_at.isoformat() + "Z"
            if event.created_at
            else event.timestamp
        )

        # Copy the song object to prevent mutability issues
        song_copy = Song(
            id=song.id,
            title=song.title,
            artist=song.artist,
            album=song.album,
            artwork=song.artwork,
            duration=song.duration,
            url=song.url,
            lyrics=song.lyrics
        )
        song_copy.resolve_url(base_url)

        chrono_items.append(TimelineItem(
            id=f"j{event.id}",
            timestamp=ts,
            song=song_copy,
            moodTag=event.mood_tag,
            timeLabel=label,
            isMilestone=is_milestone,
            milestoneText=milestone_text,
        ))

    # Return timeline items in reverse chronological order (newest first for display)
    return list(reversed(chrono_items))

