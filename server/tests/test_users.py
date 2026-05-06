"""Users 엔드포인트 테스트 (API 명세 #9–17, #43, #50).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

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
    Equipment,
    Exercise,
    Gym,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    UserGym,
    UserProfile,
)
from app.models.user import CareerLevel, EquipmentType, Gender, OnermSource, Provider

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_GYM_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()
_EQUIPMENT_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.email = "test@example.com"
    u.username = "taehyun"
    u.name = "장태현"
    u.provider = Provider.LOCAL
    return u


def _profile() -> UserProfile:
    p = MagicMock(spec=UserProfile)
    p.gender = Gender.MALE
    p.birth_date = date(1999, 1, 1)
    p.height_cm = 175.0
    p.default_goals = ["hypertrophy"]
    p.career_level = CareerLevel.INTERMEDIATE
    return p


def _measurement() -> UserBodyMeasurement:
    m = MagicMock(spec=UserBodyMeasurement)
    m.weight_kg = 75.0
    m.skeletal_muscle_kg = 35.0
    m.body_fat_pct = 15.0
    m.measured_at = date.today()
    return m


def _gym() -> Gym:
    g = MagicMock(spec=Gym)
    g.id = _GYM_ID
    g.name = "스쿼트 헬스장"
    return g


def _user_gym(*, is_primary: bool = True) -> UserGym:
    ug = MagicMock(spec=UserGym)
    ug.gym_id = _GYM_ID
    ug.is_primary = is_primary
    return ug


def _exercise() -> Exercise:
    ex = MagicMock(spec=Exercise)
    ex.id = _EXERCISE_ID
    ex.name = "벤치프레스"
    return ex


def _onerm() -> UserExercise1RM:
    r = MagicMock(spec=UserExercise1RM)
    r.id = uuid.uuid4()
    r.exercise_id = _EXERCISE_ID
    r.weight_kg = 100.0
    r.source = OnermSource.MANUAL
    r.estimated_at = _NOW
    return r


def _equipment() -> Equipment:
    eq = MagicMock(spec=Equipment)
    eq.id = _EQUIPMENT_ID
    eq.name = "바벨"
    eq.category = MagicMock()
    eq.category.value = "chest"
    eq.equipment_type = EquipmentType.BARBELL
    eq.equipment_type.value = "barbell"
    eq.pulley_ratio = 1.0
    eq.bar_weight_kg = 20.0
    eq.image_url = None
    return eq


# ── execute() 반환값 헬퍼 ─────────────────────────────────────────────────────


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalar_val(value):
    """scalar() 반환."""
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


# ── GET /users/me (#9) ────────────────────────────────────────────────────────


class TestGetMe:
    @pytest.mark.asyncio
    async def test_success_with_profile_and_measurement(self, client):
        db = _make_db(
            _exec_scalar(_profile()),  # UserProfile
            _exec_scalar(_measurement()),  # 최신 체측
            _exec_all([(_user_gym(), _gym())]),  # UserGym + Gym
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["user_id"] == str(_USER_ID)
        assert data["username"] == "taehyun"
        assert data["profile"]["height_cm"] == 175.0
        assert data["latest_measurement"]["weight_kg"] == 75.0
        assert len(data["gyms"]) == 1

    @pytest.mark.asyncio
    async def test_success_no_profile(self, client):
        db = _make_db(
            _exec_scalar(None),  # 프로필 없음
            _exec_scalar(None),  # 체측 없음
            _exec_all([]),  # 헬스장 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["profile"] is None
        assert data["latest_measurement"] is None
        assert data["gyms"] == []


# ── PATCH /users/me/body (#10) ────────────────────────────────────────────────


class TestUpdateBody:
    @pytest.mark.asyncio
    async def test_update_height_only(self, client):
        p = _profile()
        db = _make_db(_exec_scalar(p))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"height_cm": 178.0})

        assert resp.status_code == 200
        assert p.height_cm == 178.0
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_weight_adds_measurement(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"weight_kg": 80.0})

        assert resp.status_code == 200
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_weight_without_profile_is_ok(self, client):
        # weight_kg만 업데이트 시 profile 조회 없음
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"weight_kg": 77.0})

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_height_without_profile_returns_400(self, client):
        db = _make_db(_exec_scalar(None))  # 프로필 없음
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"height_cm": 175.0})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_body_fat_without_weight_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/body", json={"body_fat_pct": 15.0})

        assert resp.status_code == 400


# ── PATCH /users/me/goal (#11) ────────────────────────────────────────────────


class TestUpdateGoal:
    @pytest.mark.asyncio
    async def test_success(self, client):
        p = _profile()
        db = _make_db(_exec_scalar(p))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/goal", json={"goals": ["strength", "hypertrophy"]})

        assert resp.status_code == 200
        assert p.default_goals == ["strength", "hypertrophy"]
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_profile_returns_400(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/goal", json={"goals": ["strength"]})

        assert resp.status_code == 400


# ── PATCH /users/me/career (#12) ─────────────────────────────────────────────


class TestUpdateCareer:
    @pytest.mark.asyncio
    async def test_success(self, client):
        p = _profile()
        db = _make_db(_exec_scalar(p))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "advanced"})

        assert resp.status_code == 200
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_career_level_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "invalid_level"})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_no_profile_returns_400(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/career", json={"career_level": "beginner"})

        assert resp.status_code == 400


# ── POST /users/me/gym (#13) & PATCH /users/me/gym (#14) ─────────────────────


class TestSetPrimaryGym:
    @pytest.mark.asyncio
    async def test_post_new_gym_returns_201(self, client):
        g = _gym()
        db = _make_db(
            _exec_scalar(g),  # Gym 조회
            _exec_scalars_all([]),  # 기존 primary UserGym 없음
            _exec_scalar(None),  # 이미 등록된 UserGym 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/users/me/gym", json={"gym_id": str(_GYM_ID)})

        assert resp.status_code == 201
        assert resp.json()["data"]["gym_id"] == str(_GYM_ID)
        assert resp.json()["data"]["is_primary"] is True

    @pytest.mark.asyncio
    async def test_patch_existing_gym(self, client):
        g = _gym()
        ug = _user_gym(is_primary=False)
        db = _make_db(
            _exec_scalar(g),
            _exec_scalars_all([]),
            _exec_scalar(ug),  # 이미 등록된 헬스장
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch("/api/v1/users/me/gym", json={"gym_id": str(_GYM_ID)})

        assert resp.status_code == 200
        assert ug.is_primary is True

    @pytest.mark.asyncio
    async def test_gym_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/users/me/gym", json={"gym_id": str(_GYM_ID)})

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_gym_id_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/users/me/gym", json={"gym_id": "not-a-uuid"})

        assert resp.status_code == 400


# ── POST /users/me/1rm (#15) & PATCH /users/me/1rm (#16) ─────────────────────


class TestAdd1RM:
    @pytest.mark.asyncio
    async def test_post_manual_returns_201(self, client):
        ex = _exercise()
        db = _make_db(_exec_scalar(ex))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(_EXERCISE_ID), "weight_kg": 100.0},
        )

        assert resp.status_code == 201
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_with_reps_uses_epley(self, client):
        ex = _exercise()
        db = _make_db(_exec_scalar(ex))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(_EXERCISE_ID), "weight_kg": 80.0, "reps": 10},
        )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_patch_delegates_to_add(self, client):
        ex = _exercise()
        db = _make_db(_exec_scalar(ex))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(_EXERCISE_ID), "weight_kg": 105.0},
        )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_exercise_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": str(_EXERCISE_ID), "weight_kg": 100.0},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_exercise_id_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/1rm",
            json={"exercise_id": "not-a-uuid", "weight_kg": 100.0},
        )

        assert resp.status_code == 400


# ── GET /users/me/1rm (#43) ───────────────────────────────────────────────────


class TestList1RM:
    @pytest.mark.asyncio
    async def test_empty(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/1rm")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_returns_records(self, client):
        rec = _onerm()
        db = _make_db(_exec_all([(rec, "벤치프레스")]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/1rm")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["exercise_name"] == "벤치프레스"
        assert items[0]["weight_kg"] == 100.0


# ── GET /users/me/equipment (#50) ────────────────────────────────────────────


class TestListMyEquipment:
    @pytest.mark.asyncio
    async def test_no_primary_gym_returns_empty(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/equipment")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_returns_equipment_list(self, client):
        ug = _user_gym()
        g = _gym()
        ge = MagicMock()
        ge.equipment_id = _EQUIPMENT_ID
        g.gym_equipments = [ge]
        eq = _equipment()

        db = _make_db(
            _exec_scalar(ug),  # primary UserGym
            _exec_scalar(g),  # Gym with gym_equipments
            _exec_scalars_all([eq]),  # Equipment 목록
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/users/me/equipment")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "바벨"


# ── POST /users/me/equipment (#17) ───────────────────────────────────────────


class TestAddMyEquipment:
    @pytest.mark.asyncio
    async def test_success_returns_201(self, client):
        eq = _equipment()
        ug = _user_gym()
        db = _make_db(
            _exec_scalar(eq),  # Equipment 조회
            _exec_scalar(ug),  # primary UserGym
            _exec_scalar(None),  # GymEquipment 중복 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["equipment_id"] == str(_EQUIPMENT_ID)

    @pytest.mark.asyncio
    async def test_equipment_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_primary_gym_returns_400(self, client):
        eq = _equipment()
        db = _make_db(
            _exec_scalar(eq),  # Equipment 조회
            _exec_scalar(None),  # primary UserGym 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_duplicate_equipment_returns_409(self, client):
        from app.models import GymEquipment

        eq = _equipment()
        ug = _user_gym()
        existing_ge = MagicMock(spec=GymEquipment)
        db = _make_db(
            _exec_scalar(eq),
            _exec_scalar(ug),
            _exec_scalar(existing_ge),  # 이미 존재
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_invalid_equipment_id_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/users/me/equipment",
            json={"equipment_id": "not-a-uuid"},
        )

        assert resp.status_code == 400
