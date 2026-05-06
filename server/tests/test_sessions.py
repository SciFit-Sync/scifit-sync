"""Sessions 엔드포인트 테스트 (API 명세 #30–36, #48).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import RoutineExercise, User, WorkoutLog, WorkoutLogSet, WorkoutStatus

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()
_REX_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _session(*, status: WorkoutStatus = WorkoutStatus.IN_PROGRESS) -> WorkoutLog:
    s = MagicMock(spec=WorkoutLog)
    s.id = _SESSION_ID
    s.user_id = _USER_ID
    s.routine_day_id = None
    s.gym_id = None
    s.started_at = _NOW
    s.finished_at = None
    s.status = status
    return s


def _set_record() -> WorkoutLogSet:
    sr = MagicMock(spec=WorkoutLogSet)
    sr.id = uuid.uuid4()
    sr.exercise_id = _EXERCISE_ID
    sr.set_number = 1
    sr.weight_kg = 80.0
    sr.reps = 10
    sr.rpe = 8.0
    sr.is_completed = True
    sr.performed_at = _NOW
    return sr


def _routine_exercise() -> RoutineExercise:
    rex = MagicMock(spec=RoutineExercise)
    rex.id = _REX_ID
    rex.rest_seconds = 90
    return rex


# ── execute() 반환값 헬퍼 ─────────────────────────────────────────────────────


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalar_val(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _exec_scalars_all(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _exec_all(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _db_override(mock_db):
    async def _override():
        yield mock_db

    return _override


# ── Fixture ───────────────────────────────────────────────────────────────────

_MOCK_USER = _user()


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── POST /sessions (#30) ──────────────────────────────────────────────────────


class TestStartSession:
    @pytest.mark.asyncio
    async def test_success_returns_201(self, client):
        db = _make_db()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/sessions", json={})

        assert resp.status_code == 201
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_routine_day_and_gym(self, client):
        day_id = uuid.uuid4()
        gym_id = uuid.uuid4()
        db = _make_db()
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/sessions",
            json={"routine_day_id": str(day_id), "gym_id": str(gym_id)},
        )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_invalid_routine_day_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post("/api/v1/sessions", json={"routine_day_id": "not-a-uuid"})

        assert resp.status_code == 400


# ── POST /sessions/{id}/sets (#31) ────────────────────────────────────────────


class TestLogSet:
    @pytest.mark.asyncio
    async def test_success_returns_201(self, client):
        s = _session()
        db = _make_db(
            _exec_scalar(s),  # _get_my_session
            _exec_scalar_val("벤치프레스"),  # Exercise.name
        )
        db.refresh = AsyncMock(side_effect=lambda obj: None)
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
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_completed_session_returns_409(self, client):
        s = _session(status=WorkoutStatus.COMPLETED)
        db = _make_db(_exec_scalar(s))
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

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
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

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_session_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post(
            "/api/v1/sessions/bad-id/sets",
            json={
                "exercise_id": str(_EXERCISE_ID),
                "set_number": 1,
                "weight_kg": 80.0,
                "reps": 10,
                "is_completed": True,
            },
        )

        assert resp.status_code == 400


# ── PATCH /sessions/{id}/finish (#32) ────────────────────────────────────────


class TestFinishSession:
    @pytest.mark.asyncio
    async def test_success(self, client):
        s = _session()
        db = _make_db(_exec_scalar(s))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})

        assert resp.status_code == 200
        assert s.status == WorkoutStatus.COMPLETED
        assert s.finished_at is not None
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_completed_returns_409(self, client):
        s = _session(status=WorkoutStatus.COMPLETED)
        db = _make_db(_exec_scalar(s))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})

        assert resp.status_code == 404


# ── GET /sessions (#33) ───────────────────────────────────────────────────────


class TestListSessions:
    @pytest.mark.asyncio
    async def test_all_sessions(self, client):
        s = _session()
        db = _make_db(_exec_scalars_all([s]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_filter_by_year_month(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions?year=2026&month=5")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []


# ── GET /sessions/stats (#34) ────────────────────────────────────────────────


class TestSessionStats:
    @pytest.mark.asyncio
    async def test_success(self, client):
        today = date.today()
        db = _make_db(
            _exec_scalar_val(10),  # total_sessions
            _exec_scalar_val(50000.0),  # total_volume
            _exec_all([(_NOW - timedelta(hours=1), _NOW)]),  # finished_rows (60분)
            _exec_all([(today,), (today - timedelta(days=1),)]),  # streak dates
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/stats")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_sessions"] == 10
        assert data["total_volume_kg"] == 50000.0
        assert data["total_minutes"] == 60
        assert data["streak_days"] == 2

    @pytest.mark.asyncio
    async def test_zero_stats(self, client):
        db = _make_db(
            _exec_scalar_val(0),
            _exec_scalar_val(0.0),
            _exec_all([]),
            _exec_all([]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/stats")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_sessions"] == 0
        assert data["streak_days"] == 0


# ── GET /sessions/analysis/volume (#35) ──────────────────────────────────────


class TestVolumeAnalysis:
    @pytest.mark.asyncio
    async def test_success(self, client):
        today = date.today()
        db = _make_db(_exec_all([(today, 5000.0)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/volume")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["volume_kg"] == 5000.0

    @pytest.mark.asyncio
    async def test_empty(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/volume")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_custom_days_param(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/analysis/volume?days=7")

        assert resp.status_code == 200


# ── GET /sessions/{id}/rest-timer (#36) ──────────────────────────────────────


class TestRestTimer:
    @pytest.mark.asyncio
    async def test_default_hypertrophy(self, client):
        s = _session()
        db = _make_db(_exec_scalar(s))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["rest_seconds"] == 90
        assert data["based_on"] == "goal_default"

    @pytest.mark.asyncio
    async def test_strength_goal_returns_180(self, client):
        s = _session()
        db = _make_db(_exec_scalar(s))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer?goal=strength")

        assert resp.status_code == 200
        assert resp.json()["data"]["rest_seconds"] == 180

    @pytest.mark.asyncio
    async def test_routine_exercise_overrides_goal(self, client):
        s = _session()
        rex = _routine_exercise()
        rex.rest_seconds = 120
        db = _make_db(
            _exec_scalar(s),
            _exec_scalar(rex),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(
            f"/api/v1/sessions/{_SESSION_ID}/rest-timer?routine_exercise_id={_REX_ID}&goal=strength"
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["rest_seconds"] == 120
        assert data["based_on"] == "routine"

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}/rest-timer")

        assert resp.status_code == 404


# ── GET /sessions/{id} (#48) ──────────────────────────────────────────────────


class TestSessionDetail:
    @pytest.mark.asyncio
    async def test_success_no_sets(self, client):
        s = _session()
        db = _make_db(
            _exec_scalar(s),  # _get_my_session
            _exec_all([]),  # sets
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"] == str(_SESSION_ID)
        assert data["sets"] == []
        assert data["total_volume_kg"] == 0.0

    @pytest.mark.asyncio
    async def test_success_with_sets(self, client):
        s = _session()
        sr = _set_record()
        db = _make_db(
            _exec_scalar(s),
            _exec_all([(sr, "벤치프레스")]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["sets"]) == 1
        assert data["sets"][0]["exercise_name"] == "벤치프레스"
        assert data["total_volume_kg"] == 800.0  # 80 * 10

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/sessions/{_SESSION_ID}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/sessions/bad-id")

        assert resp.status_code == 400
