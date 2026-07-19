"""
Journey timeline router.
Converts raw play events into the Music Journey storytelling format —
grouped by time-of-day, with milestone detection.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from typing import Literal

from app.db.database import get_db, PlayEvent
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
async def journey_timeline(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PlayEvent).order_by(PlayEvent.created_at.desc()).limit(50)
    )
    events = result.scalars().all()

    base_url = str(request.base_url)

    if len(events) < 3:
        for item in MOCK_JOURNEY:
            item.song.resolve_url(base_url)
        return MOCK_JOURNEY

    items: list[TimelineItem] = []
    seen_artists: set[str] = set()
    play_count = 0

    for i, event in enumerate(events):
        song = SONG_MAP.get(event.song_id)
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

        # Copy the song object to prevent mutability issues on the global map
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

        items.append(TimelineItem(
            id=f"j{event.id}",
            timestamp=ts,
            song=song_copy,
            moodTag=event.mood_tag,
            timeLabel=label,
            isMilestone=is_milestone,
            milestoneText=milestone_text,
        ))

    return items
