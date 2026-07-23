"""
Beats — Media Router (Lightweight Metadata API)
───────────────────────────────────────────────
ytmusicapi  → Handles high-speed metadata search, charts, and native queues.
Client-Side → Playback is resolved on the client using youtubei.js.
"""

import os
import re
import json
import uuid
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
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
        from ytmusicapi import YTMusic, OAuthCredentials
        oauth_path = settings.YTMUSIC_OAUTH_PATH
        
        if os.path.exists(oauth_path):
            try:
                with open(oauth_path, "r") as f:
                    oauth_content = json.load(f)
                if "headers" in oauth_content:
                    _ytmusic = YTMusic(oauth_path)
                else:
                    import time
                    expires_at = oauth_content.get("expires_at", 0)
                    if expires_at and (expires_at - int(time.time()) < 60):
                        raise ValueError("OAuth token is expired and client credentials are not available to refresh it.")
                        
                    _ytmusic = YTMusic(
                        auth=json.dumps(oauth_content),
                        oauth_credentials=OAuthCredentials(client_id="", client_secret="")
                    )
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


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    request: Request,
    response: Response,
    q: str = Query(...),
    source: str = Query(default="youtube"),
    limit: int = Query(default=1, ge=1, le=10),
):
    """Production Search Router: Instantly runs metadata calls with zero server overhead."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    if source == "soundcloud":
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
        base_url = str(request.base_url)
        for track in raw[:limit]:
            vid_id = track.get("videoId")
            if vid_id:
                # Retain structural compatibility. Stream URL is now fully resolved on client.
                stream_link = f"{base_url}api/yt/stream?video_id={vid_id}"
                songs.append(_ytmusic_track_to_song(track, stream_link))
                
        return songs
    except Exception as e:
        logger.error(f"[Search Engine Error]: {e}")
        return []


@router.get("/queue", response_model=list[Song])
async def get_queue(
    request: Request,
    response: Response,
    video_id: str = Query(...),
    limit: int = Query(default=8, ge=3, le=15),
):
    """Fetches real-time YTMusic algorithmic track matrices."""
    response.headers["Cache-Control"] = "public, max-age=3600"
    ytmusic = get_ytmusic()
    if not ytmusic:
        return []
        
    try:
        loop = asyncio.get_event_loop()
        watch = await loop.run_in_executor(None, lambda: ytmusic.get_watch_playlist(videoId=video_id, limit=limit + 2))
        tracks = [t for t in watch.get("tracks", []) if t.get("videoId") != video_id]

        songs = []
        base_url = str(request.base_url)
        for t in tracks[:limit]:
            vid_id = t.get("videoId")
            if vid_id:
                stream_link = f"{base_url}api/yt/stream?video_id={vid_id}"
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trending", response_model=list[Song])
async def trending_searches(request: Request, response: Response, mood: Optional[str] = Query(default=None)):
    response.headers["Cache-Control"] = "public, max-age=3600"
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
        base_url = str(request.base_url)
        if results:
            for track in results[:6]:
                vid_id = track.get("videoId")
                if vid_id:
                    stream_link = f"{base_url}api/yt/stream?video_id={vid_id}"
                    songs.append(_ytmusic_track_to_song(track, stream_link))
        return songs
    except Exception as e:
        logger.warning(f"[Trending] failed: {e}")
        return []


@router.get("/charts", response_model=list[Song])
async def get_charts(
    request: Request,
    response: Response,
    country: str = Query(default="IN"),
    limit: int = Query(default=6, ge=1, le=20),
):
    response.headers["Cache-Control"] = "public, max-age=3600"
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
        base_url = str(request.base_url)
        for track in tracks[:limit]:
            vid_id = track.get("videoId")
            if vid_id:
                stream_link = f"{base_url}api/yt/stream?video_id={vid_id}"
                songs.append(_ytmusic_track_to_song(track, stream_link))
        return songs
    except Exception as e:
        logger.warning(f"[Charts] failed: {e}")
        return []


# ── CORS Proxy & Refresh Failover Endpoints ───────────────────────────────────

import httpx
from pydantic import BaseModel
from typing import Any, Dict, Optional

class ProxyRequest(BaseModel):
    url: str
    method: str = "GET"
    headers: Dict[str, str] = {}
    body: Optional[Any] = None

@router.post("/proxy")
async def yt_proxy(req: ProxyRequest):
    """
    Lightweight InnerTube API Proxy
    Routes browser-based metadata/session queries to avoid client CORS blocks.
    """
    allowed_domains = ["youtube.com", "googleapis.com", "ytimg.com"]
    if not any(domain in req.url for domain in allowed_domains):
         raise HTTPException(status_code=400, detail="Domain not authorized for proxying")
         
    try:
        headers_to_send = {k: v for k, v in req.headers.items() if k.lower() not in ["host", "origin", "referer", "accept-encoding"]}
        
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            if req.method.upper() == "POST":
                json_data = None
                content_data = None
                if req.body:
                    if isinstance(req.body, str):
                        try:
                            json_data = json.loads(req.body)
                        except:
                            content_data = req.body.encode('utf-8')
                    else:
                        json_data = req.body
                res = await client.post(req.url, headers=headers_to_send, json=json_data, content=content_data)
            else:
                res = await client.get(req.url, headers=headers_to_send)
                
            return Response(
                content=res.content,
                status_code=res.status_code,
                media_type=res.headers.get("content-type")
            )
    except Exception as e:
        logger.error(f"Proxy request failed to {req.url}: {e}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")


@router.get("/refresh")
async def refresh_stream(video_id: str, source: str = "youtube"):
    """
    Refreshes direct audio stream URL via Piped API instance failover pool.
    """
    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.yt",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.us.to",
    ]
    for instance in piped_instances:
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
                res = await client.get(f"{instance}/streams/{video_id}")
                if res.status_code == 200:
                    data = res.json()
                    audio_streams = data.get("audioStreams", [])
                    if audio_streams:
                        best_audio = audio_streams[0]
                        return {"url": best_audio.get("url")}
        except Exception as e:
            logger.warning(f"Failed to resolve stream via Piped instance {instance}: {e}")
            
    raise HTTPException(status_code=502, detail="Failed to resolve stream from all public fallbacks")
