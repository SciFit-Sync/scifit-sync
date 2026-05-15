  # <<<<<<< 마커 전체 지우고 아래만 남기기

  # ── POST /users/me/1rm/bulk ─────────────────────────────────────────────────
  @router.post(
      "/me/1rm/bulk",
      response_model=SuccessResponse[BulkOneRMData],
      status_code=201,
      summary="1RM 일괄 등록 (온보딩용)",
  )
  async def bulk_add_1rm(...):
      ...  # 현재 브랜치 코드 그대로

  @router.get("/me/1rm", response_model=SuccessResponse[OneRMListData], summary="내 1RM 목록")
  async def list_1rms(
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

  즉, 충돌 구간에서 >>>>>>> develop 쪽 (get_1rm + _BIG_LIFT_MAP body) 전부 버리고, <<<<<<< feat/yebin/onboarding 쪽만
  남기면 됩니다. 현재 원격 브랜치 코드가 이미 이 형태라 로컬에서 conflict marker만 정리하면 끝납니다.

✻ Baked for 4m 37s

> 그냥 코드 복붙하고시픈데 여기에 적어주면 안돼?? 이해를 못하겟더

● 파일 전체를 읽어서 완성본을 드릴게요.

  Read 1 file (ctrl+o to expand)

● 이게 충돌 해결된 완성본입니다. 그냥 파일 전체 교체하면 됩니다:

  """사용자 도메인 엔드포인트.

  CLAUDE.md / api-endpoints.md #9-17, #43, #50.
  """

  import logging
  import uuid
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
      Add1RMRequest,
      AddUserEquipmentRequest,
      BodyMeasurementData,
      BulkAdd1RMRequest,
      BulkOneRMData,
      GymData,
      MeData,
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
      profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
      profile = profile_result.scalar_one_or_none()

      m_result = await db.execute(
          select(UserBodyMeasurement)
          .where(UserBodyMeasurement.user_id == current_user.id)
          .order_by(UserBodyMeasurement.measured_at.desc(), UserBodyMeasurement.created_at.desc())
          .limit(1)
      )
      latest_m = m_result.scalar_one_or_none()

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
  @router.patch("/me/body", response_model=SuccessResponse[UpdateBodyData], summary="신체 정보 수정")
  async def update_body(
      body: UpdateBodyRequest,
      current_user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db),
  ):
      measurement_dto: BodyMeasurementData | None = None

      if body.height_cm is not None:
          profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
          profile = profile_result.scalar_one_or_none()
          if profile is None:
              raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
          profile.height_cm = body.height_cm

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
      profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == current_user.id))
      profile = profile_result.scalar_one_or_none()
      if profile is None:
          raise ValidationError(message="프로필이 존재하지 않습니다. 먼저 온보딩을 완료해주세요.")
      profile.default_goals = body.goals or None
      await db.commit()
      return SuccessResponse(data=_profile_to_dto(profile))  # type: ignore[arg-type]


  # ── PATCH /users/me/career ────────────────────────────────────────────────────
  @router.patch("/me/career", response_model=SuccessResponse[ProfileData], summary="경력 수정")
  async def update_career(
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

      existing = (
          (await db.execute(select(UserGym).where(UserGym.user_id == current_user.id, UserGym.is_primary.is_(True))))
          .scalars()
          .all()
      )
      for ug in existing:
          ug.is_primary = False

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


  @router.post("/me/1rm", response_model=SuccessResponse[OneRMData], status_code=201, summary="1RM 추가")
  async def add_1rm(
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
  async def update_1rm(
      body: Add1RMRequest,
      current_user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db),
  ):
      return await add_1rm(body, current_user, db)


  # ── POST /users/me/1rm/bulk ─────────────────────────────────────────────────
  @router.post(
      "/me/1rm/bulk",
      response_model=SuccessResponse[BulkOneRMData],
      status_code=201,
      summary="1RM 일괄 등록 (온보딩용)",
  )
  async def bulk_add_1rm(
      body: BulkAdd1RMRequest,
      current_user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db),
  ):
      from app.services.core_lifts import resolve_exercise_id_by_code

      created: list[tuple[UserExercise1RM, str]] = []

      for item in body.items:
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

      items = [_onerm_to_dto(rec, name) for rec, name in created]
      return SuccessResponse(data=BulkOneRMData(items=items, created_count=len(items)))


  @router.get("/me/1rm", response_model=SuccessResponse[OneRMListData], summary="내 1RM 목록")
  async def list_1rms(
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