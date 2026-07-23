from pydantic import BaseModel
from typing import Optional, List, Literal
from datetime import datetime


# ── Song ──────────────────────────────────────────────────────────────────────

class Song(BaseModel):
    id: str
    title: str
    artist: str
    album: str
    artwork: str
    duration: int           # seconds — matches frontend `duration: number`
    url: str                # audio URL
    lyrics: Optional[List[str]] = None   # array of lyric lines

    def resolve_url(self, base_url: str):
        base_url = str(base_url)
        if not base_url.endswith("/"):
            base_url += "/"
        if len(self.id) == 11 or "googlevideo.com" in self.url or "youtube.com" in self.url or "api/yt/stream" in self.url:
            self.url = f"{base_url}api/yt/stream?video_id={self.id}"
        return self


# ── Greeting ──────────────────────────────────────────────────────────────────

class GreetingResponse(BaseModel):
    message: str
    submessage: str


# ── Play Log ──────────────────────────────────────────────────────────────────

class PlayLogPayload(BaseModel):
    username: str = "default_user"
    song_id: str
    mood_tag: str
    timestamp: str          # ISO string from frontend
    session_id: str
    # ✅ Added optional metadata fields to pass raw search payloads down to the DB catalog
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    artwork: Optional[str] = None
    duration: Optional[int] = None
    url: Optional[str] = None


class PlayLogResponse(BaseModel):
    status: str


# ── Mood ──────────────────────────────────────────────────────────────────────

class MoodSetPayload(BaseModel):
    mood: str
    timestamp: str          # ISO string from frontend
    username: Optional[str] = "default_user"


class MoodSetResponse(BaseModel):
    status: str
    mood: str


# ── Analytics ─────────────────────────────────────────────────────────────────

class CircularProgressItem(BaseModel):
    label: str
    value: float            # percentage 0–100
    color: str


class GenreDataItem(BaseModel):
    name: str
    value: int              # play count / minutes


class HeatmapDataItem(BaseModel):
    day: str
    count: int


class AnalyticsSummary(BaseModel):
    totalTime: int          # minutes
    weeklyTime: int         # minutes
    streak: int             # days
    topArtist: str
    topGenre: str
    topSong: str
    circularProgress: List[CircularProgressItem]
    genreData: List[GenreDataItem]
    heatmapData: List[HeatmapDataItem]


# ── Journey / Timeline ────────────────────────────────────────────────────────

TimeLabel = Literal[
    "Morning Sessions",
    "Afternoon Focus",
    "Evening Vibes",
    "Late Night"
]


class TimelineItem(BaseModel):
    id: str
    timestamp: str
    song: Song
    moodTag: str
    timeLabel: TimeLabel
    isMilestone: Optional[bool] = False
    milestoneText: Optional[str] = None


# ── Search ────────────────────────────────────────────────────────────────────

class PlaylistMeta(BaseModel):
    id: str
    name: str
    artwork: str
    songCount: int


class SearchResult(BaseModel):
    songs: List[Song]
    artists: List[str]
    albums: List[str]
    playlists: List[PlaylistMeta]


# ── ML / Recommendation internals ────────────────────────────────────────────

class RecommendationContext(BaseModel):
    username: Optional[str] = "default_user"
    mood: Optional[str] = None
    hour: Optional[int] = None
    session_id: Optional[str] = None
    context: Optional[str] = "discover"   # 'discover' | 'home' | 'mood'