"""헬스장 도메인 엔드포인트 테스트 (#18-20, #44-45).

카카오 로컬 API는 httpx mock으로 대체한다.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Equipment, Gym, GymEquipment, User

_USER_ID = uuid.uuid4()
_GYM_ID = uuid.uuid4()
_EQUIPMENT_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

_KAKAO_DOCUMENT = {
    "id": "12345",
    "place_name": "테스트 헬스장",
    "road_address_name": "서울 강남구 테헤란로",
    "y": "37.4979",
    "x": "127.0276",
}


def _mock_user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _mock_gym() -> Gym:
    g = MagicMock(spec=Gym)
    g.id = _GYM_ID
    g.name = "테스트 헬스장"
    g.address = "서울 강남구"
    g.latitude = 37.4979
    g.longitude = 127.0276
    g.kakao_place_id = "12345"
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


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalars_all(values):
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _exec_scalars_unique_all(values):
    r = MagicMock()
    r.scalars.return_value.unique.return_value.all.return_value = values
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


def _kakao_mock_ctx(documents: list):
    """카카오 API 응답을 반환하는 httpx.AsyncClient mock."""
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"documents": documents}

    mock_http = AsyncMock()
    mock_http.get.return_value = mock_resp

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


def _kakao_error_ctx():
    """카카오 API 실패 응답을 반환하는 mock."""
    mock_resp = MagicMock()
    mock_resp.is_success = False
    mock_resp.status_code = 500

    mock_http = AsyncMock()
    mock_http.get.return_value = mock_resp

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_http)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


_MOCK_USER = _mock_user()


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


_GYM_BODY = {
    "kakao_place_id": "12345",
    "name": "테스트 헬스장",
    "address": "서울 강남구 테헤란로",
    "latitude": 37.4979,
    "longitude": 127.0276,
}


# ── POST /gyms ────────────────────────────────────────────────────────────────


class TestCreateGym:
    @pytest.mark.asyncio
    async def test_new_gym_returns_201(self, client):
        """신규 헬스장 등록 시 201 반환."""
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/gyms", json=_GYM_BODY)

        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert "gym_id" in body["data"]
        assert body["data"]["name"] == "테스트 헬스장"
        assert body["data"]["message"] == "헬스장이 등록되었습니다."

    @pytest.mark.asyncio
    async def test_existing_gym_returns_200(self, client):
        """이미 등록된 헬스장은 200 반환."""
        db = _make_db(_exec_scalar(_mock_gym()))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post("/api/v1/gyms", json=_GYM_BODY)

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["gym_id"] == str(_GYM_ID)
        assert body["data"]["message"] == "이미 등록된 헬스장입니다."

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_400(self, client):
        """필수 필드 누락 시 400."""
        resp = await client.post("/api/v1/gyms", json={"name": "헬스장만"})
        assert resp.status_code == 400


# ── GET /gyms?keyword= ────────────────────────────────────────────────────────


class TestSearchGyms:
    @pytest.mark.asyncio
    async def test_success_with_results(self, client):
        db = _make_db(_exec_scalars_all([]))  # no existing gyms in DB
        app.dependency_overrides[get_db] = _db_override(db)

        mock_settings = MagicMock()
        mock_settings.KAKAO_REST_API_KEY = "test-key"

        with (
            patch("app.api.v1.gyms.get_settings", return_value=mock_settings),
            patch("app.api.v1.gyms.httpx.AsyncClient", return_value=_kakao_mock_ctx([_KAKAO_DOCUMENT])),
        ):
            resp = await client.get("/api/v1/gyms?keyword=헬스장")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["name"] == "테스트 헬스장"
        assert body["data"]["items"][0]["kakao_place_id"] == "12345"

    @pytest.mark.asyncio
    async def test_kakao_api_failure(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        mock_settings = MagicMock()
        mock_settings.KAKAO_REST_API_KEY = "test-key"

        with (
            patch("app.api.v1.gyms.get_settings", return_value=mock_settings),
            patch("app.api.v1.gyms.httpx.AsyncClient", return_value=_kakao_error_ctx()),
        ):
            resp = await client.get("/api/v1/gyms?keyword=헬스장")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_no_kakao_key(self, client):
        mock_settings = MagicMock()
        mock_settings.KAKAO_REST_API_KEY = ""

        with patch("app.api.v1.gyms.get_settings", return_value=mock_settings):
            resp = await client.get("/api/v1/gyms?keyword=헬스장")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_missing_keyword_param(self, client):
        resp = await client.get("/api/v1/gyms")
        assert resp.status_code == 400


# ── GET /gyms/{gymId}/equipment ───────────────────────────────────────────────


class TestListGymEquipment:
    @pytest.mark.asyncio
    async def test_success(self, client):
        gym = _mock_gym()
        equipment = _mock_equipment()

        gym_eq = MagicMock(spec=GymEquipment)
        gym_eq.equipment = equipment
        gym_eq.equipment.brand = MagicMock()
        gym_eq.equipment.brand.name = "Life Fitness"

        db = _make_db(
            _exec_scalar(gym),
            _exec_scalars_unique_all([gym_eq]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/gyms/{_GYM_ID}/equipment")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_gym_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/gyms/{uuid.uuid4()}/equipment")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_gym_id(self, client):
        resp = await client.get("/api/v1/gyms/not-a-uuid/equipment")
        assert resp.status_code == 400


# ── POST /gyms/{gymId}/equipment/report ──────────────────────────────────────


class TestReportEquipment:
    @pytest.mark.asyncio
    async def test_success(self, client):
        gym = _mock_gym()
        equipment = _mock_equipment()

        db = _make_db(
            _exec_scalar(gym),
            _exec_scalar(equipment),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment/report",
            json={
                "equipment_id": str(_EQUIPMENT_ID),
                "report_type": "broken",
                "description": "기계 고장",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_gym_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{uuid.uuid4()}/equipment/report",
            json={"equipment_id": str(_EQUIPMENT_ID), "report_type": "broken", "description": "고장"},
        )

        assert resp.status_code == 404
