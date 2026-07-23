"""
Analytics router — powers the 'Your Music DNA' dashboard.

When you have real play history, this computes live stats from the DB.
Before that, falls back to mock data so the UI looks rich immediately.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from collections import Counter
from datetime import datetime, timedelta

from app.db.database import get_db, PlayEvent
from app.db.mock_data import MOCK_ANALYTICS, SONG_GENRE_MAP
from app.models.schemas import AnalyticsSummary, CircularProgressItem, GenreDataItem, HeatmapDataItem

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Song duration map (seconds) — used to calculate total time
SONG_DURATION_MAP = {
    "s1": 217, "s2": 198, "s3": 183, "s4": 234, "s5": 251,
    "s6": 209, "s7": 174, "s8": 262, "s9": 241, "s10": 228,
}

SONG_TITLE_MAP = {
    "s1": "Neon Horizons", "s2": "Midnight Drift", "s3": "Phonk Adrenaline",
    "s4": "Chill Theorem", "s5": "Solar Flare",    "s6": "Glass Echoes",
    "s7": "Iron Tempo",    "s8": "Lucid State",    "s9": "Late Night Protocol",
    "s10": "Golden Hour",
}

SONG_ARTIST_MAP = {
    "s1": "Aether Vortex", "s2": "Luna Echo",   "s3": "Drift King",
    "s4": "Lo-Fi Sage",    "s5": "Pulse Theory", "s6": "Mira Voss",
    "s7": "Gage",          "s8": "Reverie",      "s9": "Cipher",
    "s10": "Solstice",
}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PlayEvent))
    events = result.scalars().all()

    if len(events) < 5:
        # Not enough real data yet — return rich mock data
        return MOCK_ANALYTICS

    # ── Real computed analytics ─────────────────────────────────────────────

    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)

    # Total listening time (minutes)
    total_seconds = sum(
        SONG_DURATION_MAP.get(e.song_id, 200)
        for e in events
        if not e.was_skipped
    )
    total_minutes = total_seconds // 60

    # Weekly time
    weekly_events = [
        e for e in events
        if e.created_at and e.created_at >= week_ago
    ]
    weekly_seconds = sum(
        SONG_DURATION_MAP.get(e.song_id, 200)
        for e in weekly_events
        if not e.was_skipped
    )
    weekly_minutes = weekly_seconds // 60

    # Top song, artist, genre
    song_counter = Counter(e.song_id for e in events if not e.was_skipped)
    top_song_id = song_counter.most_common(1)[0][0] if song_counter else "s1"
    top_song = SONG_TITLE_MAP.get(top_song_id, "Unknown")
    top_artist = SONG_ARTIST_MAP.get(top_song_id, "Unknown")

    genre_counter = Counter(
        SONG_GENRE_MAP.get(e.song_id, "Unknown")
        for e in events if not e.was_skipped
    )
    top_genre = genre_counter.most_common(1)[0][0] if genre_counter else "Electronic"

    # Streak calculation (consecutive days with plays)
    play_days = sorted(set(
        e.created_at.date()
        for e in events
        if e.created_at
    ), reverse=True)

    streak = 0
    if play_days:
        today = datetime.utcnow().date()
        if (today - play_days[0]).days <= 1:
            streak = 1
            for i in range(1, len(play_days)):
                if (play_days[i - 1] - play_days[i]).days == 1:
                    streak += 1
                else:
                    break

    # Circular progress (daily goal = 60min, weekly = 420min, streak = 30 days max)
    circular = [
        CircularProgressItem(
            label="Daily Goal",
            value=min(100, (weekly_minutes / 7) / 60 * 100),
            color="#FF3B30"
        ),
        CircularProgressItem(
            label="Weekly",
            value=min(100, weekly_minutes / 420 * 100),
            color="#FF3B30"
        ),
        CircularProgressItem(
            label="Streak",
            value=min(100, streak / 30 * 100),
            color="#FF3B30"
        ),
    ]

    # Genre distribution
    genre_data = [
        GenreDataItem(name=genre, value=count)
        for genre, count in genre_counter.most_common(6)
    ]

    # 7-day heatmap
    heatmap: dict[str, int] = {d: 0 for d in DAY_NAMES}
    for e in weekly_events:
        if e.created_at:
            day_name = DAY_NAMES[e.created_at.weekday()]
            heatmap[day_name] += 1

    heatmap_data = [
        HeatmapDataItem(day=d, count=heatmap[d])
        for d in DAY_NAMES
    ]

    return AnalyticsSummary(
        totalTime=total_minutes,
        weeklyTime=weekly_minutes,
        streak=streak,
        topArtist=top_artist,
        topGenre=top_genre,
        topSong=top_song,
        circularProgress=circular,
        genreData=genre_data,
        heatmapData=heatmap_data,
    )
