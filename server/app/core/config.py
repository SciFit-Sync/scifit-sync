from functools import lru_cache
from typing import Any

from pydantic import field_validator
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

    # CORS — 쉼표 구분 문자열 또는 JSON 배열. 기본값: 전체 허용(개발용)
    ALLOWED_ORIGINS: list[str] = ["*"]

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Environment
    ENV: str = "development"

    def model_post_init(self, _: Any) -> None:
        if self.ENV == "production" and self.JWT_SECRET_KEY == "change-me-in-production":
            raise RuntimeError("프로덕션에서 JWT_SECRET_KEY 기본값 사용 금지")


@lru_cache
def get_settings() -> Settings:
    return Settings()
