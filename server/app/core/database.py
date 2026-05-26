import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()


def _build_connect_args() -> dict:
    """asyncpg connect_args 생성.

    Windows 한글 홈 디렉토리에서 asyncpg가 ~/.postgresql/root.crt를 로드할 때
    OSError(Errno 42)가 발생하는 문제를 회피하기 위해, ssl=disable 이 아닌 URL에서는
    인증서 검증을 건너뛰는 SSLContext를 명시적으로 주입한다.
    """
    args: dict = {"statement_cache_size": 0}
    url = settings.DATABASE_URL
    if "ssl=disable" not in url and "sslmode=disable" not in url:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        args["ssl"] = ctx
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
