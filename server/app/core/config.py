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
    WORKOUTX_API_KEY: str = ""

    # 서버 자기 공개 base URL (gif 프록시 등 self-referential 절대 URL 생성용)
    # 환경별 override: dev=http://localhost:8000, prod=https://scifit-sync.com
    PUBLIC_BASE_URL: str = "https://scifit-sync.com"

    # ChromaDB
    CHROMA_PERSIST_PATH: str = "/chroma-data"
    CHROMA_COLLECTION_NAME: str = "paper_chunks"

    # AWS SES
    AWS_REGION: str = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SES_FROM_EMAIL: str = ""  # SES에서 발신자 인증된 이메일

    # Admin
    ADMIN_API_TOKEN: str = ""

    # Email (Gmail SMTP)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""  # 발신 Gmail 주소
    SMTP_PASSWORD: str = ""  # Gmail 앱 비밀번호 (16자리)
    EMAIL_FROM_NAME: str = "SciFit-Sync"

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

    # Environment — fail-safe: 기본값 production (로컬 개발 시 ENV=development 명시 필요)
    ENV: str = "production"

    def model_post_init(self, _: Any) -> None:
        if self.ENV == "production":
            key = self.JWT_SECRET_KEY.strip()
            _weak = {"change-me-in-production", "your-secret-key-here", "secret", "password", ""}
            if not key or key in _weak or len(key) < 32:
                raise RuntimeError("프로덕션 JWT_SECRET_KEY: 최소 32자 이상, 알려진 placeholder 사용 금지")


@lru_cache
def get_settings() -> Settings:
    return Settings()
