"""Notifications 엔드포인트 테스트 (API 명세 #40–41).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Notification, User

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_NOTIF_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _notification(*, is_read: bool = False) -> Notification:
    n = MagicMock(spec=Notification)
    n.id = _NOTIF_ID
    n.type = MagicMock()
    n.type.value = "po_suggestion"
    n.title = "중량을 올릴 시간"
    n.body = "연속 2세션 목표 달성!"
    n.is_read = is_read
    n.data_json = None
    n.created_at = _NOW
    return n


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


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
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


# ── GET /notifications (#40) ──────────────────────────────────────────────────


class TestListNotifications:
    @pytest.mark.asyncio
    async def test_success_with_unread(self, client):
        n = _notification()
        db = _make_db(
            _exec_scalars_all([n]),  # 알림 목록
            _exec_scalar_val(1),  # unread_count
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/notifications")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "중량을 올릴 시간"
        assert data["unread_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_notifications(self, client):
        db = _make_db(
            _exec_scalars_all([]),
            _exec_scalar_val(0),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/notifications")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["unread_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_notifications(self, client):
        notifs = [_notification() for _ in range(3)]
        db = _make_db(
            _exec_scalars_all(notifs),
            _exec_scalar_val(3),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/notifications")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 3


# ── PATCH /notifications/{id}/read (#41) ─────────────────────────────────────


class TestMarkRead:
    @pytest.mark.asyncio
    async def test_success(self, client):
        n = _notification()
        db = _make_db(_exec_scalar(n))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/notifications/{_NOTIF_ID}/read")

        assert resp.status_code == 200
        assert n.is_read is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(f"/api/v1/notifications/{_NOTIF_ID}/read")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.patch("/api/v1/notifications/not-a-uuid/read")

        assert resp.status_code == 400
