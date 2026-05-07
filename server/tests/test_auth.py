"""인증 도메인 엔드포인트 테스트.

DB와 인증을 dependency_overrides로 대체하여 외부 인프라 없이 CI에서 실행 가능.
"""

import hashlib
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import create_refresh_token, get_current_user, hash_password
from app.core.database import get_db
from app.main import app
from app.models.user import RefreshToken, User

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_FAMILY_ID = uuid.uuid4()
_NOW = datetime.utcnow()
_HASHED_PW = hash_password("password123")  # 모듈 로드 시 1회 계산


# ── 목 헬퍼 ──────────────────────────────────────────────────────────────────


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.email = "test@example.com"
    u.username = "testuser"
    u.name = "테스트"
    u.password_hash = _HASHED_PW
    u.is_active = True
    u.provider = MagicMock()
    u.provider.value = "local"
    return u


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
    db.refresh = AsyncMock()
    return db


def _db_override(mock_db):
    async def _gen():
        yield mock_db

    return _gen


_MOCK_USER = _mock_user()


@pytest_asyncio.fixture
async def client():
    """인증 불필요 엔드포인트용."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client():
    """인증 필요 엔드포인트용."""
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── POST /auth/login ───────────────────────────────────────────────────────────


class TestLogin:
    @pytest.mark.asyncio
    async def test_success(self, client):
        db = _make_db(_exec_scalar(_MOCK_USER))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/login", json={"username": "testuser", "password": "password123"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]

    @pytest.mark.asyncio
    async def test_wrong_password(self, client):
        db = _make_db(_exec_scalar(_MOCK_USER))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/login", json={"username": "testuser", "password": "wrong"})

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/login", json={"username": "notexist", "password": "password123"})

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user(self, client):
        inactive = _mock_user()
        inactive.is_active = False
        db = _make_db(_exec_scalar(inactive))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/login", json={"username": "testuser", "password": "password123"})

        assert resp.status_code == 401


# ── POST /auth/register ────────────────────────────────────────────────────────


class TestRegister:
    @pytest.mark.asyncio
    async def test_success(self, client):
        # email check → None, username check → None
        db = _make_db(_exec_scalar(None), _exec_scalar(None))
        new_user = MagicMock(spec=User)
        new_user.id = uuid.uuid4()
        new_user.username = "newuser"
        db.flush = AsyncMock()
        db.add = MagicMock()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "username": "newuser", "password": "password123", "name": "신규"},
        )

        assert resp.status_code == 201
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_email_duplicate(self, client):
        db = _make_db(_exec_scalar(_MOCK_USER))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "username": "other", "password": "password123", "name": "중복"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "EMAIL_DUPLICATE"

    @pytest.mark.asyncio
    async def test_username_duplicate(self, client):
        # email check → None (no duplicate), username check → existing user
        db = _make_db(_exec_scalar(None), _exec_scalar(_MOCK_USER))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "unique@example.com", "username": "testuser", "password": "password123", "name": "중복"},
        )

        assert resp.status_code == 409


# ── GET /auth/check-username ───────────────────────────────────────────────────


class TestCheckUsername:
    @pytest.mark.asyncio
    async def test_available(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/auth/check-username?username=newuser")

        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is True

    @pytest.mark.asyncio
    async def test_taken(self, client):
        db = _make_db(_exec_scalar(_MOCK_USER))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/auth/check-username?username=testuser")

        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is False

    @pytest.mark.asyncio
    async def test_too_short_raises(self, client):
        resp = await client.get("/api/v1/auth/check-username?username=a")
        assert resp.status_code == 400


# ── POST /auth/refresh ─────────────────────────────────────────────────────────


class TestRefresh:
    @pytest.mark.asyncio
    async def test_success(self, client):
        token = create_refresh_token(_USER_ID, family_id=_FAMILY_ID)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        rt = MagicMock(spec=RefreshToken)
        rt.token_hash = token_hash
        rt.revoked_at = None
        rt.family_id = _FAMILY_ID
        rt.user_id = _USER_ID

        db = _make_db(_exec_scalar(rt))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})

        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]

    @pytest.mark.asyncio
    async def test_revoked_beyond_grace_period_triggers_family_revoke(self, client):
        token = create_refresh_token(_USER_ID, family_id=_FAMILY_ID)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        rt = MagicMock(spec=RefreshToken)
        rt.token_hash = token_hash
        rt.revoked_at = _NOW - timedelta(seconds=11)  # grace period(10초) 초과
        rt.family_id = _FAMILY_ID
        rt.user_id = _USER_ID

        other_rt = MagicMock(spec=RefreshToken)
        other_rt.revoked_at = None

        db = _make_db(_exec_scalar(rt), _exec_scalars_all([rt, other_rt]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})

        assert resp.status_code == 401
        assert resp.json()["error"]["message"] == "토큰 재사용이 감지되었습니다."

    @pytest.mark.asyncio
    async def test_invalid_token(self, client):
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "invalid.token.here"})
        assert resp.status_code == 401


# ── POST /auth/logout ──────────────────────────────────────────────────────────


class TestLogout:
    @pytest.mark.asyncio
    async def test_success(self, auth_client):
        token = create_refresh_token(_USER_ID, family_id=_FAMILY_ID)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        rt = MagicMock(spec=RefreshToken)
        rt.token_hash = token_hash
        rt.revoked_at = None
        rt.user_id = _USER_ID

        db = _make_db(_exec_scalar(rt))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await auth_client.post("/api/v1/auth/logout", json={"refresh_token": token})

        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── DELETE /auth/withdraw ──────────────────────────────────────────────────────


class TestWithdraw:
    @pytest.mark.asyncio
    async def test_success(self, auth_client):
        rt = MagicMock(spec=RefreshToken)
        rt.revoked_at = None

        db = _make_db(_exec_scalars_all([rt]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await auth_client.delete("/api/v1/auth/withdraw")

        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True


# ── POST /auth/password/reset-email ──────────────────────────────────────────


class TestPasswordResetEmail:
    @pytest.mark.asyncio
    async def test_always_returns_sent(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/password/reset-email", json={"email": "anyone@example.com"})

        assert resp.status_code == 200
        assert resp.json()["data"]["sent"] is True
