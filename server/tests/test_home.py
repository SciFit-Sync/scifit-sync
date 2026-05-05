"""홈 대시보드 엔드포인트 테스트 (GET /home)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import User

_USER_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.name = "테스트"
    return u


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
    db.add = MagicMock()
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


class TestHome:
    @pytest.mark.asyncio
    async def test_success_no_data(self, client):
        db = _make_db(
            _exec_scalar(None),  # active_routine → None
            _exec_scalar_raw(0.0),  # recent_volume
            _exec_scalars_all([]),  # notifications
            _exec_all([]),  # streak dates
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["streak_days"] == 0
        assert body["data"]["today_routine"] is None
        assert body["data"]["upcoming_notifications"] == []
        assert body["data"]["recent_volume_kg"] == 0.0

    @pytest.mark.asyncio
    async def test_success_with_active_routine(self, client):
        routine = MagicMock()
        routine.id = uuid.uuid4()
        routine.name = "3분할 루틴"

        day = MagicMock()
        day.label = "가슴/삼두"

        db = _make_db(
            _exec_scalar(routine),  # active_routine
            _exec_scalar(day),  # next_day
            _exec_scalar_raw(1500.0),  # recent_volume
            _exec_scalars_all([]),  # notifications
            _exec_all([]),  # streak dates
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["today_routine"]["name"] == "3분할 루틴"
        assert data["today_routine"]["next_day_label"] == "가슴/삼두"
        assert data["recent_volume_kg"] == 1500.0
