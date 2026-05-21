# Incremental Chunks Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mlops/scripts/export_embeddings.py`의 `--reuse-chunks`를 부족분만 채우는 incremental 흐름으로 확장한다.

**Architecture:** Stage 1 (chunks 결정) 단계에 사이드카(`<tag>.jsonl.gz.meta.json`) 기반 version 검증 + 부족분 계산 + 부분 크롤링 + atomic merge 분기를 추가한다. monthly_ingest.py는 변경 없음.

**Tech Stack:** Python 3.11+, pydantic, gzip, pytest, monkeypatch. 외부 신규 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-05-20-incremental-chunks-cache-design.md` (커밋 5ab52b3)

---

## File Structure

| 파일 | 역할 | 변경 |
|---|---|---|
| `mlops/scripts/export_embeddings.py` | Stage 1 분기 확장 + 신규 helper 6개 | Modify |
| `mlops/tests/test_export_embeddings.py` | 본 설계 동작 검증 테스트 모음 | Create |
| `mlops/pipeline/manifest.py` | (변경 없음) | — |
| `mlops/pipeline/crawler.py` | (변경 없음) | — |
| `mlops/pipeline/models.py` | (변경 없음) | — |
| `mlops/scripts/monthly_ingest.py` | (변경 없음, 범위 밖) | — |

신규 helper는 모두 `export_embeddings.py` 안에 둔다 (private module 함수). 다른 모듈에서 참조하지 않으므로 별도 파일로 분리하지 않는다.

---

### Task 1: 테스트 파일 스켈레톤 + fixture 작성

**Files:**
- Create: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 빈 테스트 파일 + 필수 import**

```python
"""export_embeddings.py stage 1 분기 검증 테스트.

crawl_papers / chunk_papers / embed_chunks_with_spec를 monkeypatch로
가짜화해서 chunks 캐시 흐름(no cache / sufficient / partial fill / error
fallback)을 검증한다.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from mlops.pipeline.models import Chunk


def _make_chunk(*, doi: str = "10.1/a", pmid: str = "1", idx: int = 0) -> Chunk:
    """테스트용 Chunk 인스턴스. 필수 필드만 채운다."""
    return Chunk(
        paper_pmid=pmid,
        paper_doi=doi,
        paper_title="t",
        section_name="abstract",
        chunk_index=idx,
        content="content",
        token_count=2,
        search_categories=[],
        publication_types=[],
        evidence_weight=0.5,
        fulltext_source="pmc",
        published_year=2020,
    )


@pytest.fixture
def cached_chunks_path(tmp_path: Path) -> Path:
    """tmp_path 안에 chunks 디렉토리 + 빈 chunks 파일 path 반환 (파일은 미생성)."""
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    return chunks_dir / "test_tag.jsonl.gz"
```

- [ ] **Step 2: 스켈레톤 import만 검증하는 sanity 테스트**

```python
def test_make_chunk_helper_returns_valid_chunk():
    chunk = _make_chunk(doi="10.1/a", pmid="1", idx=0)
    assert chunk.paper_doi == "10.1/a"
    assert chunk.paper_pmid == "1"
```

- [ ] **Step 3: 실행해서 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 1 passed

- [ ] **Step 4: ruff format/check**

Run: `python3 -m ruff format mlops/tests/test_export_embeddings.py && python3 -m ruff check mlops/tests/test_export_embeddings.py`
Expected: All checks passed

- [ ] **Step 5: Commit**

```bash
git add mlops/tests/test_export_embeddings.py
git commit -m "test: export_embeddings 테스트 파일 스켈레톤 + fixture"
```

---

### Task 2: `_meta_path` helper + `CHUNKS_META_VERSION` 상수

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`mlops/tests/test_export_embeddings.py`에 추가:

```python
from mlops.scripts.export_embeddings import CHUNKS_META_VERSION, _meta_path


def test_meta_path_appends_meta_json_suffix(tmp_path: Path):
    chunks_path = tmp_path / "chunks" / "run_3k.jsonl.gz"
    result = _meta_path(chunks_path)
    assert result == tmp_path / "chunks" / "run_3k.jsonl.gz.meta.json"


def test_chunks_meta_version_is_positive_int():
    assert isinstance(CHUNKS_META_VERSION, int) and CHUNKS_META_VERSION >= 1
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_meta_path_appends_meta_json_suffix -v`
Expected: FAIL — `ImportError: cannot import name '_meta_path'`

- [ ] **Step 3: helper 구현**

`mlops/scripts/export_embeddings.py`의 `_chunks_path` 정의 바로 아래에 추가:

```python
CHUNKS_META_VERSION = 1


def _meta_path(chunks_path: Path) -> Path:
    """`<tag>.jsonl.gz` → `<tag>.jsonl.gz.meta.json`. Path.with_suffix는 마지막
    suffix를 교체하므로 name에 직접 append한다."""
    return chunks_path.parent / (chunks_path.name + ".meta.json")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _meta_path helper + CHUNKS_META_VERSION 추가"
```

---

### Task 3: `_count_unique_papers` helper

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from mlops.scripts.export_embeddings import _count_unique_papers


def test_count_unique_papers_uses_doi_when_present():
    chunks = [
        _make_chunk(doi="10.1/a", pmid="1", idx=0),
        _make_chunk(doi="10.1/a", pmid="1", idx=1),
        _make_chunk(doi="10.1/b", pmid="2", idx=0),
    ]
    assert _count_unique_papers(chunks) == 2


def test_count_unique_papers_falls_back_to_pmid_when_doi_empty():
    chunks = [
        _make_chunk(doi="", pmid="1", idx=0),
        _make_chunk(doi="", pmid="2", idx=0),
        _make_chunk(doi="", pmid="2", idx=1),
    ]
    assert _count_unique_papers(chunks) == 2


def test_count_unique_papers_ignores_chunks_with_no_identifier():
    chunks = [_make_chunk(doi="", pmid="")]
    assert _count_unique_papers(chunks) == 0
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_count_unique_papers_uses_doi_when_present -v`
Expected: FAIL — ImportError

- [ ] **Step 3: helper 구현**

`_meta_path` 정의 아래에 추가:

```python
def _count_unique_papers(chunks: list[Chunk]) -> int:
    """chunks가 커버하는 고유 paper 수. paper_doi 우선, 없으면 paper_pmid 사용.
    둘 다 빈 string이면 카운트에서 제외."""
    keys: set[str] = set()
    for c in chunks:
        key = c.paper_doi or c.paper_pmid
        if key:
            keys.add(key)
    return len(keys)
```

추가로 파일 상단 import에 `Chunk` 추가 (`mlops.pipeline.models`에서 이미 import 되어있는지 확인 — 없으면 추가).

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _count_unique_papers helper (DOI 우선, PMID fallback)"
```

---

### Task 4: `_chunks_doi_set` helper

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from mlops.scripts.export_embeddings import _chunks_doi_set


def test_chunks_doi_set_excludes_empty_string():
    chunks = [
        _make_chunk(doi="10.1/a", pmid="1"),
        _make_chunk(doi="", pmid="2"),
        _make_chunk(doi="10.1/b", pmid="3"),
    ]
    assert _chunks_doi_set(chunks) == {"10.1/a", "10.1/b"}


def test_chunks_doi_set_empty_input_returns_empty_set():
    assert _chunks_doi_set([]) == set()
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_chunks_doi_set_excludes_empty_string -v`
Expected: FAIL — ImportError

- [ ] **Step 3: helper 구현**

`_count_unique_papers` 아래에 추가:

```python
def _chunks_doi_set(chunks: list[Chunk]) -> set[str]:
    """캐시 chunks의 paper_doi 집합. 빈 string은 제외 — 빈 DOI를 existing_dois에
    넣으면 crawler dedup 로직을 오염시킬 위험."""
    return {c.paper_doi for c in chunks if c.paper_doi}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _chunks_doi_set helper — 빈 DOI 필터링"
```

---

### Task 5: `_merge_chunks` helper

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from mlops.scripts.export_embeddings import _merge_chunks


def test_merge_chunks_keeps_old_paper_when_doi_collision():
    old = [_make_chunk(doi="10.1/a", pmid="1", idx=0)]
    new = [_make_chunk(doi="10.1/a", pmid="1", idx=0)]
    merged = _merge_chunks(old, new)
    assert len(merged) == 1
    assert merged[0] is old[0]


def test_merge_chunks_appends_new_papers():
    old = [_make_chunk(doi="10.1/a", pmid="1", idx=0)]
    new = [_make_chunk(doi="10.1/b", pmid="2", idx=0)]
    merged = _merge_chunks(old, new)
    assert len(merged) == 2
    assert merged[0].paper_doi == "10.1/a"
    assert merged[1].paper_doi == "10.1/b"


def test_merge_chunks_dedup_by_pmid_when_doi_empty():
    old = [_make_chunk(doi="", pmid="1", idx=0)]
    new = [_make_chunk(doi="", pmid="1", idx=1)]
    merged = _merge_chunks(old, new)
    assert len(merged) == 1


def test_merge_chunks_keeps_multiple_chunks_of_same_paper():
    """같은 paper의 여러 chunk는 모두 보존 (paper 단위 dedup이지 chunk 단위 아님)."""
    old = [
        _make_chunk(doi="10.1/a", pmid="1", idx=0),
        _make_chunk(doi="10.1/a", pmid="1", idx=1),
    ]
    new = [_make_chunk(doi="10.1/b", pmid="2", idx=0)]
    merged = _merge_chunks(old, new)
    assert len(merged) == 3
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_merge_chunks_keeps_old_paper_when_doi_collision -v`
Expected: FAIL — ImportError

- [ ] **Step 3: helper 구현**

`_chunks_doi_set` 아래에 추가:

```python
def _merge_chunks(old: list[Chunk], new: list[Chunk]) -> list[Chunk]:
    """기존 chunks + 신규 chunks를 paper 단위 dedup하여 합친다.

    paper_doi 우선, 없으면 paper_pmid로 key 생성. 같은 paper의 chunk는 모두 보존
    하지만 같은 paper의 신규 chunks는 통째로 폐기 (old 우선)."""
    old_keys: set[str] = set()
    for c in old:
        key = c.paper_doi or c.paper_pmid
        if key:
            old_keys.add(key)

    merged = list(old)
    for c in new:
        key = c.paper_doi or c.paper_pmid
        if key and key in old_keys:
            continue
        merged.append(c)
    return merged
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _merge_chunks helper — paper 단위 dedup (old 우선)"
```

---

### Task 6: `_save_chunks_atomic` helper

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from mlops.scripts.export_embeddings import _save_chunks_atomic


def test_save_chunks_atomic_writes_gzip_jsonl(tmp_path: Path):
    chunks = [_make_chunk(doi="10.1/a", pmid="1", idx=0)]
    path = tmp_path / "test_tag.jsonl.gz"
    _save_chunks_atomic(path, chunks)

    assert path.exists()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        line = f.readline().strip()
    assert "10.1/a" in line


def test_save_chunks_atomic_preserves_original_on_serialization_failure(
    tmp_path: Path, monkeypatch
):
    """중간에 예외 발생 시 원본 파일은 보존된다 (tmp 파일에만 영향)."""
    path = tmp_path / "test_tag.jsonl.gz"
    # 원본 파일 미리 생성
    original_content = b"ORIGINAL"
    path.write_bytes(original_content)

    # json.dumps가 예외 던지도록 monkeypatch
    def boom(*args, **kwargs):
        raise RuntimeError("serialization failure")

    monkeypatch.setattr("mlops.scripts.export_embeddings.json.dumps", boom)

    with pytest.raises(RuntimeError):
        _save_chunks_atomic(path, [_make_chunk()])

    # 원본은 그대로
    assert path.read_bytes() == original_content
    # tmp 파일은 없어야 (cleanup) — 또는 .tmp 이름으로 남아있어도 path 본체는 무사
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_save_chunks_atomic_writes_gzip_jsonl -v`
Expected: FAIL — ImportError

- [ ] **Step 3: helper 구현**

`_merge_chunks` 아래에 추가:

```python
def _save_chunks_atomic(path: Path, chunks: list[Chunk]) -> None:
    """chunks를 gzip JSONL로 atomic 저장. 부분 쓰기 방어용 tmp + os.replace 패턴.

    중간 실패 시 원본 path 파일은 그대로 보존된다 (.tmp는 cleanup 시도, 실패해도
    무시 — 원본 무결성이 우선).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c.model_dump(), ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
```

`os` import가 없으면 파일 상단에 추가.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 14 passed

- [ ] **Step 5: ruff format/check**

Run: `python3 -m ruff format mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py && python3 -m ruff check mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _save_chunks_atomic — tmp+os.replace 패턴, 실패 시 원본 보존"
```

---

### Task 7: 사이드카 read/write helper

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from mlops.scripts.export_embeddings import (
    _load_meta_sidecar,
    _write_meta_sidecar,
)


def test_write_meta_sidecar_emits_version_and_counts(tmp_path: Path):
    chunks_path = tmp_path / "tag.jsonl.gz"
    chunks = [
        _make_chunk(doi="10.1/a", pmid="1", idx=0),
        _make_chunk(doi="10.1/a", pmid="1", idx=1),
        _make_chunk(doi="10.1/b", pmid="2", idx=0),
    ]
    _write_meta_sidecar(chunks_path, chunks)

    meta_path = tmp_path / "tag.jsonl.gz.meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["version"] == 1
    assert meta["paper_count"] == 2
    assert meta["chunk_count"] == 3
    assert "created_at" in meta and "updated_at" in meta


def test_load_meta_sidecar_returns_none_when_missing(tmp_path: Path):
    chunks_path = tmp_path / "tag.jsonl.gz"
    assert _load_meta_sidecar(chunks_path) is None


def test_load_meta_sidecar_returns_dict_when_present(tmp_path: Path):
    chunks_path = tmp_path / "tag.jsonl.gz"
    meta_path = tmp_path / "tag.jsonl.gz.meta.json"
    meta_path.write_text(json.dumps({"version": 1, "paper_count": 5}))
    meta = _load_meta_sidecar(chunks_path)
    assert meta is not None
    assert meta["version"] == 1
    assert meta["paper_count"] == 5


def test_load_meta_sidecar_returns_none_on_corrupt_json(tmp_path: Path):
    """사이드카 JSON 손상 시 None 반환 → caller가 legacy로 취급."""
    chunks_path = tmp_path / "tag.jsonl.gz"
    meta_path = tmp_path / "tag.jsonl.gz.meta.json"
    meta_path.write_text("{not valid json")
    assert _load_meta_sidecar(chunks_path) is None
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_write_meta_sidecar_emits_version_and_counts -v`
Expected: FAIL — ImportError

- [ ] **Step 3: helper 구현**

`_save_chunks_atomic` 아래에 추가:

```python
def _load_meta_sidecar(chunks_path: Path) -> dict | None:
    """사이드카 메타파일 로드. 없거나 JSON 손상 시 None — caller가 legacy 처리."""
    meta_path = _meta_path(chunks_path)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("사이드카 JSON 손상, legacy로 fallback: %s", meta_path)
        return None


def _write_meta_sidecar(chunks_path: Path, chunks: list[Chunk]) -> None:
    """chunks 저장 직후 호출. version + 카운트 + 시각 메타를 사이드카에 기록."""
    meta_path = _meta_path(chunks_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = _load_meta_sidecar(chunks_path) or {}
    payload = {
        "version": CHUNKS_META_VERSION,
        "chunks_path": chunks_path.name,
        "paper_count": _count_unique_papers(chunks),
        "chunk_count": len(chunks),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
```

`datetime`/`timezone` import가 파일에 없으면 추가 (`from datetime import datetime, timezone`).

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: 사이드카 read/write helper — version+카운트+시각 기록"
```

---

### Task 8: Stage 1 분기 리팩토링 — full crawl 경로 추출

기존 main() 의 stage 1 로직을 helper로 분리해 향후 분기가 단순해지도록 사전 정리.

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`

- [ ] **Step 1: 기존 main()의 stage 1 블록(약 351~385줄)을 `_resolve_chunks` 함수로 추출**

함수 시그니처:

```python
def _resolve_chunks(args: argparse.Namespace) -> tuple[list[Chunk], list]:
    """Stage 1 — chunks를 결정하고 manifest 업데이트용 papers를 반환.

    Returns:
        (chunks, papers_for_manifest). papers_for_manifest는 default 모드에서만
        의미가 있고 reuse 경로에서는 빈 리스트.
    """
```

- 기존 if/else 그대로 함수 안으로 이동
- `chunks`와 `papers_for_manifest` 두 값을 반환
- `manifest: Manifest | None` 변수는 함수 내부 지역 변수로

main()에서는 `chunks, papers_for_manifest = _resolve_chunks(args)`로 대체.

- [ ] **Step 2: 기존 테스트 전체 실행 — 회귀 없음 확인**

Run: `python3 -m pytest mlops/tests --no-header -q`
Expected: 267 passed (또는 기존 통과 수 그대로)

- [ ] **Step 3: ruff format/check**

Run: `python3 -m ruff format mlops/scripts/export_embeddings.py && python3 -m ruff check mlops/scripts/export_embeddings.py`
Expected: All checks passed

- [ ] **Step 4: Commit**

```bash
git add mlops/scripts/export_embeddings.py
git commit -m "refactor: stage 1 분기를 _resolve_chunks로 추출"
```

---

### Task 9: `_resolve_chunks`에 사용자 카운트 기반 부족분 판단 추가

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성 — 캐시 충분한 케이스**

```python
import argparse
from unittest.mock import patch


def _make_args(**overrides):
    """_resolve_chunks 테스트용 args namespace."""
    defaults = dict(
        batch_tag="test_tag",
        reuse_chunks=True,
        max_papers=10,
        max_per_category=None,
        min_date=None,
        max_date=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_resolve_chunks_sufficient_cache_skips_crawl(tmp_path, monkeypatch):
    """캐시 paper 수 >= max_papers → crawl_papers 호출 0회."""
    from mlops.scripts import export_embeddings as ee

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"

    # 캐시에 paper 10개 (각 1 chunk)
    cached = [_make_chunk(doi=f"10.1/{i}", pmid=str(i), idx=0) for i in range(10)]
    ee._save_chunks_atomic(chunks_path, cached)
    ee._write_meta_sidecar(chunks_path, cached)

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)

    crawl_calls: list = []
    monkeypatch.setattr(ee, "crawl_papers", lambda **kw: crawl_calls.append(kw) or [])

    args = _make_args(max_papers=10)
    chunks, _papers = ee._resolve_chunks(args)

    assert len(chunks) == 10
    assert crawl_calls == []  # crawl 호출 안 됨
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_resolve_chunks_sufficient_cache_skips_crawl -v`
Expected: FAIL — _resolve_chunks의 기존 동작이 캐시 검증 없이 그대로 사용해서 통과하거나, 또는 호출 시 reuse_chunks=True + 파일 있음 → 무조건 load만 하고 끝나서 통과할 수도 있음

→ 첫 실행 결과에 맞춰 다음 단계 결정.
- 만약 통과한다면: 충분/부족 분기가 아직 도입되지 않아 우연 통과 → 실패 시나리오 (max_papers > cached) 테스트 먼저 작성 필요

- [ ] **Step 3: 부족분 분기 구현**

`_resolve_chunks` 안 `if args.reuse_chunks and chunks_path.exists():` 블록을 다음과 같이 보강:

```python
if args.reuse_chunks and chunks_path.exists():
    chunks = _load_chunks(chunks_path)
    logger.info("chunks 재사용: %s (paper %d개)", chunks_path, _count_unique_papers(chunks))

    cached_paper_count = _count_unique_papers(chunks)
    shortage = max(0, args.max_papers - cached_paper_count)

    if shortage == 0:
        logger.info("캐시가 요청량(%d) 충족, crawl skip", args.max_papers)
        papers_for_manifest = []
        return chunks, papers_for_manifest

    # 부족분 fill 분기는 다음 Task에서 구현
    logger.warning("부족분 %d편 — fill 분기 미구현, 캐시까지로 진행", shortage)
    papers_for_manifest = []
    return chunks, papers_for_manifest
else:
    # 기존 통째 크롤링 경로 (변경 없음)
    ...
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_resolve_chunks_sufficient_cache_skips_crawl -v`
Expected: PASS

- [ ] **Step 5: 회귀 확인**

Run: `python3 -m pytest mlops/tests --no-header -q`
Expected: 모든 기존 테스트 통과

- [ ] **Step 6: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: _resolve_chunks — 캐시 충분 시 crawl skip"
```

---

### Task 10: 부족분 fill 분기 — 신규 paper 크롤링 + merge

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성 — partial fill**

```python
def test_resolve_chunks_partial_fill_calls_crawl_with_shortage(tmp_path, monkeypatch):
    from mlops.scripts import export_embeddings as ee
    from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"

    # 캐시 5편
    cached = [_make_chunk(doi=f"10.1/{i}", pmid=str(i), idx=0) for i in range(5)]
    ee._save_chunks_atomic(chunks_path, cached)
    ee._write_meta_sidecar(chunks_path, cached)

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ee, "MANIFEST_PATH", tmp_path / "manifest.json")

    captured: dict = {}

    def fake_crawl(**kw):
        captured.update(kw)
        # 3편 반환 — 모두 본문 있음
        return [
            PaperFull(
                meta=PaperMeta(
                    pmid=str(100 + i),
                    title="t",
                    authors="",
                    journal="",
                    published_year=2020,
                    doi=f"10.1/n{i}",
                    abstract="",
                    search_categories=[],
                    publication_types=[],
                    evidence_weight=0.5,
                    fulltext_source="pmc",
                ),
                sections=[PaperSection(name="abstract", text="content here")],
            )
            for i in range(3)
        ]

    monkeypatch.setattr(ee, "crawl_papers", fake_crawl)
    monkeypatch.setattr(
        ee, "chunk_papers", lambda papers: [_make_chunk(doi=p.meta.doi, pmid=p.meta.pmid) for p in papers]
    )

    args = _make_args(max_papers=10, max_per_category=42)
    chunks, _ = ee._resolve_chunks(args)

    # crawl_papers는 부족분 5편만 요청해야
    assert captured["max_total"] == 5
    # max_per_category 그대로 전달
    assert captured["max_per_category"] == 42
    # existing_dois에 캐시 DOI 5개 포함
    assert {f"10.1/{i}" for i in range(5)}.issubset(captured["existing_dois"])
    # merge 결과 paper 8개 (캐시 5 + 신규 3)
    assert _count_unique_papers(chunks) == 8
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_resolve_chunks_partial_fill_calls_crawl_with_shortage -v`
Expected: FAIL — fill 분기 미구현이라 신규 chunks 추가 안 됨

- [ ] **Step 3: fill 분기 구현**

Task 9에서 둔 placeholder를 다음 코드로 교체:

```python
# 부족분 fill 분기
manifest = Manifest.load(MANIFEST_PATH)
manifest_skip: set[str] = set()
for doi, entry in manifest.papers.items():
    if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
        manifest_skip.add(doi)
cached_dois = _chunks_doi_set(chunks)
existing_dois = manifest_skip | cached_dois
logger.info(
    "부족분 fill: shortage=%d, existing_dois=%d (manifest_skip=%d, cached=%d)",
    shortage,
    len(existing_dois),
    len(manifest_skip),
    len(cached_dois),
)

new_papers = crawl_papers(
    max_total=shortage,
    max_per_category=args.max_per_category,
    min_date=args.min_date,
    max_date=args.max_date,
    existing_dois=existing_dois,
)
indexed_new = [p for p in new_papers if p.sections]
logger.info("부족분 크롤링: 시도 %d, 본문 확보 %d", len(new_papers), len(indexed_new))

new_chunks = chunk_papers(indexed_new) if indexed_new else []
merged = _merge_chunks(chunks, new_chunks)
_save_chunks_atomic(chunks_path, merged)
_write_meta_sidecar(chunks_path, merged)

final_paper_count = _count_unique_papers(merged)
if final_paper_count < args.max_papers:
    logger.warning(
        "부족분 fill 후에도 요청량 미충족: %d/%d (캐시까지로 임베딩 진행)",
        final_paper_count,
        args.max_papers,
    )

return merged, new_papers
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 모든 테스트 통과

- [ ] **Step 5: ruff format/check**

Run: `python3 -m ruff format mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py && python3 -m ruff check mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: 부족분 fill 분기 — crawl shortage + atomic merge"
```

---

### Task 11: `existing_dois` retry candidates 비차단 + warn 동작 검증

**Files:**
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: retry candidates 비차단 테스트**

```python
def test_resolve_chunks_existing_dois_excludes_retry_candidates(tmp_path, monkeypatch):
    """manifest에 fulltext_source=None + tried_sources < ACTIVE_SOURCES인 paper는
    existing_dois에 포함되지 않아야 한다 (retry 대상이라 다시 시도해야 함)."""
    from mlops.scripts import export_embeddings as ee
    from mlops.pipeline.manifest import Manifest, ManifestEntry

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"

    cached = [_make_chunk(doi="10.1/cached", pmid="1")]
    ee._save_chunks_atomic(chunks_path, cached)
    ee._write_meta_sidecar(chunks_path, cached)

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(ee, "MANIFEST_PATH", manifest_path)

    # manifest에 retry 대상 한 건 + indexed 한 건
    m = Manifest()
    m.papers["10.1/retry"] = ManifestEntry(
        pmid="r", pmcid=None, openalex_id=None,
        fulltext_source=None, tried_sources=["pmc"],  # europepmc 미시도
        indexed_at=None, last_tried_at="2026-05-20",
    )
    m.papers["10.1/indexed"] = ManifestEntry(
        pmid="i", pmcid=None, openalex_id=None,
        fulltext_source="pmc", tried_sources=["pmc"],
        indexed_at="2026-05-20", last_tried_at="2026-05-20",
    )
    m.save(manifest_path)

    captured: dict = {}

    def fake_crawl(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr(ee, "crawl_papers", fake_crawl)
    monkeypatch.setattr(ee, "chunk_papers", lambda papers: [])

    args = _make_args(max_papers=10)
    ee._resolve_chunks(args)

    assert "10.1/cached" in captured["existing_dois"]
    assert "10.1/indexed" in captured["existing_dois"]
    assert "10.1/retry" not in captured["existing_dois"]


def test_resolve_chunks_partial_fill_below_shortage_warns(tmp_path, monkeypatch, caplog):
    """crawl 신규 < shortage → warn 로그 + 캐시까지로 진행 (예외 X)."""
    from mlops.scripts import export_embeddings as ee

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"
    cached = [_make_chunk(doi="10.1/a", pmid="1")]
    ee._save_chunks_atomic(chunks_path, cached)
    ee._write_meta_sidecar(chunks_path, cached)

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ee, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(ee, "crawl_papers", lambda **kw: [])  # 0 신규
    monkeypatch.setattr(ee, "chunk_papers", lambda papers: [])

    args = _make_args(max_papers=10)
    with caplog.at_level("WARNING"):
        chunks, _ = ee._resolve_chunks(args)

    assert len(chunks) == 1  # 캐시 그대로
    assert any("미충족" in r.message for r in caplog.records)
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 모든 신규 테스트 통과 (Task 10 구현이 이미 retry 비차단 + warn을 처리)

- [ ] **Step 3: Commit**

```bash
git add mlops/tests/test_export_embeddings.py
git commit -m "test: existing_dois 비차단 + 부분 fill warn 동작 검증"
```

---

### Task 12: 에러 경로 — schema mismatch / 사이드카 누락 / gzip 손상

**Files:**
- Modify: `mlops/scripts/export_embeddings.py`
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
def test_resolve_chunks_sidecar_version_mismatch_falls_back_to_full_crawl(tmp_path, monkeypatch):
    """사이드카 version mismatch → 캐시 무효 + 통째 재크롤링."""
    from mlops.scripts import export_embeddings as ee

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"
    cached = [_make_chunk(doi="10.1/a", pmid="1")]
    ee._save_chunks_atomic(chunks_path, cached)
    # 잘못된 version으로 사이드카 직접 작성
    _meta = ee._meta_path(chunks_path)
    _meta.write_text(json.dumps({"version": 999, "paper_count": 1}))

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ee, "MANIFEST_PATH", tmp_path / "manifest.json")

    crawl_called = {"n": 0}

    def fake_crawl(**kw):
        crawl_called["n"] += 1
        # max_total 인자가 args.max_papers 그대로 (shortage 아님) → 통째 재크롤링 신호
        assert kw["max_total"] == 10
        return []

    monkeypatch.setattr(ee, "crawl_papers", fake_crawl)
    monkeypatch.setattr(ee, "chunk_papers", lambda papers: [])

    args = _make_args(max_papers=10)
    ee._resolve_chunks(args)
    assert crawl_called["n"] == 1

    # invalid 흔적 파일 존재 확인
    assert any(p.name.startswith("test_tag.jsonl.gz.invalid") for p in chunks_dir.iterdir())


def test_resolve_chunks_gzip_corruption_raises(tmp_path, monkeypatch):
    """gzip 손상은 silent fallback 금지 → 그대로 raise."""
    from mlops.scripts import export_embeddings as ee

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"
    chunks_path.write_bytes(b"not a gzip file")

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)

    args = _make_args(max_papers=10)
    with pytest.raises((OSError, gzip.BadGzipFile)):
        ee._resolve_chunks(args)


def test_resolve_chunks_legacy_no_sidecar_uses_cache(tmp_path, monkeypatch):
    """사이드카 없는 legacy 캐시는 _load_chunks 성공하면 그대로 사용."""
    from mlops.scripts import export_embeddings as ee

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"
    cached = [_make_chunk(doi="10.1/a", pmid="1")]
    ee._save_chunks_atomic(chunks_path, cached)
    # 사이드카 의도적으로 생성 안 함

    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ee, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(ee, "crawl_papers", lambda **kw: [])
    monkeypatch.setattr(ee, "chunk_papers", lambda papers: [])

    args = _make_args(max_papers=1)
    chunks, _ = ee._resolve_chunks(args)
    assert len(chunks) == 1
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_resolve_chunks_sidecar_version_mismatch_falls_back_to_full_crawl -v`
Expected: FAIL — version mismatch 분기 미구현

- [ ] **Step 3: 에러 경로 구현**

`_resolve_chunks`의 `if args.reuse_chunks and chunks_path.exists():` 블록 시작 부분에 다음 추가:

```python
def _invalidate_cache(chunks_path: Path, reason: str) -> None:
    """schema mismatch/손상 시 chunks 파일과 사이드카에 .invalid 접미사 부여."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f".invalid.{ts}"
    for p in (chunks_path, _meta_path(chunks_path)):
        if p.exists():
            p.rename(p.with_name(p.name + suffix))
    logger.warning("chunks 캐시 무효화 (%s): %s.invalid.%s", reason, chunks_path.name, ts)
```

`_resolve_chunks`의 reuse 분기 시작:

```python
if args.reuse_chunks and chunks_path.exists():
    meta = _load_meta_sidecar(chunks_path)
    if meta is not None and meta.get("version") != CHUNKS_META_VERSION:
        _invalidate_cache(chunks_path, f"version mismatch ({meta.get('version')} != {CHUNKS_META_VERSION})")
        # full crawl로 떨어짐
    else:
        try:
            chunks = _load_chunks(chunks_path)
        except (json.JSONDecodeError, ValidationError) as e:
            _invalidate_cache(chunks_path, f"schema/JSON error: {e}")
            chunks = None
        if chunks is not None:
            # ... 부족분 분기 (Task 9/10 코드)
            return ...

# 여기까지 떨어지면 full crawl
manifest = Manifest.load(MANIFEST_PATH)
# ... 기존 통째 크롤링 (변경 없음)
```

`ValidationError` import 추가 (`from pydantic import ValidationError`).

- [ ] **Step 4: 테스트 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py -v`
Expected: 모든 신규 테스트 통과

- [ ] **Step 5: ruff format/check**

Run: `python3 -m ruff format mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py && python3 -m ruff check mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
git commit -m "feat: chunks 캐시 무효화 경로 — schema/version mismatch, gzip 손상 처리"
```

---

### Task 13: `_count_unique_papers` 본문 미확보 paper 제외 검증

**Files:**
- Modify: `mlops/tests/test_export_embeddings.py`

- [ ] **Step 1: 추가 테스트 — chunks에 있는 paper만 카운트**

```python
def test_paper_count_based_on_chunks_papers_only(tmp_path, monkeypatch):
    """crawl_papers가 본문 미확보 paper도 반환하지만, 청킹 안 된 paper는 chunks에
    없으므로 _count_unique_papers는 본문 확보된 paper만 카운트한다."""
    from mlops.scripts import export_embeddings as ee
    from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunks_path = chunks_dir / "test_tag.jsonl.gz"
    # 캐시 비어있음 → fill 분기 진입
    cached = []
    # 파일 자체는 생성하지 않음 → reuse_chunks=True더라도 chunks_path.exists() False
    # → full crawl 경로
    monkeypatch.setattr(ee, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ee, "MANIFEST_PATH", tmp_path / "manifest.json")

    # crawl_papers는 2편 반환 — 1편만 sections 보유
    def fake_crawl(**kw):
        return [
            PaperFull(
                meta=PaperMeta(
                    pmid="1", title="t", authors="", journal="", published_year=2020,
                    doi="10.1/a", abstract="", search_categories=[], publication_types=[],
                    evidence_weight=0.5, fulltext_source="pmc",
                ),
                sections=[PaperSection(name="abstract", text="content")],
            ),
            PaperFull(
                meta=PaperMeta(
                    pmid="2", title="t", authors="", journal="", published_year=2020,
                    doi="10.1/b", abstract="", search_categories=[], publication_types=[],
                    evidence_weight=0.5, fulltext_source=None,
                ),
                sections=[],  # 본문 미확보
            ),
        ]

    monkeypatch.setattr(ee, "crawl_papers", fake_crawl)
    monkeypatch.setattr(
        ee, "chunk_papers", lambda papers: [_make_chunk(doi=p.meta.doi, pmid=p.meta.pmid) for p in papers]
    )

    args = _make_args(max_papers=2, reuse_chunks=False)
    chunks, _ = ee._resolve_chunks(args)
    # sections 있는 paper 1편만 청킹됨
    assert _count_unique_papers(chunks) == 1
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

Run: `python3 -m pytest mlops/tests/test_export_embeddings.py::test_paper_count_based_on_chunks_papers_only -v`
Expected: PASS (기존 full crawl 로직이 이미 `if p.sections` 필터 적용)

- [ ] **Step 3: Commit**

```bash
git add mlops/tests/test_export_embeddings.py
git commit -m "test: 본문 미확보 paper는 _count_unique_papers에서 제외 검증"
```

---

### Task 14: 전체 회귀 + lint + 정리

**Files:**
- (이전 task에서 누적된 변경 검증)

- [ ] **Step 1: 전체 mlops 테스트 스위트 실행**

Run: `python3 -m pytest mlops/tests --no-header -q`
Expected: 기존 267 + 신규 약 18~22 = 285+ passed

- [ ] **Step 2: 변경 파일 전체 ruff format + check**

Run:
```bash
python3 -m ruff format mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
python3 -m ruff check mlops/scripts/export_embeddings.py mlops/tests/test_export_embeddings.py
```
Expected: All checks passed

- [ ] **Step 3: monthly_ingest.py 변경 안 됐는지 확인**

Run: `git diff develop..HEAD -- mlops/scripts/monthly_ingest.py`
Expected: 빈 출력 (스코프 밖이라 변경 없어야 함)

- [ ] **Step 4: spec과 plan의 모든 테스트가 구현됐는지 점검**

Run: `grep -c "^def test_" mlops/tests/test_export_embeddings.py`
Expected: ≥ 18 (spec §5의 12개 + helper 단위 테스트 다수)

- [ ] **Step 5: 운영 노트 docstring 보강 (export_embeddings.py 상단)**

`mlops/scripts/export_embeddings.py` 모듈 docstring 끝에 다음 한 문단 추가:

```
주의: 같은 --batch-tag로 동시에 두 번 띄우지 말 것. _save_chunks_atomic이 부분
쓰기는 방어하지만 lost update는 막지 못한다. OpenAlex daily quota는 midnight UTC
(한국 09:00)에 리셋되므로 부족분 fill을 새 quota로 돌리려면 그 시각 이후에 재실행.
```

- [ ] **Step 6: 최종 commit**

```bash
git add mlops/scripts/export_embeddings.py
git commit -m "docs: incremental chunks cache 운영 노트 추가"
```

- [ ] **Step 7: 브랜치 push + PR 생성 준비**

Run: `git log --oneline origin/develop..HEAD`
Expected: 본 plan의 14개 task별 commit이 순서대로 나열

이 시점에 사용자에게 PR 생성 여부를 묻고, 승인 시:

```bash
git push -u origin docs/jingyu/incremental-chunks-cache-design
gh pr create --base develop --title "feat: export_embeddings incremental chunks cache" --body "$(cat <<'EOF'
## Summary
- export_embeddings의 --reuse-chunks를 부족분만 채우는 incremental 흐름으로 확장
- 사이드카 (`<tag>.jsonl.gz.meta.json`) 도입으로 version 관리
- atomic rewrite + 명확한 에러 분류 (schema는 fallback, gzip 손상은 raise)

설계 문서: docs/superpowers/specs/2026-05-20-incremental-chunks-cache-design.md
구현 계획: docs/superpowers/plans/2026-05-20-incremental-chunks-cache.md

## Test plan
- [x] mlops/tests/test_export_embeddings.py 신규 (캐시 충분/부족분/에러 경로)
- [x] 기존 mlops/tests 회귀 통과
- [x] monthly_ingest.py 미변경 확인

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review (writing-plans 종료 시점 점검)

**Spec coverage 확인**

| spec 요구사항 | 구현 task |
|---|---|
| §2.1 부족분 = chunks의 paper 수 | Task 3 `_count_unique_papers` + Task 13 |
| §2.2 existing_dois = manifest_skip ∪ cached_dois (retry 비차단) | Task 10, Task 11 |
| §2.3 사이드카 version 도입 | Task 7, Task 12 |
| §2.4 atomic rewrite | Task 6 |
| §2.5 에러 분류 (schema fallback / gzip raise) | Task 12 |
| §2.6 fill 경로 `max_per_category` 전달 | Task 10 |
| §3 helper 6개 (_meta_path, _count_unique_papers, _chunks_doi_set, _merge_chunks, _save_chunks_atomic, 사이드카 read/write) | Task 2~7 |
| §3 데이터 흐름 | Task 8 (refactor) → Task 9~12 (분기) |
| §4 에러 처리 표의 모든 행 | Task 12 (schema/version/gzip), Task 11 (warn 부분 사용), Task 9 (캐시 충분), Task 10 (정상 fill) |
| §5 테스트 12종 | Task 2~13 전체에 분산 |
| §7 마이그레이션 (legacy 캐시 자연 처리) | Task 12 `test_resolve_chunks_legacy_no_sidecar_uses_cache` |
| §8 운영 노트 docstring | Task 14 Step 5 |

**Placeholder/contradiction/type consistency**

- 모든 step에 구체 코드 + 명령어 + expected output
- 함수 시그니처 일관성: `_count_unique_papers(chunks)`, `_chunks_doi_set(chunks)`, `_merge_chunks(old, new)`, `_save_chunks_atomic(path, chunks)`, `_load_meta_sidecar(chunks_path)`, `_write_meta_sidecar(chunks_path, chunks)`, `_meta_path(chunks_path)`, `_invalidate_cache(chunks_path, reason)`, `_resolve_chunks(args)` — Task 간 일관됨
- TODO/TBD/"add appropriate" 패턴 없음

**Scope**

- 14 task, 각 task 2~5분 단위 step. 한 PR로 머지 가능 규모.
- 단일 파일 + 단일 테스트 파일 변경. 다른 모듈 미영향.
