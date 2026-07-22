import os
import json
import base64
import logging
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List

logger = logging.getLogger("beats.config")

COOKIES_PATH = os.environ.get("YT_COOKIES_PATH", "./cookies.txt")


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    SECRET_KEY: str = "beats-secret-change-in-prod"

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/beats.db"

    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    MODEL_PATH: str = "./data/models/recommender.pkl"
    FEATURE_STORE_PATH: str = "./data/features/"

    SEED_MOCK_DATA: int = 1

    YTMUSIC_OAUTH_PATH: str = "./oauth.json"
    OAUTH_JSON: str = ""          # full oauth.json content as env var (cloud)

    YT_COOKIES_PATH: str = "./cookies.txt"
    COOKIES_B64: str = ""         # base64 encoded cookies.txt (legacy / fallback)

    @property
    def origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def setup_oauth_file() -> None:
    """
    Writes oauth.json and verifies cookies.txt on cloud startup.
    Locally or via Render Secret Files, these files are loaded directly.
    """
    settings = get_settings()

    # ── oauth.json ────────────────────────────────────────────────────────────
    if settings.OAUTH_JSON and settings.OAUTH_JSON.strip():
        try:
            parsed = json.loads(settings.OAUTH_JSON)
            path = settings.YTMUSIC_OAUTH_PATH
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w") as f:
                json.dump(parsed, f, indent=2)
            logger.info(f"✅ oauth.json written from OAUTH_JSON env var → {path}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ OAUTH_JSON invalid JSON: {e}")
        except Exception as e:
            logger.error(f"❌ Failed to write oauth.json: {e}")
    elif os.path.exists(settings.YTMUSIC_OAUTH_PATH):
        logger.info(f"✅ oauth.json found at {settings.YTMUSIC_OAUTH_PATH}")
    else:
        logger.warning("⚠️  No oauth.json — ytmusicapi running unauthenticated")

    # ── cookies.txt ───────────────────────────────────────────────────────────
    path = settings.YT_COOKIES_PATH
    
    # Priority 1: Check if updated base64 variable is provided to overwrite/write the file
    if settings.COOKIES_B64 and settings.COOKIES_B64.strip():
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            decoded = base64.b64decode(settings.COOKIES_B64)
            with open(path, "wb") as f:
                f.write(decoded)
            logger.info(f"✅ cookies.txt written from COOKIES_B64 env var → {path}")
        except Exception as e:
            logger.error(f"❌ Failed to write cookies.txt from base64 string: {e}")
            
    # Priority 2: Use existing file (e.g. Render Secret File)
    elif os.path.exists(path) and os.path.getsize(path) > 0:
        logger.info(f"✅ cookies.txt securely loaded at {path}")
        
    else:
        logger.warning("⚠️  No cookies.txt found — yt-dlp running without auth (bot detection risk on cloud)")
