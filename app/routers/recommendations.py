from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.database import get_db
from app.ml.recommender import get_recommendations
from app.models.schemas import Song

router = APIRouter(prefix="/api", tags=["recommendations"])


@router.get("/recommendations", response_model=list[Song])
async def recommendations(
    mood: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Primary recommendation endpoint.
    Called by Home page and Mood Hub.

    Query params:
      mood  — one of Happy | Chill | Focus | Workout | Night | Sad | Party | Travel
      limit — number of songs to return (default 10)
    """
    return await get_recommendations(db, mood=mood, limit=limit, context="home")


@router.get("/recommendations/ai", response_model=list[Song])
async def ai_recommendations(
    context: str = Query(default="discover"),
    db: AsyncSession = Depends(get_db),
):
    """
    AI editorial picks for Discover page.
    Uses the ML recommender with no explicit mood — relies on time-of-day
    context and your play history to surface fresh picks.
    """
    return await get_recommendations(db, mood=None, limit=6, context=context)
