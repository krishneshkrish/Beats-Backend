"""
Beats — High-Reliability M4A Stream Resolver Engine
────────────────────────────────────────────────────
Multi-Tier Audio Stream Resolution & Cache Engine:
- In-Memory TTL Cache (4-hour expiration)
- Tier 1: Concurrent Piped API Failover Pool (4.0s timeout per node, M4A filtering)
- Tier 2: Local yt-dlp Extractor with iOS / mweb client context & Mobile User-Agent
"""

import os
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
PIPED_INSTANCES = [
    "https://pipedapi.palvelu.org",
    "https://pipedapi.mha.fi",
    "https://pipedapi.drgns.space",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.lunar.icu",
    "https://api.piped.yt",
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
]
PIPED_NODES = PIPED_INSTANCES


async def _resolve_via_piped_node(node_url: str, video_id: str) -> str:
    """Queries a single Piped node for M4A / audio/mp4 audio streams with a 3.5s timeout."""
    async with httpx.AsyncClient(timeout=3.5, follow_redirects=True) as client:
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
    """Concurrently queries Piped nodes with a 3.5s timeout per node."""
    tasks = [asyncio.create_task(_resolve_via_piped_node(node, video_id)) for node in PIPED_INSTANCES]
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


def _extract_via_ytdlp(video_id: str) -> Optional[str]:
    """
    Synchronous yt-dlp execution using android_vr / tv_embedded / ios client profile
    to bypass YouTube BotGuard / GetPOT PO token verification.
    """
    try:
        import yt_dlp
        target_url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "nocheckcertificate": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android_vr", "tv_embedded", "ios"],
                    "skip": ["hls", "dash"]
                }
            },
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (SmartTV; Linux; Tizen 6.0) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) SamsungBrowser/4.0 Chrome/76.0.3809.146 TV Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            if info and "url" in info:
                logger.info(f"[Tier 2 yt-dlp] Successfully extracted stream for {video_id} via TV/VR profile")
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
    2. Tier 1: Piped API pool (3.5s timeout per node)
    3. Tier 2: yt-dlp local extractor with tv_embedded / android_vr client profile
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


# Alias for backwards compatibility
get_audio_stream = resolve_m4a_stream
