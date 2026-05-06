"""Auth 엔드포인트 테스트 (API 명세 #1–8, #42).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.user import Provider, RefreshToken, User

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_FAMILY_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user(*, is_active: bool = True, provider: Provider = Provider.LOCAL) -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.email = "test@example.com"
    u.username = "taehyun"
    u.name = "장태현"
    u.password_hash = "hashed_pw"
    u.is_active = is_active
    u.provider = provider
    u.provider_id = None
    return u


def _refresh_token(*, revoked_at=None) -> RefreshToken:
    rt = MagicMock(spec=RefreshToken)
    rt.token_hash = "some_hash"
    rt.family_id = _FAMILY_ID
    rt.user_id = _USER_ID
    rt.revoked_at = revoked_at
    rt.expires_at = _NOW + timedelta(days=30)
    return rt


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


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── POST /auth/register (#1) ──────────────────────────────────────────────────


class TestRegister:
    @pytest.mark.asyncio
    async def test_success(self, client):
        db = _make_db(
            _exec_scalar(None),  # 이메일 중복 없음
            _exec_scalar(None),  # 아이디 중복 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "username": "newuser", "password": "password123", "name": "홍길동"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert "user_id" in body["data"]
        assert body["data"]["username"] == "newuser"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_email_returns_409(self, client):
        db = _make_db(_exec_scalar(_user()))  # 이메일 이미 존재
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "dup@example.com", "username": "newuser", "password": "password123", "name": "홍길동"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "EMAIL_DUPLICATE"

    @pytest.mark.asyncio
    async def test_duplicate_username_returns_409(self, client):
        db = _make_db(
            _exec_scalar(None),  # 이메일 없음
            _exec_scalar(_user()),  # 아이디 이미 존재
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "username": "taken", "password": "password123", "name": "홍길동"},
        )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_422(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/register", json={"email": "x@x.com"})

        assert resp.status_code == 422


# ── POST /auth/login (#2) ─────────────────────────────────────────────────────


class TestLogin:
    @pytest.mark.asyncio
    async def test_success(self, client):
        u = _user()
        db = _make_db(_exec_scalar(u))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch("app.api.v1.auth.verify_password", return_value=True):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "password123"},
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user_id"] == str(_USER_ID)
        assert data["username"] == "taehyun"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_401(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_password_returns_401(self, client):
        u = _user()
        db = _make_db(_exec_scalar(u))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch("app.api.v1.auth.verify_password", return_value=False):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "wrong"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_inactive_user_returns_401(self, client):
        u = _user(is_active=False)
        db = _make_db(_exec_scalar(u))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch("app.api.v1.auth.verify_password", return_value=True):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@example.com", "password": "password123"},
            )

        assert resp.status_code == 401


# ── POST /auth/oauth/kakao (#3) ───────────────────────────────────────────────


class TestKakaoLogin:
    def _kakao_api_resp(self, kakao_id="1234567", email="kakao@example.com", nickname="카카오유저"):
        resp = MagicMock()
        resp.status_code = 200
        resp.is_success = True
        resp.json.return_value = {
            "id": kakao_id,
            "kakao_account": {
                "email": email,
                "profile": {"nickname": nickname},
            },
        }
        return resp

    @pytest.mark.asyncio
    async def test_existing_user_login(self, client):
        u = _user(provider=Provider.KAKAO)
        db = _make_db(_exec_scalar(u))
        app.dependency_overrides[get_db] = _db_override(db)

        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(return_value=self._kakao_api_resp())
        with patch("app.api.v1.auth.httpx.AsyncClient", return_value=kakao_client):
            resp = await client.post("/api/v1/auth/oauth/kakao", json={"access_token": "kakao_token"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert data["is_new_user"] is False

    @pytest.mark.asyncio
    async def test_new_user_register_returns_201(self, client):
        db = _make_db(
            _exec_scalar(None),  # 기존 유저 없음
            _exec_scalar(None),  # 이메일 중복 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(return_value=self._kakao_api_resp())
        with (
            patch("app.api.v1.auth.httpx.AsyncClient", return_value=kakao_client),
            patch("app.api.v1.auth.create_access_token", return_value="dummy_access"),
            patch("app.api.v1.auth.create_refresh_token", return_value="dummy_refresh"),
        ):
            resp = await client.post("/api/v1/auth/oauth/kakao", json={"access_token": "new_token"})

        assert resp.status_code == 201
        assert resp.json()["data"]["is_new_user"] is True

    @pytest.mark.asyncio
    async def test_invalid_kakao_token_returns_400(self, client):
        bad_resp = MagicMock()
        bad_resp.status_code = 401
        bad_resp.is_success = False

        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(return_value=bad_resp)
        with patch("app.api.v1.auth.httpx.AsyncClient", return_value=kakao_client):
            resp = await client.post("/api/v1/auth/oauth/kakao", json={"access_token": "bad_token"})

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_kakao_network_error_returns_503(self, client):
        import httpx as _httpx

        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(
            side_effect=_httpx.RequestError("network error", request=MagicMock())
        )
        with patch("app.api.v1.auth.httpx.AsyncClient", return_value=kakao_client):
            resp = await client.post("/api/v1/auth/oauth/kakao", json={"access_token": "token"})

        assert resp.status_code == 503


# ── POST /auth/logout (#4) ────────────────────────────────────────────────────


class TestLogout:
    @pytest.mark.asyncio
    async def test_success(self, client):
        from app.core.auth import create_refresh_token as _crt

        u = _user()
        rt = _refresh_token()
        db = _make_db(_exec_scalar(rt))
        app.dependency_overrides[get_db] = _db_override(db)
        app.dependency_overrides[get_current_user] = lambda: u

        token = _crt(_USER_ID, family_id=_FAMILY_ID)
        resp = await client.post("/api/v1/auth/logout", json={"refresh_token": token})

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client):
        app.dependency_overrides[get_current_user] = lambda: _user()
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "invalid.token.here"})

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_owner_mismatch_returns_401(self, client):
        from app.core.auth import create_refresh_token as _crt

        other_user_id = uuid.uuid4()
        u = _user()  # _USER_ID 소유 유저
        app.dependency_overrides[get_current_user] = lambda: u
        app.dependency_overrides[get_db] = _db_override(_make_db())

        # 다른 유저 소유 토큰
        token = _crt(other_user_id, family_id=_FAMILY_ID)
        resp = await client.post("/api/v1/auth/logout", json={"refresh_token": token})

        assert resp.status_code == 401


# ── GET /auth/check-username (#5) ─────────────────────────────────────────────


class TestCheckUsername:
    @pytest.mark.asyncio
    async def test_available(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/auth/check-username?username=newname")

        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is True

    @pytest.mark.asyncio
    async def test_taken(self, client):
        db = _make_db(_exec_scalar(_user()))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/auth/check-username?username=taehyun")

        assert resp.status_code == 200
        assert resp.json()["data"]["available"] is False

    @pytest.mark.asyncio
    async def test_too_short_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/auth/check-username?username=a")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_too_long_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/auth/check-username?username=" + "a" * 21)

        assert resp.status_code == 400


# ── POST /auth/password/reset-email (#6) ──────────────────────────────────────


class TestPasswordResetEmail:
    @pytest.mark.asyncio
    async def test_existing_email_returns_sent_true(self, client):
        db = _make_db(_exec_scalar(_user()))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/password/reset-email", json={"email": "test@example.com"})

        assert resp.status_code == 200
        assert resp.json()["data"]["sent"] is True

    @pytest.mark.asyncio
    async def test_nonexistent_email_same_response(self, client):
        # 보안상 사용자 존재 여부 무관하게 동일 응답
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/auth/password/reset-email", json={"email": "ghost@example.com"})

        assert resp.status_code == 200
        assert resp.json()["data"]["sent"] is True


# ── PATCH /auth/password/reset (#7) ───────────────────────────────────────────


class TestPasswordReset:
    @pytest.mark.asyncio
    async def test_success(self, client):
        u = _user()
        db = _make_db(_exec_scalar(u))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch("app.api.v1.auth.verify_token", return_value={"sub": str(_USER_ID), "type": "reset"}):
            resp = await client.patch(
                "/api/v1/auth/password/reset",
                json={"token": "reset_token", "new_password": "newpassword123"},
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["success"] is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_short_password_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        with patch("app.api.v1.auth.verify_token", return_value={"sub": str(_USER_ID), "type": "reset"}):
            resp = await client.patch(
                "/api/v1/auth/password/reset",
                json={"token": "reset_token", "new_password": "short"},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self, client):
        from app.core.exceptions import UnauthorizedError

        app.dependency_overrides[get_db] = _db_override(_make_db())

        with patch("app.api.v1.auth.verify_token", side_effect=UnauthorizedError()):
            resp = await client.patch(
                "/api/v1/auth/password/reset",
                json={"token": "bad_token", "new_password": "newpassword123"},
            )

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_found_returns_401(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db(_exec_scalar(None)))

        with patch("app.api.v1.auth.verify_token", return_value={"sub": str(_USER_ID), "type": "reset"}):
            resp = await client.patch(
                "/api/v1/auth/password/reset",
                json={"token": "reset_token", "new_password": "newpassword123"},
            )

        assert resp.status_code == 401


# ── DELETE /auth/withdraw (#8) ────────────────────────────────────────────────


class TestWithdraw:
    @pytest.mark.asyncio
    async def test_success(self, client):
        u = _user()
        rt = _refresh_token()
        db = _make_db(_exec_scalars_all([rt]))
        app.dependency_overrides[get_db] = _db_override(db)
        app.dependency_overrides[get_current_user] = lambda: u

        resp = await client.delete("/api/v1/auth/withdraw")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["success"] is True
        assert body["data"]["user_id"] == str(_USER_ID)
        assert u.is_active is False
        db.commit.assert_awaited_once()


# ── POST /auth/refresh (#42) ──────────────────────────────────────────────────


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_success(self, client):
        rt = _refresh_token()
        db = _make_db(_exec_scalar(rt))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch(
            "app.api.v1.auth.verify_token",
            return_value={"sub": str(_USER_ID), "family_id": str(_FAMILY_ID), "type": "refresh"},
        ):
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "valid_refresh_token"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data

    @pytest.mark.asyncio
    async def test_reuse_after_grace_period_revokes_family(self, client):
        # grace period(10초) 초과한 revoked 토큰 재사용 → 401
        revoked_time = _NOW - timedelta(seconds=20)
        rt = _refresh_token(revoked_at=revoked_time)
        active_rt = _refresh_token()
        db = _make_db(
            _exec_scalar(rt),
            _exec_scalars_all([active_rt]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        with patch(
            "app.api.v1.auth.verify_token",
            return_value={"sub": str(_USER_ID), "family_id": str(_FAMILY_ID), "type": "refresh"},
        ):
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "reused_token"})

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_token_not_found_returns_401(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        with patch(
            "app.api.v1.auth.verify_token",
            return_value={"sub": str(_USER_ID), "family_id": str(_FAMILY_ID), "type": "refresh"},
        ):
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "unknown_token"})

        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_signature_returns_401(self, client):
        from app.core.exceptions import UnauthorizedError

        app.dependency_overrides[get_db] = _db_override(_make_db())

        with patch("app.api.v1.auth.verify_token", side_effect=UnauthorizedError()):
            resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "tampered.token"})

        assert resp.status_code == 401
