"""헬스장 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #18-20, #44-45.
"""

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, ExternalServiceError, NotFoundError, ValidationError
from app.models import (
    Equipment,
    EquipmentReport,
    EquipmentReportStatus,
    Gym,
    GymEquipment,
    User,
)
from app.schemas.common import SuccessResponse
from app.schemas.gyms import (
    AddGymEquipmentRequest,
    CreateGymData,
    CreateGymRequest,
    EquipmentItem,
    GymEquipmentListData,
    GymItem,
    GymSearchData,
    ReportData,
    ReportEquipmentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gyms", tags=["gyms"])


def _equipment_to_dto(e: Equipment, brand_name: str | None = None) -> EquipmentItem:
    return EquipmentItem(
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


# ── GET /gyms?keyword= ────────────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[GymSearchData], summary="헬스장 검색")
async def search_gyms(
    keyword: str = Query(..., min_length=1, description="검색 키워드"),
    latitude: float | None = Query(None),
    longitude: float | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """카카오 로컬 API로 검색 후, kakao_place_id로 DB 조회/매칭하여 반환한다.
    DB에 없는 헬스장은 응답에는 포함하되 gym_id 미할당 (POST /gyms로 생성 후 사용).
    """
    settings = get_settings()
    if not settings.KAKAO_REST_API_KEY:
        raise ExternalServiceError(message="카카오 로컬 API 키가 설정되지 않았습니다.")

    params: dict[str, str | float] = {"query": keyword, "category_group_code": "AT4,SW8"}
    if latitude is not None and longitude is not None:
        params.update({"x": longitude, "y": latitude, "radius": 5000, "sort": "distance"})

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                headers={"Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"},
                params=params,
            )
    except httpx.RequestError as e:
        raise ExternalServiceError(message="카카오 로컬 API에 연결할 수 없습니다.") from e

    if not resp.is_success:
        raise ExternalServiceError(message="카카오 로컬 API 요청이 실패했습니다.")

    documents = resp.json().get("documents", [])
    place_ids = [d["id"] for d in documents]

    # 기존 DB 매칭
    existing: dict[str, Gym] = {}
    if place_ids:
        result = await db.execute(select(Gym).where(Gym.kakao_place_id.in_(place_ids)))
        for g in result.scalars().all():
            if g.kakao_place_id:
                existing[g.kakao_place_id] = g

    items: list[GymItem] = []
    for d in documents:
        place_id = d["id"]
        gym = existing.get(place_id)
        items.append(
            GymItem(
                gym_id=str(gym.id) if gym else "",
                name=gym.name if gym else d.get("place_name", ""),
                address=gym.address if gym else d.get("road_address_name") or d.get("address_name", ""),
                latitude=float(gym.latitude) if gym else float(d.get("y", 0)),
                longitude=float(gym.longitude) if gym else float(d.get("x", 0)),
                kakao_place_id=place_id,
            )
        )

    return SuccessResponse(data=GymSearchData(items=items))


# ── POST /gyms ────────────────────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[CreateGymData], status_code=201, summary="헬스장 등록")
async def create_gym(
    body: CreateGymRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(select(Gym).where(Gym.kakao_place_id == body.kakao_place_id))).scalar_one_or_none()
    if existing is not None:
        response.status_code = 200
        return SuccessResponse(
            data=CreateGymData(
                gym_id=str(existing.id),
                name=existing.name,
                message="이미 등록된 헬스장입니다.",
            )
        )

    gym = Gym(
        name=body.name,
        address=body.address,
        latitude=body.latitude,
        longitude=body.longitude,
        kakao_place_id=body.kakao_place_id,
    )
    db.add(gym)
    await db.commit()
    await db.refresh(gym)

    logger.info("Gym created: %s (kakao_place_id=%s)", gym.id, gym.kakao_place_id)
    return SuccessResponse(
        data=CreateGymData(
            gym_id=str(gym.id),
            name=gym.name,
            message="헬스장이 등록되었습니다.",
        )
    )


# ── GET /gyms/{gymId}/equipment ───────────────────────────────────────────────
@router.get(
    "/{gym_id}/equipment",
    response_model=SuccessResponse[GymEquipmentListData],
    summary="헬스장 보유 장비 목록",
)
async def list_gym_equipment(
    gym_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    gym = (
        await db.execute(select(Gym).where(Gym.id == gym_uuid).options(selectinload(Gym.gym_equipments)))
    ).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    equipment_ids = [ge.equipment_id for ge in gym.gym_equipments]
    if not equipment_ids:
        return SuccessResponse(data=GymEquipmentListData(gym_id=gym_id, items=[]))

    equipments = (await db.execute(select(Equipment).where(Equipment.id.in_(equipment_ids)))).scalars().all()

    items = [_equipment_to_dto(e) for e in equipments]
    return SuccessResponse(data=GymEquipmentListData(gym_id=gym_id, items=items))


# ── POST /gyms/{id}/equipment ─────────────────────────────────────────────────
@router.post(
    "/{gym_id}/equipment",
    response_model=SuccessResponse[EquipmentItem],
    status_code=201,
    summary="헬스장에 장비 추가",
)
async def add_gym_equipment(
    gym_id: str,
    body: AddGymEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
        eq_uuid = uuid.UUID(body.equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 ID 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    equipment = (await db.execute(select(Equipment).where(Equipment.id == eq_uuid))).scalar_one_or_none()
    if equipment is None:
        raise NotFoundError(message="장비를 찾을 수 없습니다.")

    exists = (
        await db.execute(
            select(GymEquipment).where(GymEquipment.gym_id == gym_uuid, GymEquipment.equipment_id == eq_uuid)
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(message="이미 등록된 장비입니다.")

    db.add(GymEquipment(gym_id=gym_uuid, equipment_id=eq_uuid, quantity=body.quantity))
    await db.commit()

    return SuccessResponse(data=_equipment_to_dto(equipment))


# ── POST /gyms/{gymId}/equipment/report ───────────────────────────────────────
@router.post(
    "/{gym_id}/equipment/report",
    response_model=SuccessResponse[ReportData],
    status_code=201,
    summary="장비 정보 신고",
)
async def report_gym_equipment(
    gym_id: str,
    body: ReportEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
        eq_uuid = uuid.UUID(body.equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 ID 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    report = EquipmentReport(
        user_id=current_user.id,
        gym_id=gym_uuid,
        equipment_id=eq_uuid,
        report_type=body.report_type,
        status=EquipmentReportStatus.PENDING,
        description=body.description,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return SuccessResponse(data=ReportData(report_id=str(report.id), status=report.status.value))
