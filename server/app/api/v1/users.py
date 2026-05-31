"""사용자 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #9-17, #43, #50.
"""

import logging
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    GymEquipment,
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
    CoreLift1RMItem,
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
        default_goals=[g.lower() for g in profile.default_goals] if profile.default_goals else None,
        career_level=profile.career_level.value if profile.career_level else None,
        career_years=profile.career_years,
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
@router.post(
    "/me/onboard",
    response_model=SuccessResponse[OnboardData],
    status_code=201,
    summary="온보딩 완료 (최초 신체정보 등록)",
)
@rate_limit("60/minute")
async def onboard(
    request: Request,
    body: OnboardRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """회원가입 또는 재가입 직후 W-A03 화면에서 호출. 기존 프로필이 있으면 덮어씀(재가입 대응)."""
    existing = (
        await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    ).scalar_one_or_none()

    try:
        career = CareerLevel(body.career_level)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 경력 레벨입니다: {body.career_level}") from e

    try:
        gender = Gender(body.gender)
    except ValueError as e:
        raise ValidationError(message=f"알 수 없는 성별 값입니다: {body.gender}") from e

    if existing is not None:
        # 재가입(탈퇴 후 재활성화): 기존 프로필 업데이트
        existing.gender = gender
        existing.birth_date = body.birth_date
        existing.height_cm = body.height_cm
        existing.career_level = career
        existing.career_years = body.career_years
        existing.default_goals = body.default_goals or None
        profile = existing
    else:
        profile = UserProfile(
            user_id=current_user.id,
            gender=gender,
            birth_date=body.birth_date,
            height_cm=body.height_cm,
            career_level=career,
            career_years=body.career_years,
            default_goals=body.default_goals or None,
        )
        db.add(profile)

    # 체중 측정값 추가 (재가입 포함 매번 기록)
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
@router.get("/me", response_model=SuccessResponse[MeData], summary="내 정보 조회")
@rate_limit("60/minute")
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

    # 4대 운동 1RM (마이페이지 카드용)
    from app.services.core_lifts import CORE_LIFTS_KO_LABEL, resolve_exercise_id_by_code

    core_lifts_1rm: list[CoreLift1RMItem] = []
    for code, label in CORE_LIFTS_KO_LABEL.items():
        ex_id = await resolve_exercise_id_by_code(code, db)
        if ex_id is None:
            core_lifts_1rm.append(CoreLift1RMItem(code=code, name=label, weight_kg=None))
            continue
        row = (
            await db.execute(
                select(UserExercise1RM.weight_kg)
                .where(UserExercise1RM.user_id == current_user.id, UserExercise1RM.exercise_id == ex_id)
                .order_by(UserExercise1RM.estimated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        core_lifts_1rm.append(CoreLift1RMItem(code=code, name=label, weight_kg=float(row) if row else None))

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
            core_lifts_1rm=core_lifts_1rm,
        )
    )


# ── PATCH /users/me/body ──────────────────────────────────────────────────────
@router.patch("/me/body", response_model=SuccessResponse[UpdateBodyData], summary="신체 정보 수정")
@rate_limit("60/minute")
async def update_body(
    request: Request,
    body: UpdateBodyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    measurement_dto: BodyMeasurementData | None = None
    updated_birth_date: date | None = None
    updated_gender: str | None = None

    # UserProfile 갱신 (키 / 생년월일 / 성별)
    needs_profile_update = any(v is not None for v in (body.height_cm, body.birth_date, body.gender))
    if needs_profile_update:
        profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
        if body.height_cm is not None:
            profile.height_cm = body.height_cm
        if body.birth_date is not None:
            profile.birth_date = body.birth_date
            updated_birth_date = body.birth_date
        if body.gender is not None:
            profile.gender = Gender(body.gender)
            updated_gender = body.gender

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

    # 수정 후 전체 현재값 반환 (프론트 화면 갱신용)
    profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
    profile = profile_result.scalar_one_or_none()
    return SuccessResponse(
        data=UpdateBodyData(
            height_cm=profile.height_cm if profile else body.height_cm,
            birth_date=profile.birth_date if profile else updated_birth_date,
            age=_calc_age(profile.birth_date) if profile else None,
            gender=profile.gender.value if profile and profile.gender else updated_gender,
            measurement=measurement_dto,
        )
    )


# ── PATCH /users/me/goal ──────────────────────────────────────────────────────
@router.patch("/me/goal", response_model=SuccessResponse[ProfileData], summary="운동 목표 수정")
@rate_limit("60/minute")
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
@router.patch("/me/career", response_model=SuccessResponse[ProfileData], summary="경력 수정")
@rate_limit("60/minute")
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
    if body.career_years is not None:
        profile.career_years = body.career_years
    await db.commit()
    return SuccessResponse(data=_profile_to_dto(profile))  # type: ignore[arg-type]


# ── POST /users/me/gym ────────────────────────────────────────────────────────
@router.post("/me/gym", response_model=SuccessResponse[GymData], status_code=201, summary="주 헬스장 등록")
@rate_limit("60/minute")
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
@router.patch("/me/gym", response_model=SuccessResponse[GymData], summary="주 헬스장 변경")
@rate_limit("60/minute")
async def change_primary_gym(
    request: Request,
    body: SetPrimaryGymRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await add_primary_gym(request, body, current_user, db)


# ── equipment DTO ─────────────────────────────────────────────────────────────
def _equipment_to_dto(e: Equipment) -> UserEquipmentItem:
    return UserEquipmentItem(
        equipment_id=str(e.id),
        name=e.name,
        category=e.category.value if e.category else None,
        equipment_type=e.equipment_type.value if e.equipment_type else "machine",
        pulley_ratio=e.pulley_ratio,
        bar_weight=e.bar_weight,
        image_url=e.image_url,
    )


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


@router.post("/me/1rm", response_model=SuccessResponse[OneRMData], status_code=201, summary="1RM 등록")
@rate_limit("60/minute")
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


@router.patch("/me/1rm", response_model=SuccessResponse[OneRMData], summary="1RM 수정")
@rate_limit("60/minute")
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


# ── POST /users/me/1rm/bulk ─────────────────────────────────────────────────
@router.post(
    "/me/1rm/bulk",
    response_model=SuccessResponse[BulkOneRMData],
    status_code=201,
    summary="1RM 일괄 등록 (온보딩용)",
)
@rate_limit("60/minute")
async def bulk_add_1rm(
    request: Request,
    body: BulkAdd1RMRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """온보딩 1RM 설정 화면(W-A04)에서 벤치/스쿼트/데드/OHP 등을 한번에 등록한다.

    각 item 은 `exercise_id` 또는 `exercise_code` 중 하나 필수.
    code 매핑은 services.core_lifts.CORE_LIFTS_NAME_EN_MAP 참고.
    """
    from app.services.core_lifts import resolve_exercise_id_by_code

    created: list[tuple[UserExercise1RM, str]] = []

    for item in body.items:
        # exercise_id 결정
        if item.exercise_id:
            try:
                ex_uuid = uuid.UUID(item.exercise_id)
            except ValueError as e:
                raise ValidationError(message=f"잘못된 exercise_id 형식입니다: {item.exercise_id}") from e
        elif item.exercise_code:
            ex_uuid = await resolve_exercise_id_by_code(item.exercise_code, db)
            if ex_uuid is None:
                raise NotFoundError(
                    message=f"운동을 찾을 수 없습니다 (code={item.exercise_code}). "
                    "GET /exercises/core-lifts 로 사용 가능한 code 확인."
                )
        else:
            raise ValidationError(message="exercise_id 또는 exercise_code 중 하나는 필수입니다.")

        exercise = (await db.execute(select(Exercise).where(Exercise.id == ex_uuid))).scalar_one_or_none()
        if exercise is None:
            raise NotFoundError(message=f"운동을 찾을 수 없습니다: {ex_uuid}")

        # reps 있으면 Epley, 없으면 manual
        if item.reps is not None and item.reps > 1:
            weight = estimate_1rm(item.weight_kg, item.reps)
            source = OnermSource.EPLEY
        else:
            weight = item.weight_kg
            source = OnermSource.MANUAL

        record = UserExercise1RM(
            user_id=current_user.id,
            exercise_id=ex_uuid,
            weight_kg=weight,
            source=source,
        )
        db.add(record)
        created.append((record, exercise.name))

    await db.commit()
    for record, _ in created:
        await db.refresh(record)

    return SuccessResponse(
        data=BulkOneRMData(
            items=[_onerm_to_dto(rec, name) for rec, name in created],
            count=len(created),
        )
    )


@router.get("/me/1rm", response_model=SuccessResponse[OneRMListData], summary="내 1RM 목록")
@rate_limit("60/minute")
async def list_1rms(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserExercise1RM, Exercise.name)
        .join(Exercise, UserExercise1RM.exercise_id == Exercise.id)
        .where(UserExercise1RM.user_id == current_user.id)
        .order_by(UserExercise1RM.estimated_at.desc())
    )
    items = [_onerm_to_dto(rec, name) for rec, name in result.all()]
    return SuccessResponse(data=OneRMListData(items=items))


# ── /users/me/equipment ───────────────────────────────────────────────────────
@router.get("/me/equipment", response_model=SuccessResponse[UserEquipmentListData], summary="내 보유 장비")
@rate_limit("60/minute")
async def list_my_equipment(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_gym = (
        await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True)))
    ).scalar_one_or_none()
    if user_gym is None:
        return SuccessResponse(data=UserEquipmentListData(items=[]))

    gym = (await db.execute(select(Gym).where(Gym.id == user_gym.gym_id))).scalar_one_or_none()
    if gym is None or not gym.gym_equipments:
        return SuccessResponse(data=UserEquipmentListData(items=[]))

    equipment_ids = [ge.equipment_id for ge in gym.gym_equipments]
    equipments = (await db.execute(select(Equipment).where(Equipment.id.in_(equipment_ids)))).scalars().all()

    return SuccessResponse(data=UserEquipmentListData(items=[_equipment_to_dto(e) for e in equipments]))


@router.post(
    "/me/equipment",
    response_model=SuccessResponse[UserEquipmentItem],
    status_code=201,
    summary="장비 추가 (스폿)",
)
@rate_limit("60/minute")
async def add_my_equipment(
    request: Request,
    body: AddUserEquipmentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        equipment_uuid = uuid.UUID(body.equipment_id)
    except ValueError as e:
        raise ValidationError(message="잘못된 equipment_id 형식입니다.") from e

    equipment = (await db.execute(select(Equipment).where(Equipment.id == equipment_uuid))).scalar_one_or_none()
    if equipment is None:
        raise NotFoundError(message="장비를 찾을 수 없습니다.")

    user_gym = (
        await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True)))
    ).scalar_one_or_none()
    if user_gym is None:
        raise ValidationError(message="주 헬스장을 먼저 등록해주세요.")

    existing = (
        await db.execute(
            select(GymEquipment).where(
                GymEquipment.gym_id == user_gym.gym_id,
                GymEquipment.equipment_id == equipment_uuid,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(message="이미 등록된 장비입니다.")

    db.add(GymEquipment(gym_id=user_gym.gym_id, equipment_id=equipment_uuid))
    await db.commit()

    return SuccessResponse(data=_equipment_to_dto(equipment))
