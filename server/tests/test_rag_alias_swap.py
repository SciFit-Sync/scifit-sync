"""rag.py가 alias 파일을 읽어 매 요청마다 적절한 collection 사용."""

import importlib
import json
import os

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
    """alias 파일 없으면 DEFAULT_COLLECTION(=CHROMA_COLLECTION_NAME env) 사용."""
    alias_file = tmp_path / "current_alias.json"  # 미생성
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    fake = FakeClientOK()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    # DEFAULT_COLLECTION은 CHROMA_COLLECTION_NAME 환경변수 값 (B1 fix)
    assert fake.requested == [rag.DEFAULT_COLLECTION]


def test_alias_file_corrupt_falls_back(monkeypatch, tmp_path):
    """alias 파일이 JSON 깨졌으면 DEFAULT_COLLECTION으로 안전 fallback."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text("not json {{{")
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    fake = FakeClientOK()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == [rag.DEFAULT_COLLECTION]


def test_get_collection_fails_closed_when_target_missing(monkeypatch, tmp_path):
    """alias가 가리키는 collection이 실제로 없으면 RuntimeError — silent empty 방지 (B1 fix)."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text(json.dumps({"current": "nonexistent_v99"}))
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    monkeypatch.setattr(rag, "_client", FakeClientMissing())
    with pytest.raises(RuntimeError, match="not found"):
        rag._get_collection()


def test_default_collection_uses_env(monkeypatch):
    """DEFAULT_COLLECTION이 CHROMA_COLLECTION_NAME 환경변수와 일치한다 (B1 fix)."""
    # DEFAULT_COLLECTION은 모듈 로드 시 CHROMA_COLLECTION_NAME으로 설정됨
    # conftest에서 별도로 CHROMA_COLLECTION_NAME을 지정하지 않으면 기본값 "paper_chunks"
    assert rag.DEFAULT_COLLECTION == rag.CHROMA_COLLECTION_NAME


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

    # env 완전 제거 → hardcoded fallback "papers"
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    assert rag._current_collection_name() == "papers"
