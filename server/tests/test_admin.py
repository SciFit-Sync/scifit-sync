"""Admin endpoint tests — ADMIN_API_TOKEN 인증 + /rag/dois 조회.

conftest.py가 ADMIN_API_TOKEN을 'test-admin-token'으로 설정한다.
"""

import pytest

ADMIN_TOKEN = "test-admin-token"


@pytest.mark.asyncio
async def test_list_dois_missing_admin_token(client):
    """X-Admin-Token 헤더 없으면 422 (Header(...) 필수)."""
    resp = await client.get("/api/v1/admin/rag/dois")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_dois_rejects_bad_token(client):
    """잘못된 토큰은 403."""
    resp = await client.get("/api/v1/admin/rag/dois", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_dois_returns_envelope(client):
    """올바른 토큰 → 200 + 표준 success envelope. clean test DB 기준 빈 list."""
    resp = await client.get("/api/v1/admin/rag/dois", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "dois" in data
    assert "count" in data
    assert isinstance(data["dois"], list)
    assert data["count"] == len(data["dois"])
