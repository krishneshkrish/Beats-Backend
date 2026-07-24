"""
Beats — High-Reliability M4A Stream Resolver Engine
────────────────────────────────────────────────────
Multi-Tier Audio Stream Resolution & Cache Engine:
- In-Memory TTL Cache (4-hour expiration)
- Tier 1: Concurrent Piped API Failover Pool (4.0s timeout per node, M4A filtering)
- Tier 2: Local yt-dlp Extractor with iOS / mweb client context & Mobile User-Agent
"""

import time
import asyncio
import logging
from typing import Dict, Tuple, Optional
import httpx

logger = logging.getLogger("beats.stream_resolver")

# ── In-Memory Stream Cache ───────────────────────────────────────────────────
# { video_id: (direct_stream_url, timestamp_expires) }
_STREAM_CACHE: Dict[str, Tuple[str, float]] = {}
CACHE_TTL_SECONDS = 14400  # 4 hours


def get_cached_stream(video_id: str) -> Optional[str]:
    """Retrieves an unexpired cached stream URL if available."""
    entry = _STREAM_CACHE.get(video_id)
    if entry:
        url, expires_at = entry
        if time.time() < expires_at:
            logger.info(f"[Stream Cache] Hit for video_id={video_id}")
            return url
        else:
            _STREAM_CACHE.pop(video_id, None)
    return None


def set_cached_stream(video_id: str, url: str, ttl: int = CACHE_TTL_SECONDS):
    """Caches a direct stream URL with TTL."""
    _STREAM_CACHE[video_id] = (url, time.time() + ttl)


# ── Tier 1: Piped API Node Resolution Pool ───────────────────────────────────
PIPED_NODES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.yt",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.us.to",
]


async def _resolve_via_piped_node(node_url: str, video_id: str) -> str:
    """Queries a single Piped node for M4A / audio/mp4 audio streams."""
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        resp = await client.get(f"{node_url}/streams/{video_id}")
        if resp.status_code == 200:
            data = resp.json()
            audio_streams = data.get("audioStreams", [])
            
            # Filter specifically for M4A / audio/mp4 streams
            m4a_streams = [
                s for s in audio_streams
                if "audio/mp4" in s.get("mimeType", "").lower()
                or s.get("format", "").lower() == "m4a"
                or "m4a" in s.get("mimeType", "").lower()
            ]
            
            target_pool = m4a_streams if m4a_streams else audio_streams
            if target_pool:
                # Sort by bitrate descending if available
                sorted_streams = sorted(
                    target_pool,
                    key=lambda x: x.get("bitrate", 0),
                    reverse=True
                )
                stream_url = sorted_streams[0].get("url")
                if stream_url:
                    return stream_url
                    
    raise ValueError(f"No valid M4A stream returned from {node_url}")


async def _resolve_tier_1(video_id: str) -> Optional[str]:
    """Concurrently queries Piped nodes with a 4.0s timeout per node."""
    tasks = [asyncio.create_task(_resolve_via_piped_node(node, video_id)) for node in PIPED_NODES]
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                url = await completed
                if url:
                    # Cancel remaining pending tasks
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    logger.info(f"[Tier 1 Piped] Successfully resolved stream for {video_id}")
                    return url
            except Exception as e:
                logger.debug(f"[Tier 1 Node Error]: {e}")
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    return None


# ── Tier 2: yt-dlp Local Extraction Fallback ────────────────────────────────
def _extract_via_ytdlp(video_id: str) -> Optional[str]:
    """Synchronous yt-dlp execution using iOS / mweb client context."""
    try:
        import yt_dlp
        target_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            if info and "url" in info:
                logger.info(f"[Tier 2 yt-dlp] Successfully extracted stream for {video_id}")
                return info["url"]
    except Exception as e:
        logger.warning(f"[Tier 2 yt-dlp Error] Failed extraction for {video_id}: {e}")
    return None


async def _resolve_tier_2(video_id: str) -> Optional[str]:
    """Runs Tier 2 yt-dlp extraction asynchronously on an executor thread."""
    return await asyncio.to_thread(_extract_via_ytdlp, video_id)


# ── Unified Stream Resolver ─────────────────────────────────────────────────
async def resolve_m4a_stream(video_id: str) -> str:
    """
    High-reliability multi-tier M4A stream resolver:
    1. Checks in-memory cache
    2. Tier 1: Piped API pool
    3. Tier 2: yt-dlp local extractor
    """
    # 1. Cache check
    cached = get_cached_stream(video_id)
    if cached:
        return cached

    # 2. Tier 1: Piped API pool
    url = await _resolve_tier_1(video_id)
    if url:
        set_cached_stream(video_id, url)
        return url

    # 3. Tier 2: yt-dlp fallback
    url = await _resolve_tier_2(video_id)
    if url:
        set_cached_stream(video_id, url)
        return url

    raise ValueError(f"Unable to resolve stream for video_id={video_id} across all resolution tiers.")
