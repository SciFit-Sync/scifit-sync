"""POST /api/v1/admin/rag/collection-swap 테스트.

conftest.py가 ADMIN_API_TOKEN을 'test-admin-token'으로 설정한다 — 동일 패턴 재사용.
"""

import json

import pytest

from app.api.v1 import admin as admin_mod

ADMIN_TOKEN = "test-admin-token"


class _FakeColEntry:
    """list_collections용 가짜 collection 항목."""

    def __init__(self, name):
        self.name = name


class _AnyCollectionFakeClient:
    """F1 검증: 어떤 collection 이름이든 존재한다고 응답하는 fake client.

    기존 swap 테스트는 collection 이름 검증보다 atomic-write / alias 파일 내용을
    검증하므로, 존재 여부와 무관하게 swap 로직을 통과시키는 fake가 적절하다.
    """

    def list_collections(self):
        # 어떤 target이든 통과시킨다 (기존 테스트 동작 보존)
        return [_FakeColEntry("papers"), _FakeColEntry("papers_v2"), _FakeColEntry("papers_v3"), _FakeColEntry("papers_v4")]


@pytest.fixture
def alias_path(tmp_path, monkeypatch):
    """ALIAS_FILE을 tmp_path로 가리킨 뒤 keyed cache를 비워 다음 swap이 즉시 반영되게 한다.

    F1 fix 이후 swap_collection이 _chroma_client.list_collections()를 호출하므로
    테스트 환경에서 실제 ChromaDB PersistentClient 초기화를 피하기 위해
    _chroma_client도 fake로 교체한다.
    """
    p = tmp_path / "current_alias.json"
    monkeypatch.setattr("app.services.rag.ALIAS_FILE", p)
    monkeypatch.setattr("app.services.rag._collection_cache", {})
    monkeypatch.setattr(admin_mod, "_chroma_client", _AnyCollectionFakeClient())
    return p


@pytest.mark.asyncio
async def test_swap_updates_alias_file(client, alias_path):
    """올바른 토큰 + 유효 target → 200 + alias 파일 atomic write."""
    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"to": "papers_v2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["current"] == "papers_v2"
    assert "swapped_at" in body["data"]

    saved = json.loads(alias_path.read_text())
    assert saved["current"] == "papers_v2"


@pytest.mark.asyncio
async def test_swap_rejects_without_admin_token(client, alias_path):
    """X-Admin-Token 누락 → 400/401/403 중 하나로 거부."""
    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        json={"to": "papers_v2"},
    )
    assert r.status_code in (400, 401, 403)


@pytest.mark.asyncio
async def test_swap_rejects_empty_target(client, alias_path):
    """빈 문자열/공백만 있는 target은 400 VALIDATION_ERROR."""
    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"to": "   "},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_swap_leaves_no_tmp_file(client, alias_path):
    """swap 완료 후 .tmp 파일이 남아있지 않음 — M3 fix: unique tmp → atomic replace."""
    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"to": "papers_v3"},
    )
    assert r.status_code == 200
    # alias_path의 부모 디렉토리에 .tmp 잔여물이 없어야 함
    tmp_files = list(alias_path.parent.glob("*.tmp"))
    assert tmp_files == [], f".tmp 파일이 남아있음: {tmp_files}"


@pytest.mark.asyncio
async def test_swap_unique_tmp_even_under_rapid_calls(client, alias_path):
    """연속 swap 호출 후 .tmp 파일이 남지 않는다 — M3 잔여 픽스: uuid4 suffix로 충돌 방지.

    pid+ms timestamp 방식은 동일 프로세스 동시 요청에서 동일 ms에 충돌 가능.
    uuid4.hex suffix는 이 가능성을 제거한다.
    """
    for target in ["papers_v2", "papers_v3", "papers_v4"]:
        r = await client.post(
            "/api/v1/admin/rag/collection-swap",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"to": target},
        )
        assert r.status_code == 200, r.text

    # 모든 swap 완료 후 .tmp 잔여물 없어야 함
    leftover_tmps = list(alias_path.parent.glob("*.tmp"))
    assert leftover_tmps == [], f".tmp 파일 잔여: {leftover_tmps}"

    # 마지막 alias는 papers_v4여야 함
    import json as _json

    saved = _json.loads(alias_path.read_text())
    assert saved["current"] == "papers_v4"


@pytest.mark.asyncio
async def test_swap_rejects_nonexistent_collection(client, alias_path, monkeypatch):
    """target collection이 ChromaDB에 없으면 404 반환 — F1 fix: 오타로 인한 500 회귀 방지.

    alias_path fixture가 주입한 _AnyCollectionFakeClient를 "papers만 있는" fake로 재override.
    """

    class _LimitedFakeClient:
        def list_collections(self):
            return [_FakeColEntry("papers"), _FakeColEntry("paper_chunks")]

    monkeypatch.setattr(admin_mod, "_chroma_client", _LimitedFakeClient())

    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"to": "papers_typo"},
    )
    assert r.status_code == 404, r.text
    # envelope({"success":false,"error":{...}}) or raw({"detail":...}) 모두 지원
    assert "papers_typo" in json.dumps(r.json(), ensure_ascii=False)


@pytest.mark.asyncio
async def test_swap_succeeds_when_collection_exists(client, alias_path, monkeypatch):
    """target collection이 ChromaDB에 존재하면 swap이 정상 처리된다 — F1 fix 회귀.

    alias_path fixture가 주입한 fake client에 papers_v2가 있으므로 그대로 통과.
    """
    r = await client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={"to": "papers_v2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["current"] == "papers_v2"
