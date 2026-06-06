"""GET /gyms/{gym_id}/equipments?muscle_group_id= 엔드포인트 테스트.

DB 연결 없이 AsyncMock으로 의존성을 주입한다.
외부 API 호출 없음 (이 엔드포인트는 카카오 API를 사용하지 않음).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Gym, User

_USER_ID = uuid.uuid4()
_GYM_ID = uuid.uuid4()
_MUSCLE_GROUP_ID = uuid.uuid4()
_EQUIPMENT_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()


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


def _exec_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
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


# ── 머신 row mock ──────────────────────────────────────────────────────────────
def _machine_row(
    eq_id=None,
    movement_label_ko="체스트 프레스",
    name="Chest Press Newtech",
    equipment_type="machine",
    image_url=None,
):
    row = MagicMock()
    row.id = eq_id or _EQUIPMENT_ID
    row.movement_label_ko = movement_label_ko
    row.name = name
    row.equipment_type = equipment_type
    row.image_url = image_url
    return row


# ── 프리웨이트 row mock ────────────────────────────────────────────────────────
def _fw_row(
    ex_id=None,
    name="Bench Press",
    name_en="Bench Press",
    eq_id=None,
    equipment_type="barbell",
):
    row = MagicMock()
    row.id = ex_id or _EXERCISE_ID
    row.name = name
    row.name_en = name_en
    row.equipment_id = eq_id or _EQUIPMENT_ID
    row.equipment_type = equipment_type
    return row


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── 정상 케이스: 머신 + 프리웨이트 모두 반환 ──────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_by_muscle_ok(client):
    mock_db = _make_db(
        _exec_scalar(_mock_gym()),  # gym 존재 확인
        _exec_all([_machine_row()]),  # 머신 목록
        _exec_all([_fw_row()]),  # 프리웨이트 목록
    )
    app.dependency_overrides[get_db] = _db_override(mock_db)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID), "involvement": "primary"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert "machines" in data
        assert "free_weights" in data
        assert len(data["machines"]) == 1
        assert len(data["free_weights"]) == 1

        machine = data["machines"][0]
        assert machine["equipment_id"] == str(_EQUIPMENT_ID)
        assert machine["label"] == "체스트 프레스"
        assert machine["equipment_type"] == "machine"

        fw = data["free_weights"][0]
        assert fw["exercise_id"] == str(_EXERCISE_ID)
        assert fw["name"] == "Bench Press"
        assert fw["equipment_type"] == "barbell"
    finally:
        app.dependency_overrides.clear()


# ── 머신 없고 프리웨이트만 반환 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_no_machines(client):
    mock_db = _make_db(
        _exec_scalar(_mock_gym()),
        _exec_all([]),  # 머신 없음
        _exec_all([_fw_row()]),
    )
    app.dependency_overrides[get_db] = _db_override(mock_db)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID)},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["machines"]) == 0
        assert len(body["data"]["free_weights"]) == 1
    finally:
        app.dependency_overrides.clear()


# ── muscle_group_id 미지정 → 400 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_missing_muscle_group(client):
    app.dependency_overrides[get_current_user] = lambda: _mock_user()
    app.dependency_overrides[get_db] = _db_override(AsyncMock())

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


# ── 잘못된 gym_id 형식 → 400 ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_invalid_gym_id(client):
    app.dependency_overrides[get_current_user] = lambda: _mock_user()
    app.dependency_overrides[get_db] = _db_override(AsyncMock())

    try:
        resp = await client.get(
            "/api/v1/gyms/not-a-uuid/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID)},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


# ── 잘못된 muscle_group_id 형식 → 400 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_invalid_muscle_group_id(client):
    app.dependency_overrides[get_current_user] = lambda: _mock_user()
    app.dependency_overrides[get_db] = _db_override(AsyncMock())

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": "bad-uuid"},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


# ── 존재하지 않는 헬스장 → 404 ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_gym_not_found(client):
    mock_db = _make_db(
        _exec_scalar(None),  # gym 없음
    )
    app.dependency_overrides[get_db] = _db_override(mock_db)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID)},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"
    finally:
        app.dependency_overrides.clear()


# ── movement_label_ko 없을 때 name으로 fallback ───────────────────────────────
@pytest.mark.asyncio
async def test_machine_label_falls_back_to_name(client):
    row = _machine_row(movement_label_ko=None, name="Chest Press Newtech")
    mock_db = _make_db(
        _exec_scalar(_mock_gym()),
        _exec_all([row]),
        _exec_all([]),
    )
    app.dependency_overrides[get_db] = _db_override(mock_db)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID)},
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        machine = resp.json()["data"]["machines"][0]
        # movement_label_ko=None → name 사용
        assert machine["label"] == "Chest Press Newtech"
    finally:
        app.dependency_overrides.clear()


# ── involvement 기본값 primary ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_equipments_default_involvement_primary(client):
    mock_db = _make_db(
        _exec_scalar(_mock_gym()),
        _exec_all([]),
        _exec_all([]),
    )
    app.dependency_overrides[get_db] = _db_override(mock_db)
    app.dependency_overrides[get_current_user] = lambda: _mock_user()

    try:
        resp = await client.get(
            f"/api/v1/gyms/{_GYM_ID}/equipments",
            params={"muscle_group_id": str(_MUSCLE_GROUP_ID)},
            # involvement 생략 → 기본값 primary
            headers={"Authorization": "Bearer test"},
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
    finally:
        app.dependency_overrides.clear()
