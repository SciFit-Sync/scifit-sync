from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/scifiitsync"

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # LLM
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # External API
    KAKAO_REST_API_KEY: str = ""

    # ChromaDB
    CHROMA_PERSIST_PATH: str = "/chroma-data"
    CHROMA_COLLECTION_NAME: str = "paper_chunks"

    # Admin
    ADMIN_API_TOKEN: str = ""

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True

    # Environment
    ENV: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
