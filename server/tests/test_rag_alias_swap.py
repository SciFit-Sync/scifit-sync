"""rag.py가 alias 파일을 읽어 매 요청마다 적절한 collection 사용."""

import json

from app.services import rag


def test_get_collection_reads_alias_file(monkeypatch, tmp_path):
    """current_alias.json의 'current'를 collection 이름으로 사용."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text(json.dumps({"current": "papers_v2"}))
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})
    monkeypatch.setattr(rag, "_client", None)

    class FakeClient:
        def __init__(self):
            self.requested = []

        def get_or_create_collection(self, name, metadata=None):
            self.requested.append(name)

            class FakeCol:
                def count(self):
                    return 0

            return FakeCol()

    fake = FakeClient()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers_v2"]


def test_alias_missing_falls_back_to_default(monkeypatch, tmp_path):
    """alias 파일 없으면 기본 'papers' 사용."""
    alias_file = tmp_path / "current_alias.json"  # 미생성
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    class FakeClient:
        def __init__(self):
            self.requested = []

        def get_or_create_collection(self, name, metadata=None):
            self.requested.append(name)

            class FakeCol:
                def count(self):
                    return 0

            return FakeCol()

    fake = FakeClient()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers"]


def test_alias_file_corrupt_falls_back(monkeypatch, tmp_path):
    """alias 파일이 JSON 깨졌으면 기본 'papers'로 안전 fallback."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text("not json {{{")
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    class FakeClient:
        def __init__(self):
            self.requested = []

        def get_or_create_collection(self, name, metadata=None):
            self.requested.append(name)

            class FakeCol:
                def count(self):
                    return 0

            return FakeCol()

    fake = FakeClient()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers"]
