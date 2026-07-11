"""
Beats — Recommendation Router
─────────────────────────────
Exposes entry endpoints for pulling automated contextual queues,
routing inputs natively into the isolated multi-user ML matrix structures.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.schemas import Song
from app.ml.recommender import get_recommendations

logger = logging.getLogger("beats.recommendations")
router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("", response_model=list[Song])
async def fetch_recommendations(
    mood: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=20),
    context: str = Query(default="home"),
    username: str = Query(default="default_user"),  # ✅ Hooks up multi-user scoring
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches algorithmic song lists, evaluating features based on the active username profile.
    """
    logger.info(f"[API] Recommendations requested for user '{username}' — Mood Context: {mood}")
    
    songs = await get_recommendations(
        db=db,
        mood=mood,
        limit=limit,
        context=context,
        username=username  # ✅ Passes tracking parameter to isolated classifier matrix
    )
    return songs