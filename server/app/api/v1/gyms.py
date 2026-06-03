"""헬스장 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #18-20, #44-45.
"""

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, ExternalServiceError, NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import (
    Equipment,
    EquipmentMuscle,
    EquipmentReport,
    EquipmentReportStatus,
    EquipmentSuggestion,
    Gym,
    GymEquipment,
    User,
    UserGym,
)
from app.models.exercise import Exercise, ExerciseEquipmentMap, ExerciseMuscle
from app.schemas.common import SuccessResponse
from app.schemas.gyms import (
    AddGymEquipmentRequest,
    BulkAddEquipmentRequest,
    BulkLinkData,
    CreateGymRequest,
    EquipmentItem,
    FreeWeightItem,
    GymEquipmentItem,
    GymEquipmentListData,
    GymItem,
    GymSearchData,
    MachineItem,
    MuscleEquipmentData,
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


def _equipment_to_gym_dto(e: Equipment) -> GymEquipmentItem:
    is_cable_machine = str(e.equipment_type) in ("cable", "machine")
    sw = None
    if is_cable_machine and e.stack_weight and isinstance(e.stack_weight, dict):
        sw = float(e.stack_weight["value"]) if "value" in e.stack_weight else None
    return GymEquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        brand=e.brand.name if e.brand else None,
        ratio=_ratio_str(e.pulley_ratio) if is_cable_machine else None,
        image_url=e.image_url,
        stack_weight=sw,
    )


def _equipment_to_dto(e: Equipment, image_url: str | None = None) -> EquipmentItem:
    is_cable_machine = str(e.equipment_type) in ("cable", "machine")
    is_barbell = str(e.equipment_type) == "barbell"
    return EquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        brand=e.brand.name if e.brand else None,
        category=str(e.category) if e.category else None,
        equipment_type=str(e.equipment_type),
        pulley_ratio=e.pulley_ratio if is_cable_machine else None,
        bar_weight=e.bar_weight if is_barbell else None,
        has_weight_assist=e.has_weight_assist,
        min_stack=e.min_stack,
        max_stack=e.max_stack,
        stack_weight=e.stack_weight if is_cable_machine else None,
        image_url=image_url if image_url is not None else e.image_url,
        ratio=_ratio_str(e.pulley_ratio) if is_cable_machine else None,
    )


# ── GET /gyms?keyword= ────────────────────────────────────────────────────────
@router.get("", response_model=SuccessResponse[GymSearchData], summary="헬스장 검색")
@rate_limit("60/minute")
async def search_gyms(
    request: Request,
    keyword: str | None = Query(None, description="검색 키워드 (없으면 주변 헬스장)"),
    latitude: float | None = Query(None),
    longitude: float | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """카카오 로컬 API로 검색 후, kakao_place_id로 DB 조회/매칭하여 반환한다.
    keyword 없이 좌표만 넘기면 주변 헬스장을 거리순으로 반환한다.
    DB에 없는 헬스장은 응답에는 포함하되 gym_id 미할당 (POST /gyms로 생성 후 사용).
    """
    settings = get_settings()
    if not settings.KAKAO_REST_API_KEY:
        raise ExternalServiceError(message="카카오 로컬 API 키가 설정되지 않았습니다.")

    # keyword 없으면 "헬스장"으로 검색 — 좌표와 함께 쓰면 거리순 주변 헬스장
    has_keyword = bool(keyword and keyword.strip())
    kakao_keyword = keyword.strip() if has_keyword else "헬스장"
    params: dict[str, str | float] = {"query": kakao_keyword}
    if latitude is not None and longitude is not None:
        params.update({"x": longitude, "y": latitude, "sort": "distance"})
        # 주변 헬스장 탐색(키워드 없음)일 때만 반경 5km 제한 — 키워드 검색은 거리 제한 없이 표시
        if not has_keyword:
            params["radius"] = 5000

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
        logger.error("카카오 로컬 API 실패: status=%d body=%s", resp.status_code, resp.text[:200])
        raise ExternalServiceError(message=f"카카오 로컬 API 요청이 실패했습니다. (status={resp.status_code})")

    # 헬스장/피트니스 관련 카테고리만 필터링
    GYM_KEYWORDS = ("헬스", "피트니스", "크로스핏", "스포츠클럽", "pt샵", "pt 샵", "웨이트", "짐", "gym", "스포츠시설")
    raw_docs = resp.json().get("documents", [])
    documents = [
        d
        for d in raw_docs
        if any(
            kw in (d.get("category_name") or "").lower() or kw in (d.get("place_name") or "").lower()
            for kw in GYM_KEYWORDS
        )
    ]
    place_ids = [d["id"] for d in documents]

    # 기존 DB 매칭 — equipment_count만 필요하므로 COUNT 서브쿼리 사용 (전체 로드 방지)
    eq_count_subq = (
        select(func.count(GymEquipment.equipment_id))
        .where(GymEquipment.gym_id == Gym.id)
        .correlate(Gym)
        .scalar_subquery()
    )
    existing: dict[str, tuple[Gym, int]] = {}
    if place_ids:
        rows = (
            await db.execute(select(Gym, eq_count_subq.label("eq_count")).where(Gym.kakao_place_id.in_(place_ids)))
        ).all()
        for g, cnt in rows:
            if g.kakao_place_id:
                existing[g.kakao_place_id] = (g, cnt)

    items: list[GymItem] = []
    for d in documents:
        place_id = d["id"]
        entry = existing.get(place_id)
        gym, eq_count = entry if entry else (None, 0)
        items.append(
            GymItem(
                gym_id=str(gym.id) if gym else "",
                name=gym.name if gym else d.get("place_name", ""),
                address=gym.address if gym else d.get("road_address_name") or d.get("address_name", ""),
                latitude=gym.latitude if gym else float(d.get("y") or 0),
                longitude=gym.longitude if gym else float(d.get("x") or 0),
                kakao_place_id=place_id,
                equipment_count=eq_count,
            )
        )

    return SuccessResponse(data=GymSearchData(gyms=items))


# ── POST /gyms ────────────────────────────────────────────────────────────────
@router.post("", response_model=SuccessResponse[GymItem], status_code=201, summary="헬스장 등록")
@rate_limit("60/minute")
async def create_gym(
    request: Request,
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
@rate_limit("60/minute")
async def list_gym_equipment(
    request: Request,
    gym_id: str,
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

    # GymEquipment JOIN Equipment — 2번 쿼리를 1번으로 단축
    equipments = (
        (
            await db.execute(
                select(Equipment)
                .join(GymEquipment, GymEquipment.equipment_id == Equipment.id)
                .where(GymEquipment.gym_id == gym_uuid)
                .options(selectinload(Equipment.brand))
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
    summary="헬스장 장비 단건 추가",
)
@rate_limit("60/minute")
async def add_gym_equipment(
    request: Request,
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
    summary="헬스장 장비 복수 추가 (일괄 연결)",
)
@rate_limit("60/minute")
async def bulk_add_gym_equipment(
    request: Request,
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


# ── DELETE /gyms/{gymId}/equipment/{equipmentId} ─────────────────────────────
@router.delete(
    "/{gym_id}/equipment/{equipment_id}",
    response_model=SuccessResponse[dict],
    status_code=200,
    summary="헬스장 기구 삭제",
)
@rate_limit("60/minute")
async def delete_gym_equipment(
    request: Request,
    gym_id: str,
    equipment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(gym_id)
        eq_uuid = uuid.UUID(equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 ID 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    # 요청자가 해당 헬스장 소속인지 확인
    user_gym = (
        await db.execute(
            select(UserGym).where(
                UserGym.user_id == current_user.id,
                UserGym.gym_id == gym_uuid,
            )
        )
    ).scalar_one_or_none()
    if user_gym is None:
        raise NotFoundError(message="본인의 헬스장 기구만 삭제할 수 있습니다.")

    row = (
        await db.execute(
            select(GymEquipment).where(
                GymEquipment.gym_id == gym_uuid,
                GymEquipment.equipment_id == eq_uuid,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(message="해당 기구가 헬스장에 등록되어 있지 않습니다.")

    await db.delete(row)
    await db.commit()

    return SuccessResponse(data={"message": "기구가 삭제되었습니다."})


# ── POST /gyms/{gymId}/equipment/report ───────────────────────────────────────
@router.post(
    "/{gym_id}/equipment/report",
    response_model=SuccessResponse[ReportData],
    status_code=201,
    summary="장비 정보 신고",
)
@rate_limit("60/minute")
async def report_gym_equipment(
    request: Request,
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

    return SuccessResponse(data=ReportData(report_id=str(report.id), status=str(report.status)))


# ── POST /gyms/{gymId}/equipment/suggest ─────────────────────────────────────
@router.post(
    "/{gym_id}/equipment/suggest",
    response_model=SuccessResponse[SuggestEquipmentData],
    status_code=201,
    summary="미등록 기구 제보",
)
@rate_limit("60/minute")
async def suggest_gym_equipment(
    request: Request,
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
        )
    )
    await db.commit()

    return SuccessResponse(data=SuggestEquipmentData(message="기구 제보가 접수되었습니다. 검토 후 반영됩니다."))


# ── GET /gyms/{gym_id}/equipments?muscle_group_id=&involvement= ───────────────
@router.get(
    "/{gym_id}/equipments",
    response_model=SuccessResponse[MuscleEquipmentData],
    summary="근육별 기구 목록 (머신 + 프리웨이트)",
)
@rate_limit("60/minute")
async def list_equipments_by_muscle(
    request: Request,
    gym_id: str,
    muscle_group_id: str | None = Query(None, description="근육군 UUID. 미지정 시 400 반환"),
    involvement: str = Query("primary", description="primary | secondary | stabilizer"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """특정 근육군을 타깃으로 하는 기구 목록을 머신(헬스장별)과 프리웨이트(공통)로 분리하여 반환한다.

    - machines[]: 해당 헬스장(gym_id)이 보유한 머신/케이블만. equipment_muscles 백필 기반.
    - free_weights[]: 전 헬스장 공통. exercise_muscles의 primary 운동 중 프리웨이트 기구에 연결된 운동.
    """
    # muscle_group_id 필수 검증
    if not muscle_group_id:
        raise ValidationError(message="muscle_group_id 파라미터는 필수입니다.")

    try:
        gym_uuid = uuid.UUID(gym_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    try:
        mg_uuid = uuid.UUID(muscle_group_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 muscle_group_id 형식입니다.") from e

    # 헬스장 존재 확인
    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    # ── 머신 목록 ─────────────────────────────────────────────────────────────
    # equipment_muscles em JOIN equipments e(is_freeweight=false)
    # JOIN gym_equipments ge(ge.gym_id=path) WHERE em.muscle_group_id=q AND em.involvement=q
    machine_rows = (
        await db.execute(
            select(
                Equipment.id,
                Equipment.movement_label_ko,
                Equipment.name,
                Equipment.equipment_type,
                Equipment.image_url,
            )
            .join(EquipmentMuscle, EquipmentMuscle.equipment_id == Equipment.id)
            .join(
                GymEquipment,
                (GymEquipment.equipment_id == Equipment.id) & (GymEquipment.gym_id == gym_uuid),
            )
            .where(
                EquipmentMuscle.muscle_group_id == mg_uuid,
                EquipmentMuscle.involvement == involvement,
                Equipment.equipment_type.notin_(["barbell", "dumbbell", "bodyweight"]),
            )
            .order_by(Equipment.name)
        )
    ).all()

    # 브랜드명은 별도 조회 없이 equipment.brand 관계 활용 시 N+1 발생.
    # 여기서는 equipment_id로 brand JOIN을 추가한 subquery 대신
    # 단순 selectinload 없이 brand_id 조인으로 처리한다 (brand_name 필요 시 join 확장 가능).
    # PR-1 범위에서는 brand 없이 반환 (필요 시 후속 PR에서 JOIN 추가).
    machines: list[MachineItem] = [
        MachineItem(
            equipment_id=str(row.id),
            label=row.movement_label_ko or row.name,
            equipment_type=str(row.equipment_type),
            image_url=row.image_url,
            brand=None,
        )
        for row in machine_rows
    ]

    # ── 프리웨이트 목록 ───────────────────────────────────────────────────────
    # exercise_muscles xm JOIN exercises x JOIN exercise_equipment_map eem
    # JOIN equipments e(is_freeweight=true)
    # WHERE xm.muscle_group_id=q AND xm.involvement='primary'
    # 프리웨이트는 항상 involvement='primary' 기준으로 운동 선택
    # (involvement 쿼리 파라미터는 머신에만 적용; 프리웨이트는 primary 고정)
    fw_rows = (
        await db.execute(
            select(
                Exercise.id,
                Exercise.name,
                Exercise.name_en,
                Equipment.id.label("equipment_id"),
                Equipment.equipment_type,
            )
            .join(ExerciseMuscle, ExerciseMuscle.exercise_id == Exercise.id)
            .join(ExerciseEquipmentMap, ExerciseEquipmentMap.exercise_id == Exercise.id)
            .join(Equipment, Equipment.id == ExerciseEquipmentMap.equipment_id)
            .where(
                ExerciseMuscle.muscle_group_id == mg_uuid,
                ExerciseMuscle.involvement == "primary",
                Equipment.equipment_type.in_(["barbell", "dumbbell", "bodyweight"]),
            )
            .distinct()
            .order_by(Exercise.name)
        )
    ).all()

    free_weights: list[FreeWeightItem] = [
        FreeWeightItem(
            exercise_id=str(row.id),
            name=row.name,
            name_en=row.name_en,
            equipment_id=str(row.equipment_id) if row.equipment_id else None,
            equipment_type=str(row.equipment_type) if row.equipment_type else None,
        )
        for row in fw_rows
    ]

    logger.debug(
        "list_equipments_by_muscle: gym_id=%s muscle_group_id=%s involvement=%s "
        "machines=%d free_weights=%d",
        gym_id,
        muscle_group_id,
        involvement,
        len(machines),
        len(free_weights),
    )

    return SuccessResponse(
        data=MuscleEquipmentData(
            free_weights=free_weights,
            machines=machines,
        )
    )
