import asyncio
import os
import ssl
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# .env에서 DATABASE_URL 로딩
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", "").replace("%", "%%"))

# 모든 모델의 MetaData를 import
from app.models import Base  # noqa: E402

target_metadata = Base.metadata


_LOCAL_HOSTS = ("localhost", "127.0.0.1", "@db:", "@db/")


def _build_connect_args() -> dict:
    """URL에 따라 asyncpg connect_args를 결정한다.

    Windows 한글 홈 디렉토리에서 asyncpg가 ~/.postgresql/root.crt를 로드할 때
    OSError(Errno 42)가 발생하므로, 원격 호스트(Supabase 등)에 연결할 때만
    파일시스템 탐색을 건너뛰는 SSLContext를 주입한다.
    로컬·CI 환경(localhost, 127.0.0.1, Docker db 서비스)은 SSL을 사용하지 않는다.
    """
    url = os.getenv("DATABASE_URL", "")
    args: dict = {"statement_cache_size": 0}
    ssl_disabled = "ssl=disable" in url or "sslmode=disable" in url
    is_local = any(h in url for h in _LOCAL_HOSTS)
    if not ssl_disabled and not is_local:
        args["ssl"] = _make_ssl_ctx()
    return args


def _make_ssl_ctx() -> ssl.SSLContext:
    """파일시스템 탐색 없이 SSL 암호화만 활성화하는 SSLContext.

    asyncpg 기본 동작은 ~/.postgresql/root.crt 등 시스템 cert를 로드하는데,
    경로에 한글이 포함된 Windows 환경에서 OSError(Errno 42)가 발생한다.
    직접 SSLContext를 생성하면 파일 탐색을 건너뛴다.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def _build_ssl_arg():
    """개발(로컬 postgres): SSL 비활성화. 프로덕션(Supabase): SSL 인증서 무검증."""
    if os.getenv("ENV", "production") in ("development", "test"):
        return False
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode (async)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_build_connect_args(),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
