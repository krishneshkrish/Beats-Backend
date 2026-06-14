import os
import json
import logging
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List

logger = logging.getLogger("beats.config")


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

    # On Render/cloud — paste the full oauth.json content as this env var
    # Leave empty when running locally (uses oauth.json file directly)
    OAUTH_JSON: str = ""

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
    On cloud platforms (Render, Koyeb etc.) there's no persistent filesystem
    to upload oauth.json. Instead we store the JSON content as an env var
    called OAUTH_JSON and write it to disk on every startup.

    Locally: oauth.json already exists → this function does nothing.
    On Render: OAUTH_JSON env var is set → writes it to oauth.json on startup.
    """
    settings = get_settings()

    # If OAUTH_JSON env var is set and non-empty → write it to disk
    if settings.OAUTH_JSON and settings.OAUTH_JSON.strip():
        try:
            # Validate it's real JSON before writing
            parsed = json.loads(settings.OAUTH_JSON)
            path = settings.YTMUSIC_OAUTH_PATH

            # Make sure parent directory exists
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            with open(path, "w") as f:
                json.dump(parsed, f, indent=2)

            logger.info(f"✅ oauth.json written from OAUTH_JSON env var → {path}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ OAUTH_JSON env var contains invalid JSON: {e}")
        except Exception as e:
            logger.error(f"❌ Failed to write oauth.json: {e}")

    elif os.path.exists(settings.YTMUSIC_OAUTH_PATH):
        logger.info(f"✅ oauth.json found at {settings.YTMUSIC_OAUTH_PATH}")

    else:
        logger.warning(
            "⚠️  No oauth.json found and OAUTH_JSON env var is empty. "
            "ytmusicapi will run unauthenticated (limited functionality). "
            "Run `ytmusicapi oauth` locally and set OAUTH_JSON on Render."
        )
