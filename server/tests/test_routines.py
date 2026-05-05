import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from datetime import datetime, timezone

from app.services.routine import (
    delete_routine,
    get_exercise_paper,
    get_routine_detail,
    list_routines,
    rename_routine,
    replace_exercise,
)
from app.core.exceptions import ForbiddenError, NotFoundError


def make_routine(user_id=None, deleted_at=None):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.user_id = user_id or uuid.uuid4()
    r.name = "테스트 루틴"
    r.fitness_goal = "hypertrophy"
    r.deleted_at = deleted_at
    r.days = []
    r.papers = []
    r.created_at = datetime(2026, 1, 1)
    return r


class TestListRoutines:
    @pytest.mark.asyncio
    async def test_returns_routines(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        routines_result = MagicMock()
        routines_result.scalars.return_value.all.return_value = [routine]

        db.execute.side_effect = [count_result, routines_result]

        routines, total = await list_routines(db, user_id, goal=None, page=0, size=10)
        assert total == 1
        assert routines[0] is routine

    @pytest.mark.asyncio
    async def test_empty_result(self):
        db = AsyncMock()
        user_id = uuid.uuid4()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        routines_result = MagicMock()
        routines_result.scalars.return_value.all.return_value = []

        db.execute.side_effect = [count_result, routines_result]

        routines, total = await list_routines(db, user_id, goal=None, page=0, size=10)
        assert total == 0
        assert routines == []


class TestGetRoutineDetail:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await get_routine_detail(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_forbidden(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=uuid.uuid4())

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await get_routine_detail(db, routine.id, user_id)

    @pytest.mark.asyncio
    async def test_success(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        found = await get_routine_detail(db, routine.id, user_id)
        assert found is routine


class TestRenameRoutine:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await rename_routine(db, uuid.uuid4(), uuid.uuid4(), "새 이름")

    @pytest.mark.asyncio
    async def test_forbidden(self):
        db = AsyncMock()
        routine = make_routine(user_id=uuid.uuid4())

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await rename_routine(db, routine.id, uuid.uuid4(), "새 이름")

    @pytest.mark.asyncio
    async def test_success(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        updated = await rename_routine(db, routine.id, user_id, "새 이름")
        assert updated.name == "새 이름"
        db.commit.assert_awaited_once()


class TestDeleteRoutine:
    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await delete_routine(db, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_forbidden(self):
        db = AsyncMock()
        routine = make_routine(user_id=uuid.uuid4())

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        with pytest.raises(ForbiddenError):
            await delete_routine(db, routine.id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_soft_delete(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)
        routine.deleted_at = None

        result = MagicMock()
        result.scalar_one_or_none.return_value = routine
        db.execute.return_value = result

        deleted = await delete_routine(db, routine.id, user_id)
        assert deleted.deleted_at is not None
        db.commit.assert_awaited_once()


class TestGetExercisePaper:
    @pytest.mark.asyncio
    async def test_routine_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(NotFoundError):
            await get_exercise_paper(db, uuid.uuid4(), uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_paper_not_found(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)

        routine_result = MagicMock()
        routine_result.scalar_one_or_none.return_value = routine
        paper_result = MagicMock()
        paper_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [routine_result, paper_result]

        with pytest.raises(NotFoundError):
            await get_exercise_paper(db, routine.id, uuid.uuid4(), user_id)

    @pytest.mark.asyncio
    async def test_success(self):
        db = AsyncMock()
        user_id = uuid.uuid4()
        routine = make_routine(user_id=user_id)

        routine_paper = MagicMock()
        routine_paper.paper = MagicMock()

        routine_result = MagicMock()
        routine_result.scalar_one_or_none.return_value = routine
        paper_result = MagicMock()
        paper_result.scalar_one_or_none.return_value = routine_paper
        db.execute.side_effect = [routine_result, paper_result]

        found = await get_exercise_paper(db, routine.id, uuid.uuid4(), user_id)
        assert found is routine_paper
