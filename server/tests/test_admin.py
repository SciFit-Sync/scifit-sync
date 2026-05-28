"""Admin endpoint tests — ADMIN_API_TOKEN 인증 + /rag/dois 조회.

conftest.py가 ADMIN_API_TOKEN을 'test-admin-token'으로 설정한다.
"""

from unittest.mock import MagicMock

import pytest

from app.api.v1.admin import _fetch_all_metadatas_paged

ADMIN_TOKEN = "test-admin-token"


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
    resp = await client.get("/api/v1/admin/rag/dois", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "dois" in data
    assert "count" in data
    assert isinstance(data["dois"], list)
    assert data["count"] == len(data["dois"])


# ── _fetch_all_metadatas_paged 단위 테스트 (대용량 컬렉션 페이지네이션) ────


def _fake_chroma_collection(total_chunks: int, page_size: int = 1000):
    """offset/limit 응답하는 가짜 collection. metadata에 chunk_index 부여."""
    coll = MagicMock()

    def _get(include=None, limit=None, offset=0):
        end = min(offset + (limit or total_chunks), total_chunks)
        ids = [f"chunk_{i}" for i in range(offset, end)]
        metas = [{"paper_pmid": str(i % 50)} for i in range(offset, end)]
        return {"ids": ids, "metadatas": metas}

    coll.get.side_effect = _get
    return coll


class TestPaginationHelper:
    def test_empty_collection(self):
        coll = _fake_chroma_collection(0)
        ids, metas = _fetch_all_metadatas_paged(coll)
        assert ids == []
        assert metas == []

    def test_single_page(self):
        """페이지 사이즈(1000) 미만이면 한 번에 가져옴."""
        coll = _fake_chroma_collection(500)
        ids, metas = _fetch_all_metadatas_paged(coll)
        assert len(ids) == 500
        assert len(metas) == 500
        assert coll.get.call_count == 1

    def test_exactly_one_page(self):
        """정확히 페이지 사이즈면 한 번 호출 후 빈 페이지로 종료."""
        coll = _fake_chroma_collection(1000)
        ids, _ = _fetch_all_metadatas_paged(coll)
        assert len(ids) == 1000
        # 1000개 → 1000개 받고 빈 페이지 받으러 한 번 더 호출 가능
        assert coll.get.call_count >= 1

    def test_multi_page_accumulation(self):
        """여러 페이지에 걸친 누적 — 대용량 컬렉션 시나리오."""
        coll = _fake_chroma_collection(2500)  # 1000 + 1000 + 500
        ids, metas = _fetch_all_metadatas_paged(coll)
        assert len(ids) == 2500
        assert len(metas) == 2500
        # 페이지가 3번 호출됨 (1000, 1000, 500)
        assert coll.get.call_count == 3

    def test_huge_collection_no_sql_var_error(self):
        """수만개 청크여도 페이지당 1000개라 SQLite 한계 안 걸림."""
        # 30k는 옛 코드에서 InternalError 났던 규모
        coll = _fake_chroma_collection(30000)
        ids, metas = _fetch_all_metadatas_paged(coll)
        assert len(ids) == 30000
        assert len(metas) == 30000
        # 30 페이지로 분할 호출됨
        assert coll.get.call_count == 30
