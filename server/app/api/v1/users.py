"""사용자 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #9-17, #43, #50.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import (
    CareerLevel,
    Equipment,
    Exercise,
    Gender,
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
    Add1RMRequest,
    AddUserEquipmentRequest,
    BodyMeasurementData,
    BulkAdd1RMRequest,
    BulkOneRMData,
    GymData,
    MeData,
    OnboardData,
    OnboardRequest,
    OneRMData,
    OneRMListData,
    ProfileData,
    SetPrimaryGymRequest,
    UpdateBodyData,
    UpdateBodyRequest,
    UpdateCareerRequest,
    UpdateGoalRequest,
    UserEquipmentItem,
    UserEquipmentListData,
)
from app.services.load_calc import estimate_1rm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _calc_age(birth_date: date | None) -> int | None:
    if birth_date is None:
        return None
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _profile_to_dto(profile: UserProfile | None) -> ProfileData | None:
    if profile is None:
        return None
    return ProfileData(
        gender=profile.gender.value if profile.gender else None,
        birth_date=profile.birth_date,
        age=_calc_age(profile.birth_date),
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


# ── POST /users/me/onboard ───────────────────────────────────────────────────
@rate_limit("60/minute")
@router.post(
    "/me/onboard",
    response_model=SuccessResponse[OnboardData],
    status_code=201,
    summary="온보딩 완료 (최초 신체정보 등록)",
)
async def onboard(
    request: Request,
    body: OnboardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """회원가입 직후 W-A03 화면에서 호출. UserProfile이 이미 존재하면 409."""
    existing = (
        await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(message="이미 온보딩이 완료된 계정입니다.")

    try:
        career = CareerLevel(body.career_level)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 경력 레벨입니다: {body.career_level}") from e

    try:
        gender = Gender(body.gender)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 성별 값입니다: {body.gender}") from e

    profile = UserProfile(
        user_id=current_user.id,
        gender=gender,
        birth_date=body.birth_date,
        height_cm=body.height_cm,
        career_level=career,
        default_goals=body.default_goals or None,
    )
    db.add(profile)

    # 초기 체중 측정값
    db.add(
        UserBodyMeasurement(
            user_id=current_user.id,
            weight_kg=body.weight_kg,
            measured_at=datetime.now(timezone.utc).date(),
        )
    )

    await db.commit()
    await db.refresh(profile)

    logger.info("User %s onboarding complete", current_user.id)
    return SuccessResponse(
        data=OnboardData(
            user_id=str(current_user.id),
            profile=_profile_to_dto(profile),  # type: ignore[arg-type]
        )
    )


# ── GET /users/me ─────────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.get("/me", response_model=SuccessResponse[MeData], summary="내 정보 조회")
async def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 프로필
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = profile_result.scalar_one_or_none()

    # 최신 체측 (measured_at desc)
    m_result = await db.execute(
        select(UserBodyMeasurement)
        .where(UserBodyMeasurement.user_id == current_user.id)
        .order_by(UserBodyMeasurement.measured_at.desc(), UserBodyMeasurement.created_at.desc())
        .limit(1)
    )
    latest_m = m_result.scalar_one_or_none()

    # 등록 헬스장
    gyms_result = await db.execute(
        select(UserGym, Gym).join(Gym, UserGym.gym_id == Gym.id).where(UserGym.user_id == current_user.id)
    )
    gyms = [GymData(gym_id=str(ug.gym_id), name=g.name, is_primary=ug.is_primary) for ug, g in gyms_result.all()]

    return SuccessResponse(
        data=MeData(
            user_id=str(current_user.id),
            email=current_user.email,
            username=current_user.username,
            name=current_user.name,
            provider=current_user.provider.value if current_user.provider else "local",
            profile=_profile_to_dto(profile),
            latest_measurement=_measurement_to_dto(latest_m),
            gyms=gyms,
        )
    )


# ── PATCH /users/me/body ──────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.patch("/me/body", response_model=SuccessResponse[UpdateBodyData], summary="신체 정보 수정")
async def update_body(
    request: Request,
    body: UpdateBodyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    measurement_dto: BodyMeasurementData | None = None

    # 키는 UserProfile.height_cm에 저장
    if body.height_cm is not None:
        profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
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
@rate_limit("60/minute")
@router.patch("/me/goal", response_model=SuccessResponse[ProfileData], summary="운동 목표 수정")
async def update_goal(
    request: Request,
    body: UpdateGoalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
    profile.default_goals = body.goals or None
    await db.commit()
    return SuccessResponse(data=_profile_to_dto(profile))  # type: ignore[arg-type]


# ── PATCH /users/me/career ────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.patch("/me/career", response_model=SuccessResponse[ProfileData], summary="경력 수정")
async def update_career(
    request: Request,
    body: UpdateCareerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        career = CareerLevel(body.career_level)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 경력 레벨입니다: {body.career_level}") from e

    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = profile_result.scalar_one_or_none()
    if profile is None:
        raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
    profile.career_level = career
    await db.commit()
    return SuccessResponse(data=_profile_to_dto(profile))  # type: ignore[arg-type]


# ── POST /users/me/gym ────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.post("/me/gym", response_model=SuccessResponse[GymData], status_code=201, summary="주 헬스장 등록")
async def add_primary_gym(
    request: Request,
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
@rate_limit("60/minute")
@router.patch("/me/gym", response_model=SuccessResponse[GymData], summary="주 헬스장 변경")
async def change_primary_gym(
    request: Request,
    body: SetPrimaryGymRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_primary_gym(request, body, current_user, db)

# ── 1RM ───────────────────────────────────────────────────────────────────────
def _onerm_to_dto(record: UserExercise1RM, exercise_name: str | None = None) -> OneRMData:
    return OneRMData(
        id=str(record.id),
        exercise_id=str(record.exercise_id),
        exercise_name=exercise_name,
        weight_kg=record.weight_kg,
        source=record.source.value if record.source else "manual",
        estimated_at=record.estimated_at,
    )


@rate_limit("60/minute")
@router.post("/me/1rm", response_model=SuccessResponse[OneRMData], status_code=201, summary="1RM 등록")
async def add_1rm(
    request: Request,
    body: Add1RMRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        exercise_uuid = uuid.UUID(body.exercise_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 exercise_id 형식입니다.") from e

    exercise = (await db.execute(select(Exercise).where(Exercise.id == exercise_uuid))).scalar_one_or_none()
    if exercise is None:
        raise NotFoundError(message="운동을 찾을 수 없습니다.")

    if body.reps is not None and body.reps > 1:
        weight = estimate_1rm(body.weight_kg, body.reps)
        source = OnermSource.EPLEY
    else:
        weight = body.weight_kg
        source = OnermSource.MANUAL

    record = UserExercise1RM(
        user_id=current_user.id,
        exercise_id=exercise_uuid,
        weight_kg=weight,
        source=source,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return SuccessResponse(data=_onerm_to_dto(record, exercise.name))


@rate_limit("60/minute")
@router.patch("/me/1rm", response_model=SuccessResponse[OneRMData], summary="1RM 수정")
async def update_1rm(
    request: Request,
    body: Add1RMRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        exercise_uuid = uuid.UUID(body.exercise_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 exercise_id 형식입니다.") from e

    exercise = (await db.execute(select(Exercise).where(Exercise.id == exercise_uuid))).scalar_one_or_none()
    if exercise is None:
        raise NotFoundError(message="운동을 찾을 수 없습니다.")

    if body.reps is not None and body.reps > 1:
        weight = estimate_1rm(body.weight_kg, body.reps)
        source = OnermSource.EPLEY
    else:
        weight = body.weight_kg
        source = OnermSource.MANUAL

    existing = (
        await db.execute(
            select(UserExercise1RM).where(
                UserExercise1RM.user_id == current_user.id,
                UserExercise1RM.exercise_id == exercise_uuid,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        record = UserExercise1RM(
            user_id=current_user.id,
            exercise_id=exercise_uuid,
            weight_kg=weight,
            source=source,
        )
        db.add(record)
    else:
        existing.weight_kg = weight
        existing.source = source
        existing.estimated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record = existing

    await db.commit()
    await db.refresh(record)

    return SuccessResponse(data=_onerm_to_dto(record, exercise.name))