"""장비 카탈로그 엔드포인트 (#46 GET /equipment + 브랜드 목록 GET /equipment/brands)."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.models import Equipment, EquipmentBrand, User
from app.schemas.common import SuccessResponse
from app.schemas.gyms import BrandItem, BrandListData, EquipmentItem, EquipmentListData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/equipment", tags=["equipment"])


def _ratio_str(pulley_ratio: float | None) -> str | None:
    if pulley_ratio is None:
        return None
    n = int(pulley_ratio) if pulley_ratio == int(pulley_ratio) else pulley_ratio
    return f"{n}:1"


# ── GET /equipment/brands ─────────────────────────────────────────────────────
@router.get("/brands", response_model=SuccessResponse[BrandListData], summary="기구 브랜드 목록")
async def list_brands(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """W-O02 기구 설정 화면의 브랜드 탭에 표시할 전체 브랜드 목록을 반환한다."""
    rows = (await db.execute(select(EquipmentBrand).order_by(EquipmentBrand.name))).scalars().all()
    items = [BrandItem(brand_id=str(b.id), name=b.name, logo_url=b.logo_url) for b in rows]
    return SuccessResponse(data=BrandListData(items=items))


# ── GET /equipment ────────────────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[EquipmentListData], summary="장비 카탈로그")
async def list_equipment(
    keyword: str | None = Query(None, description="기구 이름 부분 일치 검색"),
    brand_id: str | None = Query(None, description="브랜드 UUID 필터"),
    equipment_type: str | None = Query(None, description="cable / machine / barbell / dumbbell / bodyweight"),
    category: str | None = Query(None, description="chest / back / shoulders / arms / core / legs"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Equipment, EquipmentBrand.name).outerjoin(EquipmentBrand, Equipment.brand_id == EquipmentBrand.id)

    if keyword:
        stmt = stmt.where(Equipment.name.ilike(f"%{keyword}%"))
    if brand_id:
        try:
            brand_uuid = uuid.UUID(brand_id)
        except ValueError as e:
            raise ValidationError(message="잘못된 brand_id 형식입니다.") from e
        stmt = stmt.where(Equipment.brand_id == brand_uuid)
    if equipment_type:
        stmt = stmt.where(Equipment.equipment_type == equipment_type)
    if category:
        stmt = stmt.where(Equipment.category == category)

    rows = (await db.execute(stmt)).all()
    items = [
        EquipmentItem(
            equipment_id=str(e.id),
            name=e.name,
            name_en=e.name_en,
            brand=brand_name,
            category=e.category.value if e.category else None,
            equipment_type=e.equipment_type.value,
            pulley_ratio=e.pulley_ratio,
            bar_weight_kg=e.bar_weight_kg,
            has_weight_assist=e.has_weight_assist,
            min_stack_kg=e.min_stack_kg,
            max_stack_kg=e.max_stack_kg,
            stack_weight_kg=e.stack_weight_kg,
            image_url=e.image_url,
            # 표시용 호환 필드
            ratio=_ratio_str(e.pulley_ratio) if e.equipment_type.value in ("cable", "machine") else None,
            stack_weight=e.stack_weight_kg if e.equipment_type.value in ("cable", "machine") else None,
            bar_weight=e.bar_weight_kg if e.equipment_type.value == "barbell" else None,
        )
        for e, brand_name in rows
    ]
    return SuccessResponse(data=EquipmentListData(items=items))
