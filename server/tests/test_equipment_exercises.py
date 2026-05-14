"""Equipment/Exercises 카탈로그 엔드포인트 테스트 (API 명세 #46–47).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Equipment, Exercise, User

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _equipment(name: str = "바벨") -> Equipment:
    eq = MagicMock(spec=Equipment)
    eq.id = uuid.uuid4()
    eq.name = name
    eq.name_en = "Barbell"
    eq.category = MagicMock()
    eq.category.value = "chest"
    eq.equipment_type = MagicMock()
    eq.equipment_type.value = "barbell"
    eq.pulley_ratio = 1.0
    eq.bar_weight_kg = 20.0
    eq.has_weight_assist = False
    eq.min_stack_kg = None
    eq.max_stack_kg = None
    eq.stack_weight_kg = None
    eq.image_url = None
    return eq


def _exercise(name: str = "벤치프레스") -> Exercise:
    ex = MagicMock(spec=Exercise)
    ex.id = uuid.uuid4()
    ex.name = name
    ex.name_en = "Bench Press"
    ex.description = "가슴 운동"
    ex.category = "chest"
    ex.muscle_maps = []
    return ex


# ── execute() 반환값 헬퍼 ─────────────────────────────────────────────────────


def _exec_all(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _exec_scalar_one(value):
    """scalar_one() 반환 (COUNT 쿼리용)."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _exec_scalars_unique_all(values):
    r = MagicMock()
    r.scalars.return_value.unique.return_value.all.return_value = values
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
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


# ── GET /equipment (#46) ──────────────────────────────────────────────────────


class TestListEquipment:
    @pytest.mark.asyncio
    async def test_success_returns_list(self, client):
        eq = _equipment()
        db = _make_db(_exec_all([(eq, "브랜드A")]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/equipment")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "바벨"
        assert items[0]["brand"] == "브랜드A"

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/equipment")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_keyword_filter(self, client):
        eq = _equipment("케이블 머신")
        db = _make_db(_exec_all([(eq, None)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/equipment?keyword=케이블")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"][0]["name"] == "케이블 머신"

    @pytest.mark.asyncio
    async def test_type_filter(self, client):
        db = _make_db(_exec_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/equipment?equipment_type=barbell")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_brand_returns_none(self, client):
        eq = _equipment()
        db = _make_db(_exec_all([(eq, None)]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/equipment")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"][0]["brand"] is None


# ── GET /exercises (#47) ──────────────────────────────────────────────────────


class TestListExercises:
    @pytest.mark.asyncio
    async def test_success_returns_list(self, client):
        ex = _exercise()
        db = _make_db(
            _exec_scalar_one(1),  # total_count
            _exec_scalars_unique_all([ex]),  # exercises
            _exec_all([]),  # muscle_rows
            _exec_all([]),  # eq_rows
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/exercises")

        assert resp.status_code == 200
        data = resp.json()["data"]
        items = data["items"]
        assert len(items) == 1
        assert items[0]["name"] == "벤치프레스"
        assert items[0]["primary_muscle_groups"] == []
        assert data["total_count"] == 1
        assert data["page"] == 0

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        db = _make_db(
            _exec_scalar_one(0),  # total_count
            _exec_scalars_unique_all([]),  # exercises (빈 목록 → early return)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/exercises")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_keyword_filter(self, client):
        ex = _exercise("스쿼트")
        db = _make_db(
            _exec_scalar_one(1),
            _exec_scalars_unique_all([ex]),
            _exec_all([]),  # muscle_rows
            _exec_all([]),  # eq_rows
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/exercises?keyword=스쿼트")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"][0]["name"] == "스쿼트"

    @pytest.mark.asyncio
    async def test_with_primary_muscles(self, client):
        from app.models import MuscleInvolvement

        ex = _exercise()
        db = _make_db(
            _exec_scalar_one(1),
            _exec_scalars_unique_all([ex]),
            _exec_all([(ex.id, MuscleInvolvement.PRIMARY, "대흉근")]),  # muscle_rows
            _exec_all([]),  # eq_rows
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/exercises")

        assert resp.status_code == 200
        assert "대흉근" in resp.json()["data"]["items"][0]["primary_muscle_groups"]

    @pytest.mark.asyncio
    async def test_muscle_filter(self, client):
        db = _make_db(
            _exec_scalar_one(0),  # total_count
            _exec_scalars_unique_all([]),  # exercises (빈 목록 → early return)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/exercises?muscle=pectoralis_major")

        assert resp.status_code == 200
