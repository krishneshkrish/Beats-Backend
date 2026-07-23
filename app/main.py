"""
Beats Backend — FastAPI entry point.
"""

import os
import re
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings, setup_oauth_file
from app.db.database import create_tables, get_session_local
from app.db.seeder import seed_catalog
from app.routers import greeting, recommendations, log, mood, analytics, journey, search, ml
from app.api import yt as yt_api

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
        async with get_session_local() as db:
            await seed_catalog(db)

    logger.info(f"🚀 Beats API running on port {settings.APP_PORT}")
    logger.info(f"   Env: {settings.APP_ENV}")

    yield

    logger.info("👋 Beats backend shutting down.")


app = FastAPI(
    title="Beats API",
    description="Backend for the Beats Premium AI Music PWA",
    version="1.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def normalize_double_slashes(request: Request, call_next):
    if request.scope.get("path", "").startswith("//"):
        request.scope["path"] = re.sub(r"^/+", "/", request.scope["path"])
    return await call_next(request)

# ── CORS — allow Next.js dev server + production ──────────────────────────────
# Configure explicitly allowed origins
origins = list(settings.origins_list)
for extra in ["http://localhost:3000", "capacitor://localhost", "http://localhost", "https://beats-pearl.vercel.app"]:
    if extra not in origins:
        origins.append(extra)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Range"],
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
app.include_router(yt_api.router)



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
