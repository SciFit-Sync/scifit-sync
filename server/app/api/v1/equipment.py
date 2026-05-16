"""장비 카탈로그 엔드포인트 (#46 GET /equipment, POST /equipment/select)."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models import (
    Equipment,
    EquipmentBrand,
    EquipmentMuscle,
    GymEquipment,
    MuscleGroup,
    User,
    UserGym,
)
from app.schemas.common import PaginatedResponse, PaginationMeta, SuccessResponse
from app.schemas.gyms import (
    BrandItem,
    BrandListData,
    EquipmentItem,
    EquipmentListData,
    SelectData,
    SelectEquipmentRequest,
)
from app.services.image_gen import get_or_generate_image_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/equipment", tags=["equipment"])


def _to_item(
    e: Equipment,
    brand_name: str | None,
    primary_muscles: list[str] | None = None,
    image_url_override: str | None = None,
) -> EquipmentItem:
    return EquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        brand=brand_name,
        category=e.category.value if e.category else None,
        equipment_type=e.equipment_type.value,
        pulley_ratio=e.pulley_ratio,
        min_stack_kg=e.min_stack_kg,
        max_stack_kg=e.max_stack_kg,
        primary_muscles=primary_muscles or [],
        image_url=image_url_override if image_url_override is not None else e.image_url,
    )


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


# ── GET /equipment/brands ─────────────────────────────────────────────────────
@router.get(
    "/brands", response_model=SuccessResponse[BrandListData], summary="기구 브랜드 목록"
)
async def list_brands(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        (await db.execute(select(EquipmentBrand).order_by(EquipmentBrand.name)))
        .scalars()
        .all()
    )
    items = [
        BrandItem(brand_id=str(b.id), name=b.name, logo_url=b.logo_url) for b in rows
    ]
    return SuccessResponse(data=BrandListData(items=items))


# ── GET /equipment ────────────────────────────────────────────────────────────
# page 파라미터 없음 → SuccessResponse[EquipmentListData]  {"data": {"items": [...]}}
# page 파라미터 있음 → PaginatedResponse[EquipmentItem]    {"data": [...], "pagination": {...}}
@router.get("", summary="장비 카탈로그")
async def list_equipment(
    keyword: str | None = Query(None, description="기구 이름 부분 일치 검색"),
    brand: str | None = Query(
        None, description="브랜드명 필터 (예: Life Fitness, 라이프피트니스)"
    ),
    brand_id: str | None = Query(None, description="브랜드 UUID 필터"),
    equipment_type: str | None = Query(
        None, description="cable / machine / barbell / dumbbell / bodyweight"
    ),
    category: str | None = Query(
        None, description="chest / back / shoulders / arms / core / legs"
    ),
    muscle: str | None = Query(
        None, description="부위 필터 — category와 동일 (예: chest / back)"
    ),
    page: int | None = Query(
        None, ge=0, description="페이지 번호 (지정 시 페이지네이션 응답 반환)"
    ),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Equipment, EquipmentBrand.name).outerjoin(
        EquipmentBrand, Equipment.brand_id == EquipmentBrand.id
    )

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
        total = (
            await db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (await db.execute(stmt.offset(page * size).limit(size))).all()
        items = [_to_item(e, b) for e, b in rows]
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
    items = [_to_item(e, b) for e, b in rows]
    return SuccessResponse(data=EquipmentListData(items=items))


# ── GET /equipment/{equipment_id} ────────────────────────────────────────────
@router.get(
    "/{equipment_id}",
    response_model=PaginatedResponse[EquipmentItem],
    summary="기구 상세 조회",
)
async def get_equipment(
    equipment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        eq_uuid = uuid.UUID(equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 equipment_id 형식입니다.") from e

    row = (
        await db.execute(
            select(Equipment, EquipmentBrand.name)
            .outerjoin(EquipmentBrand, Equipment.brand_id == EquipmentBrand.id)
            .where(Equipment.id == eq_uuid)
        )
    ).one_or_none()

    if row is None:
        raise NotFoundError(message="기구를 찾을 수 없습니다.")

    e, brand_name = row
    muscles = await _fetch_muscles(db, [e.id])
    image_url = e.image_url or await get_or_generate_image_url(
        str(e.id), e.name, e.name_en
    )
    item = _to_item(e, brand_name, muscles.get(str(e.id)), image_url_override=image_url)
    return PaginatedResponse(
        data=[item],
        pagination=PaginationMeta(total=1, page=0, limit=1, has_next=False),
    )


# ── POST /equipment/select ────────────────────────────────────────────────────
@router.post(
    "/select", response_model=SuccessResponse[SelectData], summary="기구 선택 저장"
)
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
            raise ValidationError(
                message=f"잘못된 equipment_id 형식입니다: {eid_str}"
            ) from e

    await db.execute(delete(GymEquipment).where(GymEquipment.gym_id == gym_id))
    for eid in valid_ids:
        db.add(GymEquipment(gym_id=gym_id, equipment_id=eid))
    await db.commit()

    return SuccessResponse(data=SelectData(selected_count=len(valid_ids)))
