"""admin /rag/ingest — collection override 단위 테스트 (C8).

monkeypatch로 ChromaDB + DB를 완전히 격리.
실제 소켓/DB 연결 없이 collection routing 로직만 검증한다.
"""

from __future__ import annotations

import pytest

ADMIN_TOKEN = "test-admin-token"

# ── 최소 유효 ChunkIngestPayload ────────────────────────────────────────────
_CHUNK = {
    "paper_doi": "10.1234/test",
    "paper_pmid": "12345",
    "paper_title": "Test Paper",
    "section_name": "Methods",
    "chunk_index": 0,
    "content": "Test content for collection override test.",
    "token_count": 10,
    "embedding": [0.1] * 1024,
    "search_categories": ["strength"],
    "publication_types": ["Journal Article"],
    "evidence_weight": 0.5,
    "fulltext_source": "pmc",
    "published_year": 2023,
}


# ── helpers ─────────────────────────────────────────────────────────────────


class _FakeCollection:
    """ChromaDB Collection 대역."""

    def __init__(self, name: str, received: dict):
        self.name = name
        self._received = received

    def upsert(self, **kwargs):
        self._received["upsert_called"] = True
        self._received["upsert_count"] = len(kwargs.get("ids", []))

    def count(self):
        return self._received.get("upsert_count", 0)


class _FakeChromaClient:
    """chromadb.PersistentClient 대역."""

    def __init__(self, received: dict):
        self._received = received

    def get_or_create_collection(self, name: str, metadata=None):
        self._received["collection_name"] = name
        return _FakeCollection(name, self._received)


def _patch_db(monkeypatch):
    """AsyncSession.execute / commit을 no-op으로 교체.

    monkeypatch.setattr은 unbound method 패치 시 self가 첫 인자로 전달되므로
    lambda self, *a, **kw: None 형태가 필요하다.
    코루틴 반환이 필요하지 않은 경우 asyncio.coroutine 대신 async lambda와 동등한
    래퍼를 사용한다.
    """

    async def _noop_execute(self, *args, **kwargs):
        return None

    async def _noop_commit(self):
        return None

    monkeypatch.setattr("sqlalchemy.ext.asyncio.AsyncSession.execute", _noop_execute)
    monkeypatch.setattr("sqlalchemy.ext.asyncio.AsyncSession.commit", _noop_commit)


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_default_collection_uses_alias(client, monkeypatch):
    """collection 미명시 → _get_collection()(alias-aware 기본값) 경로."""
    received = {}
    fake_col = _FakeCollection("papers", received)

    monkeypatch.setattr("app.api.v1.admin._get_collection", lambda: fake_col)
    _patch_db(monkeypatch)

    resp = await client.post(
        "/api/v1/admin/rag/ingest",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"chunks": [_CHUNK]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["upserted"] == 1
    assert received.get("upsert_called") is True
    # named collection 경로를 타지 않았으므로 collection_name 키 없음
    assert "collection_name" not in received


@pytest.mark.asyncio
async def test_ingest_explicit_collection_override(client, monkeypatch):
    """body.collection='papers_v2' → alias 무시, 해당 컬렉션에 직접 upsert."""
    received = {}
    fake_client = _FakeChromaClient(received)

    # _chroma_client를 fake로 교체 (None이 아니므로 재생성 분기 건너뜀)
    monkeypatch.setattr("app.api.v1.admin._chroma_client", fake_client)
    _patch_db(monkeypatch)

    resp = await client.post(
        "/api/v1/admin/rag/ingest",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"chunks": [_CHUNK], "collection": "papers_v2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["upserted"] == 1
    assert received.get("collection_name") == "papers_v2"
    assert received.get("upsert_called") is True


@pytest.mark.asyncio
async def test_ingest_empty_collection_string_uses_default(client, monkeypatch):
    """collection='' 또는 공백 → strip 후 falsy → alias 기본값 경로."""
    received = {}
    fake_col = _FakeCollection("papers", received)

    monkeypatch.setattr("app.api.v1.admin._get_collection", lambda: fake_col)
    _patch_db(monkeypatch)

    for empty_val in ("", "   "):
        received.clear()
        resp = await client.post(
            "/api/v1/admin/rag/ingest",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"chunks": [_CHUNK], "collection": empty_val},
        )
        assert resp.status_code == 200, f"collection={empty_val!r} → expected 200"
        assert resp.json()["success"] is True
        assert received.get("upsert_called") is True
        assert "collection_name" not in received


@pytest.mark.asyncio
async def test_ingest_whitespace_trimmed_collection_uses_named(client, monkeypatch):
    """collection='  papers_v2  ' → strip → 'papers_v2' → named 경로."""
    received = {}
    fake_client = _FakeChromaClient(received)

    monkeypatch.setattr("app.api.v1.admin._chroma_client", fake_client)
    _patch_db(monkeypatch)

    resp = await client.post(
        "/api/v1/admin/rag/ingest",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"chunks": [_CHUNK], "collection": "  papers_v2  "},
    )
    assert resp.status_code == 200
    assert received.get("collection_name") == "papers_v2"
    assert received.get("upsert_called") is True


@pytest.mark.asyncio
async def test_ingest_no_token_rejected(client):
    """X-Admin-Token 없으면 400 (RequiredValidationError → VALIDATION_ERROR)."""
    resp = await client.post(
        "/api/v1/admin/rag/ingest",
        json={"chunks": [_CHUNK], "collection": "papers_v2"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_ingest_wrong_token_rejected(client):
    """잘못된 토큰은 403."""
    resp = await client.post(
        "/api/v1/admin/rag/ingest",
        headers={"X-Admin-Token": "wrong-token"},
        json={"chunks": [_CHUNK]},
    )
    assert resp.status_code == 403
