from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.routines import router as routines_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(routines_router)
