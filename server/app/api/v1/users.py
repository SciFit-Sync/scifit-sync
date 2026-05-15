"""사용자 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #9-17, #43, #50.
"""

import logging
import uuid
from datetime import date as date_type
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    CareerLevel,
    Equipment,
    Exercise,
    Gym,
    OnermSource,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    UserGym,
    UserProfile,
)
from app.schemas.common import SuccessResponse
from app.schemas.users import (
    AddUserEquipmentRequest,
    BodyMeasurementData,
    GymData,
    MeData,
    OneRM4BigLiftData,
    ProfileData,
    Set1RMRequest,
    SetPrimaryGymRequest,
    UpdateBodyData,
    UpdateBodyRequest,
    UpdateCareerData,
    UpdateCareerRequest,
    UpdateGoalRequest,
    UserBodyData,
    UserCareerData,
    UserEquipmentItem,
    UserEquipmentListData,
    UserGymData,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

# ── 경력 레벨 설명 매핑 ───────────────────────────────────────────────────────
_CAREER_DESCRIPTIONS: dict[str, str] = {
    "beginner": "초보자",
    "novice": "초보자 · 1-2년",
    "intermediate": "중급자 · 3년",
    "advanced": "고급자 · 5년+",
}

# ── 4대 운동 필드명 ↔ DB 운동명 매핑 ─────────────────────────────────────────
_BIG_LIFT_MAP: dict[str, str] = {
    "bench_press": "벤치 프레스",
    "squat": "스쿼트",
    "deadlift": "데드리프트",
    "overhead_press": "오버헤드 프레스",
}
_REVERSE_BIG_LIFT_MAP: dict[str, str] = {v: k for k, v in _BIG_LIFT_MAP.items()}


def _calc_age(birth_date: date_type | None) -> int | None:
    if birth_date is None:
        return None
    today = date_type.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _profile_to_dto(profile: UserProfile | None) -> ProfileData | None:
    if profile is None:
        return None
    return ProfileData(
        gender=profile.gender.value if profile.gender else None,
        birth_date=profile.birth_date,
        height_cm=profile.height_cm,
        default_goals=profile.default_goals,
        career_level=profile.career_level.value if profile.career_level else None,
    )


def _measurement_to_dto(m: UserBodyMeasurement | None) -> BodyMeasurementData | None:
    if m is None:
        return None
    return BodyMeasurementData(
        weight_kg=m.weight_kg,
        skeletal_muscle_kg=m.skeletal_muscle_kg,
        body_fat_pct=m.body_fat_pct,
        measured_at=m.measured_at,
    )


# ── GET /users/me ─────────────────────────────────────────────────────────────
@router.get("/me", response_model=SuccessResponse[MeData], summary="내 정보 조회")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 프로필
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))).scalar_one_or_none()

    # 최신 체측
    latest_m = (
        await db.execute(
            select(UserBodyMeasurement)
            .where(UserBodyMeasurement.user_id == current_user.id)
            .order_by(UserBodyMeasurement.measured_at.desc(), UserBodyMeasurement.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    # 주 헬스장
    primary_gym = (
        await db.execute(
            select(Gym)
            .join(UserGym, UserGym.gym_id == Gym.id)
            .where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True))
        )
    ).scalar_one_or_none()

    # 1RM (4대 운동 최신)
    one_rm_rows = (
        await db.execute(
            select(UserExercise1RM, Exercise.name)
            .join(Exercise, UserExercise1RM.exercise_id == Exercise.id)
            .where(
                UserExercise1RM.user_id == current_user.id,
                Exercise.name.in_(list(_BIG_LIFT_MAP.values())),
            )
            .order_by(UserExercise1RM.estimated_at.desc())
        )
    ).all()

    # 운동별 최신 1RM만 유지
    latest_1rm: dict[str, float] = {}
    for record, ex_name in one_rm_rows:
        if ex_name not in latest_1rm:
            latest_1rm[ex_name] = record.weight_kg

    # body 서브오브젝트
    body_data = UserBodyData(
        gender=profile.gender.value if profile and profile.gender else None,
        age=_calc_age(profile.birth_date if profile else None),
        height_cm=profile.height_cm if profile else None,
        weight_kg=latest_m.weight_kg if latest_m else None,
    )

    # career 서브오브젝트
    career_level = profile.career_level.value if profile and profile.career_level else None
    career_data = (
        UserCareerData(
            level=career_level,
            description=_CAREER_DESCRIPTIONS.get(career_level),
        )
        if career_level
        else None
    )

    # gym 서브오브젝트
    gym_data = UserGymData(gym_id=str(primary_gym.id), name=primary_gym.name) if primary_gym else None

    # one_rm 서브오브젝트
    one_rm_weights = {_REVERSE_BIG_LIFT_MAP[name]: weight for name, weight in latest_1rm.items()}
    one_rm_data = OneRM4BigLiftData(unit="KG", **one_rm_weights) if one_rm_weights else None

    return SuccessResponse(
        data=MeData(
            user_id=str(current_user.id),
            email=current_user.email,
            name=current_user.name,
            username=current_user.username,
            body=body_data,
            career=career_data,
            gym=gym_data,
            one_rm=one_rm_data,
        )
    )


# ── PATCH /users/me/body ──────────────────────────────────────────────────────
@router.patch("/me/body", response_model=SuccessResponse[UpdateBodyData], summary="신체 정보 수정")
async def update_body(
    body: UpdateBodyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    measurement_dto: BodyMeasurementData | None = None

    # 키는 UserProfile.height_cm에 저장 (upsert)
    if body.height_cm is not None:
        profile = (
            await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
        ).scalar_one_or_none()
        if profile is None:
            profile = UserProfile(user_id=current_user.id, height_cm=body.height_cm)
            db.add(profile)
        else:
            profile.height_cm = body.height_cm

    # 체중/근육량/체지방률은 새 측정 기록으로 추가
    if any(v is not None for v in (body.weight_kg, body.skeletal_muscle_kg, body.body_fat_pct)):
        if body.weight_kg is None:
            raise ValidationError(message="체중(weight_kg)은 필수입니다.")
        m = UserBodyMeasurement(
            user_id=current_user.id,
            weight_kg=body.weight_kg,
            skeletal_muscle_kg=body.skeletal_muscle_kg,
            body_fat_pct=body.body_fat_pct,
            measured_at=body.measured_at or datetime.now(timezone.utc).date(),
        )
        db.add(m)
        await db.flush()
        measurement_dto = _measurement_to_dto(m)

    await db.commit()
    return SuccessResponse(data=UpdateBodyData(height_cm=body.height_cm, measurement=measurement_dto))


# ── PATCH /users/me/goal ──────────────────────────────────────────────────────
@router.patch("/me/goal", response_model=SuccessResponse[ProfileData], summary="운동 목표 수정")
async def update_goal(
    body: UpdateGoalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=current_user.id, default_goals=body.goals or None)
        db.add(profile)
    else:
        profile.default_goals = body.goals or None
    await db.commit()
    return SuccessResponse(data=_profile_to_dto(profile))  # type: ignore[arg-type]


# ── PATCH /users/me/career ────────────────────────────────────────────────────
@router.patch("/me/career", response_model=SuccessResponse[UpdateCareerData], summary="경력 수정")
async def update_career(
    body: UpdateCareerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        career = CareerLevel(body.career_level)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 경력 레벨입니다: {body.career_level}") from e

    profile = (await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=current_user.id, career_level=career)
        db.add(profile)
    else:
        profile.career_level = career
    await db.commit()
    return SuccessResponse(
        data=UpdateCareerData(
            message="운동 경력이 수정되었습니다.",
            career_level=career.value,
        )
    )


# ── POST /users/me/gym ────────────────────────────────────────────────────────
@router.post("/me/gym", response_model=SuccessResponse[GymData], status_code=201, summary="주 헬스장 등록")
async def add_primary_gym(
    body: SetPrimaryGymRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        gym_uuid = uuid.UUID(body.gym_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 gym_id 형식입니다.") from e

    gym = (await db.execute(select(Gym).where(Gym.id == gym_uuid))).scalar_one_or_none()
    if gym is None:
        raise NotFoundError(message="헬스장을 찾을 수 없습니다.")

    # 기존 primary 해제
    existing = (
        (await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True))))
        .scalars()
        .all()
    )
    for ug in existing:
        ug.is_primary = False

    # 이미 등록된 헬스장이면 primary로 승격, 아니면 새로 추가
    own = (
        await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.gym_id == gym_uuid))
    ).scalar_one_or_none()
    if own is None:
        own = UserGym(user_id=current_user.id, gym_id=gym_uuid, is_primary=True)
        db.add(own)
    else:
        own.is_primary = True

    await db.commit()
    return SuccessResponse(data=GymData(gym_id=str(gym.id), name=gym.name, is_primary=True))


# ── PATCH /users/me/gym ───────────────────────────────────────────────────────
@router.patch("/me/gym", response_model=SuccessResponse[GymData], summary="주 헬스장 변경")
async def change_primary_gym(
    body: SetPrimaryGymRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_primary_gym(body, current_user, db)


# ── 1RM (Big 4) ───────────────────────────────────────────────────────────────
async def _save_1rm_records(body: Set1RMRequest, user_id: uuid.UUID, db: AsyncSession) -> dict[str, float | None]:
    """4대 운동 1RM을 DB에 저장하고 저장된 필드별 weight를 반환한다.

    IN 쿼리 1회로 필요한 운동을 일괄 조회하여 N+1 쿼리를 방지한다.
    """
    requested: dict[str, float] = {
        field: getattr(body, field) for field in _BIG_LIFT_MAP if getattr(body, field) is not None
    }
    result_weights: dict[str, float | None] = {k: None for k in _BIG_LIFT_MAP}
    if not requested:
        return result_weights

    needed_names = [_BIG_LIFT_MAP[f] for f in requested]
    exercises = (await db.execute(select(Exercise).where(Exercise.name.in_(needed_names)))).scalars().all()
    ex_by_name = {e.name: e for e in exercises}

    for field_name, weight in requested.items():
        exercise = ex_by_name.get(_BIG_LIFT_MAP[field_name])
        if exercise is None:
            continue
        db.add(UserExercise1RM(user_id=user_id, exercise_id=exercise.id, weight_kg=weight, source=OnermSource.MANUAL))
        result_weights[field_name] = weight

    await db.commit()
    return result_weights


@router.post("/me/1rm", response_model=SuccessResponse[OneRM4BigLiftData], status_code=201, summary="1RM 설정")
async def set_1rm(
    body: Set1RMRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result_weights = await _save_1rm_records(body, current_user.id, db)
    return SuccessResponse(data=OneRM4BigLiftData(unit="KG", **result_weights))


@router.patch("/me/1rm", response_model=SuccessResponse[OneRM4BigLiftData], summary="1RM 수정")
async def update_1rm(
    body: Set1RMRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result_weights = await _save_1rm_records(body, current_user.id, db)
    return SuccessResponse(data=OneRM4BigLiftData(unit="KG", **result_weights))


@router.get("/me/1rm", response_model=SuccessResponse[OneRM4BigLiftData], summary="1RM 데이터 조회")
async def get_1rm(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    exercise_names = list(_BIG_LIFT_MAP.values())
    rows = (
        await db.execute(
            select(UserExercise1RM, Exercise.name)
            .join(Exercise, UserExercise1RM.exercise_id == Exercise.id)
            .where(
                UserExercise1RM.user_id == current_user.id,
                Exercise.name.in_(exercise_names),
            )
            .order_by(UserExercise1RM.estimated_at.desc())
        )
    ).all()

    latest: dict[str, float] = {}
    for record, ex_name in rows:
        if ex_name not in latest:
            latest[ex_name] = record.weight_kg

    weights = {_REVERSE_BIG_LIFT_MAP[name]: weight for name, weight in latest.items()}
    return SuccessResponse(data=OneRM4BigLiftData(unit="KG", **weights))


# ── /users/me/equipment ───────────────────────────────────────────────────────
@router.get("/me/equipment", response_model=SuccessResponse[UserEquipmentListData], summary="내 보유 장비")
async def list_my_equipment(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    primary = (
        await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True)))
    ).scalar_one_or_none()
    if primary is None:
        return SuccessResponse(data=UserEquipmentListData(items=[]))

    result = await db.execute(select(Gym).where(Gym.id == primary.gym_id).options(selectinload(Gym.gym_equipments)))
    gym = result.scalar_one_or_none()
    if gym is None:
        return SuccessResponse(data=UserEquipmentListData(items=[]))

    equipment_ids = [ge.equipment_id for ge in gym.gym_equipments]
    if not equipment_ids:
        return SuccessResponse(data=UserEquipmentListData(items=[]))

    equipments = (await db.execute(select(Equipment).where(Equipment.id.in_(equipment_ids)))).scalars().all()

    items = [
        UserEquipmentItem(
            equipment_id=str(e.id),
            name=e.name,
            category=e.category.value if e.category else None,
            equipment_type=e.equipment_type.value,
            pulley_ratio=e.pulley_ratio,
            bar_weight_kg=e.bar_weight_kg,
            image_url=e.image_url,
        )
        for e in equipments
    ]
    return SuccessResponse(data=UserEquipmentListData(items=items))


@router.post(
    "/me/equipment",
    response_model=SuccessResponse[UserEquipmentItem],
    status_code=201,
    summary="장비 추가 (스폿)",
)
async def add_my_equipment(
    body: AddUserEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        eq_uuid = uuid.UUID(body.equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 equipment_id 형식입니다.") from e

    equipment = (await db.execute(select(Equipment).where(Equipment.id == eq_uuid))).scalar_one_or_none()
    if equipment is None:
        raise NotFoundError(message="장비를 찾을 수 없습니다.")

    primary = (
        await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True)))
    ).scalar_one_or_none()
    if primary is None:
        raise ValidationError(message="주 헬스장이 등록되어 있지 않습니다.")

    from app.models import GymEquipment

    exists = (
        await db.execute(
            select(GymEquipment).where(
                GymEquipment.gym_id == primary.gym_id,
                GymEquipment.equipment_id == eq_uuid,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(message="이미 등록된 장비입니다.")

    db.add(GymEquipment(gym_id=primary.gym_id, equipment_id=eq_uuid))
    await db.commit()

    return SuccessResponse(
        data=UserEquipmentItem(
            equipment_id=str(equipment.id),
            name=equipment.name,
            category=equipment.category.value if equipment.category else None,
            equipment_type=equipment.equipment_type.value,
            pulley_ratio=equipment.pulley_ratio,
            bar_weight_kg=equipment.bar_weight_kg,
            image_url=equipment.image_url,
        )
    )
