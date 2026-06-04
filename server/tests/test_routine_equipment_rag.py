"""PR-3 기구 중심 루틴 생성 테스트.

테스트 범위:
  (a) _build_rag_profile — 머신 + 프리웨이트 후보 생성
  (b) _build_rag_profile — gym_id 있고 후보 0개 → 404 (no_gym_equipments)
  (c) _persist_day — equipment_label → equipment_id/exercise_id 해석 (머신/프리 각각) 후 RoutineExercise 저장
  (d) derive_exercise_targets에 전달되는 equipment_type이 _resolve_label_to_ids 결과에서 옴을 검증

모든 DB 호출을 AsyncMock으로 대체하여 외부 인프라 없이 실행한다.
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


def _machine_row(eq_id=None, label="Cable Fly", eq_type="cable"):
    r = MagicMock()
    r.id = eq_id or _EQ_MACHINE_ID
    r.movement_label_en = label
    r.name_en = label
    r.name = label
    r.equipment_type = eq_type
    return r


def _free_row(ex_id=None, eq_id=None, label="Barbell Bench Press", eq_type="barbell"):
    r = MagicMock()
    r.exercise_id = ex_id or _EX_ID
    r.exercise_name_en = label
    r.equipment_id = eq_id or _EQ_FREE_ID
    r.equipment_type = eq_type
    return r


# ── (a) _build_rag_profile — 머신 + 프리웨이트 후보 생성 ──────────────────────


class TestBuildRagProfileEquipments:
    """gym_id 있을 때 머신과 프리웨이트 후보가 모두 available_equipments에 담긴다."""

    @pytest.mark.asyncio
    async def test_machine_and_free_both_in_available_equipments(self):
        user = _make_user()
        req = GenerateRoutineRequest(
            goals=["hypertrophy"],
            gym_id=str(_GYM_ID),
        )

        machine_row = _machine_row()
        free_row = _free_row()

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

        assert len(profile.available_equipments) == 2

        machine_items = [e for e in profile.available_equipments if e["source"] == "MACHINE"]
        free_items = [e for e in profile.available_equipments if e["source"] == "FREE"]

        assert len(machine_items) == 1
        assert machine_items[0]["label"] == "Cable Fly"
        assert machine_items[0]["equipment_type"] == "cable"

        assert len(free_items) == 1
        assert free_items[0]["label"] == "Barbell Bench Press"
        assert free_items[0]["equipment_type"] == "barbell"

    @pytest.mark.asyncio
    async def test_no_gym_id_returns_only_free_equipments(self):
        """gym_id 없으면 전체 DB 프리웨이트만 반환."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["strength"])  # gym_id 없음

        free_row = _free_row(label="Deadlift", eq_type="barbell")

        # gym_id 없으므로 머신 쿼리 없음, 프리웨이트 전체 fallback만
        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([free_row]),  # fb_free fallback
        )

        profile = await _build_rag_profile(user, req, db)

        sources = {e["source"] for e in profile.available_equipments}
        assert "MACHINE" not in sources
        assert "FREE" in sources

    @pytest.mark.asyncio
    async def test_fitness_career_passed_correctly(self):
        """profile.fitness_career가 CareerLevel 값으로 정확히 전달된다."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["hypertrophy"], gym_id=str(_GYM_ID))

        db = _make_db(
            _exec_scalar(_make_profile_row(CareerLevel.ADVANCED)),
            _exec_scalar(_make_body_row()),
            _exec_all([_machine_row()]),
            _exec_all([_free_row()]),
        )

        profile = await _build_rag_profile(user, req, db)

        assert "advanced" in str(profile.fitness_career).lower()


# ── (b) gym_id 있고 후보 0개 → 404 ───────────────────────────────────────────


class TestBuildRagProfileNoEquipments:
    """gym_id 지정 후 머신/프리웨이트 모두 0개면 NotFoundError(no_gym_equipments)."""

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
            _exec_all([]),  # 머신 0개
            _exec_all([]),  # 프리 0개
        )

        with pytest.raises(NotFoundError) as exc_info:
            await _build_rag_profile(user, req, db)

        err = exc_info.value
        assert err.details.get("reason") == "no_gym_equipments"
        assert err.details.get("gym_id") == str(_GYM_ID)

    @pytest.mark.asyncio
    async def test_only_free_but_no_machine_does_not_raise(self):
        """머신 0개여도 프리웨이트가 있으면 정상 반환 (404 없음)."""
        user = _make_user()
        req = GenerateRoutineRequest(goals=["hypertrophy"], gym_id=str(_GYM_ID))

        db = _make_db(
            _exec_scalar(_make_profile_row()),
            _exec_scalar(_make_body_row()),
            _exec_all([]),  # 머신 0개
            _exec_all([_free_row()]),  # 프리 1개
        )

        profile = await _build_rag_profile(user, req, db)
        assert len(profile.available_equipments) == 1
        assert profile.available_equipments[0]["source"] == "FREE"


# ── (c) _persist_day — label 해석 후 RoutineExercise 저장 ────────────────────


class TestPersistDay:
    """_persist_day가 equipment_label을 _resolve_label_to_ids로 해석하여 RoutineExercise를 저장."""

    def _make_day_data(self, label: str, source_key: str = "equipment_label") -> dict:
        return {
            "day": 1,
            "focus": "Chest",
            "exercises": [
                {
                    source_key: label,
                    "equipment_type": "cable",
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
        """머신 label → (equipment_id, exercise_id) 해석 후 RoutineExercise에 저장."""
        day_data = self._make_day_data("Cable Fly")

        # _resolve_label_to_ids 내부의 DB 쿼리를 patch로 대체
        eq_id = _EQ_MACHINE_ID
        ex_id = _EX_ID
        eq_type = "cable"

        async def fake_resolve(label, gym_id, db):
            return eq_id, ex_id, eq_type, 1.0, None

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

        # derive_exercise_targets에 equipment_type이 올바르게 전달됐는지
        mock_targets.assert_called_once()
        call_kwargs = mock_targets.call_args.kwargs
        assert call_kwargs["equipment_type"] == eq_type

    @pytest.mark.asyncio
    async def test_free_weight_label_resolved_and_saved(self):
        """프리웨이트 label → (equipment_id, exercise_id) 해석 후 RoutineExercise에 저장."""
        day_data = self._make_day_data("Barbell Bench Press")

        eq_id = _EQ_FREE_ID
        ex_id = _EX_ID
        eq_type = "barbell"

        async def fake_resolve(label, gym_id, db):
            return eq_id, ex_id, eq_type, 1.0, 20.0

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
        assert rex.equipment_id == eq_id
        assert rex.display_name == "Barbell Bench Press"

        call_kwargs = mock_targets.call_args.kwargs
        assert call_kwargs["equipment_type"] == "barbell"
        assert call_kwargs["bar_weight"] == 20.0
        assert call_kwargs["user_1rm_kg"] == 100.0

    @pytest.mark.asyncio
    async def test_unresolved_label_excluded_from_results(self):
        """exercise_id 해석 실패(None) 시 해당 운동은 제외 (dropped 처리)."""
        day_data = self._make_day_data("UnknownMachine X9000")

        async def fake_resolve_none(label, gym_id, db):
            return None, None, None, 1.0, None

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
    async def test_unresolved_equipment_excluded_from_results(self):
        """PR-4: exercise_id는 해석됐으나 equipment_id=None이면 equipment_id NOT NULL 위반을 피하기 위해 제외."""
        day_data = self._make_day_data("Some Free Exercise")

        async def fake_resolve_no_equip(label, gym_id, db):
            return None, _EX_ID, None, 1.0, None  # 운동은 있으나 기구 해석 실패

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
        # eq_id None 가드는 derive_exercise_targets 호출 전에 continue → 타겟 계산도 안 됨
        mock_targets.assert_not_called()

    @pytest.mark.asyncio
    async def test_name_fallback_used_when_no_equipment_label(self):
        """'name' 키만 있는 LLM 출력(하위 호환)도 equipment_label처럼 해석된다."""
        day_data = {
            "day": 1,
            "focus": "Back",
            "exercises": [
                {
                    "name": "Pull-Up",  # 구버전 LLM 출력 (equipment_label 없음)
                    "sets": 3,
                    "reps_min": 6,
                    "reps_max": 10,
                    "rest_seconds": 90,
                }
            ],
        }

        async def fake_resolve(label, gym_id, db):
            assert label == "Pull-Up"
            return _EQ_FREE_ID, _EX_ID, "bodyweight", 1.0, None

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


# ── (d) _resolve_label_to_ids 단위 테스트 ─────────────────────────────────────


class TestResolveLabelToIds:
    """_resolve_label_to_ids의 머신/프리웨이트 해석 경로를 직접 단위 테스트."""

    @pytest.mark.asyncio
    async def test_machine_path_returns_equipment_and_exercise(self):
        """movement_label_en 매치 → equipment_id + exercise_id 모두 반환."""
        eq_id = _EQ_MACHINE_ID
        ex_id = _EX_ID

        machine_row = MagicMock()
        machine_row.id = eq_id
        machine_row.equipment_type = "cable"
        machine_row.pulley_ratio = 0.5
        machine_row.bar_weight = None

        db = _make_db(
            _exec_first(machine_row),  # machine_stmt.first()
            _exec_scalar(ex_id),  # Exercise.id scalar
        )

        result_eq_id, result_ex_id, eq_type, pulley, bar = await _resolve_label_to_ids("Cable Fly", _GYM_ID, db)

        assert result_eq_id == eq_id
        assert result_ex_id == ex_id
        assert eq_type == "cable"
        assert pulley == 0.5

    @pytest.mark.asyncio
    async def test_free_weight_path_returns_both_ids(self):
        """movement_label_en 미매치 → exercises.name_en 매치 → default_equipment_id로 equipment 반환 (PR-4.5)."""
        ex_id = _EX_ID
        eq_id = _EQ_FREE_ID

        # PR-4.5: 프리 경로는 Exercise(id, default_equipment_id) 조회 후 그 기구 정보를 조회한다
        ex_row = MagicMock()
        ex_row.id = ex_id
        ex_row.default_equipment_id = eq_id

        eq_row = MagicMock()
        eq_row.equipment_type = "barbell"
        eq_row.pulley_ratio = 1.0
        eq_row.bar_weight = 20.0

        db = _make_db(
            _exec_first(None),  # machine_stmt.first() → None (머신 미매치)
            _exec_first(ex_row),  # Exercise(id, default_equipment_id) by name_en
            _exec_first(eq_row),  # default_equipment_id 기구 정보 (equipment_type/pulley/bar)
        )

        result_eq_id, result_ex_id, eq_type, pulley, bar = await _resolve_label_to_ids("Barbell Bench Press", None, db)

        assert result_ex_id == ex_id
        assert result_eq_id == eq_id
        assert eq_type == "barbell"
        assert bar == 20.0

    @pytest.mark.asyncio
    async def test_both_paths_fail_returns_none_ids(self):
        """머신/프리 모두 실패하고 fuzzy fallback도 실패 → (None, None, ...)."""
        db = _make_db(
            _exec_first(None),  # machine_stmt → None
            _exec_first(None),  # Exercise(id, default_equipment_id) → None (프리 미매치)
            # fuzzy: _resolve_exercise_id 내부 쿼리들
            _exec_scalar(None),  # name_en 정확 매치
            _exec_scalar(None),  # name 한글 매치
            _exec_scalar(None),  # ilike 매치
            _exec_all([]),  # all_exercises
        )

        result = await _resolve_label_to_ids("CompletelyUnknownExercise", None, db)

        eq_id, ex_id, eq_type, pulley, bar = result
        assert eq_id is None
        assert ex_id is None
