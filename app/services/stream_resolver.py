import os
import logging
import httpx
import time
from typing import Optional, Tuple

logger = logging.getLogger("beats.media")

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://api.piped.yt"
]

async def get_audio_stream(video_id: str) -> Tuple[Optional[str], dict]:
    """
    Resolves the audio stream URL for a given YouTube video ID.
    1. Iterates through public Piped API instances with a 4.0s timeout.
    2. Filters for format='M4A' or mimeType='audio/mp4'.
    3. Falls back to a custom local yt-dlp extraction (player_client=['ios', 'mweb']).
    4. Ultimate fallback to backend's multi-tier _get_stream_url.
    Returns (stream_url, headers).
    """
    # 1. Piped Multi-Instance Resolution Pool
    for instance_url in PIPED_INSTANCES:
        try:
            logger.info(f"[Piped Resolver] Querying {instance_url} for {video_id}")
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
                resp = await client.get(f"{instance_url}/streams/{video_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    audio_streams = data.get("audioStreams", [])
                    if not audio_streams:
                        logger.warning(f"[Piped Resolver] No audio streams found on {instance_url} for {video_id}")
                        continue
                    
                    target_stream = None
                    # Filter for format == "M4A" or mimeType == "audio/mp4" (highest priority)
                    for stream in audio_streams:
                        fmt = stream.get("format", "").upper()
                        mime = stream.get("mimeType", "").lower()
                        if fmt == "M4A" or "audio/mp4" in mime or "m4a" in mime:
                            target_stream = stream
                            break
                    
                    # Fallback to any available audio stream if M4A is missing
                    if not target_stream:
                        target_stream = audio_streams[0]
                        logger.info(f"[Piped Resolver] M4A missing on {instance_url}, falling back to format: {target_stream.get('format')}")
                        
                    stream_url = target_stream.get("url")
                    if stream_url:
                        logger.info(f"[Piped Resolver Succeeded] Resolved {video_id} via {instance_url}")
                        # Provide a standard iOS Safari User-Agent since it's targeted for iOS background play
                        headers = {
                            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                        }
                        return stream_url, headers
                else:
                    logger.warning(f"[Piped Resolver Failed] {instance_url} returned status {resp.status_code}")
        except Exception as e:
            logger.warning(f"[Piped Resolver Warning] {instance_url} failed: {e}")

    # 2. Local yt-dlp Extraction Fallback (player_client=['ios', 'mweb'])
    logger.info(f"[Piped Resolver] All Piped instances failed. Running local yt-dlp fallback (ios/mweb) for {video_id}...")
    try:
        import yt_dlp
        cookies_path = "cookies.txt"
        cookiefile = cookies_path if os.path.exists(cookies_path) else None
        ydl_opts = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'mweb'],
                    'skip': ['hls', 'dash'],
                    'js_runtime': 'node'
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
            }
        }
        if cookiefile:
            ydl_opts['cookiefile'] = cookiefile
            
        def extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                url = info.get('url')
                if url and "googlevideo.com" in url:
                    return url, info.get('http_headers', {})
            return None, {}
            
        import asyncio
        loop = asyncio.get_event_loop()
        url, headers = await loop.run_in_executor(None, extract)
        if url:
            logger.info(f"[Piped Resolver Fallback Succeeded] Local yt-dlp resolved {video_id} using ios/mweb client")
            return url, headers
    except Exception as e:
        logger.warning(f"[Piped Resolver Fallback Warning] Local yt-dlp fallback failed for {video_id}: {e}")

    # 3. Ultimate Fallback: Backend Multi-Tier Solver
    logger.info(f"[Piped Resolver] Local fallback failed. Attempting ultimate multi-tier solver for {video_id}...")
    try:
        from app.api.yt import _get_stream_url
        url, headers = await _get_stream_url(video_id)
        if url and "youtube.com/watch" not in url:
            logger.info(f"[Piped Resolver Ultimate Succeeded] Resolved {video_id} via multi-tier fallback")
            return url, headers
    except Exception as e:
        logger.error(f"[Piped Resolver Ultimate Failed] Ultimate fallback failed for {video_id}: {e}")
        
    return None, {}
