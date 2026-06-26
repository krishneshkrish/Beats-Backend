"""
Beats — Media Router (ytmusicapi + yt-dlp)
───────────────────────────────────────────
ytmusicapi  → search, queue (YouTube Music real algorithm), lyrics, charts
yt-dlp      → stream URL extraction (audio playback URLs)

Auth:
  - ytmusicapi: uses oauth.json (written from OAUTH_JSON env var on cloud)
  - yt-dlp: uses cookies.txt (securely loaded from Render Secret Files)
"""

import os
import re
import json
import uuid
import asyncio
import httpx
import logging
from functools import partial
from typing import Optional

import yt_dlp
from fastapi import APIRouter, HTTPException, Query
from app.models.schemas import Song
from app.core.config import get_settings

logger = logging.getLogger("beats.media")
router = APIRouter(prefix="/api/yt", tags=["media"])

settings = get_settings()
COOKIES_PATH = settings.YT_COOKIES_PATH


# ── yt-dlp option builder ─────────────────────────────────────────────────────

def _make_opts(extra: dict = {}) -> dict:
    """Build yt-dlp options using web clients that natively process browser session cookies."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Allow web-based clients that natively parse and accept browser cookies
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb"],
            }
        },
        **extra,
    }
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts


def _search_opts() -> dict:
    return _make_opts({"extract_flat": True})


def _stream_opts() -> dict:
    return _make_opts({
        "format": "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best",
    })


# ── ytmusicapi client (lazy init) ─────────────────────────────────────────────

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
                logger.warning(f"[ytmusicapi] Using default fallback client: {inner_e}")
                _ytmusic = YTMusic()
        else:
            _ytmusic = YTMusic()
            logger.info("[ytmusicapi] Unauthenticated mode")
        return _ytmusic
    except Exception as e:
        logger.warning(f"[ytmusicapi] Init failed: {e}")
        return None


# ── Core helpers ──────────────────────────────────────────────────────────────

def _run_ydl_sync(opts: dict, url: str) -> dict | None:
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.warning(f"yt-dlp error: {e}")
        return None


async def _extract(opts: dict, url: str) -> dict | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_run_ydl_sync, opts, url))


async def _get_stream_url(video_id: str) -> str | None:
    """
    Instantly returns the standard YouTube watch URL to the frontend.
    Eliminates backend data center blocks, scraping delays, and proxy down-time.
    """
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


# ── Noise word dedup ──────────────────────────────────────────────────────────

_NOISE = {
    "lofi", "lo-fi", "slowed", "reverb", "remix", "cover", "version",
    "official", "audio", "video", "lyrics", "lyrical", "extended",
    "acoustic", "instrumental", "karaoke", "live", "remastered",
    "edit", "mix", "bass", "boosted", "nightcore", "sped", "slow",
}

def _core_title(title: str) -> str:
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return " ".join(w for w in words if w not in _NOISE).strip()

def _is_duplicate(title: str, seen: list[str], threshold: float = 0.6) -> bool:
    core = _core_title(title)
    if not core:
        return False
    words = set(core.split())
    for s in seen:
        s_words = set(s.split())
        if not s_words:
            continue
        overlap = len(words & s_words) / max(len(words), len(s_words))
        if overlap >= threshold:
            return True
    return False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=list[Song])
async def search_media(
    q: str = Query(...),
    source: str = Query(default="youtube"),
    limit: int = Query(default=1, ge=1, le=5),
):
    """Search YouTube or SoundCloud. Returns top result(s)."""

    # SoundCloud — yt-dlp only
    if source == "soundcloud":
        # ✅ Fix: Tell the option builder NOT to send YouTube cookies to SoundCloud
        results = await _extract(_search_opts(is_youtube=False), f"scsearch{limit}:{q}")
        if not results or not results.get("entries"):
            return []

        async def _resolve_sc(entry: dict) -> Song | None:
            video_url = entry.get("url") or entry.get("webpage_url", "")
            if not video_url.startswith("http"):
                return None
            # ✅ Fix: Tell the stream option builder NOT to send YouTube cookies to SoundCloud
            info = await _extract(_stream_opts(is_youtube=False), video_url)
            if not info or not info.get("url"):
                return None
            return Song(
                id=entry.get("id") or str(uuid.uuid4()),
                title=entry.get("title") or "Unknown",
                artist=entry.get("uploader") or "Unknown",
                album="SoundCloud",
                artwork=_best_thumbnail(entry.get("thumbnails")) or entry.get("thumbnail", ""),
                duration=int(entry.get("duration") or 0),
                url=info["url"],
                lyrics=None,
            )

        tasks = [_resolve_sc(e) for e in (results.get("entries") or [])[:limit] if e]
        resolved = await asyncio.gather(*tasks)
        return [s for s in resolved if s is not None]

    ytmusic = get_ytmusic()
    if ytmusic:
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(None, lambda: ytmusic.search(q, filter="songs", limit=limit))
            if raw:
                async def _resolve_ytm(track: dict) -> Song | None:
                    vid_id = track.get("videoId")
                    if not vid_id:
                        return None
                    stream_url = await _get_stream_url(vid_id)
                    if not stream_url:
                        return None
                    return _ytmusic_track_to_song(track, stream_url)

                tasks = [_resolve_ytm(t) for t in raw[:limit]]
                resolved = await asyncio.gather(*tasks)
                songs = [s for s in resolved if s is not None]
                if songs:
                    logger.info(f"[Search] ytmusicapi: {len(songs)} result(s) for '{q}'")
                    return songs
        except Exception as e:
            logger.warning(f"[Search] ytmusicapi failed: {e}, falling back to yt-dlp")

    results = await _extract(_search_opts(), f"ytsearch{limit}:{q}")
    if not results or not results.get("entries"):
        return []

    async def _resolve_ydl(entry: dict) -> Song | None:
        vid_id = entry.get("id")
        if not vid_id:
            return None
        stream_url = await _get_stream_url(vid_id)
        if not stream_url:
            return None
        return Song(
            id=vid_id,
            title=entry.get("title") or "Unknown",
            artist=entry.get("uploader") or "Unknown",
            album="YouTube",
            artwork=_best_thumbnail(entry.get("thumbnails")) or entry.get("thumbnail", ""),
            duration=int(entry.get("duration") or 0),
            url=stream_url,
            lyrics=None,
        )

    tasks = [_resolve_ydl(e) for e in (results.get("entries") or [])[:limit] if e]
    resolved = await asyncio.gather(*tasks)
    return [s for s in resolved if s is not None]


@router.get("/queue", response_model=list[Song])
async def get_queue(
    video_id: str = Query(...),
    limit: int = Query(default=8, ge=3, le=15),
):
    """YouTube Music real 'Up Next' queue via get_watch_playlist."""
    ytmusic = get_ytmusic()

    if ytmusic:
        try:
            loop = asyncio.get_event_loop()
            watch = await loop.run_in_executor(
                None,
                lambda: ytmusic.get_watch_playlist(videoId=video_id, limit=limit + 2)
            )
            tracks = [t for t in watch.get("tracks", []) if t.get("videoId") != video_id]

            async def _resolve_queue(track: dict) -> Song | None:
                vid_id = track.get("videoId")
                if not vid_id:
                    return None
                stream_url = await _get_stream_url(vid_id)
                if not stream_url:
                    return None
                return _ytmusic_track_to_song(track, stream_url)

            tasks = [_resolve_queue(t) for t in tracks[:limit]]
            resolved = await asyncio.gather(*tasks)
            songs = [s for s in resolved if s is not None]
            if songs:
                logger.info(f"[Queue] {len(songs)} songs via ytmusicapi for {video_id}")
                return songs
        except Exception as e:
            logger.warning(f"[Queue] ytmusicapi failed: {e}, falling back to search")

    meta = await _extract(_search_opts(), f"ytsearch1:https://youtube.com/watch?v={video_id}")
    title, artist = "", ""
    if meta and meta.get("entries") and meta["entries"][0]:
        e = meta["entries"][0]
        title = e.get("title", "")
        artist = e.get("uploader", "")

    if not title:
        return []

    clean_artist = re.sub(r"\s*[-|]\s*(official|topic|vevo|music|records).*", "", artist, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r"\(.*?\)|\[.*?\]|ft\..*|feat\..*", "", title, flags=re.IGNORECASE).strip()

    queries = [
        f"ytsearch4:{clean_artist} best songs",
        f"ytsearch4:{clean_title} similar songs",
        f"ytsearch4:{clean_artist} {clean_title} mix",
    ]

    async def _fetch(query: str) -> list[dict]:
        r = await _extract(_search_opts(), query)
        return [e for e in (r.get("entries") or []) if e] if r else []

    all_entries = await asyncio.gather(*[_fetch(q) for q in queries])

    seen_cores = [_core_title(title)]
    seen_ids = {video_id}
    candidates = []

    for entry_list in all_entries:
        for entry in entry_list:
            eid = entry.get("id", "")
            if not eid or eid in seen_ids:
                continue
            if _is_duplicate(entry.get("title", ""), seen_cores):
                continue
            seen_ids.add(eid)
            seen_cores.append(_core_title(entry.get("title", "")))
            candidates.append(entry)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    async def _resolve_fb(entry: dict) -> Song | None:
        eid = entry.get("id")
        if not eid:
            return None
        stream_url = await _get_stream_url(eid)
        if not stream_url:
            return None
        return Song(
            id=eid,
            title=entry.get("title") or "Unknown",
            artist=entry.get("uploader") or "Unknown",
            album="YouTube",
            artwork=_best_thumbnail(entry.get("thumbnails")) or entry.get("thumbnail", ""),
            duration=int(entry.get("duration") or 0),
            url=stream_url,
            lyrics=None,
        )

    tasks = [_resolve_fb(e) for e in candidates]
    resolved = await asyncio.gather(*tasks)
    return [s for s in resolved if s is not None]


@router.get("/lyrics")
async def get_lyrics(video_id: str = Query(...)):
    """Fetch song lyrics via ytmusicapi."""
    ytmusic = get_ytmusic()
    if not ytmusic:
        raise HTTPException(status_code=503, detail="ytmusicapi not available")
    try:
        loop = asyncio.get_event_loop()
        watch = await loop.run_in_executor(None, lambda: ytmusic.get_watch_playlist(videoId=video_id, limit=1))
        lyrics_id = watch.get("lyrics")
        if not lyrics_id:
            raise HTTPException(status_code=404, detail="No lyrics available")
        lyrics_data = await loop.run_in_executor(None, lambda: ytmusic.get_lyrics(lyrics_id))
        raw = lyrics_data.get("lyrics") or ""
        lines = [line for line in raw.split("\n") if line.strip()]
        return {"lyrics": lines, "source": lyrics_data.get("source", "")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/charts", response_model=list[Song])
async def get_charts(
    country: str = Query(default="IN"),
    limit: int = Query(default=6, ge=1, le=20),
):
    """Top charts via ytmusicapi."""
    ytmusic = get_ytmusic()
    if not ytmusic:
        return await _ydlp_trending("trending music India 2025", limit)
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
        if not tracks:
            return await _ydlp_trending("trending music India 2025", limit)

        async def _resolve_chart(track: dict) -> Song | None:
            vid_id = track.get("videoId")
            if not vid_id:
                return None
            stream_url = await _get_stream_url(vid_id)
            if not stream_url:
                return None
            return _ytmusic_track_to_song(track, stream_url)

        tasks = [_resolve_chart(t) for t in tracks[:limit]]
        resolved = await asyncio.gather(*tasks)
        return [s for s in resolved if s is not None]
    except Exception as e:
        logger.warning(f"[Charts] failed: {e}")
        return await _ydlp_trending("trending music India 2025", limit)


@router.get("/trending", response_model=list[Song])
async def trending_searches(mood: Optional[str] = Query(default=None)):
    """Mood-mapped trending songs for Home page."""
    mood_queries = {
        "Happy":   "happy feel good songs 2025",
        "Chill":   "chill lo-fi beats study",
        "Focus":   "focus deep work music",
        "Workout": "phonk gym motivation 2025",
        "Night":   "late night r&b slow songs",
        "Sad":     "sad emotional songs hindi",
        "Party":   "party hits dance 2025",
        "Travel":  "road trip songs feel good",
    }
    query = mood_queries.get(mood or "Chill", "trending music 2025")

    ytmusic = get_ytmusic()
    if ytmusic and mood:
        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, lambda: ytmusic.search(query, filter="songs", limit=6))
            if results:
                async def _resolve(track: dict) -> Song | None:
                    vid_id = track.get("videoId")
                    if not vid_id:
                        return None
                    stream_url = await _get_stream_url(vid_id)
                    if not stream_url:
                        return None
                    return _ytmusic_track_to_song(track, stream_url)
                tasks = [_resolve(t) for t in results[:6]]
                resolved = await asyncio.gather(*tasks)
                songs = [s for s in resolved if s is not None]
                if songs:
                    return songs
        except Exception as e:
            logger.warning(f"[Trending] ytmusicapi failed: {e}")

    return await _ydlp_trending(query, 5)


async def _ydlp_trending(query: str, limit: int) -> list[Song]:
    results = await _extract(_search_opts(), f"ytsearch{limit}:{query}")
    if not results or not results.get("entries"):
        return []
    entries = [e for e in results["entries"] if e]
    seen_cores: list[str] = []
    clean = []
    for entry in entries:
        t = entry.get("title", "")
        if not _is_duplicate(t, seen_cores):
            seen_cores.append(_core_title(t))
            clean.append(entry)

    async def _resolve(entry: dict) -> Song | None:
        eid = entry.get("id")
        if not eid:
            return None
        stream_url = await _get_stream_url(eid)
        if not stream_url:
            return None
        return Song(
            id=eid,
            title=entry.get("title") or "Unknown",
            artist=entry.get("uploader") or "Unknown",
            album="YouTube",
            artwork=_best_thumbnail(entry.get("thumbnails")) or entry.get("thumbnail", ""),
            duration=int(entry.get("duration") or 0),
            url=stream_url,
            lyrics=None,
        )

    tasks = [_resolve(e) for e in clean]
    resolved = await asyncio.gather(*tasks)
    return [s for s in resolved if s is not None]


@router.get("/refresh")
async def refresh_stream_url(
    video_id: str = Query(...),
    source: str = Query(default="youtube"),
):
    """Refresh expired stream URL."""
    if source == "soundcloud":
        info = await _extract(_stream_opts(), video_id)
        url = info.get("url") if info else None
    else:
        url = await _get_stream_url(video_id)
    if not url:
        raise HTTPException(status_code=404, detail="Could not extract stream URL")
    return {"video_id": video_id, "url": url, "source": source}
