"""rag.py가 alias 파일을 읽어 매 요청마다 적절한 collection 사용."""

import json

import pytest

from app.services import rag


class _FakeCol:
    def count(self):
        return 42


class FakeClientOK:
    """get_collection 성공 fake."""

    def __init__(self):
        self.requested = []

    def get_collection(self, name):
        self.requested.append(name)
        return _FakeCol()


class FakeClientMissing:
    """get_collection이 항상 ValueError를 raise하는 fake."""

    def get_collection(self, name):
        raise ValueError(f"Collection {name} does not exist.")

    # get_or_create_collection은 절대 호출되면 안 됨
    def get_or_create_collection(self, name, metadata=None):
        raise AssertionError("get_or_create_collection should NOT be called (B1 fix)")


def test_get_collection_reads_alias_file(monkeypatch, tmp_path):
    """current_alias.json의 'current'를 collection 이름으로 사용."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text(json.dumps({"current": "papers_v2"}))
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    fake = FakeClientOK()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers_v2"]


def test_alias_missing_falls_back_to_default(monkeypatch, tmp_path):
    """alias 파일 없고 CHROMA_COLLECTION_NAME env 없으면 'paper_chunks' fallback (F2 fix)."""
    alias_file = tmp_path / "current_alias.json"  # 미생성
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})
    # CI 환경의 CHROMA_COLLECTION_NAME env를 정리해 fallback 'paper_chunks' 확정
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)

    fake = FakeClientOK()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["paper_chunks"]


def test_alias_file_corrupt_falls_back(monkeypatch, tmp_path):
    """alias 파일이 JSON 깨졌고 env 없으면 'paper_chunks' 안전 fallback (F2 fix)."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text("not json {{{")
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)

    fake = FakeClientOK()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["paper_chunks"]


def test_get_collection_fails_closed_when_target_missing(monkeypatch, tmp_path):
    """alias가 가리키는 collection이 실제로 없으면 RuntimeError — silent empty 방지 (B1 fix)."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text(json.dumps({"current": "nonexistent_v99"}))
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    monkeypatch.setattr(rag, "_client", FakeClientMissing())
    with pytest.raises(RuntimeError, match="not found"):
        rag._get_collection()


def test_default_collection_uses_env(monkeypatch, tmp_path):
    """env 없을 때 _current_collection_name()이 'paper_chunks'를 반환한다 (F4: DEFAULT_COLLECTION 제거 후 대체).

    DEFAULT_COLLECTION 모듈 상수는 dead variable로 제거됨 (F4 fix).
    fallback은 _current_collection_name()의 os.getenv(..., 'paper_chunks')로 처리.
    """
    monkeypatch.setattr(rag, "ALIAS_FILE", tmp_path / "no_alias.json")
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    assert rag._current_collection_name() == "paper_chunks"


def test_default_collection_reads_env_at_call_time(monkeypatch, tmp_path):
    """alias 파일 없을 때 _current_collection_name이 매 호출마다 env를 재조회한다 (B1 잔여 픽스).

    모듈 상수 DEFAULT_COLLECTION이 아닌 call-time os.getenv를 사용하므로
    env 런타임 변경이 다음 호출부터 즉시 반영된다.
    """
    alias_file = tmp_path / "current_alias.json"  # 미생성 — alias 없음
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "paper_chunks")
    assert rag._current_collection_name() == "paper_chunks"

    # env 런타임 변경 — 다음 호출부터 즉시 반영되어야 함
    monkeypatch.setenv("CHROMA_COLLECTION_NAME", "papers_v2")
    assert rag._current_collection_name() == "papers_v2"

    # env 완전 제거 → hardcoded fallback "paper_chunks" (F2 fix: config default와 일치)
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    assert rag._current_collection_name() == "paper_chunks"
