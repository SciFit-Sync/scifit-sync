"""세션(운동 로그) 도메인 엔드포인트 테스트 (#30-36, #48)."""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_required_profile
from app.core.database import get_db
from app.main import app
from app.models import User, WorkoutLog, WorkoutStatus

_USER_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _mock_session(status: WorkoutStatus = WorkoutStatus.IN_PROGRESS) -> WorkoutLog:
    s = MagicMock(spec=WorkoutLog)
    s.id = _SESSION_ID
    s.user_id = _USER_ID
    s.routine_day_id = None
    s.gym_id = None
    s.started_at = _NOW
    s.finished_at = None
    s.status = status
    return s


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalar_raw(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _exec_scalar_one(value):
    r = MagicMock()
    r.scalar_one.return_value = value
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
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    return db


def _db_override(mock_db):
    async def _gen():
        yield mock_db

    return _gen


_MOCK_USER = _mock_user()


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_required_profile] = lambda: _MOCK_USER
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── POST /sessions ─────────────────────────────────────────────────────────────


class TestStartSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        db = _make_db()

        async def _set_fields(obj):
            obj.started_at = _NOW

        db.refresh = AsyncMock(side_effect=_set_fields)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/sessions", json={})

        assert resp.status_code == 201
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_success_with_routine_day(self, client):
        db = _make_db()

        async def _set_fields(obj):
            obj.started_at = _NOW

        db.refresh = AsyncMock(side_effect=_set_fields)
        app.dependency_overrides[get_db] = _db_override(db)

        routine_day_id = str(uuid.uuid4())
        resp = await client.post("/api/v1/sessions", json={"routine_day_id": routine_day_id})

        assert resp.status_code == 201


# ── POST /sessions/{id}/sets ──────────────────────────────────────────────────


class TestLogSet:
    @pytest.mark.asyncio
    async def test_success(self, client):
        session = _mock_session()

        db = _make_db(
            _exec_scalar(session),
            _exec_scalar("벤치프레스"),  # exercise name query
        )

        async def _set_fields(obj):
            obj.performed_at = _NOW

        db.refresh = AsyncMock(side_effect=_set_fields)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/sessions/{_SESSION_ID}/sets",
            json={
                "exercise_id": str(_EXERCISE_ID),
                "set_number": 1,
                "weight_kg": 80.0,
                "reps": 10,
                "is_completed": True,
            },
        )

        assert resp.status_code == 201
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_session_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/sessions/{uuid.uuid4()}/sets",
            json={
                "exercise_id": str(_EXERCISE_ID),
                "set_number": 1,
                "weight_kg": 50.0,
                "reps": 8,
                "is_completed": True,
            },
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_already_finished_raises(self, client):
        session = _mock_session(status=WorkoutStatus.COMPLETED)
        db = _make_db(_exec_scalar(session))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/sessions/{_SESSION_ID}/sets",
            json={
                "exercise_id": str(_EXERCISE_ID),
                "set_number": 1,
                "weight_kg": 50.0,
                "reps": 8,
                "is_completed": True,
            },
        )

        assert resp.status_code == 409


# ── PATCH /sessions/{id}/finish ───────────────────────────────────────────────


class TestFinishSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        session = _mock_session()

        db = _make_db(
            _exec_scalar(session),  # _get_my_session
            _exec_scalars_all([]),  # ex_rows in _create_po_notifications
            _exec_scalar_one(0),  # total_sets
            _exec_scalar_one(0),  # completed_exercises
            _exec_scalar(None),  # UserBodyMeasurement (없으면 70kg 기본값)
        )
        db.refresh = AsyncMock()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_already_finished_raises(self, client):
        session = _mock_session(status=WorkoutStatus.COMPLETED)
        db = _make_db(_exec_scalar(session))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})

        assert resp.status_code == 409


# ── GET /sessions?year=&month= ────────────────────────────────────────────────


class TestListSessions:
    @pytest.mark.asyncio
    async def test_empty(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions")

        assert resp.status_code == 200
        assert resp.json()["data"]["records"] == []

    @pytest.mark.asyncio
    async def test_with_year_month_filter(self, client):
        session = _mock_session()
        db = _make_db(
            _exec_scalars_all([session]),  # WorkoutLog 목록 조회
            # session_agg: 세트 기록 없는 세션은 필터링되므로 세트 1개 제공
            _exec_all([(session.id, 62.5, 3, 62.5)]),  # (workout_log_id, volume, sets, weight)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions?year=2025&month=5")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["records"]) == 1


# ── GET /sessions/stats ───────────────────────────────────────────────────────


class TestSessionStats:
    @pytest.mark.asyncio
    async def test_success(self, client):
        finished_at = _NOW + timedelta(minutes=60)

        # total_sessions: (started_at, routine_day_id) 5개 — 날짜 다르게 해 5개 카운트
        session_rows_5 = [(_NOW - timedelta(days=i), None) for i in range(5)]
        # weekly_session_count: 2개
        session_rows_2 = [(_NOW - timedelta(days=i), None) for i in range(2)]

        db = _make_db(
            _exec_all(session_rows_5),  # all_session_rows → total_sessions 계산용
            _exec_scalar_raw(12500.0),  # total_volume (weight × reps)
            _exec_scalar_raw(250.0),  # total_weight (세트 무게 합산)
            _exec_scalar_raw(30),  # total_sets
            _exec_all([(_NOW, finished_at)]),  # finished_rows → total_duration_minutes
            _exec_scalar(None),  # UserBodyMeasurement → 70kg fallback
            _exec_all(session_rows_2),  # weekly_rows → weekly_session_count 계산용
            _exec_scalar(None),  # recent_row
            _exec_all([]),  # streak dates
            _exec_all([]),  # by_gym 집계 (D-M9)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/stats")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_sessions"] == 5
        assert data["total_volume_kg"] == 12500.0
        assert data["total_duration_minutes"] == 60
        assert data["total_calories_kcal"] == 350  # round(5.0 * 70 * 60 / 60)
        assert data["by_gym"] == []


# ── GET /sessions/{id} ────────────────────────────────────────────────────────


class TestGetSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        session = _mock_session()
        sets_result = MagicMock()
        sets_result.scalars.return_value.all.return_value = []

        db = _make_db(_exec_scalar(session), sets_result)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}")

        assert resp.status_code == 200
        assert resp.json()["data"]["session_id"] == str(_SESSION_ID)

    @pytest.mark.asyncio
    async def test_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{uuid.uuid4()}")

        assert resp.status_code == 404


# ── GET /sessions/analysis/volume (#35) ──────────────────────────────────────


class TestVolumeAnalysis:
    @pytest.mark.asyncio
    async def test_success_empty(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/volume")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_success_with_data(self, client):
        db = _make_db(_exec_all([(date(2025, 5, 1), 5000.0)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/volume?days=30")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["volume_kg"] == 5000.0

    @pytest.mark.asyncio
    async def test_invalid_days_zero(self, client):
        resp = await client.get("/api/v1/sessions/analysis/volume?days=0")

        assert resp.status_code == 400


# ── GET /sessions/{id}/rest-timer (#36) ──────────────────────────────────────


class TestRestTimer:
    @pytest.mark.asyncio
    async def test_goal_default_strength(self, client):
        session = _mock_session()
        db = _make_db(_exec_scalar(session))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer?goal=strength")

        assert resp.status_code == 200
        assert resp.json()["data"]["rest_seconds"] == 180
        assert resp.json()["data"]["based_on"] == "goal_default"

    @pytest.mark.asyncio
    async def test_no_goal_defaults_to_hypertrophy(self, client):
        session = _mock_session()
        db = _make_db(_exec_scalar(session))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer")

        assert resp.status_code == 200
        assert resp.json()["data"]["rest_seconds"] == 90
        assert resp.json()["data"]["based_on"] == "goal_default"

    @pytest.mark.asyncio
    async def test_routine_exercise_overrides_goal(self, client):
        session = _mock_session()
        rex = MagicMock()
        rex.rest_seconds = 120

        db = _make_db(_exec_scalar(session), _exec_scalar(rex))
        app.dependency_overrides[get_db] = _db_override(db)

        rex_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer?routine_exercise_id={rex_id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["rest_seconds"] == 120
        assert resp.json()["data"]["based_on"] == "routine"

    @pytest.mark.asyncio
    async def test_session_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{uuid.uuid4()}/rest-timer")

        assert resp.status_code == 404


# ── GET /sessions/analysis/muscle-volume ─────────────────────────────────────


class TestMuscleVolumeAnalysis:
    """근육 부위별 볼륨 분석 엔드포인트 테스트."""

    @pytest.mark.asyncio
    async def test_empty_no_workout_records(self, client):
        """운동 기록 없으면 전체 15개 근육 모두 0볼륨, 첫 운동 안내 메시지."""
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/muscle-volume")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["period"] == "WEEK"
        assert len(data["volume_by_muscle"]) == 15
        assert all(item["weekly_volume"] == 0.0 for item in data["volume_by_muscle"])
        assert all(item["status"] == "LOW" for item in data["volume_by_muscle"])
        assert "첫 운동을 시작해보세요" in data["ai_coach_message"]

    @pytest.mark.asyncio
    async def test_optimal_volume_returns_optimal_message(self, client):
        """볼륨이 최적 범위(4000~6000) 내이면 OPTIMAL 상태 및 격려 메시지."""
        db = _make_db(_exec_all([("대흉근", 5000.0), ("광배근", 4500.0)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/muscle-volume")

        assert resp.status_code == 200
        data = resp.json()["data"]
        chest = next(i for i in data["volume_by_muscle"] if i["muscle"] == "대흉근")
        assert chest["status"] == "OPTIMAL"
        assert chest["weekly_volume"] == 5000.0
        assert chest["optimal_min"] == 4000.0
        assert chest["optimal_max"] == 6000.0
        assert "훌륭합니다" in data["ai_coach_message"]

    @pytest.mark.asyncio
    async def test_low_volume_nonzero_returns_low_message(self, client):
        """볼륨이 최적 하한 미만(단, 0 초과)이면 LOW 상태 및 볼륨 증가 메시지."""
        db = _make_db(_exec_all([("대흉근", 1000.0)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/muscle-volume")

        assert resp.status_code == 200
        data = resp.json()["data"]
        chest = next(i for i in data["volume_by_muscle"] if i["muscle"] == "대흉근")
        assert chest["status"] == "LOW"
        assert "볼륨을 늘려보세요" in data["ai_coach_message"]

    @pytest.mark.asyncio
    async def test_high_volume_returns_high_message(self, client):
        """볼륨이 최적 상한 초과이면 HIGH 상태 및 회복 권장 메시지."""
        db = _make_db(_exec_all([("대흉근", 9000.0)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/muscle-volume")

        assert resp.status_code == 200
        data = resp.json()["data"]
        chest = next(i for i in data["volume_by_muscle"] if i["muscle"] == "대흉근")
        assert chest["status"] == "HIGH"
        assert "회복" in data["ai_coach_message"]

    @pytest.mark.asyncio
    async def test_period_month_uses_30_days(self, client):
        """period=MONTH 파라미터가 정상 처리되고 응답 period 필드에 반영된다."""
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/muscle-volume?period=MONTH")

        assert resp.status_code == 200
        assert resp.json()["data"]["period"] == "MONTH"

    @pytest.mark.asyncio
    async def test_invalid_period_returns_400(self, client):
        """허용되지 않는 period 값(DAILY 등)은 400 Bad Request 반환."""
        resp = await client.get("/api/v1/sessions/analysis/muscle-volume?period=DAILY")

        assert resp.status_code == 400


# ── GET /sessions/active ──────────────────────────────────────────────────────


class TestGetActiveSession:
    @pytest.mark.asyncio
    async def test_no_active_session_returns_null(self, client):
        """진행 중 세션이 없으면 data: null 반환."""
        db = _make_db(_exec_first(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/active")

        assert resp.status_code == 200
        assert resp.json()["data"] is None

    @pytest.mark.asyncio
    async def test_returns_active_session_with_elapsed(self, client):
        """진행 중 세션이 있으면 session_id와 elapsed_seconds를 반환한다."""
        routine_id = uuid.uuid4()
        session = _mock_session()
        session.started_at = datetime(2026, 6, 1, 10, 0, 0)

        db = _make_db(_exec_first((session, routine_id)))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/active")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"] == str(_SESSION_ID)
        assert data["routine_id"] == str(routine_id)
        assert data["elapsed_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_routine_id_filter_no_match_returns_null(self, client):
        """routine_id 필터 지정 시 해당 루틴의 세션이 없으면 data: null 반환."""
        db = _make_db(_exec_first(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/active?routine_id={uuid.uuid4()}")

        assert resp.status_code == 200
        assert resp.json()["data"] is None
