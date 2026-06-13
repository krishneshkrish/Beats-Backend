"""
Database layer — SQLAlchemy async + SQLite (aiosqlite).
All play events, mood logs, and session data land here.
This is the raw material for your ML model training.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime
from datetime import datetime
from typing import AsyncGenerator

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# ── Tables ────────────────────────────────────────────────────────────────────

class PlayEvent(Base):
    """
    Core ML training data.
    Every song play is logged here — this is how the model learns your taste.
    """
    __tablename__ = "play_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[str] = mapped_column(String(64))
    mood_tag: Mapped[str] = mapped_column(String(32))
    session_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[str] = mapped_column(String(32))       # ISO from frontend

    # Enriched server-side
    hour_of_day: Mapped[int] = mapped_column(Integer)        # 0–23
    day_of_week: Mapped[int] = mapped_column(Integer)        # 0=Mon … 6=Sun
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ML signals — updated later (skip detection, replay detection)
    play_duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    was_skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    was_replayed: Mapped[bool] = mapped_column(Boolean, default=False)


class MoodLog(Base):
    """
    Tracks when user switches mood — used to correlate mood → time-of-day patterns.
    """
    __tablename__ = "mood_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mood: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[str] = mapped_column(String(32))
    hour_of_day: Mapped[int] = mapped_column(Integer)
    day_of_week: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SongCatalog(Base):
    """
    Song metadata store — source of truth for all song data.
    Audio features extracted by Librosa are stored here once processed.
    """
    __tablename__ = "song_catalog"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    artist: Mapped[str] = mapped_column(String(256))
    album: Mapped[str] = mapped_column(String(256))
    artwork: Mapped[str] = mapped_column(Text)
    duration: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    lyrics: Mapped[str] = mapped_column(Text, nullable=True)    # JSON array string
    genre: Mapped[str] = mapped_column(String(64), default="Unknown")
    mood_tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of mood strings

    # Librosa audio features — populated by background task
    bpm: Mapped[float] = mapped_column(Float, nullable=True)
    energy: Mapped[float] = mapped_column(Float, nullable=True)  # 0.0–1.0
    valence: Mapped[float] = mapped_column(Float, nullable=True) # 0.0–1.0 (sad→happy)
    danceability: Mapped[float] = mapped_column(Float, nullable=True)
    features_extracted: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserSession(Base):
    """
    Session-level context — used for sequence modeling (Phase 4 ML).
    """
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_active: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    mood_at_start: Mapped[str] = mapped_column(String(32), default="Chill")
    songs_played: Mapped[int] = mapped_column(Integer, default=0)
    total_duration: Mapped[float] = mapped_column(Float, default=0.0)


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
