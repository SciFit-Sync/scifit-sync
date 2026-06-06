"""WorkoutX 운동-중심 루틴 생성 테스트 (재설계 후 계약).

테스트 범위:
  (a) _build_rag_profile — 머신 + 프리웨이트 후보 운동을 available_exercises({name, load_mode})로 생성
  (b) _build_rag_profile — gym_id 있고 후보 0개 → 404 (no_gym_equipments)
  (c) _persist_day — exercise_name → exercise_id/equipment_id/load_mode 해석 (머신/프리 각각) 후 RoutineExercise 저장
  (d) derive_exercise_targets에 전달되는 load_mode가 _resolve_label_to_ids 결과에서 옴을 검증

모든 DB 호출을 AsyncMock으로 대체하여 외부 인프라 없이 실행한다.

운동-중심 계약(WorkoutX 재설계):
  - RagUserProfile.available_exercises = [{"name", "load_mode"}] (이전 available_equipments/source 태그 폐기).
  - LLM 출력 키 exercise_name (이전 equipment_label). "name"은 하위 호환 fallback.
  - _resolve_label_to_ids 반환은 6-tuple
    (equipment_id, exercise_id, load_mode, pulley_ratio, bar_weight, has_weight_assist).
  - 프리웨이트(load_mode ∈ FREEWEIGHT_MODES)는 equipment_id=NULL이 정상(전 헬스장 공통).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.routines import (
    _build_rag_profile,
    _persist_day,
    _resolve_label_to_ids,
)
from app.core.exceptions import NotFoundError
from app.models import CareerLevel
from app.schemas.routines import GenerateRoutineRequest

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_GYM_ID = uuid.uuid4()
_EQ_MACHINE_ID = uuid.uuid4()
_EQ_FREE_ID = uuid.uuid4()
_EX_ID = uuid.uuid4()
_DAY_ID = uuid.uuid4()
_ROUTINE_ID = uuid.uuid4()

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _make_user():
    u = MagicMock()
    u.id = _USER_ID
    return u


def _make_profile_row(career_level=CareerLevel.INTERMEDIATE):
    p = MagicMock()
    p.career_level = career_level
    p.gender = None
    return p


def _make_body_row(weight_kg=72.5):
    bm = MagicMock()
    bm.weight_kg = weight_kg
    return bm


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalars_all(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _exec_all(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _exec_first(row):
    r = MagicMock()
    r.first.return_value = row
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _machine_row(ex_id=None, eq_id=None, name="Cable Fly", load_mode="cable"):
    """_build_rag_profile machine_stmt 결과 행 (exercise_id, name_en, load_mode, equipment_id 컬럼)."""
    r = MagicMock()
    r.exercise_id = ex_id or _EX_ID
    r.name_en = name
    r.load_mode = load_mode
    r.equipment_id = eq_id or _EQ_MACHINE_ID
    return r


def _free_row(ex_id=None, name="Barbell Bench Press", load_mode="barbell"):
    """_build_rag_profile free_stmt 결과 행 (exercise_id, name_en, load_mode 컬럼)."""
    r = MagicMock()
    r.exercise_id = ex_id or _EX_ID
    r.name_en = name
    r.load_mode = load_mode
    return r


# ── (a) _build_rag_profile — 머신 + 프리웨이트 후보 운동 생성 ─────────────────


class TestBuildRagProfileEquipments:
    """gym_id 있을 때 머신과 프리웨이트 운동이 모두 available_exercises에 담긴다."""

    @pytest.mark.asyncio
    async def test_machine_and_free_both_in_available_exercises(self):
        user = _make_user()
        req = GenerateRoutineRequest(
            goals=["hypertrophy"],
            gym_id=str(_GYM_ID),
        )

        machine_row = _machine_row()
        free_row = _free_row(ex_id=uuid.uuid4())  # 다른 운동 (name 중복 제거 방지)

        # DB 쿼리 순서:
        # 1. UserProfile  → scalar_one_or_none
        # 2. UserBodyMeasurement → scalar_one_or_none
        # 3. machine query → .all()
        # 4. free query   → .all()
        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([machine_row]),
            _exec_all([free_row]),
        )

        profile = await _build_rag_profile(user, req, db)

        # 운동-중심: available_exercises = [{"name", "load_mode"}]. source/[MACHINE]/[FREE] 태그 없음.
        assert len(profile.available_exercises) == 2

        names = {e["name"] for e in profile.available_exercises}
        assert "Cable Fly" in names
        assert "Barbell Bench Press" in names

        by_name = {e["name"]: e for e in profile.available_exercises}
        assert by_name["Cable Fly"]["load_mode"] == "cable"
        assert by_name["Barbell Bench Press"]["load_mode"] == "barbell"

    @pytest.mark.asyncio
    async def test_no_gym_id_returns_only_free_exercises(self):
        """gym_id 없으면 전체 DB 프리웨이트 운동만 반환 (머신은 gym 컨텍스트 필수)."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["strength"])  # gym_id 없음

        free_row = _free_row(name="Deadlift", load_mode="barbell")

        # gym_id 없으므로 머신 쿼리 없음, 프리웨이트 전체 fallback만
        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([free_row]),  # fb_free fallback
        )

        profile = await _build_rag_profile(user, req, db)

        assert len(profile.available_exercises) == 1
        assert profile.available_exercises[0]["name"] == "Deadlift"
        # 프리웨이트 load_mode만 (머신 cable/machine 없음)
        load_modes = {e["load_mode"] for e in profile.available_exercises}
        assert "cable" not in load_modes
        assert "machine" not in load_modes
        assert "barbell" in load_modes

    @pytest.mark.asyncio
    async def test_fitness_career_passed_correctly(self):
        """profile.fitness_career가 CareerLevel 값으로 정확히 전달된다."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["hypertrophy"], gym_id=str(_GYM_ID))

        db = _make_db(
            _exec_scalar(_make_profile_row(CareerLevel.ADVANCED)),
            _exec_scalar(_make_body_row()),
            _exec_all([_machine_row()]),
            _exec_all([_free_row(ex_id=uuid.uuid4())]),
        )

        profile = await _build_rag_profile(user, req, db)

        assert "advanced" in str(profile.fitness_career).lower()


# ── (b) gym_id 있고 후보 0개 → 404 ───────────────────────────────────────────


class TestBuildRagProfileNoEquipments:
    """gym_id 지정 후 머신/프리웨이트 운동 모두 0개면 NotFoundError(no_gym_equipments)."""

    @pytest.mark.asyncio
    async def test_empty_gym_equipments_raises_not_found(self):
        user = _make_user()
        req = GenerateRoutineRequest(
            goals=["hypertrophy"],
            gym_id=str(_GYM_ID),
        )

        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([]),  # 머신 운동 0개
            _exec_all([]),  # 프리 운동 0개
        )

        with pytest.raises(NotFoundError) as exc_info:
            await _build_rag_profile(user, req, db)

        err = exc_info.value
        assert err.details.get("reason") == "no_gym_equipments"
        assert err.details.get("gym_id") == str(_GYM_ID)

    @pytest.mark.asyncio
    async def test_only_free_but_no_machine_does_not_raise(self):
        """머신 운동 0개여도 프리웨이트 운동이 있으면 정상 반환 (404 없음)."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["hypertrophy"], gym_id=str(_GYM_ID))

        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([]),  # 머신 0개
            _exec_all([_free_row()]),  # 프리 1개
        )

        profile = await _build_rag_profile(user, req, db)
        assert len(profile.available_exercises) == 1
        assert profile.available_exercises[0]["name"] == "Barbell Bench Press"
        assert profile.available_exercises[0]["load_mode"] == "barbell"


# ── (c) _persist_day — exercise_name 해석 후 RoutineExercise 저장 ─────────────


class TestPersistDay:
    """_persist_day가 exercise_name을 _resolve_label_to_ids로 해석하여 RoutineExercise를 저장."""

    def _make_day_data(self, label: str, source_key: str = "exercise_name") -> dict:
        return {
            "day": 1,
            "focus": "Chest",
            "exercises": [
                {
                    source_key: label,
                    "sets": 3,
                    "reps_min": 8,
                    "reps_max": 12,
                    "rest_seconds": 90,
                    "notes": "근거 기반 선택",
                    "paper_index": 1,
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_machine_label_resolved_and_saved(self):
        """머신 exercise_name → (equipment_id, exercise_id, load_mode) 해석 후 RoutineExercise에 저장."""
        day_data = self._make_day_data("Cable Fly")

        # _resolve_label_to_ids 내부의 DB 쿼리를 patch로 대체
        eq_id = _EQ_MACHINE_ID
        ex_id = _EX_ID
        load_mode = "cable"

        # 6-tuple: (equipment_id, exercise_id, load_mode, pulley_ratio, bar_weight, has_weight_assist)
        async def fake_resolve(label, gym_id, db, *, chosen_equipment_id=None):
            return eq_id, ex_id, load_mode, 0.5, None, False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with (
            patch("app.api.v1.routines._resolve_label_to_ids", side_effect=fake_resolve),
            patch("app.api.v1.routines.derive_exercise_targets") as mock_targets,
        ):
            mock_targets.return_value = {
                "sets": 3,
                "reps_min": 8,
                "reps_max": 12,
                "weight_kg": 50.0,
                "rest_seconds": 90,
            }
            day, rex_pairs, dropped = await _persist_day(
                routine_id=_ROUTINE_ID,
                day_data=day_data,
                primary_goal="hypertrophy",
                user_1rms={},
                user_body_weight=72.5,
                user_gender=None,
                user_career_level="intermediate",
                gym_id=_GYM_ID,
                db=db,
            )

        assert len(rex_pairs) == 1
        rex, paper_index = rex_pairs[0]
        assert rex.exercise_id == ex_id
        assert rex.equipment_id == eq_id
        assert rex.display_name == "Cable Fly"
        assert paper_index == 1

        # derive_exercise_targets에 load_mode가 올바르게 전달됐는지
        mock_targets.assert_called_once()
        call_kwargs = mock_targets.call_args.kwargs
        assert call_kwargs["load_mode"] == load_mode
        assert call_kwargs["pulley_ratio"] == 0.5

    @pytest.mark.asyncio
    async def test_free_weight_label_resolved_and_saved(self):
        """프리웨이트 exercise_name → exercise_id 해석, equipment_id=NULL 정상 저장."""
        day_data = self._make_day_data("Barbell Bench Press")

        ex_id = _EX_ID
        load_mode = "barbell"

        # 프리웨이트: equipment_id=None(전 헬스장 공통), bar_weight는 load_calc 모듈상수 사용 → None
        async def fake_resolve(label, gym_id, db, *, chosen_equipment_id=None):
            return None, ex_id, load_mode, 1.0, None, False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with (
            patch("app.api.v1.routines._resolve_label_to_ids", side_effect=fake_resolve),
            patch("app.api.v1.routines.derive_exercise_targets") as mock_targets,
        ):
            mock_targets.return_value = {
                "sets": 3,
                "reps_min": 4,
                "reps_max": 6,
                "weight_kg": 80.0,
                "rest_seconds": 180,
            }
            _, rex_pairs, _ = await _persist_day(
                routine_id=_ROUTINE_ID,
                day_data=day_data,
                primary_goal="strength",
                user_1rms={_EX_ID: 100.0},
                user_body_weight=80.0,
                user_gender="male",
                user_career_level="advanced",
                gym_id=None,
                db=db,
            )

        assert len(rex_pairs) == 1
        rex, _ = rex_pairs[0]
        assert rex.exercise_id == ex_id
        # 프리웨이트는 equipment_id=NULL이 정상 (전 헬스장 공통, D7)
        assert rex.equipment_id is None
        assert rex.display_name == "Barbell Bench Press"

        call_kwargs = mock_targets.call_args.kwargs
        assert call_kwargs["load_mode"] == "barbell"
        assert call_kwargs["user_1rm_kg"] == 100.0

    @pytest.mark.asyncio
    async def test_unresolved_label_excluded_from_results(self):
        """exercise_id 해석 실패(None) 시 해당 운동은 제외 (dropped 처리)."""
        day_data = self._make_day_data("UnknownMachine X9000")

        async def fake_resolve_none(label, gym_id, db, *, chosen_equipment_id=None):
            return None, None, None, 1.0, None, False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch("app.api.v1.routines._resolve_label_to_ids", side_effect=fake_resolve_none):
            _, rex_pairs, _ = await _persist_day(
                routine_id=_ROUTINE_ID,
                day_data=day_data,
                primary_goal="hypertrophy",
                user_1rms={},
                user_body_weight=70.0,
                user_gender=None,
                user_career_level=None,
                gym_id=None,
                db=db,
            )

        assert rex_pairs == []

    @pytest.mark.asyncio
    async def test_unresolved_machine_equipment_excluded_from_results(self):
        """머신 운동인데 가용 기구 0개(equipment_id=None & load_mode∈MACHINE_MODES)면 부하 기준이 없어 제외."""
        day_data = self._make_day_data("Some Machine Exercise")

        # 운동은 해석됐으나 머신 기구 후보 0개 → equipment_id=None, load_mode='machine'
        async def fake_resolve_no_equip(label, gym_id, db, *, chosen_equipment_id=None):
            return None, _EX_ID, "machine", 1.0, None, False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with (
            patch("app.api.v1.routines._resolve_label_to_ids", side_effect=fake_resolve_no_equip),
            patch("app.api.v1.routines.derive_exercise_targets") as mock_targets,
        ):
            _, rex_pairs, _ = await _persist_day(
                routine_id=_ROUTINE_ID,
                day_data=day_data,
                primary_goal="hypertrophy",
                user_1rms={},
                user_body_weight=70.0,
                user_gender=None,
                user_career_level=None,
                gym_id=_GYM_ID,
                db=db,
            )

        assert rex_pairs == []
        # 머신 eq_id None 가드는 derive_exercise_targets 호출 전에 continue → 타겟 계산도 안 됨
        mock_targets.assert_not_called()

    @pytest.mark.asyncio
    async def test_name_fallback_used_when_no_exercise_name(self):
        """'name' 키만 있는 LLM 출력(하위 호환)도 exercise_name처럼 해석된다."""
        day_data = {
            "day": 1,
            "focus": "Back",
            "exercises": [
                {
                    "name": "Pull-Up",  # 구버전 LLM 출력 (exercise_name 없음)
                    "sets": 3,
                    "reps_min": 6,
                    "reps_max": 10,
                    "rest_seconds": 90,
                }
            ],
        }

        async def fake_resolve(label, gym_id, db, *, chosen_equipment_id=None):
            assert label == "Pull-Up"
            # 맨몸 운동: equipment_id=None(전 헬스장 공통)
            return None, _EX_ID, "bodyweight", 1.0, None, False

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        with (
            patch("app.api.v1.routines._resolve_label_to_ids", side_effect=fake_resolve),
            patch("app.api.v1.routines.derive_exercise_targets") as mock_targets,
        ):
            mock_targets.return_value = {
                "sets": 3,
                "reps_min": 6,
                "reps_max": 10,
                "weight_kg": None,
                "rest_seconds": 90,
            }
            _, rex_pairs, _ = await _persist_day(
                routine_id=_ROUTINE_ID,
                day_data=day_data,
                primary_goal="endurance",
                user_1rms={},
                user_body_weight=70.0,
                user_gender=None,
                user_career_level=None,
                gym_id=None,
                db=db,
            )

        assert len(rex_pairs) == 1
        rex, _ = rex_pairs[0]
        assert rex.display_name == "Pull-Up"
        # bodyweight는 프리웨이트 계열 → equipment_id=NULL 정상
        assert rex.equipment_id is None


# ── (d) _resolve_label_to_ids 단위 테스트 ─────────────────────────────────────


class TestResolveLabelToIds:
    """_resolve_label_to_ids의 운동(name_en)→머신/프리웨이트 해석 경로를 직접 단위 테스트.

    반환은 6-tuple: (equipment_id, exercise_id, load_mode, pulley_ratio, bar_weight, has_weight_assist).
    """

    @pytest.mark.asyncio
    async def test_machine_path_returns_equipment_and_exercise(self):
        """name_en 매치(load_mode=cable) → exercise_equipment ⋈ gym_equipments에서 equipment 선택."""
        eq_id = _EQ_MACHINE_ID
        ex_id = _EX_ID

        # 1) Exercise(id, load_mode) by name_en
        ex_row = MagicMock()
        ex_row.id = ex_id
        ex_row.load_mode = "cable"

        # 2) ExerciseEquipment.equipment_id pick (gym_equipments 정션) — first()는 (equipment_id,) 튜플
        pick_row = (eq_id,)

        # 3) Equipment(pulley_ratio, bar_weight, has_weight_assist)
        eq_row = MagicMock()
        eq_row.pulley_ratio = 0.5
        eq_row.bar_weight = None
        eq_row.has_weight_assist = False

        db = _make_db(
            _exec_first(ex_row),  # Exercise(id, load_mode) by name_en
            _exec_first(pick_row),  # ExerciseEquipment.equipment_id pick
            _exec_first(eq_row),  # Equipment 부하 파라미터
        )

        result_eq_id, result_ex_id, load_mode, pulley, bar, assist = await _resolve_label_to_ids(
            "Cable Fly", _GYM_ID, db
        )

        assert result_eq_id == eq_id
        assert result_ex_id == ex_id
        assert load_mode == "cable"
        assert pulley == 0.5
        assert bar is None
        assert assist is False

    @pytest.mark.asyncio
    async def test_free_weight_path_returns_null_equipment(self):
        """name_en 매치(load_mode=barbell) → 프리웨이트: equipment_id=NULL, 단일 쿼리로 종료."""
        ex_id = _EX_ID

        ex_row = MagicMock()
        ex_row.id = ex_id
        ex_row.load_mode = "barbell"

        # 프리웨이트는 Exercise 조회 1회로 끝 (머신 정션/Equipment 조회 없음)
        db = _make_db(
            _exec_first(ex_row),  # Exercise(id, load_mode) by name_en
        )

        result_eq_id, result_ex_id, load_mode, pulley, bar, assist = await _resolve_label_to_ids(
            "Barbell Bench Press", None, db
        )

        assert result_ex_id == ex_id
        # 프리웨이트 → equipment_id=NULL(전 헬스장 공통)
        assert result_eq_id is None
        assert load_mode == "barbell"
        assert pulley == 1.0
        assert bar is None
        assert assist is False

    @pytest.mark.asyncio
    async def test_machine_no_gym_equipment_returns_null_equipment(self):
        """머신 운동이나 gym 보유 기구 0개 → equipment_id=None(호출부에서 제외), exercise_id는 유효."""
        ex_id = _EX_ID

        ex_row = MagicMock()
        ex_row.id = ex_id
        ex_row.load_mode = "machine"

        db = _make_db(
            _exec_first(ex_row),  # Exercise(id, load_mode) by name_en
            _exec_first(None),  # ExerciseEquipment pick → 없음 (gym 보유분 0)
        )

        result_eq_id, result_ex_id, load_mode, pulley, bar, assist = await _resolve_label_to_ids(
            "Lat Pulldown", _GYM_ID, db
        )

        assert result_ex_id == ex_id
        assert result_eq_id is None
        assert load_mode == "machine"

    @pytest.mark.asyncio
    async def test_exercise_not_found_returns_none_ids(self):
        """name_en 정확 매칭 실패 → (None, None, None, ...). fuzzy fallback 비활성."""
        db = _make_db(
            _exec_first(None),  # Exercise(id, load_mode) → None (운동 미매치)
        )

        result = await _resolve_label_to_ids("CompletelyUnknownExercise", None, db)

        eq_id, ex_id, load_mode, pulley, bar, assist = result
        assert eq_id is None
        assert ex_id is None
        assert load_mode is None
