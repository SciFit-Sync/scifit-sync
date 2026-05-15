"""헬스장 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #18-20, #44-45.
"""

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, Query
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
    EquipmentSuggestion,
    Gym,
    GymEquipment,
    User,
)
from app.schemas.common import SuccessResponse
from app.schemas.gyms import (
    AddGymEquipmentRequest,
    BulkAddEquipmentRequest,
    BulkLinkData,
    CreateGymRequest,
    EquipmentItem,
    GymEquipmentListData,
    GymItem,
    GymSearchData,
    ReportData,
    ReportEquipmentRequest,
    SuggestEquipmentData,
    SuggestEquipmentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gyms", tags=["gyms"])


def _ratio_str(pulley_ratio: float) -> str:
    n = int(pulley_ratio) if pulley_ratio == int(pulley_ratio) else pulley_ratio
    return f"{n}:1"


def _equipment_to_dto(e: Equipment) -> EquipmentItem:
    is_cable_machine = e.equipment_type.value in ("cable", "machine")
    is_barbell = e.equipment_type.value == "barbell"
    return EquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        name_en=e.name_en,
        brand=e.brand.name if e.brand else None,
        category=e.category.value if e.category else None,
        equipment_type=e.equipment_type.value,
        pulley_ratio=e.pulley_ratio if is_cable_machine else None,
        bar_weight_kg=e.bar_weight_kg if is_barbell else None,
        has_weight_assist=e.has_weight_assist,
        min_stack_kg=e.min_stack_kg,
        max_stack_kg=e.max_stack_kg,
        stack_weight_kg=e.stack_weight_kg if is_cable_machine else None,
        image_url=e.image_url,
        # 표시용 호환 필드
        ratio=_ratio_str(e.pulley_ratio) if is_cable_machine else None,
        stack_weight=e.stack_weight_kg if is_cable_machine else None,
        bar_weight=e.bar_weight_kg if is_barbell else None,
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

    params: dict[str, str | float] = {"query": keyword}
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
        result = await db.execute(
            select(Gym).where(Gym.kakao_place_id.in_(place_ids)).options(selectinload(Gym.gym_equipments))
        )
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
                equipment_count=len(gym.gym_equipments) if gym else 0,
            )
        )

    return SuccessResponse(data=GymSearchData(gyms=items))


# ── POST /gyms ────────────────────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[GymItem], status_code=201, summary="헬스장 등록")
async def create_gym(
    body: CreateGymRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.kakao_place_id:
        existing = (
            await db.execute(
                select(Gym).where(Gym.kakao_place_id == body.kakao_place_id).options(selectinload(Gym.gym_equipments))
            )
        ).scalar_one_or_none()
        if existing is not None:
            return SuccessResponse(
                data=GymItem(
                    gym_id=str(existing.id),
                    name=existing.name,
                    address=existing.address,
                    latitude=existing.latitude,
                    longitude=existing.longitude,
                    kakao_place_id=existing.kakao_place_id,
                    equipment_count=len(existing.gym_equipments),
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

    return SuccessResponse(
        data=GymItem(
            gym_id=str(gym.id),
            name=gym.name,
            address=gym.address,
            latitude=gym.latitude,
            longitude=gym.longitude,
            kakao_place_id=gym.kakao_place_id,
            equipment_count=0,
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
        return SuccessResponse(data=GymEquipmentListData(gym_id=gym_id, gym_name=gym.name, equipment=[]))

    equipments = (
        (
            await db.execute(
                select(Equipment).where(Equipment.id.in_(equipment_ids)).options(selectinload(Equipment.brand))
            )
        )
        .scalars()
        .all()
    )

    return SuccessResponse(
        data=GymEquipmentListData(
            gym_id=gym_id,
            gym_name=gym.name,
            equipment=[_equipment_to_dto(e) for e in equipments],
        )
    )


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

    equipment = (
        await db.execute(select(Equipment).where(Equipment.id == eq_uuid).options(selectinload(Equipment.brand)))
    ).scalar_one_or_none()
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


# ── POST /gyms/{gymId}/equipment/bulk ────────────────────────────────────────
@router.post(
    "/{gym_id}/equipment/bulk",
    response_model=SuccessResponse[BulkLinkData],
    status_code=200,
    summary="헬스장에 기구 일괄 연결",
)
async def bulk_add_gym_equipment(
    gym_id: str,
    body: BulkAddEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    eq_uuids: list[uuid.UUID] = []
    for eid in body.equipment_ids:
        try:
            eq_uuids.append(uuid.UUID(eid))
        except ValueError as e:
            raise ValidationError(message=f"잘못된 equipment_id 형식입니다: {eid}") from e

    existing_ids: set[uuid.UUID] = set()
    if eq_uuids:
        rows = (
            (
                await db.execute(
                    select(GymEquipment.equipment_id).where(
                        GymEquipment.gym_id == gym_uuid,
                        GymEquipment.equipment_id.in_(eq_uuids),
                    )
                )
            )
            .scalars()
            .all()
        )
        existing_ids = set(rows)

    valid_ids = (await db.execute(select(Equipment.id).where(Equipment.id.in_(eq_uuids)))).scalars().all()
    valid_id_set = set(valid_ids)

    linked_count = 0
    for eq_uuid in eq_uuids:
        if eq_uuid not in valid_id_set or eq_uuid in existing_ids:
            continue
        db.add(GymEquipment(gym_id=gym_uuid, equipment_id=eq_uuid, quantity=1))
        linked_count += 1

    await db.commit()

    return SuccessResponse(
        data=BulkLinkData(
            gym_id=gym_id,
            linked_count=linked_count,
            message="기구가 헬스장에 연결되었습니다.",
        )
    )


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


# ── POST /gyms/{gymId}/equipment/suggest ─────────────────────────────────────
@router.post(
    "/{gym_id}/equipment/suggest",
    response_model=SuccessResponse[SuggestEquipmentData],
    status_code=201,
    summary="미등록 기구 제보",
)
async def suggest_gym_equipment(
    gym_id: str,
    body: SuggestEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    db.add(
        EquipmentSuggestion(
            user_id=current_user.id,
            gym_id=gym_uuid,
            name=body.name,
            brand=body.brand,
            description=body.description,
        )
    )
    await db.commit()

    return SuccessResponse(data=SuggestEquipmentData(message="기구 제보가 접수되었습니다. 검토 후 반영됩니다."))
