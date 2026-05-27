"""Admin endpoint tests — ADMIN_API_TOKEN 인증 + /rag/dois 조회.

conftest.py가 ADMIN_API_TOKEN을 'test-admin-token'으로 설정한다.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.database import get_db
from app.main import app

ADMIN_TOKEN = "test-admin-token"


def _db_override(mock_db):
    async def _override():
        yield mock_db

    return _override


@pytest.mark.asyncio
async def test_list_dois_missing_admin_token(client):
    """X-Admin-Token 헤더 없으면 400 — 서버 RequestValidationError 핸들러가
    FastAPI 기본 422를 CLAUDE.md §7의 VALIDATION_ERROR(400)로 매핑한다."""
    resp = await client.get("/api/v1/admin/rag/dois")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_dois_rejects_bad_token(client):
    """잘못된 토큰은 403."""
    resp = await client.get("/api/v1/admin/rag/dois", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_dois_returns_envelope(client):
    """올바른 토큰 → 200 + 표준 success envelope. clean test DB 기준 빈 list."""
    result_mock = MagicMock()
    result_mock.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result_mock

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        resp = await client.get("/api/v1/admin/rag/dois", headers={"X-Admin-Token": ADMIN_TOKEN})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "dois" in data
    assert "count" in data
    assert isinstance(data["dois"], list)
    assert data["count"] == len(data["dois"])
