"""장비 카탈로그 엔드포인트 (#46 GET /equipment, POST /equipment/select)."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models import Equipment, EquipmentBrand, EquipmentMuscle, GymEquipment, MuscleGroup, User, UserGym
from app.schemas.common import PaginatedResponse, PaginationMeta, SuccessResponse
from app.schemas.gyms import (
    BrandItem,
    BrandListData,
    EquipmentItem,
    EquipmentListData,
    SelectData,
    SelectEquipmentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/equipment", tags=["equipment"])


def _ratio_str(pulley_ratio: float | None) -> str | None:
    if pulley_ratio is None:
        return None
    n = int(pulley_ratio) if pulley_ratio == int(pulley_ratio) else pulley_ratio
    return f"{n}:1"


def _to_item(e: Equipment, brand_name: str | None, primary_muscles: list[str] | None = None) -> EquipmentItem:
    type_val = e.equipment_type.value
    return EquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        name_en=e.name_en,
        brand=brand_name,
        category=e.category.value if e.category else None,
        equipment_type=type_val,
        pulley_ratio=e.pulley_ratio,
        bar_weight_kg=e.bar_weight_kg,
        has_weight_assist=e.has_weight_assist,
        min_stack_kg=e.min_stack_kg,
        max_stack_kg=e.max_stack_kg,
        stack_weight_kg=e.stack_weight_kg,
        image_url=e.image_url,
        primary_muscles=primary_muscles or [],
        ratio=_ratio_str(e.pulley_ratio) if type_val in ("cable", "machine") else None,
        stack_weight=e.stack_weight_kg if type_val in ("cable", "machine") else None,
        bar_weight=e.bar_weight_kg if type_val == "barbell" else None,
    )


# ── GET /equipment/brands ─────────────────────────────────────────────────────
@router.get("/brands", response_model=SuccessResponse[BrandListData], summary="기구 브랜드 목록")
async def list_brands(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(EquipmentBrand).order_by(EquipmentBrand.name))).scalars().all()
    items = [BrandItem(brand_id=str(b.id), name=b.name, logo_url=b.logo_url) for b in rows]
    return SuccessResponse(data=BrandListData(items=items))


async def _fetch_muscles(db: AsyncSession, eq_ids: list) -> dict[str, list[str]]:
    if not eq_ids:
        return {}
    rows = (
        await db.execute(
            select(EquipmentMuscle.equipment_id, MuscleGroup.name)
            .join(MuscleGroup, MuscleGroup.id == EquipmentMuscle.muscle_group_id)
            .where(EquipmentMuscle.equipment_id.in_(eq_ids))
        )
    ).all()
    result: dict[str, list[str]] = {}
    for eid, mname in rows:
        result.setdefault(str(eid), []).append(mname)
    return result


# ── GET /equipment ────────────────────────────────────────────────────────────
# page 파라미터 없음 → SuccessResponse[EquipmentListData]  {"data": {"items": [...]}}
# page 파라미터 있음 → PaginatedResponse[EquipmentItem]    {"data": [...], "pagination": {...}}
@router.get("", summary="장비 카탈로그")
async def list_equipment(
    keyword: str | None = Query(None, description="기구 이름 부분 일치 검색"),
    brand: str | None = Query(None, description="브랜드명 필터 (예: Life Fitness, 라이프피트니스)"),
    brand_id: str | None = Query(None, description="브랜드 UUID 필터"),
    equipment_type: str | None = Query(None, description="cable / machine / barbell / dumbbell / bodyweight"),
    category: str | None = Query(None, description="chest / back / shoulders / arms / core / legs"),
    muscle: str | None = Query(None, description="부위 필터 — category와 동일 (예: chest / back)"),
    page: int | None = Query(None, ge=0, description="페이지 번호 (지정 시 페이지네이션 응답 반환)"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Equipment, EquipmentBrand.name).outerjoin(EquipmentBrand, Equipment.brand_id == EquipmentBrand.id)

    if keyword:
        stmt = stmt.where(Equipment.name.ilike(f"%{keyword}%"))
    if brand:
        stmt = stmt.where(EquipmentBrand.name.ilike(f"%{brand}%"))
    if brand_id:
        try:
            brand_uuid = uuid.UUID(brand_id)
        except ValueError as e:
            raise ValidationError(message="잘못된 brand_id 형식입니다.") from e
        stmt = stmt.where(Equipment.brand_id == brand_uuid)
    if equipment_type:
        stmt = stmt.where(Equipment.equipment_type == equipment_type)
    category_filter = category or muscle
    if category_filter:
        stmt = stmt.where(Equipment.category == category_filter)

    if page is not None:
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await db.execute(stmt.offset(page * size).limit(size))).all()
        muscles = await _fetch_muscles(db, [e.id for e, _ in rows])
        items = [_to_item(e, b, muscles.get(str(e.id))) for e, b in rows]
        return PaginatedResponse(
            data=items,
            pagination=PaginationMeta(
                total=total,
                page=page,
                limit=size,
                has_next=(page + 1) * size < total,
            ),
        )

    rows = (await db.execute(stmt)).all()
    muscles = await _fetch_muscles(db, [e.id for e, _ in rows])
    items = [_to_item(e, b, muscles.get(str(e.id))) for e, b in rows]
    return SuccessResponse(data=EquipmentListData(items=items))


# ── POST /equipment/select ────────────────────────────────────────────────────
@router.post("/select", response_model=SuccessResponse[SelectData], summary="기구 선택 저장")
async def select_equipment(
    body: SelectEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """유저의 주 헬스장에 선택한 기구 목록을 저장한다 (기존 목록 교체)."""
    user_gym = (
        await db.execute(
            select(UserGym).where(
                UserGym.user_id == current_user.id,
                UserGym.is_primary.is_(True),
            )
        )
    ).scalar_one_or_none()

    if user_gym is None:
        raise NotFoundError(message="등록된 헬스장이 없습니다.")

    gym_id = user_gym.gym_id

    valid_ids: list[uuid.UUID] = []
    for eid_str in body.equipment_ids:
        try:
            valid_ids.append(uuid.UUID(eid_str))
        except ValueError as e:
            raise ValidationError(message=f"잘못된 equipment_id 형식입니다: {eid_str}") from e

    await db.execute(delete(GymEquipment).where(GymEquipment.gym_id == gym_id))
    for eid in valid_ids:
        db.add(GymEquipment(gym_id=gym_id, equipment_id=eid))
    await db.commit()

    return SuccessResponse(data=SelectData(selected_count=len(valid_ids)))
