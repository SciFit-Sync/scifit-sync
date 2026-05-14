"""루틴 API 엔드포인트 테스트 (GET/PATCH/DELETE/SSE).

DB 커넥션과 인증을 FastAPI dependency_overrides로 대체하여
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
from app.models import User
from app.models.routine import (
    GeneratedBy,
    RoutineExercise,
    RoutineStatus,
    SplitType,
    WorkoutRoutine,
)

# ── 상수 ──────────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_ROUTINE_ID = uuid.uuid4()
_EXERCISE_ID = uuid.uuid4()
_REX_ID = uuid.uuid4()  # routine_exercise_id
_PAPER_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)

# ── 목 생성 헬퍼 ──────────────────────────────────────────────────────────────


def _user() -> User:
    u = MagicMock(spec=User)
    u.id = _USER_ID
    u.username = "taehyun"
    return u


def _routine() -> WorkoutRoutine:
    r = MagicMock(spec=WorkoutRoutine)
    r.id = _ROUTINE_ID
    r.user_id = _USER_ID
    r.name = "테스트 루틴"
    r.fitness_goals = ["hypertrophy"]
    r.split_type = SplitType.TWO
    r.generated_by = GeneratedBy.AI
    r.status = RoutineStatus.ACTIVE
    r.created_at = _NOW
    r.updated_at = _NOW
    r.deleted_at = None
    r.target_muscle_group_ids = []
    r.session_duration_minutes = 60
    r.ai_reasoning = None
    return r


def _routine_exercise() -> RoutineExercise:
    rex = MagicMock(spec=RoutineExercise)
    rex.id = _REX_ID
    rex.exercise_id = _EXERCISE_ID
    rex.equipment_id = None
    rex.order_index = 0
    rex.sets = 3
    rex.reps_min = 8
    rex.reps_max = 12
    rex.weight_kg = 60.0
    rex.rest_seconds = 90
    rex.note = None
    return rex


# execute() 반환값 헬퍼 ─────────────────────────────────────────────────────


def _exec_scalar(value):
    """scalar_one_or_none() 반환."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _exec_scalars_all(values):
    """scalars().all() 반환."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = values
    return r


def _exec_scalars_unique_all(values):
    """scalars().unique().all() 반환 (selectinload 쿼리용)."""
    r = MagicMock()
    r.scalars.return_value.unique.return_value.all.return_value = values
    return r


def _exec_all(rows):
    """.all() 반환 (조인 쿼리용)."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _make_db(*side_effects):
    """주어진 side_effect 순서로 execute()를 응답하는 목 AsyncSession."""
    db = AsyncMock()
    db.execute.side_effect = list(side_effects)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _db_override(mock_db):
    """get_db dependency override (async generator)."""

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


# ── GET /routines ─────────────────────────────────────────────────────────────


class TestListRoutines:
    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        db = _make_db(_exec_scalars_all([]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/routines")

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_returns_routine_summaries(self, client):
        r = _routine()
        db = _make_db(_exec_scalars_all([r]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/routines")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["routine_id"] == str(_ROUTINE_ID)
        assert items[0]["name"] == "테스트 루틴"
        assert items[0]["fitness_goals"] == ["hypertrophy"]
        assert items[0]["status"] == "active"

    @pytest.mark.asyncio
    async def test_multiple_routines(self, client):
        r1 = _routine()
        r2 = _routine()
        r2.id = uuid.uuid4()
        r2.name = "루틴2"
        db = _make_db(_exec_scalars_all([r1, r2]))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/routines")

        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 2


# ── GET /routines/{id} ────────────────────────────────────────────────────────


class TestGetRoutine:
    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client):
        # _get_my_routine → None
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get("/api/v1/routines/not-a-uuid")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_success_no_days(self, client):
        r = _routine()
        # _get_my_routine, RoutineDay 쿼리 (일수 없음), RoutinePaper 쿼리
        db = _make_db(
            _exec_scalar(r),
            _exec_scalars_unique_all([]),
            _exec_all([]),  # RoutinePaper (has_paper)
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["routine_id"] == str(_ROUTINE_ID)
        assert data["days"] == []
        assert data["session_duration_minutes"] == 60

    @pytest.mark.asyncio
    async def test_success_with_exercises(self, client):
        r = _routine()
        rex = _routine_exercise()

        day = MagicMock()
        day.id = uuid.uuid4()
        day.day_number = 1
        day.label = "가슴"
        day.exercises = [rex]

        # _get_my_routine, RoutineDay+exercises, Exercise names, Equipment names
        db = _make_db(
            _exec_scalar(r),
            _exec_scalars_unique_all([day]),
            _exec_all([(_EXERCISE_ID, "벤치프레스")]),
            _exec_all([]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["days"]) == 1
        exercises = data["days"][0]["exercises"]
        assert len(exercises) == 1
        assert exercises[0]["exercise_name"] == "벤치프레스"
        assert exercises[0]["sets"] == 3


# ── PATCH /routines/{id}/name ─────────────────────────────────────────────────


class TestRenameRoutine:
    @pytest.mark.asyncio
    async def test_success(self, client):
        r = _routine()
        db = _make_db(_exec_scalar(r))
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/name",
            json={"name": "새 루틴 이름"},
        )

        assert resp.status_code == 200
        assert r.name == "새 루틴 이름"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/name",
            json={"name": "이름"},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_name_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/name",
            json={"name": ""},
        )

        assert resp.status_code == 400


# ── PATCH /routines/{id}/exercises/{exId} ─────────────────────────────────────


class TestUpdateRoutineExercise:
    @pytest.mark.asyncio
    async def test_success(self, client):
        r = _routine()
        rex = _routine_exercise()
        new_ex = MagicMock()
        new_ex.id = _EXERCISE_ID
        new_ex.name = "스쿼트"

        db = _make_db(
            _exec_scalar(r),  # _get_my_routine
            _exec_scalar(rex),  # RoutineExercise 조회
            _exec_scalar(new_ex),  # 교체할 Exercise 조회
        )
        db.refresh = AsyncMock(side_effect=lambda obj: None)
        app.dependency_overrides[get_db] = _db_override(db)

        new_exercise_id = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}",
            json={"new_exercise_id": new_exercise_id},
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["message"] == "종목이 교체되었습니다."
        assert data["new_exercise"]["name"] == "스쿼트"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_routine_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}",
            json={"new_exercise_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_exercise_not_found(self, client):
        r = _routine()
        db = _make_db(
            _exec_scalar(r),  # _get_my_routine
            _exec_scalar(None),  # RoutineExercise 없음
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}",
            json={"new_exercise_id": str(uuid.uuid4())},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_new_exercise_id_returns_400(self, client):
        db = _make_db()
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.patch(
            f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}",
            json={},
        )

        assert resp.status_code == 400


# ── DELETE /routines/{id} ─────────────────────────────────────────────────────


class TestDeleteRoutine:
    @pytest.mark.asyncio
    async def test_success_soft_delete(self, client):
        r = _routine()
        db = _make_db(_exec_scalar(r))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.delete(f"/api/v1/routines/{_ROUTINE_ID}")

        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # soft delete 확인
        assert r.deleted_at is not None
        assert r.status == RoutineStatus.ARCHIVED
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.delete(f"/api/v1/routines/{_ROUTINE_ID}")

        assert resp.status_code == 404


# ── GET /routines/{id}/exercises/{exId}/paper ─────────────────────────────────


class TestGetRoutineExercisePapers:
    @pytest.mark.asyncio
    async def test_no_papers(self, client):
        r = _routine()
        db = _make_db(
            _exec_scalar(r),  # _get_my_routine
            _exec_all([]),  # RoutinePaper + Paper 조인
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}/paper")

        assert resp.status_code == 200
        assert resp.json()["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_returns_paper_items(self, client):
        r = _routine()

        rp = MagicMock()
        rp.relevance_summary = "근거 요약"
        paper = MagicMock()
        paper.id = _PAPER_ID
        paper.title = "운동 효과 논문"
        paper.authors = "Kim et al."
        paper.journal = "JSCR"
        paper.year = 2023
        paper.doi = "10.1000/test"
        paper.pmid = "12345"

        db = _make_db(
            _exec_scalar(r),
            _exec_all([(rp, paper)]),
        )
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}/paper")

        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["title"] == "운동 효과 논문"
        assert items[0]["relevance_summary"] == "근거 요약"

    @pytest.mark.asyncio
    async def test_routine_not_found(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.get(f"/api/v1/routines/{_ROUTINE_ID}/exercises/{_REX_ID}/paper")

        assert resp.status_code == 404


# ── POST /routines/generate (SSE) ─────────────────────────────────────────────


class TestGenerateRoutine:
    @pytest.mark.asyncio
    async def test_returns_sse_content_type(self, client):
        # generate는 DB 불필요 (get_current_user만 필요)
        resp = await client.post(
            "/api/v1/routines/generate",
            json={"goals": ["hypertrophy"], "split_type": "2split"},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_stream_contains_started_event(self, client):
        resp = await client.post(
            "/api/v1/routines/generate",
            json={"goals": ["strength"]},
        )

        body = resp.text
        assert "started" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_missing_goals_returns_400(self, client):
        resp = await client.post(
            "/api/v1/routines/generate",
            json={},
        )

        assert resp.status_code == 400


# ── POST /routines/{id}/regenerate (SSE) ──────────────────────────────────────


class TestRegenerateRoutine:
    @pytest.mark.asyncio
    async def test_returns_sse_content_type(self, client):
        r = _routine()
        db = _make_db(_exec_scalar(r))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/routines/{_ROUTINE_ID}/regenerate",
            json={"feedback": "등 운동 더 추가해줘"},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_stream_contains_started_event(self, client):
        r = _routine()
        db = _make_db(_exec_scalar(r))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/routines/{_ROUTINE_ID}/regenerate",
            json={},
        )

        body = resp.text
        assert "started" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_routine_not_found_returns_404(self, client):
        db = _make_db(_exec_scalar(None))
        app.dependency_overrides[get_db] = _db_override(db)

        resp = await client.post(
            f"/api/v1/routines/{_ROUTINE_ID}/regenerate",
            json={},
        )

        assert resp.status_code == 404
