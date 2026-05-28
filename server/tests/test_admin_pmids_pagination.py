"""GET /api/v1/admin/rag/pmids 페이지네이션 테스트."""

import pytest

ADMIN_TOKEN = "test-admin-token"


class _FakeCol:
    """1000개 청크 fake ChromaDB collection.

    청크 20개당 같은 PMID → unique PMID 50개 (chunk 1000 / 20 = 50).
    """

    def __init__(self, n: int = 1000, chunks_per_pmid: int = 20):
        self._n = n
        self._chunks_per_pmid = chunks_per_pmid
        self._metadatas = [
            {"paper_pmid": f"pmid_{i // chunks_per_pmid:04d}"} for i in range(n)
        ]
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
async def test_pmids_total_is_unique_pmid_count(client, fake_collection):
    """`total`은 chunk 수가 아니라 unique PMID 수여야 한다 (신규 MAJOR 픽스)."""
    r = await client.get(
        "/api/v1/admin/rag/pmids?limit=100&offset=0",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    body = r.json()
    data = body["data"]
    # fake_collection: 1000 chunks, 20 chunks/pmid → 50 unique PMIDs
    assert data["total"] == 50, f"total이 unique PMID 수(50)여야 함, got {data['total']}"
    assert data["total_chunks"] == 1000, "total_chunks는 하위 호환용 chunk 총수"


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
async def test_pmids_no_duplicates_across_pages(client, monkeypatch):
    """페이지 경계에서 PMID 중복/누락 없음 — 신규 MAJOR 픽스 핵심 검증.

    100 chunks, 5 chunks/pmid → 20 unique PMIDs.
    페이지 1(limit=10, offset=0) + 페이지 2(limit=10, offset=10)를 합치면
    중복 없이 정확히 20개여야 한다.
    """

    class _DupFakeCol:
        def count(self):
            return 100

        def get(self, limit=None, offset=None, include=None, **kw):
            metas = [{"paper_pmid": f"pmid_{i // 5:03d}"} for i in range(100)]
            ids = [f"chunk_{i}" for i in range(100)]
            s = offset or 0
            e = s + (limit or 100)
            return {"ids": ids[s:e], "metadatas": metas[s:e]}

    monkeypatch.setattr("app.api.v1.admin._get_collection", lambda: _DupFakeCol())

    r1 = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=0",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    r2 = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=10",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    p1 = set(r1.json()["data"]["pmids"])
    p2 = set(r2.json()["data"]["pmids"])

    # 중복 없음
    assert p1.isdisjoint(p2), f"페이지 경계 PMID 중복: {p1 & p2}"
    # 합치면 20개 unique
    assert len(p1 | p2) == 20, f"합산 unique PMID가 20이어야 함, got {len(p1 | p2)}"
    # total은 unique PMID 수
    assert r1.json()["data"]["total"] == 20


@pytest.mark.asyncio
async def test_pmids_has_next_false_on_last_page(client, fake_collection):
    """마지막 페이지(offset+limit >= total_pmids)에서 has_next는 False.

    fake_collection: 50 unique PMIDs → offset=45, limit=10 이면 마지막 페이지.
    """
    r = await client.get(
        "/api/v1/admin/rag/pmids?limit=10&offset=45",
        headers={"X-Admin-Token": ADMIN_TOKEN},
    )
    body = r.json()
    assert body["data"]["has_next"] is False


@pytest.mark.asyncio
async def test_pmids_no_silent_full_fetch_fallback(client, monkeypatch):
    """limit/offset 미지원 ChromaDB에서 silent full fetch를 허용하지 않음 — M4 fix.

    fallback 제거 후: get()에서 TypeError 발생 시 500 에러(또는 예외 전파)를 반환해야 함.
    silent하게 전체 데이터를 fetch하는 메모리 폭증 path(include만 있는 무인자 get 호출)가
    없어야 한다는 것이 핵심 검증 항목.
    """
    full_fetch_called = []

    class _FullFetchCol:
        """limit/offset을 받으면 TypeError를 raise하는 fake — 구버전 ChromaDB 시뮬레이션."""

        def count(self) -> int:
            return 100

        def get(self, **kw):
            if "limit" in kw or "offset" in kw:
                raise TypeError("get() got unexpected keyword argument 'limit'")
            # 이 경로(include만 있는 전체 fetch)는 절대 호출되면 안 됨 — M4 fallback 제거 확인
            full_fetch_called.append(True)
            return {"ids": [], "metadatas": []}

    col = _FullFetchCol()
    monkeypatch.setattr("app.api.v1.admin._get_collection", lambda: col)

    # fallback 제거 후: TypeError가 500으로 변환되거나 예외로 전파되어야 함
    # 어떤 경우든 silent full fetch(full_fetch_called)가 발생해서는 안 됨
    try:
        r = await client.get(
            "/api/v1/admin/rag/pmids?limit=10",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        # 응답이 왔다면 500이어야 함 (full fetch silent degrade가 아닌 에러)
        assert r.status_code == 500, f"fallback 제거 후 TypeError는 500이어야 함, got {r.status_code}"
    except Exception:
        # asyncio.to_thread TypeError가 테스트 레벨로 전파되는 경우도 허용
        pass

    # 핵심: include만 있는 full fetch path가 호출되지 않았어야 함
    assert full_fetch_called == [], "silent full fetch fallback이 호출됨 — M4 fix 누락"
