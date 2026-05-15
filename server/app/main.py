import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
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

settings = get_settings()

logging.basicConfig(
    level=logging.WARNING if settings.ENV == "production" else logging.INFO,
    format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="SciFit-Sync",
        version="1.0.0",
        docs_url=None if settings.ENV == "production" else "/docs",
        redoc_url=None if settings.ENV == "production" else "/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
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
