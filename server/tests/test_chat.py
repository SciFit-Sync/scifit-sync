"""Chat 엔드포인트 테스트 (API 명세 #37–39).

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
from app.models import ChatMessage, ChatSession, User
from app.models.chat import ChatRole

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_SESSION_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _chat_session() -> ChatSession:
    s = MagicMock(spec=ChatSession)
    s.id = _SESSION_ID
    s.user_id = _USER_ID
    s.title = "운동 루틴 추천"
    return s


def _chat_message(role: ChatRole = ChatRole.USER) -> ChatMessage:
    m = MagicMock(spec=ChatMessage)
    m.id = uuid.uuid4()
    m.role = role
    m.content = "안녕하세요"
    m.paper_ids = None
    m.created_at = _NOW
    return m


# ── execute() 반환값 헬퍼 ─────────────────────────────────────────────────────


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


# ── POST /chat/messages (SSE) (#37) ──────────────────────────────────────────


class TestSendChatMessage:
    @pytest.mark.asyncio
    async def test_new_session_returns_sse(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/chat/messages", json={"content": "루틴 추천해줘"})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "session" in resp.text
        assert "[DONE]" in resp.text

    @pytest.mark.asyncio
    async def test_existing_session(self, client):
        session = _chat_session()
        db = _make_db(_exec_scalar(session))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/chat/messages",
            json={"content": "계속 얘기하자", "session_id": str(_SESSION_ID)},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/chat/messages",
            json={"content": "안녕", "session_id": str(_SESSION_ID)},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_content_returns_422(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post("/api/v1/chat/messages", json={})

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_session_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post(
            "/api/v1/chat/messages",
            json={"content": "안녕", "session_id": "not-a-uuid"},
        )

        assert resp.status_code == 400


# ── GET /chat/messages (#38) ──────────────────────────────────────────────────


class TestListChatMessages:
    @pytest.mark.asyncio
    async def test_success(self, client):
        session = _chat_session()
        user_msg = _chat_message(ChatRole.USER)
        ai_msg = _chat_message(ChatRole.ASSISTANT)
        db = _make_db(
            _exec_scalar(session),
            _exec_scalars_all([user_msg, ai_msg]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/chat/messages?session_id={_SESSION_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"] == str(_SESSION_ID)
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_empty_history(self, client):
        session = _chat_session()
        db = _make_db(
            _exec_scalar(session),
            _exec_scalars_all([]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/chat/messages?session_id={_SESSION_ID}")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_session_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/chat/messages?session_id={_SESSION_ID}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_session_id_returns_422(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/chat/messages")

        assert resp.status_code == 422


# ── GET /chat/recommended-routines (#39) ─────────────────────────────────────


class TestRecommendedRoutines:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self, client):
        resp = await client.get("/api/v1/chat/recommended-routines")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []
