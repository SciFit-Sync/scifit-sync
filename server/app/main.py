import gc
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.core.exception_handlers import (
    app_error_handler,
    http_exception_handler,
    rate_limit_exceeded_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.exceptions import AppError
from app.core.limiter import limiter
from app.core.middleware import RequestIdMiddleware
from app.services import rag as rag_svc

settings = get_settings()

logging.basicConfig(
    level=logging.WARNING if settings.ENV == "production" else logging.INFO,
    format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: 별도 초기화 없음 (ChromaDB는 최초 요청 시 lazy-init)
    yield
    # shutdown — ChromaDB graceful close
    # SIGTERM 수신 시 alias cache + _client 레퍼런스를 정리해
    # ChromaDB PersistentClient의 pending write가 finalize될 시간을 보장한다.
    # design spec §3.6 B4 risk: HNSW partial-write 방지의 1차 방어선.
    try:
        rag_svc._collection_cache.clear()
        if rag_svc._client is not None:
            rag_svc._client = None
        # B2 fix: admin writer client도 정리 — reader만 정리하던 기존 누락 수정
        from app.api.v1 import admin as admin_mod

        admin_mod._close_chroma_writer()
        # F3 fix: GC finalizer 강제 실행 — PersistentClient의 sqlite WAL flush 보장.
        # ChromaDB PersistentClient는 명시적 close() API가 없어 GC finalizer에 의존하는데,
        # ECS stopTimeout 30초 안에 finalizer가 미실행될 경우 HNSW partial-write 위험 잔존.
        # gc.collect()로 참조 해제 즉시 finalizer를 트리거해 추가 방어선을 확보한다.
        gc.collect()
        logger.info("ChromaDB read+write client released gracefully (gc.collect 완료)")
    except Exception as e:
        logger.error("Graceful shutdown 중 ChromaDB cleanup 실패: %s", e)


def create_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
        title="SciFit-Sync",
        version="1.0.0",
        docs_url=None if settings.ENV == "production" else "/docs",
        redoc_url=None if settings.ENV == "production" else "/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials="*" not in settings.ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    if settings.RATE_LIMIT_ENABLED:
        app.state.limiter = limiter
        app.add_middleware(SlowAPIMiddleware)

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(v1_router)

    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        schema["components"]["securitySchemes"] = {
            "HTTPBearer": {
                "type": "http",
                "scheme": "bearer",
            }
        }
        for path in schema.get("paths", {}).values():
            for operation in path.values():
                operation.setdefault("security", [{"HTTPBearer": []}])
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
    return app


app = create_app()
