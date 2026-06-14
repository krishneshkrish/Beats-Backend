"""
Beats Backend — FastAPI entry point.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings, setup_oauth_file
from app.db.database import create_tables, AsyncSessionLocal
from app.db.seeder import seed_catalog
from app.routers import greeting, recommendations, log, mood, analytics, journey, search, ml, ytdlp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("beats")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("🎵 Beats backend starting up...")
    setup_oauth_file()  # write oauth.json from env var on cloud platforms

    # Create DB tables
    await create_tables()
    logger.info("✅ Database tables ready.")

    # Seed song catalog if enabled
    if settings.SEED_MOCK_DATA:
        async with AsyncSessionLocal() as db:
            await seed_catalog(db)

    logger.info(f"🚀 Beats API running on port {settings.APP_PORT}")
    logger.info(f"   CORS origins: {settings.origins_list}")
    logger.info(f"   Env: {settings.APP_ENV}")

    yield

    logger.info("👋 Beats backend shutting down.")


app = FastAPI(
    title="Beats API",
    description="Backend for the Beats Premium AI Music PWA",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS — allow Next.js dev server + production ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(greeting.router)
app.include_router(recommendations.router)
app.include_router(log.router)
app.include_router(mood.router)
app.include_router(analytics.router)
app.include_router(journey.router)
app.include_router(search.router)
app.include_router(ml.router)
app.include_router(ytdlp.router)


@app.get("/")
async def root():
    return {
        "app": "Beats API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
