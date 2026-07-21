import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, func
from datetime import datetime
from typing import AsyncGenerator

from app.core.config import get_settings

logger = logging.getLogger("beats.db")
settings = get_settings()


def _build_engine_and_session(url: str):
    connect_args = {}
    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    elif "postgresql+asyncpg" in url:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        if "sslmode=disable" in url.lower():
            connect_args["ssl"] = False
        elif "sslmode=require" in url.lower() or "ssl=true" in url.lower():
            connect_args["ssl"] = "require"

    eng = create_async_engine(
        url,
        echo=settings.APP_ENV == "development",
        connect_args=connect_args,
    )
    session_factory = async_sessionmaker(
        eng,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return eng, session_factory


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


raw_db_url = _normalize_db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./beats.db"))
engine, AsyncSessionLocal = _build_engine_and_session(raw_db_url)


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
    username: Mapped[str] = mapped_column(String(64), default="default_user", index=True) # ✅ Added user scoping
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
    username: Mapped[str] = mapped_column(String(64), default="default_user", index=True) # ✅ Added user scoping
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


class MLModelStore(Base):
    """
    Stores trained ML recommendation model artifacts directly in PostgreSQL/SQLite database
    so they persist across Render container restarts.
    """
    __tablename__ = "ml_models"

    username: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    model_data: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    global engine, AsyncSessionLocal
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables ready.")
    except Exception as e:
        logger.warning(f"⚠️ Primary DB connection failed ({e}). Falling back to local SQLite database.")
        fallback_url = "sqlite+aiosqlite:///./beats.db"
        engine, AsyncSessionLocal = _build_engine_and_session(fallback_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Fallback SQLite database tables ready.")