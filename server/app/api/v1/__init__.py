from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.equipment import router as equipment_router
from app.api.v1.exercises import router as exercises_router
from app.api.v1.gyms import router as gyms_router
from app.api.v1.health import router as health_router
from app.api.v1.home import router as home_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.routines import router as routines_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.users import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(gyms_router)
router.include_router(equipment_router)
router.include_router(exercises_router)
router.include_router(routines_router)
router.include_router(sessions_router)
router.include_router(chat_router)
router.include_router(notifications_router)
router.include_router(home_router)
