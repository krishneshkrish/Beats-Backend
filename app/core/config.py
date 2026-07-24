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
    YOUTUBE_COOKIES_BASE64: str = "" # base64 encoded YouTube cookies for Render/cloud deployment

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
    b64_cookie_str = os.environ.get("YOUTUBE_COOKIES_BASE64") or settings.YOUTUBE_COOKIES_BASE64 or settings.COOKIES_B64

    # Priority 1: Check if base64 variable is provided to write cookie files
    if b64_cookie_str and b64_cookie_str.strip():
        try:
            decoded = base64.b64decode(b64_cookie_str.strip())
            for target_path in ["/tmp/cookies.txt", path]:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
                    with open(target_path, "wb") as f:
                        f.write(decoded)
                    logger.info(f"✅ cookies.txt written from base64 env var → {target_path}")
                except Exception as inner_e:
                    logger.warning(f"Could not write cookies to {target_path}: {inner_e}")
        except Exception as e:
            logger.error(f"❌ Failed to write cookies.txt from base64 string: {e}")
            
    # Priority 2: Use existing file (e.g. Render Secret File)
    elif os.path.exists(path) and os.path.getsize(path) > 0:
        logger.info(f"✅ cookies.txt securely loaded at {path}")
        
    else:
        logger.warning("⚠️  No cookies.txt found — yt-dlp running without auth (bot detection risk on cloud)")
