"""세션(운동 로그) 도메인 엔드포인트 테스트 (#30-36, #48)."""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
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
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
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
        db = _make_db(_exec_scalar(session))
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
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_with_year_month_filter(self, client):
        session = _mock_session()
        db = _make_db(_exec_scalars_all([session]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions?year=2025&month=5")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 1


# ── GET /sessions/stats ───────────────────────────────────────────────────────


class TestSessionStats:
    @pytest.mark.asyncio
    async def test_success(self, client):
        finished_at = _NOW + timedelta(minutes=60)
        db = _make_db(
            _exec_scalar_raw(5),  # total_sessions count
            _exec_scalar_raw(12500.0),  # total_volume
            _exec_all([(_NOW, finished_at)]),  # finished sessions for minutes calc
            _exec_all([]),  # streak dates
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/sessions/stats")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_sessions"] == 5
        assert data["total_volume_kg"] == 12500.0
        assert data["total_minutes"] == 60


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
