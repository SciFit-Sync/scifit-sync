import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _build_ssl_arg():
    """개발(로컬 postgres): SSL 비활성화. 프로덕션(Supabase): SSL 인증서 무검증."""
    if settings.ENV in ("development", "test"):
        return False
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENV == "development",
    pool_size=5,
    max_overflow=10,
    connect_args={"statement_cache_size": 0, "ssl": _build_ssl_arg()},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
