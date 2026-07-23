import os
import re
import logging
import httpx
import time
import asyncio
from typing import Optional, Tuple

logger = logging.getLogger("beats.media")

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://api.piped.yt"
]

INVIDIOUS_INSTANCES = [
    "https://yewtu.be",
    "https://invidious.projectsegfau.lt",
    "https://invidious.flokinet.to",
    "https://invidious.nerdvpn.de",
    "https://invidious.no-logs.com"
]

async def query_piped_instance(instance_url: str, video_id: str) -> Optional[Tuple[str, dict]]:
    url = f"{instance_url}/streams/{video_id}"
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                audio_streams = data.get("audioStreams", [])
                if audio_streams:
                    target_stream = None
                    for stream in audio_streams:
                        fmt = stream.get("format", "").upper()
                        mime = stream.get("mimeType", "").lower()
                        if fmt == "M4A" or "audio/mp4" in mime or "m4a" in mime:
                            target_stream = stream
                            break
                    if not target_stream:
                        target_stream = audio_streams[0]
                    stream_url = target_stream.get("url")
                    if stream_url:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                        }
                        return stream_url, headers
    except Exception as e:
        logger.warning(f"[Piped Pool Warning] {instance_url} failed: {type(e).__name__}")
    return None

async def query_invidious_instance(instance_url: str, video_id: str) -> Optional[Tuple[str, dict]]:
    url = f"{instance_url}/api/v1/videos/{video_id}"
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                formats = data.get("adaptiveFormats", [])
                audio_streams = [f for f in formats if "audio" in f.get("type", "").lower()]
                if audio_streams:
                    m4a_stream = None
                    for fmt in audio_streams:
                        if "audio/mp4" in fmt.get("type", "").lower():
                            m4a_stream = fmt
                            break
                    selected = m4a_stream or audio_streams[0]
                    stream_url = selected.get("url")
                    if stream_url:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                        }
                        if stream_url.startswith("/"):
                            stream_url = f"{instance_url}{stream_url}"
                        return stream_url, headers
    except Exception as e:
        logger.warning(f"[Invidious Pool Warning] {instance_url} failed: {type(e).__name__}")
    return None

def clean_title(title: str) -> str:
    # Split camelCase words (e.g. SaiAbhyankkar -> Sai Abhyankkar)
    title_split = re.sub(r'([a-z])([A-Z])', r'\1 \2', title)
    query = title_split.replace("@", " ")
    
    suffixes = [
        r'\bofficial\b', r'\baudio\b', r'\bvideo\b', r'\blyrical\b', 
        r'\blyrics\b', r'\bmusic\b', r'\bextended\b', r'\bversion\b', 
        r'\bhd\b', r'\b4k\b', r'\bfull\b', r'\bsong\b'
    ]
    query_lower = query.lower()
    for s in suffixes:
        query_lower = re.sub(s, '', query_lower)
        
    query_lower = re.sub(r'\(.*?\)', '', query_lower)
    query_lower = re.sub(r'\[.*?\]', '', query_lower)
    query_lower = re.sub(r'[^\w\s\-]', '', query_lower)
    query_lower = re.sub(r'\s+', ' ', query_lower).strip()
    return query_lower

async def resolve_soundcloud(title: str, artist: str, target_duration: Optional[int]) -> Optional[Tuple[str, dict]]:
    if not title:
        return None
        
    t_clean = clean_title(title)
    a_clean = re.sub(r'[^\w\s\-]', '', artist.lower()) if artist else ""
    a_clean = re.sub(r'\s+', ' ', a_clean).strip()
    
    queries = []
    if a_clean and a_clean not in t_clean:
        queries.append(f"{t_clean} {a_clean}")
    queries.append(t_clean)
    
    parts = [p.strip() for p in re.split(r'[-|]', title)]
    if len(parts) > 1:
        first_part = clean_title(parts[0])
        if first_part and first_part not in queries:
            queries.append(first_part)
            
    logger.info(f"[SoundCloud Fallback] Formed search queries: {queries}")
    
    for query in queries:
        logger.info(f"[SoundCloud Fallback] Searching SoundCloud for: '{query}'...")
        ydl_opts_sc = {
            'format': 'best[protocol=http]/bestaudio[protocol=http]/http_mp3/best',
            'quiet': True,
            'no_warnings': True,
        }
        try:
            import yt_dlp
            def extract_sc():
                with yt_dlp.YoutubeDL(ydl_opts_sc) as ydl:
                    info = ydl.extract_info(f"scsearch5:{query}", download=False)
                    return info.get('entries') if info else []
                    
            loop = asyncio.get_running_loop()
            entries = await loop.run_in_executor(None, extract_sc)
            
            if not entries:
                continue
                
            best_candidate = None
            best_diff = float('inf')
            
            for entry in entries:
                url = entry.get('url')
                if not url:
                    continue
                dur = entry.get('duration')
                
                if target_duration and dur:
                    diff = abs(dur - target_duration)
                    if dur < 60 and target_duration >= 60:
                        continue
                    threshold = max(20, int(target_duration * 0.12))
                    if diff <= threshold:
                        if diff < best_diff:
                            best_diff = diff
                            best_candidate = entry
                else:
                    if dur and dur >= 60:
                        best_candidate = entry
                        break
                        
            if not best_candidate:
                for entry in entries:
                    url = entry.get('url')
                    dur = entry.get('duration') or 0
                    if url and dur >= 60:
                        best_candidate = entry
                        logger.info(f"[SoundCloud Fallback] No perfect duration match. Selected first full-length candidate: '{entry.get('title')}' ({dur}s)")
                        break
            
            if not best_candidate and entries:
                best_candidate = entries[0]
                
            if best_candidate:
                url = best_candidate.get('url')
                headers = best_candidate.get('http_headers') or {}
                logger.info(f"[SoundCloud Fallback Succeeded] Resolved '{best_candidate.get('title')}' ({best_candidate.get('duration')}s) via query '{query}'")
                return url, headers
                
        except Exception as sc_err:
            logger.error(f"[SoundCloud Fallback Failed] Search failed for query '{query}': {sc_err}")
            
    return None

async def get_metadata(video_id: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    title, artist, duration = None, None, None
    try:
        from app.api.yt import get_ytmusic
        ytmusic = get_ytmusic()
        if ytmusic:
            loop = asyncio.get_running_loop()
            song_details = await loop.run_in_executor(None, ytmusic.get_song, video_id)
            if song_details and "videoDetails" in song_details:
                details = song_details["videoDetails"]
                title = details.get("title")
                artist = details.get("author")
                length_str = details.get("lengthSeconds")
                if length_str:
                    duration = int(length_str)
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
                    duration = row.duration
        except Exception as db_err:
            logger.warning(f"DB metadata fetch failed: {db_err}")
            
    return title, artist, duration

async def get_audio_stream(video_id: str) -> Tuple[Optional[str], dict]:
    """
    Resolves the audio stream URL for a given YouTube video ID.
    1. Checks the shared memory cache for an active resolved URL.
    2. Runs a fast local yt-dlp tv_embedded client lookup (DASH enabled, HLS skipped).
       This bypasses bot checks natively without requiring cookies or POT.
    3. Fallback: Queries Piped & Invidious public instances in PARALLEL.
    4. Fallback: Smart, cleaned, duration-matched SoundCloud lookup.
    5. Ultimate Fallback: Direct lookup with cookies.
    """
    # 0. Check Shared Cache First
    try:
        from app.api.yt import _STREAM_URL_CACHE
        cached_data = _STREAM_URL_CACHE.get(video_id)
        if cached_data:
            if len(cached_data) == 3:
                expiry, url, headers = cached_data
            else:
                expiry, url = cached_data
                headers = {}
            if time.time() < expiry - 600:
                logger.info(f"[Stream Resolver Cache Hit] Resolved {video_id} from cache.")
                return url, headers
    except Exception as cache_err:
        logger.warning(f"[Stream Resolver Cache Check Failed] {cache_err}")

    # Helper to cache and return the stream URL
    def cache_and_return(url, headers):
        try:
            from app.api.yt import _STREAM_URL_CACHE, _get_url_expiry
            expiry = _get_url_expiry(url)
            _STREAM_URL_CACHE[video_id] = (expiry, url, headers)
            logger.info(f"[Stream Resolver Cache Populate] Cached {video_id} (expires in {int(expiry - time.time())}s)")
        except Exception as cache_err:
            logger.warning(f"[Stream Resolver Cache Write Failed] {cache_err}")
        return url, headers

    # 1. Fast tv_embedded Local Extraction (Bypasses bot checks without cookies/POT)
    logger.info(f"[Stream Resolver] Attempting fast TV embedded lookup for {video_id}...")
    try:
        import yt_dlp
        ydl_opts_tv = {
            'format': 'bestaudio/best/140/251/18/ba/b',
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'nocheckcertificate': True,
            'no_plugins': True,  # Critical: Prevent plugins from loading/interfering!
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded'],
                    'player_skip': ['web', 'web_embedded', 'mweb', 'ios', 'android'],
                    'skip': ['hls'],
                    'js_runtime': 'node'
                }
            }
        }
        
        def extract_tv():
            with yt_dlp.YoutubeDL(ydl_opts_tv) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                url = info.get('url')
                if url and "googlevideo.com" in url:
                    return url, info.get('http_headers', {})
            return None, {}
            
        loop = asyncio.get_running_loop()
        # Add strict timeout of 4 seconds to prevent blocking
        url, headers = await asyncio.wait_for(
            loop.run_in_executor(None, extract_tv), 
            timeout=4.0
        )
        if url:
            logger.info(f"[Stream Resolver TV Succeeded] Resolved {video_id} via TV embedded client")
            return cache_and_return(url, headers)
    except Exception as e:
        logger.warning(f"[Stream Resolver TV Failed] Fast TV client fallback failed for {video_id}: {type(e).__name__}: {e}")

    # 2. Parallel Piped & Invidious Queries
    logger.info(f"[Stream Resolver] TV failed. Attempting Parallel Piped & Invidious Pool for {video_id}...")
    tasks = []
    for inst in PIPED_INSTANCES:
        tasks.append(query_piped_instance(inst, video_id))
    for inst in INVIDIOUS_INSTANCES:
        tasks.append(query_invidious_instance(inst, video_id))
        
    try:
        # Check tasks concurrently; return first successful one
        for future in asyncio.as_completed(tasks, timeout=5.0):
            res = await future
            if res:
                stream_url, headers = res
                logger.info(f"[Stream Resolver Pool Succeeded] Resolved {video_id} via Parallel instances")
                return cache_and_return(stream_url, headers)
    except Exception as pool_err:
        logger.warning(f"[Stream Resolver Pool Failed] Parallel lookup failed: {pool_err}")

    # 3. Smart SoundCloud Fallback
    logger.info(f"[Stream Resolver] Pool failed. Fetching metadata for SoundCloud fallback for {video_id}...")
    title, artist, duration = await get_metadata(video_id)
    if title:
        sc_res = await resolve_soundcloud(title, artist or "Unknown", duration)
        if sc_res:
            stream_url, headers = sc_res
            return cache_and_return(stream_url, headers)

    # 4. Ultimate Fallback (Should rarely be reached)
    logger.info(f"[Stream Resolver] Fallbacks failed. Attempting ultimate cookie/POT solver for {video_id}...")
    try:
        from app.api.yt import _get_stream_url
        url, headers = await _get_stream_url(video_id)
        if url:
            return cache_and_return(url, headers)
    except Exception as e:
        logger.error(f"[Stream Resolver Ultimate Failed] Ultimate fallback failed for {video_id}: {e}")
        
    return None, {}
