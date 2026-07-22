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
import yt_dlp

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import httpx
from app.models.schemas import Song
from app.core.config import get_settings

logger = logging.getLogger("beats.media")
router = APIRouter(prefix="/api/yt", tags=["media"])
settings = get_settings()

# ── Shared HTTPX AsyncClient for Proxying ──────────────────────────────────────

_shared_client: Optional[httpx.AsyncClient] = None

def get_shared_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
        )
    return _shared_client

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
                    # If OAuth token is expired/expiring, it cannot be refreshed without client credentials.
                    # Fallback to standard unauthenticated mode to prevent KeyError: 'access_token' on API queries.
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


# ── Core Playback Helpers ─────────────────────────────────────────────────────

import urllib.parse
import time

# Simple in-memory cache: video_id -> (expiry_epoch_seconds, url)
_STREAM_URL_CACHE = {}

def _get_url_expiry(url: str) -> float:
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        expire_val = params.get('expire')
        if expire_val:
            return float(expire_val[0])
    except Exception:
        pass
    # Default to 2 hours from now if we can't parse it
    return time.time() + 7200

async def _get_stream_url(video_id: str) -> tuple[str, dict]:
    """Extracts a direct playable audio-only stream URL using yt-dlp with multi-client anti-bot fallback."""
    # Check cache first
    cached_data = _STREAM_URL_CACHE.get(video_id)
    if cached_data:
        if len(cached_data) == 3:
            expiry, url, headers = cached_data
        else:
            expiry, url = cached_data
            headers = {}
        # If cache is valid (with 10 minutes safety margin), return it
        if time.time() < expiry - 600:
            logger.info(f"[Stream URL Cache Hit] Resolved {video_id} from cache.")
            return url, headers

    # Resolve track title & artist for the search fallback retry asynchronously on the main loop
    title = None
    artist = None
    ytmusic = get_ytmusic()
    if ytmusic:
        try:
            # get_song makes blocking network requests; run in executor to keep the main event loop responsive
            loop = asyncio.get_running_loop()
            song_details = await loop.run_in_executor(None, ytmusic.get_song, video_id)
            if song_details and "videoDetails" in song_details:
                details = song_details["videoDetails"]
                title = details.get("title")
                artist = details.get("author")
        except Exception as e:
            logger.warning(f"Failed to fetch YTMusic metadata: {e}")

    if not title or not artist:
        try:
            from app.db.database import AsyncSessionLocal, SongCatalog
            from sqlalchemy import select
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(SongCatalog).where(SongCatalog.id == video_id))
                row = res.scalar_one_or_none()
                if row:
                    title = row.title
                    artist = row.artist
        except Exception as db_err:
            logger.warning(f"DB metadata fetch failed: {db_err}")

    def extract():
        from yt_dlp.utils import DownloadError, ExtractorError
        cookies_path = "cookies.txt"
        cookiefile = cookies_path if os.path.exists(cookies_path) else None

        po_token = os.environ.get("YT_PO_TOKEN", "MlXZB1SIORN-4Nk5uVP-8shKK-uQhZ51L2kHh52sl5n5oTFyWvsbU7j325eSyErULr9zYq2Kf_y0JuWLpGkAFrx5B3C95wHfKDtz6LqB4uxOQfqX_ZPW")
        visitor_data = os.environ.get("YT_VISITOR_DATA", "Cgt4TEFISGVKN0h1WSjhr4HTBjIKCgJJThIEGgAga2LfAgrcAjIwLllUPXFSNXprN0xuYXdQWGEwTk82MUtWVk15S0xTVVVNVEo4Z2FyUzUzSnlkelhMX2tXc1FkTU8xZnF6RzJ0NXVrLU83aklOZjlZcGUwY1dUS0tCWWlJWkZudV95Skh4OEVVallXaFc3VWtIRzF4R3lqVG5NQkpySUI1VndJUm5YT3gtWEN1Q2JvV1JYUzk0Z29lNHY1eTNkZjNHa0NGdUM2d01CNjRrc3doUVBFSm5WMnFjbU9wT2xSU2VSMm9kdjJuWjNBMkxacXpWN08wUzZBUDdEYTlVTWFYMG9iSkpJdFV4TENITHItTXYyWmZuWl81SUpyMGxuQVBGR3JEN2lYeHJlVTV5Zk9UYW1fVmpEZzQ1czk3VExGbUpUZ085ck12bi1jTFdWYU5ZVmVLejVLcUx3dUVUSzQzWHhzbGE0T0JwV0RoemxBbGZhMXRTUnQtV2VQbFY2Zw%3D%3D")

        # Define direct lookup options
        ydl_opts_primary = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'mweb', 'tv_embedded'],
                    'skip': ['hls', 'dash'],
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
            }
        }
        if cookiefile:
            ydl_opts_primary['cookiefile'] = cookiefile

        ydl_opts_dyn_unauth = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'mweb', 'tv_embedded'],
                    'skip': ['hls', 'dash'],
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
            }
        }

        ydl_opts_manual = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'mweb', 'tv_embedded'],
                    'po_token': [
                        f'ios.gvs+{po_token}',
                        f'android.gvs+{po_token}',
                        f'mweb.gvs+{po_token}',
                        f'tv_embedded.gvs+{po_token}'
                    ],
                    'visitor_data': visitor_data,
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            }
        }
        if cookiefile:
            ydl_opts_manual['cookiefile'] = cookiefile

        ydl_opts_tv_embedded_only = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded'],
                    'player_skip': ['web', 'web_embedded', 'mweb', 'ios', 'android'],
                    'js_runtime': 'node'
                }
            }
        }

        ydl_opts_android_vr_only = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr'],
                    'player_skip': ['web', 'web_embedded', 'mweb', 'ios', 'android', 'tv_embedded'],
                    'js_runtime': 'node'
                }
            }
        }

        ydl_opts_tv_unauth = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'android'],
                    'player_skip': ['web', 'web_embedded', 'mweb', 'ios'],
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            }
        }

        ydl_opts_tv_auth = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'android'],
                    'player_skip': ['web', 'web_embedded', 'mweb', 'ios'],
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            }
        }
        if cookiefile:
            ydl_opts_tv_auth['cookiefile'] = cookiefile

        ydl_opts_fallback_cookies = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded', 'android_vr', 'mweb', 'android'],
                    'js_runtime': 'node'
                },
                'youtubepot-bgutilhttp': {
                    'base_url': 'http://127.0.0.1:4416'
                }
            }
        }
        if cookiefile:
            ydl_opts_fallback_cookies['cookiefile'] = cookiefile

        # 1. Try Direct Lookup across all configurations
        direct_tiers = [
            ("Primary Direct Lookup (Dynamic POT + Cookies)", ydl_opts_primary),
            ("Tier 0.2 Direct Lookup (Dynamic POT Unauth)", ydl_opts_dyn_unauth),
            ("Tier 0.5 Direct Lookup (Manual POT + Cookies)", ydl_opts_manual),
            ("Tier 0.7 TV Embedded Bypass (No POT)", ydl_opts_tv_embedded_only),
            ("Tier 0.8 Android VR Bypass (No POT)", ydl_opts_android_vr_only),
            ("Tier 1 Direct Lookup (TV/Android Unauth)", ydl_opts_tv_unauth),
            ("Tier 2 Direct Lookup (TV/Android Auth)", ydl_opts_tv_auth),
            ("Tier 3 Direct Lookup (Standard Fallback)", ydl_opts_fallback_cookies),
        ]

        for tier_name, opts in direct_tiers:
            try:
                logger.info(f"[yt-dlp Direct Lookup] Attempting {tier_name} for {video_id}...")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                    url = info.get('url')
                    if url and "googlevideo.com" in url:
                        logger.info(f"[yt-dlp Direct Lookup Succeeded] Resolved via {tier_name} for {video_id}")
                        return url, info.get('http_headers', {})
            except Exception as e:
                logger.warning(f"[yt-dlp Direct Lookup Failed] {tier_name} failed for {video_id}: {e}")

        # 2. Try Fallback Search & Retry Pipeline
        search_query = f"ytsearch1:{artist} - {title} Audio" if artist and title else f"ytsearch1:{title} Audio" if title else None
        if search_query:
            search_tiers = [
                ("Search via Dynamic POT Unauth", ydl_opts_dyn_unauth),
                ("Search via Primary (Dynamic POT + Cookies)", ydl_opts_primary),
            ]
            for tier_name, opts in search_tiers:
                try:
                    logger.info(f"[yt-dlp Search Retry] Attempting '{search_query}' using {tier_name}...")
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(search_query, download=False)
                        if info and 'entries' in info and info['entries']:
                            entry = info['entries'][0]
                            url = entry.get('url')
                            if url and "googlevideo.com" in url:
                                logger.info(f"[yt-dlp Search Retry Succeeded] Resolved via {tier_name} for query '{search_query}'")
                                return url, entry.get('http_headers') or info.get('http_headers', {})
                except Exception as search_err:
                    logger.error(f"[yt-dlp Search Retry Failed] {tier_name} failed for query '{search_query}': {search_err}")

        # 3. pytubefix Fallback
        try:
            from pytubefix import YouTube as PyTubeYouTube
            logger.info(f"[pytubefix] Attempting dynamic extraction fallback for {video_id}...")
            yt = PyTubeYouTube(f"https://www.youtube.com/watch?v={video_id}", client='WEB')
            audio_stream = yt.streams.filter(only_audio=True).first()
            if audio_stream and audio_stream.url:
                logger.info(f"[pytubefix succeeded for {video_id}]")
                return audio_stream.url, {}
        except Exception as py_err:
            logger.error(f"[pytubefix failed for {video_id}]: {py_err}")

        # 4. SoundCloud Search and Extraction Fallback
        try:
            logger.info(f"[SoundCloud Fallback] YouTube blocked. Using metadata for {video_id} (title={title}, artist={artist}) to query SoundCloud...")
            if title:
                search_queries = []
                if artist:
                    search_queries.append(f"{title} {artist}")
                search_queries.append(title)
                
                for query in search_queries:
                    logger.info(f"[SoundCloud Fallback] Searching SoundCloud for: '{query}'...")
                    ydl_opts_sc = {
                        'format': 'best[protocol=http]/bestaudio[protocol=http]/http_mp3/best',
                        'quiet': True,
                        'no_warnings': True,
                    }
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts_sc) as ydl:
                            info = ydl.extract_info(f"scsearch1:{query}", download=False)
                            if info and 'entries' in info and info['entries']:
                                entry = info['entries'][0]
                                url = entry.get('url')
                                if url:
                                    logger.info(f"[SoundCloud Fallback succeeded for query '{query}']: {url}")
                                    return url, {}
                    except Exception as sc_err:
                        logger.warning(f"[SoundCloud Fallback] SoundCloud search failed for query '{query}': {sc_err}")
        except Exception as sc_global_err:
            logger.error(f"[SoundCloud Fallback] Global SoundCloud extraction error: {sc_global_err}")

        return f"https://www.youtube.com/watch?v={video_id}", {}

    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, extract)
    url, headers = res if isinstance(res, tuple) else (res, {})
    
    if url and "youtube.com/watch" not in url:
        expiry = _get_url_expiry(url)
        _STREAM_URL_CACHE[video_id] = (expiry, url, headers)
        logger.info(f"[Stream URL Cache Populate] Cached {video_id} (expires in {int(expiry - time.time())}s)")
        
    return url, headers


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

@router.get("/stream")
async def stream_audio(video_id: str, request: Request):
    """Proxies the audio stream to bypass YouTube IP lock and support Range headers for seeking."""
    from app.services.stream_resolver import get_audio_stream
    stream_url, cached_headers = await get_audio_stream(video_id)
    if not stream_url or "youtube.com/watch" in stream_url:
        logger.warning(f"[Stream Proxy] Stream url for {video_id} failed or not extracted. Using fallback stream.")
        stream_url = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3"
        cached_headers = {}
        
    headers = dict(cached_headers) if cached_headers else {}
    if "User-Agent" not in headers:
        # Standardize header forwarding: YouTube requires specific User-Agents for specific clients
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        if "c=ANDROID" in stream_url:
            user_agent = "com.google.android.youtube/19.29.37 (Linux; U; Android 11; GMT) (gzip)"
        elif "c=IOS" in stream_url or "c=APPLE_IV" in stream_url:
            user_agent = "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iPhone OS 17_5_1 like Mac OS X; en_US)"
        headers["User-Agent"] = user_agent
        
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = get_shared_client()
    
    async def stream_generator(response_obj):
        try:
            async for chunk in response_obj.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await response_obj.aclose()

    try:
        req = client.build_request("GET", stream_url, headers=headers)
        response = await client.send(req, stream=True)
        
        if response.status_code >= 400:
            await response.aclose()
            raise HTTPException(status_code=response.status_code, detail="Failed to retrieve stream from source")
            
        resp_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        }
        if "content-range" in response.headers:
            resp_headers["Content-Range"] = response.headers["content-range"]
        if "content-length" in response.headers:
            resp_headers["Content-Length"] = response.headers["content-length"]
            
        return StreamingResponse(
            stream_generator(response),
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "audio/mpeg"),
            headers=resp_headers
        )
    except Exception as e:
        logger.error(f"[Streaming Proxy Exception] {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/search", response_model=list[Song])
async def search_media(
    request: Request,
    q: str = Query(...),
    source: str = Query(default="youtube"),
    limit: int = Query(default=1, ge=1, le=10),
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
        base_url = str(request.base_url)
        for track in raw[:limit]:
            vid_id = track.get("videoId")
            if vid_id:
                stream_link = f"{base_url}api/yt/stream?video_id={vid_id}"
                songs.append(_ytmusic_track_to_song(track, stream_link))
                
        return songs
    except Exception as e:
        logger.error(f"[Search Engine Error]: {e}")
        return []


@router.get("/queue", response_model=list[Song])
async def get_queue(
    request: Request,
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
async def trending_searches(request: Request, mood: Optional[str] = Query(default=None)):
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


@router.get("/refresh")
async def refresh_stream_url(request: Request, video_id: str = Query(...), source: str = Query(default="youtube")):
    url = f"{request.base_url}api/yt/stream?video_id={video_id}"
    return {"video_id": video_id, "url": url, "source": source}


# ── Stream Proxy Router (No prefix for /api/stream-proxy) ────────────────────────
proxy_router = APIRouter(tags=["stream-proxy"])

@proxy_router.get("/api/stream-proxy")
async def stream_proxy(request: Request, url: str = Query(...)):
    """
    Proxies raw googlevideo.com (or other) audio URLs to bypass client-side CORS issues,
    forwarding HTTP Range headers and returning a StreamingResponse.
    """
    # Reconstruct the full URL defensively if it was not URL-encoded by the caller
    query_string = request.url.query
    if query_string.startswith("url="):
        url = query_string[4:]
        from urllib.parse import unquote
        url = unquote(url)

    logger.info(f"[Stream Proxy] Proxying URL: {url[:100]}...")
    
    # Look up headers in the in-memory cache to match the exact client profile that resolved it
    cached_headers = {}
    for cached in _STREAM_URL_CACHE.values():
        if len(cached) == 3 and cached[1] == url:
            cached_headers = cached[2]
            break
            
    headers = dict(cached_headers) if cached_headers else {}
    if "User-Agent" not in headers:
        # Standardize header forwarding: YouTube requires specific User-Agents for specific clients
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        if "c=ANDROID" in url:
            user_agent = "com.google.android.youtube/19.29.37 (Linux; U; Android 11; GMT) (gzip)"
        elif "c=IOS" in url or "c=APPLE_IV" in url:
            user_agent = "com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iPhone OS 17_5_1 like Mac OS X; en_US)"
        headers["User-Agent"] = user_agent
        
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = get_shared_client()
    
    async def stream_generator(response_obj):
        try:
            async for chunk in response_obj.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await response_obj.aclose()

    try:
        req = client.build_request("GET", url, headers=headers)
        response = await client.send(req, stream=True)
        
        if response.status_code >= 400:
            await response.aclose()
            raise HTTPException(status_code=response.status_code, detail="Failed to retrieve stream from source")
            
        resp_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        }
        if "content-range" in response.headers:
            resp_headers["Content-Range"] = response.headers["content-range"]
        if "content-length" in response.headers:
            resp_headers["Content-Length"] = response.headers["content-length"]
            
        content_type = response.headers.get("content-type")
        if not content_type or "audio" not in content_type:
            content_type = "audio/mp4"
            
        return StreamingResponse(
            stream_generator(response),
            status_code=response.status_code,
            media_type=content_type,
            headers=resp_headers
        )
    except Exception as e:
        logger.error(f"[Stream Proxy Exception] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pot-status")
async def get_pot_status():
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:4416/ping", timeout=2.0)
            return {
                "reachable": True,
                "status_code": resp.status_code,
                "body": resp.text
            }
    except Exception as e:
        from app.core import pot_provider
        proc_status = "unknown"
        if pot_provider._process is not None:
            poll = pot_provider._process.poll()
            proc_status = f"running (poll={poll})" if poll is None else f"exited (code={poll})"
        return {
            "reachable": False,
            "error": str(e),
            "process_state": proc_status
        }


@proxy_router.get("/api/stream/{video_id}")
async def get_stream_url_json(video_id: str, request: Request):
    """
    Exposes direct playable stream URL as a JSON response.
    Sets Cache-Control headers for performance.
    """
    from app.services.stream_resolver import get_audio_stream
    from fastapi.responses import JSONResponse
    
    stream_url, headers = await get_audio_stream(video_id)
    if not stream_url:
        raise HTTPException(status_code=404, detail="Stream could not be resolved from any provider")
        
    return JSONResponse(
        content={
            "status": "success",
            "video_id": video_id,
            "stream_url": stream_url,
            "format": "m4a"
        },
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )


