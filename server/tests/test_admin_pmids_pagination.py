"""GET /api/v1/admin/rag/pmids 페이지네이션 테스트."""

import pytest

ADMIN_TOKEN = "test-admin-token"


class _FakeCol:
    """1000개 청크 fake ChromaDB collection."""

    def __init__(self, n: int = 1000):
        self._n = n
        self._metadatas = [{"paper_pmid": f"{i:08d}"} for i in range(n)]
        self._ids = [f"chunk_{i}" for i in range(n)]

    def count(self) -> int:
        return self._n

    def get(self, limit=None, offset=None, include=None, **kw):
        start = offset or 0
        end = start + (limit if limit is not None else self._n)
        return {
            "ids": self._ids[start:end],
            "metadatas": self._metadatas[start:end],
        }


@pytest.fixture
def fake_collection(monkeypatch):
    """admin._get_collection이 fake collection을 반환하도록 monkeypatch."""
    col = _FakeCol()
    monkeypatch.setattr("app.api.v1.admin._get_collection", lambda: col)
    return col


@pytest.mark.asyncio
async def test_pmids_paginated(client, fake_collection):
    """limit=10, offset=0 → 10개 이하 반환 + 페이지 메타 포함."""
    r = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=0",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    data = body["data"]
    assert len(data["pmids"]) <= 10
    assert "total" in data
    assert "has_next" in data
    assert data["limit"] == 10
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_pmids_offset_advances(client, fake_collection):
    """offset=0과 offset=10은 겹치지 않는 pmid 집합을 반환한다."""
    r1 = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=0",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    r2 = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=10",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    pmids1 = set(r1.json()["data"]["pmids"])
    pmids2 = set(r2.json()["data"]["pmids"])
    assert pmids1.isdisjoint(pmids2), "다른 페이지에 동일 pmid가 존재해서는 안 됨"


@pytest.mark.asyncio
async def test_pmids_has_next_false_on_last_page(client, fake_collection):
    """마지막 페이지(offset+limit >= total)에서 has_next는 False."""
    r = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=990",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    body = r.json()
    assert body["data"]["has_next"] is False
