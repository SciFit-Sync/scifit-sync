import platform
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _build_connect_args() -> dict:
    """asyncpg connect_args 생성.

    Windows 개발 환경에서 asyncpg가 한글 홈 디렉토리의 ~/.postgresql/root.crt를
    로드할 때 OSError(Errno 42)가 발생하는 문제를 회피한다.
    프로덕션(ECS Fargate + Supabase)에서는 정상 SSL 연결을 유지한다.
    """
    args: dict = {"statement_cache_size": 0}
    if settings.ENV == "development" and platform.system() == "Windows":
        args["ssl"] = False  # Windows 한글 경로 asyncpg 버그 우회
    return args


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENV == "development",
    pool_size=5,
    max_overflow=10,
    connect_args=_build_connect_args(),
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
