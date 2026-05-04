"""장비 카탈로그 엔드포인트 (#46 GET /equipment)."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models import Equipment, EquipmentBrand, User
from app.schemas.common import SuccessResponse
from app.schemas.gyms import EquipmentItem, EquipmentListData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("", response_model=SuccessResponse[EquipmentListData], summary="장비 카탈로그")
async def list_equipment(
    keyword: str | None = Query(None),
    equipment_type: str | None = Query(None, description="cable / machine / barbell / dumbbell / bodyweight"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Equipment, EquipmentBrand.name).outerjoin(EquipmentBrand, Equipment.brand_id == EquipmentBrand.id)
    if keyword:
        stmt = stmt.where(Equipment.name.ilike(f"%{keyword}%"))
    if equipment_type:
        stmt = stmt.where(Equipment.equipment_type == equipment_type)

    rows = (await db.execute(stmt)).all()
    items = [
        EquipmentItem(
            equipment_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            category=e.category.value if e.category else None,
            equipment_type=e.equipment_type.value,
            brand=brand_name,
            pulley_ratio=e.pulley_ratio,
            bar_weight_kg=e.bar_weight_kg,
            has_weight_assist=e.has_weight_assist,
            min_stack_kg=e.min_stack_kg,
            max_stack_kg=e.max_stack_kg,
            stack_weight_kg=e.stack_weight_kg,
            image_url=e.image_url,
        )
        for e, brand_name in rows
    ]
    return SuccessResponse(data=EquipmentListData(items=items))
