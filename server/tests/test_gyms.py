"""Gyms 엔드포인트 테스트 (API 명세 #18–20, #44–45).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Equipment, EquipmentReport, Gym, GymEquipment, User
from app.models.user import EquipmentType

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_GYM_ID = uuid.uuid4()
_EQUIPMENT_ID = uuid.uuid4()

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    return u


def _gym() -> Gym:
    g = MagicMock(spec=Gym)
    g.id = _GYM_ID
    g.name = "스쿼트 헬스장"
    g.address = "서울시 마포구"
    g.latitude = 37.5
    g.longitude = 126.9
    g.kakao_place_id = "123456"
    g.gym_equipments = []
    return g


def _equipment() -> Equipment:
    eq = MagicMock(spec=Equipment)
    eq.id = _EQUIPMENT_ID
    eq.name = "바벨"
    eq.name_en = "Barbell"
    eq.category = MagicMock()
    eq.category.value = "chest"
    eq.equipment_type = EquipmentType.BARBELL
    eq.equipment_type.value = "barbell"
    eq.pulley_ratio = 1.0
    eq.bar_weight_kg = 20.0
    eq.has_weight_assist = False
    eq.min_stack_kg = None
    eq.max_stack_kg = None
    eq.stack_weight_kg = None
    eq.image_url = None
    return eq


def _report() -> EquipmentReport:
    r = MagicMock(spec=EquipmentReport)
    r.id = uuid.uuid4()
    r.status = MagicMock()
    r.status.value = "pending"
    return r


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
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _db_override(mock_db):
    async def _override():
        yield mock_db

    return _override


def _kakao_resp(documents: list) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = {"documents": documents}
    return resp


# ── Fixture ───────────────────────────────────────────────────────────────────

_MOCK_USER = _user()


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_current_user] = lambda: _MOCK_USER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── GET /gyms?keyword= (#18) ──────────────────────────────────────────────────


class TestSearchGyms:
    def _patch_kakao(self, documents):
        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(return_value=_kakao_resp(documents))
        return patch("app.api.v1.gyms.httpx.AsyncClient", return_value=kakao_client)

    @pytest.mark.asyncio
    async def test_success_returns_items(self, client):
        docs = [
            {"id": "111", "place_name": "스쿼트 헬스장", "road_address_name": "서울 마포구", "x": "126.9", "y": "37.5"},
        ]
        db = _make_db(_exec_scalars_all([]))  # DB에 매칭 없음
        app.dependency_overrides[get_db] = _db_override(db)

        with (
            self._patch_kakao(docs),
            patch("app.api.v1.gyms.get_settings", return_value=MagicMock(KAKAO_REST_API_KEY="test-key")),
        ):
            resp = await client.get("/api/v1/gyms?keyword=스쿼트")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "스쿼트 헬스장"
        assert items[0]["gym_id"] == ""  # DB 미등록이므로 빈 문자열

    @pytest.mark.asyncio
    async def test_db_matched_gym_has_gym_id(self, client):
        g = _gym()
        g.kakao_place_id = "111"
        docs = [{"id": "111", "place_name": "스쿼트", "road_address_name": "서울", "x": "126.9", "y": "37.5"}]
        db = _make_db(_exec_scalars_all([g]))
        app.dependency_overrides[get_db] = _db_override(db)

        with (
            self._patch_kakao(docs),
            patch("app.api.v1.gyms.get_settings", return_value=MagicMock(KAKAO_REST_API_KEY="test-key")),
        ):
            resp = await client.get("/api/v1/gyms?keyword=스쿼트")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"][0]["gym_id"] == str(_GYM_ID)

    @pytest.mark.asyncio
    async def test_no_kakao_key_returns_503(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        with patch("app.api.v1.gyms.get_settings", return_value=MagicMock(KAKAO_REST_API_KEY="")):
            resp = await client.get("/api/v1/gyms?keyword=헬스")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_kakao_network_error_returns_503(self, client):
        import httpx as _httpx

        app.dependency_overrides[get_db] = _db_override(_make_db())
        kakao_client = AsyncMock()
        kakao_client.__aenter__.return_value.get = AsyncMock(
            side_effect=_httpx.RequestError("timeout", request=MagicMock())
        )
        with (
            patch("app.api.v1.gyms.httpx.AsyncClient", return_value=kakao_client),
            patch("app.api.v1.gyms.get_settings", return_value=MagicMock(KAKAO_REST_API_KEY="test-key")),
        ):
            resp = await client.get("/api/v1/gyms?keyword=헬스")

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_missing_keyword_returns_422(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/gyms")

        assert resp.status_code == 422


# ── GET /gyms/{gymId}/equipment (#19) ────────────────────────────────────────


class TestListGymEquipment:
    @pytest.mark.asyncio
    async def test_success_empty_equipment(self, client):
        g = _gym()
        g.gym_equipments = []
        db = _make_db(_exec_scalar(g))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/gyms/{_GYM_ID}/equipment")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_success_with_equipment(self, client):
        ge = MagicMock()
        ge.equipment_id = _EQUIPMENT_ID
        g = _gym()
        g.gym_equipments = [ge]
        eq = _equipment()
        db = _make_db(
            _exec_scalar(g),
            _exec_scalars_all([eq]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/gyms/{_GYM_ID}/equipment")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "바벨"

    @pytest.mark.asyncio
    async def test_gym_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/gyms/{_GYM_ID}/equipment")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_gym_id_returns_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.get("/api/v1/gyms/not-a-uuid/equipment")

        assert resp.status_code == 400


# ── POST /gyms/{gymId}/equipment/report (#20) ─────────────────────────────────


class TestReportGymEquipment:
    @pytest.mark.asyncio
    async def test_success_returns_201(self, client):
        g = _gym()
        db = _make_db(_exec_scalar(g))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment/report",
            json={
                "equipment_id": str(_EQUIPMENT_ID),
                "report_type": "incorrect_info",
                "description": "중량이 잘못 표기됨",
            },
        )

        assert resp.status_code == 201
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_gym_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment/report",
            json={"equipment_id": str(_EQUIPMENT_ID), "report_type": "incorrect_info"},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_ids_return_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post(
            "/api/v1/gyms/bad-id/equipment/report",
            json={"equipment_id": "also-bad", "report_type": "incorrect_info"},
        )

        assert resp.status_code == 400


# ── POST /gyms (#44) ──────────────────────────────────────────────────────────


class TestCreateGym:
    @pytest.mark.asyncio
    async def test_success_new_gym_returns_201(self, client):
        db = _make_db(_exec_scalar(None))  # kakao_place_id 중복 없음
        db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", _GYM_ID))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/gyms",
            json={
                "name": "새 헬스장",
                "address": "서울시 강남구",
                "latitude": 37.5,
                "longitude": 127.0,
                "kakao_place_id": "999",
            },
        )

        assert resp.status_code == 201
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_existing_kakao_place_returns_existing(self, client):
        g = _gym()
        db = _make_db(_exec_scalar(g))  # 이미 존재
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/gyms",
            json={
                "name": "스쿼트 헬스장",
                "address": "서울시 마포구",
                "latitude": 37.5,
                "longitude": 126.9,
                "kakao_place_id": "123456",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["gym_id"] == str(_GYM_ID)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_kakao_place_id_creates_new(self, client):
        db = _make_db()
        db.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", _GYM_ID))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            "/api/v1/gyms",
            json={"name": "동네 헬스장", "address": "서울 은평구", "latitude": 37.6, "longitude": 126.9},
        )

        assert resp.status_code == 201


# ── POST /gyms/{id}/equipment (#45) ───────────────────────────────────────────


class TestAddGymEquipment:
    @pytest.mark.asyncio
    async def test_success_returns_201(self, client):
        g = _gym()
        eq = _equipment()
        db = _make_db(
            _exec_scalar(g),  # Gym 조회
            _exec_scalar(eq),  # Equipment 조회
            _exec_scalar(None),  # 중복 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 201
        assert resp.json()["data"]["name"] == "바벨"

    @pytest.mark.asyncio
    async def test_gym_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_equipment_not_found_returns_404(self, client):
        g = _gym()
        db = _make_db(
            _exec_scalar(g),
            _exec_scalar(None),  # Equipment 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_equipment_returns_409(self, client):
        g = _gym()
        eq = _equipment()
        existing = MagicMock(spec=GymEquipment)
        db = _make_db(
            _exec_scalar(g),
            _exec_scalar(eq),
            _exec_scalar(existing),  # 이미 존재
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/gyms/{_GYM_ID}/equipment",
            json={"equipment_id": str(_EQUIPMENT_ID)},
        )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_invalid_ids_return_400(self, client):
        app.dependency_overrides[get_db] = _db_override(_make_db())

        resp = await client.post(
            "/api/v1/gyms/bad-id/equipment",
            json={"equipment_id": "also-bad"},
        )

        assert resp.status_code == 400
