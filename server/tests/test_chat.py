"""챗봇 도메인 엔드포인트 테스트 (#37-39)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import ChatMessage, ChatRole, ChatSession, User

_USER_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _mock_session() -> ChatSession:
    s = MagicMock(spec=ChatSession)
    s.id = _SESSION_ID
    s.user_id = _USER_ID
    s.title = "테스트 세션"
    return s


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
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


# ── POST /chat/messages (SSE) ─────────────────────────────────────────────────


class TestSendChatMessage:
    @pytest.mark.asyncio
    async def test_new_session_streams_sse(self, client):
        db = _make_db()
        db.flush = AsyncMock(side_effect=lambda: setattr(db, "_flushed", True))
        db.add = MagicMock()

        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/chat/messages",
            json={"content": "어깨 운동 루틴 추천해줘"},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "DONE" in resp.text

    @pytest.mark.asyncio
    async def test_existing_session_not_found(self, client):
        bad_session_id = str(uuid.uuid4())
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/chat/messages",
            json={"content": "안녕", "session_id": bad_session_id},
        )

        assert resp.status_code == 404


# ── GET /chat/messages ────────────────────────────────────────────────────────


class TestListChatMessages:
    @pytest.mark.asyncio
    async def test_session_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/chat/messages?session_id={uuid.uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_success_returns_messages(self, client):
        session = _mock_session()

        msg = MagicMock(spec=ChatMessage)
        msg.id = uuid.uuid4()
        msg.role = ChatRole.USER
        msg.content = "운동 알려줘"
        msg.paper_ids = None
        msg.created_at = _NOW

        db = _make_db(
            _exec_scalar(session),
            _exec_scalars_all([msg]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/chat/messages?session_id={_SESSION_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["content"] == "운동 알려줘"

    @pytest.mark.asyncio
    async def test_invalid_session_id_format(self, client):
        resp = await client.get("/api/v1/chat/messages?session_id=not-a-uuid")

        assert resp.status_code == 400


# ── GET /chat/recommended-routines ───────────────────────────────────────────


class TestRecommendedRoutines:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self, client):
        resp = await client.get("/api/v1/chat/recommended-routines")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
