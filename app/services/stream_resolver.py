"""
Beats — Stream Resolver (Lightweight Metadata & Cache Helper)
─────────────────────────────────────────────────────────────
All heavy datacenter audio stream proxying and yt-dlp extractions
are deprecated to prevent IP-based BotGuard challenges on cloud instances.
Audio streaming is resolved directly via Next.js serverless edge routes (/api/stream).
"""

import logging
import time
from typing import Dict, Tuple, Optional

logger = logging.getLogger("beats.stream_resolver")

# ── In-Memory Stream Cache ───────────────────────────────────────────────────
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


async def resolve_m4a_stream(video_id: str) -> str:
    """
    Lightweight Stream Resolver:
    Returns cached stream URL if present; otherwise logs notice.
    Datacenter stream proxying is offloaded to prevent cloud IP bot challenges.
    """
    cached = get_cached_stream(video_id)
    if cached:
        return cached

    logger.info(f"[Stream Resolver] Stream resolution for video_id={video_id} offloaded to client edge proxy.")
    raise ValueError(f"Datacenter stream proxying deprecated for video_id={video_id}. Use edge stream route.")


# Alias for backward compatibility
get_audio_stream = resolve_m4a_stream
