"""프로그램 도메인 엔드포인트 테스트."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Program, ProgramRoutine, User, WorkoutRoutine

_USER_ID = uuid.uuid4()
_PROGRAM_ID = uuid.uuid4()
_ROUTINE_ID_1 = uuid.uuid4()
_ROUTINE_ID_2 = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _mock_routine(rid: uuid.UUID, name: str = "테스트 루틴") -> WorkoutRoutine:
    r = MagicMock(spec=WorkoutRoutine)
    r.id = rid
    r.name = name
    r.user_id = _USER_ID
    r.deleted_at = None
    return r


def _mock_program_routine(rid: uuid.UUID, order: int = 0) -> ProgramRoutine:
    pr = MagicMock(spec=ProgramRoutine)
    pr.routine_id = rid
    pr.order_index = order
    pr.routine = _mock_routine(rid)
    return pr


def _mock_program(program_routines=None) -> Program:
    p = MagicMock(spec=Program)
    p.id = _PROGRAM_ID
    p.user_id = _USER_ID
    p.name = "테스트 프로그램"
    p.description = None
    p.created_at = _NOW
    p.program_routines = program_routines or []
    return p


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar_one.return_value = value
    return r


def _exec_scalars_all(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
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


# ── POST /programs ────────────────────────────────────────────────────────────


class TestCreateProgram:
    @pytest.mark.asyncio
    async def test_success(self, client):
        pr = _mock_program_routine(_ROUTINE_ID_1)
        program = _mock_program([pr])
        db = _make_db(
            _exec_scalars_all([_ROUTINE_ID_1]),  # valid routines
            _exec_scalar(program),               # program_loaded
        )
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.post(
            "/api/v1/programs",
            json={"name": "테스트", "routine_ids": [str(_ROUTINE_ID_1)]},
        )
        assert res.status_code == 201
        assert res.json()["success"] is True
        assert res.json()["data"]["name"] == program.name

    @pytest.mark.asyncio
    async def test_duplicate_routine_ids_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)
        rid = str(_ROUTINE_ID_1)
        res = await client.post(
            "/api/v1/programs",
            json={"name": "테스트", "routine_ids": [rid, rid]},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_other_user_routine_400(self, client):
        db = _make_db(
            _exec_scalars_all([]),  # valid 0개 → 타인 루틴
        )
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.post(
            "/api/v1/programs",
            json={"name": "테스트", "routine_ids": [str(_ROUTINE_ID_1)]},
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# ── GET /programs ─────────────────────────────────────────────────────────────


class TestListPrograms:
    @pytest.mark.asyncio
    async def test_success(self, client):
        pr = _mock_program_routine(_ROUTINE_ID_1)
        program = _mock_program([pr])
        db = _make_db(_exec_scalars_all([program]))
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.get("/api/v1/programs")
        assert res.status_code == 200
        assert isinstance(res.json()["data"]["items"], list)

    @pytest.mark.asyncio
    async def test_empty(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.get("/api/v1/programs")
        assert res.status_code == 200
        assert res.json()["data"]["items"] == []


# ── DELETE /programs/{id} ─────────────────────────────────────────────────────


class TestDeleteProgram:
    @pytest.mark.asyncio
    async def test_success(self, client):
        program = _mock_program()
        db = _make_db(_exec_scalar(program))
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.delete(f"/api/v1/programs/{_PROGRAM_ID}")
        assert res.status_code == 200
        assert "삭제" in res.json()["data"]["message"]

    @pytest.mark.asyncio
    async def test_not_found_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)
        res = await client.delete(f"/api/v1/programs/{_PROGRAM_ID}")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
