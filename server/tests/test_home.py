"""Home 엔드포인트 테스트 (API 명세 #29 GET /home).

DB 커넥션과 인증을 FastAPI dependency_overrides + unittest.mock으로 대체해
외부 인프라 없이 CI에서 실행 가능하다.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.database import get_db
from app.main import app
from app.models import Notification, RoutineStatus, User, WorkoutRoutine

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_ROUTINE_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.name = "장태현"
    return u


def _routine() -> WorkoutRoutine:
    r = MagicMock(spec=WorkoutRoutine)
    r.id = _ROUTINE_ID
    r.name = "주 5일 루틴"
    r.status = RoutineStatus.ACTIVE
    r.deleted_at = None
    r.updated_at = _NOW
    return r


def _routine_day(label: str = "가슴"):
    d = MagicMock()
    d.label = label
    return d


def _notification() -> Notification:
    n = MagicMock(spec=Notification)
    n.id = uuid.uuid4()
    n.type = MagicMock()
    n.type.value = "system"
    n.title = "PO 제안"
    n.body = "중량을 올릴 시간입니다."
    n.is_read = False
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


def _exec_all(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_db(*side_effects):
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
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


# ── GET /home (#29) ───────────────────────────────────────────────────────────


class TestHome:
    @pytest.mark.asyncio
    async def test_success_full_data(self, client):
        """활성 루틴, 최근 볼륨, 알림, 연속 일수 모두 있는 경우."""
        r = _routine()
        day = _routine_day("가슴")
        notif = _notification()
        today = date.today()

        db = _make_db(
            _exec_scalar(r),  # 활성 루틴
            _exec_scalar(day),  # 다음 루틴 day
            _exec_scalar_val(5000.0),  # 최근 7일 볼륨
            _exec_scalars_all([notif]),  # 미확인 알림
            _exec_all([(today,), (today - timedelta(days=1),)]),  # 운동 날짜 목록 (streak=2)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["user_name"] == "장태현"
        assert data["today_routine"]["routine_id"] == str(_ROUTINE_ID)
        assert data["today_routine"]["next_day_label"] == "가슴"
        assert data["recent_volume_kg"] == 5000.0
        assert len(data["upcoming_notifications"]) == 1
        assert data["streak_days"] == 2

    @pytest.mark.asyncio
    async def test_no_active_routine(self, client):
        """활성 루틴이 없으면 today_routine은 None."""
        db = _make_db(
            _exec_scalar(None),  # 활성 루틴 없음
            _exec_scalar_val(0.0),  # 볼륨 0
            _exec_scalars_all([]),  # 알림 없음
            _exec_all([]),  # 운동 기록 없음 (streak=0)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["today_routine"] is None
        assert data["streak_days"] == 0
        assert data["upcoming_notifications"] == []

    @pytest.mark.asyncio
    async def test_routine_without_days(self, client):
        """활성 루틴은 있지만 day가 없는 경우 next_day_label은 None."""
        r = _routine()
        db = _make_db(
            _exec_scalar(r),
            _exec_scalar(None),  # day 없음
            _exec_scalar_val(0.0),
            _exec_scalars_all([]),
            _exec_all([]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        assert resp.json()["data"]["today_routine"]["next_day_label"] is None

    @pytest.mark.asyncio
    async def test_streak_only_yesterday(self, client):
        """오늘은 운동 안 했고 어제부터 연속인 경우 streak 포함."""
        yesterday = date.today() - timedelta(days=1)
        two_days_ago = date.today() - timedelta(days=2)
        db = _make_db(
            _exec_scalar(None),
            _exec_scalar_val(0.0),
            _exec_scalars_all([]),
            _exec_all([(yesterday,), (two_days_ago,)]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        assert resp.json()["data"]["streak_days"] == 2

    @pytest.mark.asyncio
    async def test_streak_broken(self, client):
        """연속이 끊긴 경우 streak=0."""
        old_date = date.today() - timedelta(days=3)
        db = _make_db(
            _exec_scalar(None),
            _exec_scalar_val(0.0),
            _exec_scalars_all([]),
            _exec_all([(old_date,)]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        assert resp.json()["data"]["streak_days"] == 0

    @pytest.mark.asyncio
    async def test_multiple_notifications(self, client):
        """알림 최대 5개 반환 확인."""
        notifs = [_notification() for _ in range(3)]
        db = _make_db(
            _exec_scalar(None),
            _exec_scalar_val(0.0),
            _exec_scalars_all(notifs),
            _exec_all([]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/home")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["upcoming_notifications"]) == 3
