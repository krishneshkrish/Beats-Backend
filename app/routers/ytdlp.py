"""
Beats — Media Router (Production Endpoint)
───────────────────────────────────────────
ytmusicapi  → Handles high-speed metadata search, charts, and native queues.
Client-Side → Bypasses server datacenter locks by returning direct player handles.
"""

import os  # ✅ Fixed: Added missing import statement
import re
import json
import uuid
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import Song
from app.core.config import get_settings

logger = logging.getLogger("beats.media")
router = APIRouter(prefix="/api/yt", tags=["media"])
settings = get_settings()

# ── ytmusicapi Client Lazy Initializer ────────────────────────────────────────

_ytmusic = None

def get_ytmusic():
    global _ytmusic
    if _ytmusic is not None:
        return _ytmusic
    try:
        from ytmusicapi import YTMusic
        oauth_path = settings.YTMUSIC_OAUTH_PATH
        
        if os.path.exists(oauth_path):
            try:
                with open(oauth_path, "r") as f:
                    oauth_content = json.load(f)
                if "headers" in oauth_content:
                    _ytmusic = YTMusic(oauth_path)
                else:
                    _ytmusic = YTMusic(auth=json.dumps(oauth_content))
                logger.info(f"[ytmusicapi] Authenticated via {oauth_path}")
            except Exception as inner_e:
                logger.warning(f"[ytmusicapi] Falling back to standard mode: {inner_e}")
                _ytmusic = YTMusic()
        else:
            _ytmusic = YTMusic()
            logger.info("[ytmusicapi] Unauthenticated mode")
        return _ytmusic
    except Exception as e:
        logger.warning(f"[ytmusicapi] Init failed: {e}")
        return None


# ── Core Playback Helpers ─────────────────────────────────────────────────────

async def _get_stream_url(video_id: str) -> str:
    """Instantly returns an unblockable watch handle for the frontend player."""
    return f"https://www.youtube.com/watch?v={video_id}"


def _best_thumbnail(thumbnails) -> str:
    if not thumbnails:
        return ""
    if isinstance(thumbnails, list):
        for t in reversed(thumbnails):
            if isinstance(t, dict) and t.get("url"):
                return t["url"]
    return ""


def _duration_to_seconds(length: str | None) -> int:
    if not length:
        return 0
    try:
        parts = [int(p) for p in length.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except Exception:
        pass
    return 0


def _ytmusic_track_to_song(track: dict, stream_url: str) -> Song:
    thumbnails = track.get("thumbnail") or track.get("thumbnails") or []
    artists = track.get("artists") or []
    artist_name = artists[0].get("name", "Unknown") if artists else track.get("artist", "Unknown")
    album_data = track.get("album") or {}
    album_name = album_data.get("name", "YouTube Music") if isinstance(album_data, dict) else "YouTube Music"
    duration_str = track.get("duration") or track.get("length") or ""
    return Song(
        id=track.get("videoId") or str(uuid.uuid4()),
        title=track.get("title") or "Unknown Title",
        artist=artist_name,
        album=album_name,
        artwork=_best_thumbnail(thumbnails),
        duration=_duration_to_seconds(duration_str),
        url=stream_url,
        lyrics=None,
    )


# ── Production Endpoints ──────────────────────────────────────────────────────

@router.get("/search", response_model=list[Song])
async def search_media(
    q: str = Query(...),
    source: str = Query(default="youtube"),
    limit: int = Query(default=1, ge=1, le=5),
):
    """Production Search Router: Instantly runs metadata calls with zero server overhead."""
    if source == "soundcloud":
        # Gracefully handle soundcloud source searches now that yt-dlp is dropped
        return []

    ytmusic = get_ytmusic()
    if not ytmusic:
        raise HTTPException(status_code=503, detail="Search platform catalog unavailable")
        
    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, lambda: ytmusic.search(q, filter="songs", limit=limit))
        if not raw:
            return []
            
        songs = []
        for track in raw[:limit]:
            vid_id = track.get("videoId")
            if vid_id:
                stream_link = await _get_stream_url(vid_id)
                songs.append(_ytmusic_track_to_song(track, stream_link))
                
        return songs
    except Exception as e:
        logger.error(f"[Search Engine Error]: {e}")
        return []


@router.get("/queue", response_model=list[Song])
async def get_queue(
    video_id: str = Query(...),
    limit: int = Query(default=8, ge=3, le=15),
):
    """Fetches real-time YTMusic algorithmic track matrices."""
    ytmusic = get_ytmusic()
    if not ytmusic:
        return []
        
    try:
        loop = asyncio.get_event_loop()
        watch = await loop.run_in_executor(None, lambda: ytmusic.get_watch_playlist(videoId=video_id, limit=limit + 2))
        tracks = [t for t in watch.get("tracks", []) if t.get("videoId") != video_id]

        songs = []
        for t in tracks[:limit]:
            vid_id = t.get("videoId")
            if vid_id:
                stream_link = await _get_stream_url(vid_id)
                songs.append(_ytmusic_track_to_song(t, stream_link))
        return songs
    except Exception as e:
        logger.warning(f"Queue sequence optimization bypassed: {e}")
        return []


@router.get("/lyrics")
async def get_lyrics(video_id: str = Query(...)):
    ytmusic = get_ytmusic()
    if not ytmusic:
        raise HTTPException(status_code=503, detail="Lyrics engine offline")
    try:
        loop = asyncio.get_event_loop()
        watch = await loop.run_in_executor(None, lambda: ytmusic.get_watch_playlist(videoId=video_id, limit=1))
        lyrics_id = watch.get("lyrics")
        if not lyrics_id:
            raise HTTPException(status_code=404, detail="No lyrics available")
        lyrics_data = await loop.run_in_executor(None, lambda: ytmusic.get_lyrics(lyrics_id))
        return {"lyrics": [line for line in (lyrics_data.get("lyrics") or "").split("\n") if line.strip()], "source": lyrics_data.get("source", "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trending", response_model=list[Song])
async def trending_searches(mood: Optional[str] = Query(default=None)):
    """✅ Fixed: Added trending endpoints to prevent frontend 404s"""
    mood_queries = {
        "Happy":   "happy feel good songs 2026",
        "Chill":   "chill lo-fi beats study",
        "Focus":   "focus deep work music",
        "Workout": "phonk gym motivation 2026",
        "Night":   "late night r&b slow songs",
        "Sad":     "sad emotional songs hindi",
        "Party":   "party hits dance 2026",
        "Travel":  "road trip songs feel good",
    }
    query = mood_queries.get(mood or "Chill", "trending music 2026")
    ytmusic = get_ytmusic()
    if not ytmusic:
        return []
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, lambda: ytmusic.search(query, filter="songs", limit=6))
        songs = []
        if results:
            for track in results[:6]:
                vid_id = track.get("videoId")
                if vid_id:
                    stream_link = await _get_stream_url(vid_id)
                    songs.append(_ytmusic_track_to_song(track, stream_link))
        return songs
    except Exception as e:
        logger.warning(f"[Trending] failed: {e}")
        return []


@router.get("/charts", response_model=list[Song])
async def get_charts(
    country: str = Query(default="IN"),
    limit: int = Query(default=6, ge=1, le=20),
):
    """✅ Fixed: Added charts fallback handling to prevent router 404s"""
    ytmusic = get_ytmusic()
    if not ytmusic:
        return []
    try:
        loop = asyncio.get_event_loop()
        charts = await loop.run_in_executor(None, lambda: ytmusic.get_charts(country=country))
        tracks = []
        for section in ["songs", "videos", "trending"]:
            items = charts.get(section, {})
            if isinstance(items, dict):
                items = items.get("items", [])
            if items:
                tracks = items
                break
        songs = []
        for track in tracks[:limit]:
            vid_id = track.get("videoId")
            if vid_id:
                stream_link = await _get_stream_url(vid_id)
                songs.append(_ytmusic_track_to_song(track, stream_link))
        return songs
    except Exception as e:
        logger.warning(f"[Charts] failed: {e}")
        return []


@router.get("/refresh")
async def refresh_stream_url(video_id: str = Query(...), source: str = Query(default="youtube")):
    url = await _get_stream_url(video_id)
    return {"video_id": video_id, "url": url, "source": source}
