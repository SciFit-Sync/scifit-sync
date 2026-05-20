"""mlops.scripts.export_embeddings 단위 테스트.

외부 의존성(crawl/HF 모델)은 모두 monkeypatch — pytest 단독 실행 가능.
"""

import gzip
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from mlops.pipeline.models import Chunk, PaperFull, PaperMeta, PaperSection
from mlops.scripts.export_embeddings import CHUNKS_META_VERSION, _meta_path


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


def test_make_chunk_helper_returns_valid_chunk():
    chunk = _make_chunk(doi="10.1/a", pmid="1", idx=0)
    assert chunk.paper_doi == "10.1/a"
    assert chunk.paper_pmid == "1"


def test_meta_path_appends_meta_json_suffix(tmp_path: Path):
    chunks_path = tmp_path / "chunks" / "run_3k.jsonl.gz"
    result = _meta_path(chunks_path)
    assert result == tmp_path / "chunks" / "run_3k.jsonl.gz.meta.json"


def test_chunks_meta_version_is_positive_int():
    assert isinstance(CHUNKS_META_VERSION, int) and CHUNKS_META_VERSION >= 1


# ── 공용 fixture: scripts 모듈을 fresh import ──────────────────────────
# DATA_DIR 등 모듈 레벨 상수가 monkeypatch 가능하도록 fresh load + DATA_DIR 우회.


@pytest.fixture
def export_module(tmp_path, monkeypatch):
    """tmp_path를 DATA_DIR로 사용하도록 패치된 export_embeddings 모듈."""
    # MLOPS_EMBED_DEVICE를 cpu로 결정론적 고정
    monkeypatch.setenv("MLOPS_EMBED_DEVICE", "cpu")

    # sentence_transformers fake (Phase 2의 _FakeSentenceTransformer와 동일 컨셉)
    fake_module = types.ModuleType("sentence_transformers")

    class _FakeST:
        def __init__(self, hf_name, device="cpu"):
            self.hf_name = hf_name
            self.device = device
            dim_lookup = {
                "BAAI/bge-large-en-v1.5": 1024,
                "BAAI/bge-base-en-v1.5": 768,
                "pritamdeka/S-PubMedBert-MS-MARCO": 768,
            }
            self.dim = dim_lookup[hf_name]

        def encode(self, texts, batch_size=64, show_progress_bar=False, normalize_embeddings=False):
            items = texts if isinstance(texts, list) else [texts]
            rng = np.random.default_rng(seed=hash(self.hf_name) & 0xFFFFFFFF)
            out = rng.standard_normal((len(items), self.dim)).astype(np.float32)
            if normalize_embeddings:
                out = out / np.linalg.norm(out, axis=1, keepdims=True)
            if not isinstance(texts, list):
                return out[0]
            return out

    fake_module.SentenceTransformer = _FakeST  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    # embedder의 캐시 초기화 (이전 테스트 영향 차단)
    from mlops.pipeline import embedder as _emb

    _emb._model_cache.clear()

    # config.DATA_DIR / MANIFEST_PATH를 tmp_path로 우회
    monkeypatch.setattr("mlops.pipeline.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("mlops.pipeline.config.MANIFEST_PATH", tmp_path / "manifest.json")

    # 모듈 reload — 모듈 import 시 DATA_DIR을 캡처하기 때문
    if "mlops.scripts.export_embeddings" in sys.modules:
        del sys.modules["mlops.scripts.export_embeddings"]
    import mlops.scripts.export_embeddings as ee

    # eval/reports 디렉토리도 tmp로 옮기기 위해 _report_path 재정의
    reports_dir = tmp_path / "eval_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ee, "_report_path", lambda tag, key: reports_dir / f"{tag}_{key}.md")

    return ee


def _fake_paper(pmid: str, doi: str = "", with_body: bool = True) -> PaperFull:
    return PaperFull(
        meta=PaperMeta(pmid=pmid, title=f"title-{pmid}", doi=doi or f"10.x/{pmid}"),
        sections=[PaperSection(name="abstract", content=f"body-{pmid} " * 20)] if with_body else [],
    )


def _patch_crawl(monkeypatch, papers: list[PaperFull]) -> dict:
    """crawl_papers를 papers 리스트로 고정. 호출 인자 capture."""
    captured: dict = {"called": False, "kwargs": None}

    def _fake_crawl(**kwargs):
        captured["called"] = True
        captured["kwargs"] = kwargs
        return papers

    monkeypatch.setattr("mlops.scripts.export_embeddings.crawl_papers", _fake_crawl)
    return captured


def _patch_chunker(monkeypatch, chunks_per_paper: int = 2):
    """chunk_papers를 결정론적으로 — paper당 N개 chunk 생성."""

    def _fake_chunk(papers):
        out: list[Chunk] = []
        for p in papers:
            for i in range(chunks_per_paper):
                out.append(
                    Chunk(
                        paper_pmid=p.meta.pmid,
                        paper_title=p.meta.title,
                        section_name="abstract",
                        chunk_index=i,
                        content=f"chunk-{p.meta.pmid}-{i}",
                        token_count=50,
                    )
                )
        return out

    monkeypatch.setattr("mlops.scripts.export_embeddings.chunk_papers", _fake_chunk)


# ── default 모드 ────────────────────────────────────────────────────────


def test_default_mode_writes_chunks_emb_and_timing(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100"), _fake_paper("200")])
    _patch_chunker(monkeypatch)

    rc = export_module.main(["--model", "bge-large", "--batch-tag", "run1", "--max-papers", "2"])
    assert rc == 0

    chunks_p = tmp_path / "chunks" / "run1.jsonl.gz"
    emb_p = tmp_path / "emb_bge-large" / "run1.jsonl.gz"
    timing_p = tmp_path / "emb_bge-large" / "run1_timing.json"
    assert chunks_p.exists()
    assert emb_p.exists()
    assert timing_p.exists()


def test_default_mode_embeddings_are_unit_vectors(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)

    rc = export_module.main(["--model", "bge-base", "--batch-tag", "norm1"])
    assert rc == 0
    emb_p = tmp_path / "emb_bge-base" / "norm1.jsonl.gz"
    with gzip.open(emb_p, "rt", encoding="utf-8") as f:
        first = json.loads(f.readline())
    vec = np.asarray(first["embedding"])
    assert vec.shape == (768,)
    np.testing.assert_allclose(np.linalg.norm(vec), 1.0, atol=1e-5)


def test_default_mode_timing_json_schema(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)

    export_module.main(["--model", "bge-large", "--batch-tag", "t1"])
    timing = json.loads((tmp_path / "emb_bge-large" / "t1_timing.json").read_text())
    for key in (
        "model_key",
        "hf_name",
        "dim",
        "n_chunks",
        "batch_size",
        "device",
        "total_sec",
        "query_prefix",
        "normalize_embeddings",
        "started_at",
        "finished_at",
    ):
        assert key in timing, f"timing.json missing key: {key}"
    assert timing["model_key"] == "bge-large"
    assert timing["dim"] == 1024
    assert timing["normalize_embeddings"] is True


# ── Test 모드 ────────────────────────────────────────────────────────


def _write_goldset(path: Path, pmids: list[str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for i, p in enumerate(pmids):
            f.write(
                json.dumps(
                    {
                        "id": f"Q{i}",
                        "query": f"want_0 query-{i}",
                        "category": "programming",
                        "expected_pmids": [p],
                    }
                )
            )
            f.write("\n")


def test_test_mode_produces_three_models_artifacts(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100"), _fake_paper("200")])
    _patch_chunker(monkeypatch)
    goldset = tmp_path / "goldset.jsonl"
    _write_goldset(goldset, ["100", "200"])

    rc = export_module.main(["--test", "--batch-tag", "abtest1", "--goldset", str(goldset), "--max-papers", "2"])
    assert rc == 0
    # 3 모델 산출물
    for key in ("bge-large", "bge-base", "pubmedbert-msmarco"):
        assert (tmp_path / f"emb_{key}" / "abtest1.jsonl.gz").exists()
        assert (tmp_path / f"emb_{key}" / "abtest1_timing.json").exists()
    # reports/<tag>_<key>.md 3개
    reports_dir = tmp_path / "eval_reports"
    for key in ("bge-large", "bge-base", "pubmedbert-msmarco"):
        assert (reports_dir / f"abtest1_{key}.md").exists()


def test_test_mode_models_subset(export_module, tmp_path, monkeypatch):
    """--models로 부분 선택 시 그 모델만 처리."""
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    goldset = tmp_path / "goldset.jsonl"
    _write_goldset(goldset, ["100"])

    rc = export_module.main(
        [
            "--test",
            "--batch-tag",
            "subset1",
            "--goldset",
            str(goldset),
            "--models",
            "bge-large,bge-base",
        ]
    )
    assert rc == 0
    assert (tmp_path / "emb_bge-large" / "subset1.jsonl.gz").exists()
    assert (tmp_path / "emb_bge-base" / "subset1.jsonl.gz").exists()
    assert not (tmp_path / "emb_pubmedbert-msmarco" / "subset1.jsonl.gz").exists()


# ── Fail-fast ───────────────────────────────────────────────────────────


def test_failfast_default_mode_requires_model(export_module, tmp_path):
    with pytest.raises(SystemExit):
        export_module.main(["--batch-tag", "x"])


def test_failfast_unknown_model_key(export_module, tmp_path):
    with pytest.raises(SystemExit):
        export_module.main(["--model", "nonexistent", "--batch-tag", "x"])


def test_failfast_unknown_models_key_in_test_mode(export_module, tmp_path):
    goldset = tmp_path / "gs.jsonl"
    _write_goldset(goldset, ["1"])
    with pytest.raises(SystemExit):
        export_module.main(["--test", "--batch-tag", "x", "--goldset", str(goldset), "--models", "bge-large,bogus"])


def test_failfast_test_requires_goldset_exists(export_module, tmp_path):
    with pytest.raises(SystemExit):
        export_module.main(["--test", "--batch-tag", "x", "--goldset", str(tmp_path / "missing.jsonl")])


def test_failfast_goldset_invalid_json(export_module, tmp_path):
    goldset = tmp_path / "bad.jsonl"
    goldset.write_text("this is not json\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        export_module.main(["--test", "--batch-tag", "x", "--goldset", str(goldset)])


def test_failfast_existing_emb_without_overwrite(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    # 1차 실행 — 산출물 생성
    rc = export_module.main(["--model", "bge-large", "--batch-tag", "dup"])
    assert rc == 0
    # 2차 실행 — 동일 tag, --overwrite 없음 → fail
    with pytest.raises(SystemExit):
        export_module.main(["--model", "bge-large", "--batch-tag", "dup"])


def test_failfast_partial_emb_in_test_mode_without_overwrite(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    goldset = tmp_path / "gs.jsonl"
    _write_goldset(goldset, ["100"])
    # bge-large 산출물만 미리 생성 (다른 두 모델은 없음)
    rc = export_module.main(["--model", "bge-large", "--batch-tag", "partial"])
    assert rc == 0
    # test 모드 — 일부만 존재해도 fail-fast
    with pytest.raises(SystemExit):
        export_module.main(["--test", "--batch-tag", "partial", "--goldset", str(goldset)])


def test_overwrite_allows_replacing_existing(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    export_module.main(["--model", "bge-large", "--batch-tag", "ow"])
    # overwrite 명시 → 통과
    rc = export_module.main(["--model", "bge-large", "--batch-tag", "ow", "--overwrite", "--reuse-chunks"])
    assert rc == 0


def test_failfast_require_gpu_without_cuda(export_module, tmp_path, monkeypatch):
    """device=cpu 환경에서 --require-gpu는 즉시 실패."""
    monkeypatch.setenv("MLOPS_EMBED_DEVICE", "cpu")
    with pytest.raises(SystemExit):
        export_module.main(["--model", "bge-large", "--batch-tag", "g", "--require-gpu"])


# ── reuse-chunks ────────────────────────────────────────────────────────


def test_reuse_chunks_skips_crawl(export_module, tmp_path, monkeypatch):
    """chunks 파일이 이미 있으면 --reuse-chunks가 crawl_papers를 호출하지 않아야."""
    _patch_chunker(monkeypatch)
    # 1차 — 정상 crawl
    captured = _patch_crawl(monkeypatch, [_fake_paper("100")])
    export_module.main(["--model", "bge-large", "--batch-tag", "rc"])
    assert captured["called"] is True

    # 2차 — reuse-chunks 사용. crawl 인자 capture 리셋
    captured["called"] = False
    export_module.main(["--model", "bge-large", "--batch-tag", "rc", "--reuse-chunks", "--overwrite"])
    assert captured["called"] is False


# ── chunks-only ─────────────────────────────────────────────────────────


def test_chunks_only_skips_embedding(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    rc = export_module.main(["--model", "bge-large", "--batch-tag", "co", "--chunks-only"])
    assert rc == 0
    assert (tmp_path / "chunks" / "co.jsonl.gz").exists()
    assert not (tmp_path / "emb_bge-large" / "co.jsonl.gz").exists()


# ── strict-goldset ──────────────────────────────────────────────────────


def test_strict_goldset_fails_on_missing_pmid(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])  # corpus는 100만
    _patch_chunker(monkeypatch)
    goldset = tmp_path / "gs.jsonl"
    _write_goldset(goldset, ["100", "NOT_IN_CORPUS"])  # corpus에 없는 PMID 포함

    rc = export_module.main(["--test", "--batch-tag", "strict", "--goldset", str(goldset), "--strict-goldset"])
    assert rc == 2  # _goldset_coverage에서 return 2


def test_warn_only_goldset_missing_pmid_proceeds(export_module, tmp_path, monkeypatch):
    _patch_crawl(monkeypatch, [_fake_paper("100")])
    _patch_chunker(monkeypatch)
    goldset = tmp_path / "gs.jsonl"
    _write_goldset(goldset, ["100", "NOT_IN_CORPUS"])

    # --strict-goldset 없음 → WARNING + 계속 진행
    rc = export_module.main(["--test", "--batch-tag", "warn1", "--goldset", str(goldset)])
    assert rc == 0


# ── output paths helpers ────────────────────────────────────────────────


def test_chunks_path_format(export_module, tmp_path):
    assert export_module._chunks_path("xyz") == tmp_path / "chunks" / "xyz.jsonl.gz"


def test_emb_path_format(export_module, tmp_path):
    assert export_module._emb_path("xyz", "bge-large") == tmp_path / "emb_bge-large" / "xyz.jsonl.gz"


def test_timing_path_format(export_module, tmp_path):
    assert export_module._timing_path("xyz", "bge-large") == tmp_path / "emb_bge-large" / "xyz_timing.json"
