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

        resp = await client.patch("/api/v1/users/me/goal", json={"goals": ["strength", "hypertrophy"]})

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_profile_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/goal", json={"goals": ["strength"]})

        assert resp.status_code == 400


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
        # 앱 커스텀 핸들러가 ValidationError를 400으로 변환
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "expert"})

        assert resp.status_code == 400


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

        db = _make_db(_exec_all([(orm, "벤치프레스")]))
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
        exercise.name = "벤치프레스"

        db = _make_db(_exec_scalar(exercise))

        async def _set_fields(obj):
            obj.estimated_at = _NOW

        db.refresh = AsyncMock(side_effect=_set_fields)
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


# ── POST /users/me/gym ────────────────────────────────────────────────────────

_GYM_ID = uuid.uuid4()
_EQUIPMENT_ID = uuid.uuid4()


def _mock_gym() -> Gym:
    g = MagicMock(spec=Gym)
    g.id = _GYM_ID
    g.name = "테스트 헬스장"
    g.gym_equipments = []
    return g


def _mock_equipment() -> Equipment:
    e = MagicMock(spec=Equipment)
    e.id = _EQUIPMENT_ID
    e.name = "케이블 머신"
    e.name_en = "Cable Machine"
    e.category = MagicMock()
    e.category.value = "back"
    e.equipment_type = MagicMock()
    e.equipment_type.value = "cable"
    e.pulley_ratio = 1.0
    e.bar_weight_kg = None
    e.has_weight_assist = False
    e.min_stack_kg = None
    e.max_stack_kg = None
    e.stack_weight_kg = 2.5
    e.image_url = None
    return e


def _mock_user_gym(is_primary: bool = True) -> UserGym:
    ug = MagicMock(spec=UserGym)
    ug.gym_id = _GYM_ID
    ug.user_id = _USER_ID
    ug.is_primary = is_primary
    return ug


class TestAddPrimaryGym:
    @pytest.mark.asyncio
    async def test_success_new_gym(self, client):
        gym = _mock_gym()

        db = _make_db(
            _exec_scalar(gym),         # gym 존재 확인
            _exec_scalars_all([]),     # 기존 primary 없음
            _exec_scalar(None),        # UserGym 없음 → 새로 추가
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/gym",
            json={"gym_id": str(_GYM_ID)},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["gym_id"] == str(_GYM_ID)
        assert body["data"]["is_primary"] is True

    @pytest.mark.asyncio
    async def test_success_upgrade_existing(self, client):
        gym = _mock_gym()
        existing_ug = _mock_user_gym(is_primary=False)

        db = _make_db(
            _exec_scalar(gym),            # gym 존재
            _exec_scalars_all([]),        # 기존 primary 없음
            _exec_scalar(existing_ug),   # UserGym 이미 있음 → primary 승격
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/gym",
            json={"gym_id": str(_GYM_ID)},
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["is_primary"] is True

    @pytest.mark.asyncio
    async def test_gym_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/gym",
            json={"gym_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_gym_id(self, client):
        resp = await client.post(
            "/api/v1/users/me/gym",
            json={"gym_id": "not-a-uuid"},
        )

        assert resp.status_code == 400


# ── PATCH /users/me/gym ───────────────────────────────────────────────────────


class TestChangePrimaryGym:
    @pytest.mark.asyncio
    async def test_success(self, client):
        gym = _mock_gym()

        db = _make_db(
            _exec_scalar(gym),
            _exec_scalars_all([]),
            _exec_scalar(None),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            "/api/v1/users/me/gym",
            json={"gym_id": str(_GYM_ID)},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["is_primary"] is True


# ── GET /users/me/equipment ───────────────────────────────────────────────────


class TestListMyEquipment:
    @pytest.mark.asyncio
    async def test_success_with_equipment(self, client):
        user_gym = _mock_user_gym()
        equipment = _mock_equipment()

        gym = _mock_gym()
        gym_eq = MagicMock(spec=GymEquipment)
        gym_eq.equipment_id = _EQUIPMENT_ID
        gym.gym_equipments = [gym_eq]

        db = _make_db(
            _exec_scalar(user_gym),       # primary gym
            _exec_scalar(gym),            # gym with equipments
            _exec_scalars_all([equipment]), # equipment 목록
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/equipment")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["items"]) == 1

    @pytest.mark.asyncio
    async def test_no_primary_gym(self, client):
        db = _make_db(_exec_scalar(None))  # primary gym 없음
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/equipment")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []


# ── POST /users/me/equipment ──────────────────────────────────────────────────


class TestAddMyEquipment:
    @pytest.mark.asyncio
    async def test_success(self, client):
        equipment = _mock_equipment()
        user_gym = _mock_user_gym()

        db = _make_db(
            _exec_scalar(equipment),  # equipment 존재
            _exec_scalar(user_gym),   # primary gym 있음
            _exec_scalar(None),       # 중복 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["equipment_id"] == str(_EQUIPMENT_ID)

    @pytest.mark.asyncio
    async def test_equipment_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_primary_gym(self, client):
        equipment = _mock_equipment()

        db = _make_db(
            _exec_scalar(equipment),  # equipment 있음
            _exec_scalar(None),       # primary gym 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_duplicate_equipment(self, client):
        equipment = _mock_equipment()
        user_gym = _mock_user_gym()
        existing = MagicMock(spec=GymEquipment)

        db = _make_db(
            _exec_scalar(equipment),  # equipment 있음
            _exec_scalar(user_gym),   # primary gym 있음
            _exec_scalar(existing),   # 중복
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 409
