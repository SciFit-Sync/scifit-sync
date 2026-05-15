"""load_embeddings / export_embeddings 단위 테스트.

외부 NCBI/임베딩/HTTP/ChromaDB 호출은 모두 mock 처리한다.
PR #63 리뷰 반영:
- iter_records fail-fast 정책 + --skip-errors 동작
- gzip 입력 경로 회귀 방지
- skip_errors 인자가 load_local/load_api까지 전파됨을 검증
- export_embeddings의 update_manifest 기본값(False) + --update-manifest 플래그 동작
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mlops.pipeline.config import EMBEDDING_DIM
from mlops.scripts import export_embeddings, load_embeddings


def _make_record(pmid: str = "12345", chunk_index: int = 0, dim: int = EMBEDDING_DIM) -> dict[str, Any]:
    return {
        "paper_pmid": pmid,
        "paper_title": f"Paper {pmid}",
        "section_name": "Methods",
        "chunk_index": chunk_index,
        "content": "sample content",
        "token_count": 10,
        "search_categories": ["volume", "hypertrophy_strength"],
        "embedding": [0.01] * dim,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any] | str]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            if isinstance(r, dict):
                f.write(json.dumps(r))
            else:
                f.write(r)
            f.write("\n")


class TestIterRecords:
    def test_iter_records_fail_fast_on_dirty_line(self, tmp_path: Path) -> None:
        """기본 동작: 단일 오염 라인에서 즉시 raise."""
        p = tmp_path / "dirty.jsonl"
        _write_jsonl(p, [_make_record("1"), "{not valid json", _make_record("2")])
        with pytest.raises(json.JSONDecodeError):
            list(load_embeddings.iter_records(p))

    def test_iter_records_skip_errors_continues(self, tmp_path: Path) -> None:
        """skip_errors=True: 오염 라인 skip, 정상 라인은 yield."""
        p = tmp_path / "mixed.jsonl"
        _write_jsonl(p, [_make_record("1"), "{not valid json", _make_record("2")])
        results = list(load_embeddings.iter_records(p, skip_errors=True))
        assert len(results) == 2
        pmids = [chunk.paper_pmid for chunk, _ in results]
        assert pmids == ["1", "2"]

    def test_iter_records_skip_errors_dim_mismatch(self, tmp_path: Path) -> None:
        """임베딩 차원 불일치 라인을 skip."""
        p = tmp_path / "dim.jsonl"
        bad = _make_record("bad", dim=512)
        _write_jsonl(p, [_make_record("1"), bad, _make_record("2")])
        results = list(load_embeddings.iter_records(p, skip_errors=True))
        assert [chunk.paper_pmid for chunk, _ in results] == ["1", "2"]

    def test_iter_records_skip_errors_missing_embedding_key(self, tmp_path: Path) -> None:
        """embedding 키 누락 라인을 skip."""
        p = tmp_path / "missing.jsonl"
        no_emb = _make_record("no_emb")
        del no_emb["embedding"]
        _write_jsonl(p, [_make_record("1"), no_emb, _make_record("2")])
        results = list(load_embeddings.iter_records(p, skip_errors=True))
        assert [chunk.paper_pmid for chunk, _ in results] == ["1", "2"]

    def test_iter_records_blank_lines(self, tmp_path: Path) -> None:
        """빈 줄은 정상 skip (오류 아님)."""
        p = tmp_path / "blank.jsonl"
        with p.open("w", encoding="utf-8") as f:
            f.write(json.dumps(_make_record("1")) + "\n")
            f.write("\n")
            f.write("   \n")
            f.write(json.dumps(_make_record("2")) + "\n")
        results = list(load_embeddings.iter_records(p))
        assert [chunk.paper_pmid for chunk, _ in results] == ["1", "2"]

    def test_iter_records_all_dirty_skip(self, tmp_path: Path) -> None:
        """모두 오염 + skip_errors=True → yield 0건, raise 없음."""
        p = tmp_path / "all_dirty.jsonl"
        _write_jsonl(p, ["{bad1", "{bad2", "{bad3"])
        results = list(load_embeddings.iter_records(p, skip_errors=True))
        assert results == []

    def test_iter_records_gzip_input(self, tmp_path: Path) -> None:
        """.jsonl.gz 입력에서도 동일하게 yield/skip 동작."""
        p = tmp_path / "data.jsonl.gz"
        records = [_make_record("1"), _make_record("2")]
        with gzip.open(p, "wt", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        results = list(load_embeddings.iter_records(p))
        assert [chunk.paper_pmid for chunk, _ in results] == ["1", "2"]


class TestLoadPropagation:
    def test_load_local_propagates_skip_errors(self, tmp_path: Path) -> None:
        """load_local의 skip_errors가 iter_records에 전달된다."""
        p = tmp_path / "in.jsonl"
        _write_jsonl(p, [_make_record("1")])

        with (
            patch.object(load_embeddings, "iter_records") as mock_iter,
            patch.object(load_embeddings, "upsert_chunks", return_value=0),
        ):
            mock_iter.return_value = iter([])
            load_embeddings.load_local(p, batch_size=10, skip_errors=True)
            mock_iter.assert_called_once_with(p, skip_errors=True)

    def test_load_api_propagates_skip_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """load_api의 skip_errors가 iter_records에 전달된다."""
        p = tmp_path / "in.jsonl"
        _write_jsonl(p, [_make_record("1")])

        monkeypatch.setattr(load_embeddings, "API_BASE_URL", "https://example.com")
        monkeypatch.setattr(load_embeddings, "ADMIN_API_TOKEN", "token")

        with patch.object(load_embeddings, "iter_records") as mock_iter:
            mock_iter.return_value = iter([])
            load_embeddings.load_api(p, batch_size=10, skip_errors=True)
            mock_iter.assert_called_once_with(p, skip_errors=True)


class TestExportManifest:
    def test_export_main_default_no_manifest_change(self, tmp_path: Path) -> None:
        """update_manifest=False(기본)면 save_manifest 호출 안 됨."""
        output = tmp_path / "out.jsonl"
        fake_paper = MagicMock()
        fake_paper.meta.pmid = "1"
        fake_chunk = MagicMock()
        fake_chunk.model_dump.return_value = {"paper_pmid": "1"}

        with (
            patch.object(export_embeddings, "crawl_papers", return_value=[fake_paper]),
            patch.object(export_embeddings, "chunk_papers", return_value=[fake_chunk]),
            patch.object(export_embeddings, "embed_chunks", return_value=[(fake_chunk, [0.0] * 4)]),
            patch.object(export_embeddings, "load_manifest", return_value=set()),
            patch.object(export_embeddings, "save_manifest") as mock_save,
        ):
            export_embeddings.main(
                max_papers=1,
                output=output,
                use_gzip=False,
                dry_run=False,
                min_date=None,
                max_date=None,
                update_manifest=False,
            )
            mock_save.assert_not_called()

    def test_export_main_update_manifest_flag(self, tmp_path: Path) -> None:
        """update_manifest=True면 save_manifest 호출됨."""
        output = tmp_path / "out.jsonl"
        fake_paper = MagicMock()
        fake_paper.meta.pmid = "1"
        fake_chunk = MagicMock()
        fake_chunk.model_dump.return_value = {"paper_pmid": "1"}

        with (
            patch.object(export_embeddings, "crawl_papers", return_value=[fake_paper]),
            patch.object(export_embeddings, "chunk_papers", return_value=[fake_chunk]),
            patch.object(export_embeddings, "embed_chunks", return_value=[(fake_chunk, [0.0] * 4)]),
            patch.object(export_embeddings, "load_manifest", return_value=set()),
            patch.object(export_embeddings, "save_manifest") as mock_save,
        ):
            export_embeddings.main(
                max_papers=1,
                output=output,
                use_gzip=False,
                dry_run=False,
                min_date=None,
                max_date=None,
                update_manifest=True,
            )
            mock_save.assert_called_once()
            (saved_pmids,) = mock_save.call_args.args
            assert saved_pmids == {"1"}
