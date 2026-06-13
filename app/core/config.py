from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    SECRET_KEY: str = "beats-secret-change-in-prod"

    DATABASE_URL: str = "sqlite+aiosqlite:///./data/beats.db"

    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    MODEL_PATH: str = "./data/models/recommender.pkl"
    FEATURE_STORE_PATH: str = "./data/features/"

    SEED_MOCK_DATA: int = 1

    @property
    def origins_list(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
