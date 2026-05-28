"""ChromaDB graceful shutdown — lifespan 종료 시 alias cache + client 정리."""

from app.api.v1 import admin as admin_mod
from app.main import app
from app.services import rag


def test_testclient_shutdown_clears_chroma_state():
    """TestClient context exit(shutdown) 후 rag._collection_cache / rag._client 모두 cleared."""
    from fastapi.testclient import TestClient

    # 진입 전 캐시에 dummy 값 주입
    rag._collection_cache["dummy"] = object()
    rag._client = object()

    with TestClient(app) as tc:
        tc.get("/health")  # startup 보장

    # context exit → lifespan shutdown 트리거
    assert rag._collection_cache == {}, "shutdown 후 _collection_cache가 비어있어야 함"
    assert rag._client is None, "shutdown 후 _client가 None이어야 함"


def test_lifespan_closes_admin_writer():
    """shutdown에서 admin._chroma_client도 None 처리 — B2 fix 검증."""
    from fastapi.testclient import TestClient

    # 진입 전 양쪽에 placeholder 주입
    rag._client = object()
    admin_mod._chroma_client = object()

    with TestClient(app) as tc:
        tc.get("/health")

    # context exit → lifespan shutdown 트리거
    assert rag._client is None, "shutdown 후 rag._client가 None이어야 함"
    assert admin_mod._chroma_client is None, "shutdown 후 admin._chroma_client가 None이어야 함 (B2)"
