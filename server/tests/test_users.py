"""사용자 도메인 엔드포인트 테스트 (#9-17, #43, #50)."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import (
    CareerLevel,
    Exercise,
    Gender,
    OnermSource,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    UserProfile,
)

_USER_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.email = "test@example.com"
    u.username = "testuser"
    u.name = "테스트"
    u.provider = MagicMock()
    u.provider.value = "local"
    return u


def _mock_profile() -> UserProfile:
    p = MagicMock(spec=UserProfile)
    p.gender = Gender.MALE
    p.birth_date = date(1995, 1, 1)
    p.height_cm = 175.0
    p.default_goals = ["hypertrophy"]
    p.career_level = CareerLevel.INTERMEDIATE
    return p


def _mock_measurement() -> UserBodyMeasurement:
    m = MagicMock(spec=UserBodyMeasurement)
    m.weight_kg = 75.0
    m.skeletal_muscle_kg = 35.0
    m.body_fat_pct = 15.0
    m.measured_at = date.today()
    return m


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


# ── GET /users/me ─────────────────────────────────────────────────────────────


class TestGetMe:
    @pytest.mark.asyncio
    async def test_success_with_profile(self, client):
        db = _make_db(
            _exec_scalar(_mock_profile()),
            _exec_scalar(_mock_measurement()),
            _exec_all([]),  # gyms join result
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["username"] == "testuser"
        assert body["data"]["profile"]["height_cm"] == 175.0

    @pytest.mark.asyncio
    async def test_success_no_profile(self, client):
        db = _make_db(
            _exec_scalar(None),  # no profile
            _exec_scalar(None),  # no measurement
            _exec_all([]),  # gyms
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me")

        assert resp.status_code == 200
        assert resp.json()["data"]["profile"] is None


# ── PATCH /users/me/body ──────────────────────────────────────────────────────


class TestUpdateBody:
    @pytest.mark.asyncio
    async def test_update_weight_only(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"weight_kg": 76.5})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_update_height_requires_profile(self, client):
        db = _make_db(_exec_scalar(None))  # no profile
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"height_cm": 180.0})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_update_height_success(self, client):
        profile = _mock_profile()
        db = _make_db(_exec_scalar(profile))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"height_cm": 178.0})

        assert resp.status_code == 200
        assert resp.json()["data"]["height_cm"] == 178.0


# ── PATCH /users/me/goal ──────────────────────────────────────────────────────


class TestUpdateGoal:
    @pytest.mark.asyncio
    async def test_success(self, client):
        profile = _mock_profile()
        db = _make_db(_exec_scalar(profile))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/goal", json={"default_goals": ["strength", "hypertrophy"]})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_profile_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/goal", json={"default_goals": ["strength"]})

        assert resp.status_code == 404


# ── PATCH /users/me/career ────────────────────────────────────────────────────


class TestUpdateCareer:
    @pytest.mark.asyncio
    async def test_success(self, client):
        profile = _mock_profile()
        db = _make_db(_exec_scalar(profile))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "advanced"})

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_career_level(self, client):
        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "expert"})

        assert resp.status_code == 422  # Pydantic validation error


# ── GET /users/me/1rm ─────────────────────────────────────────────────────────


class TestGet1RM:
    @pytest.mark.asyncio
    async def test_success_empty(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/1rm")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_success_with_data(self, client):
        exercise = MagicMock(spec=Exercise)
        exercise.id = _EXERCISE_ID
        exercise.name = "벤치프레스"
        exercise.name_en = "Bench Press"

        orm = MagicMock(spec=UserExercise1RM)
        orm.id = uuid.uuid4()
        orm.exercise_id = _EXERCISE_ID
        orm.weight_kg = 100.0
        orm.source = OnermSource.MANUAL
        orm.estimated_at = _NOW
        orm.exercise = exercise

        db = _make_db(_exec_scalars_all([orm]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/1rm")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["weight_kg"] == 100.0


# ── POST /users/me/1rm ────────────────────────────────────────────────────────


class TestAdd1RM:
    @pytest.mark.asyncio
    async def test_success_manual(self, client):
        exercise = MagicMock(spec=Exercise)
        exercise.id = _EXERCISE_ID

        db = _make_db(_exec_scalar(exercise))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(_EXERCISE_ID), "weight_kg": 120.0, "source": "manual"},
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["weight_kg"] == 120.0

    @pytest.mark.asyncio
    async def test_exercise_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(uuid.uuid4()), "weight_kg": 100.0, "source": "manual"},
        )

        assert resp.status_code == 404
