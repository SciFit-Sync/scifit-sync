"""full_reingest orchestrator 단위 테스트 (Stage 3.5 게이트 + Stage 4 retry)."""

import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from mlops.scripts.full_reingest import stage3_5_validate, stage4_upsert


def _make_ok_jsonl(n=60) -> Path:
    """모든 임계 충족하는 jsonl."""
    weights = [0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0]
    types_list = [
        ["Case Reports"],
        ["Review"],
        ["Journal Article"],
        ["Cohort Study"],
        ["Clinical Trial"],
        ["Randomized Controlled Trial"],
        ["Meta-Analysis"],
    ]
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    records = []
    for p in range(3):
        for c in range(25):
            i = p * 25 + c
            records.append(
                {
                    "chunk_index": c,
                    "paper_pmid": f"pmid{p}",
                    "paper_title": "T",
                    "section_name": "Methods",
                    # local_pdf 서브셋은 PDF_AVG_TOKEN 범위(150~250) 안으로,
                    # 그 외는 AVG_TOKEN 범위(300~450) 만족하도록 분기
                    "token_count": 200 if p == 0 else 400,
                    "search_categories": [],
                    "paper_doi": f"10.1/{p}",
                    "publication_types": types_list[i % len(types_list)],
                    "evidence_weight": weights[i % len(weights)],
                    "fulltext_source": "local_pdf" if p == 0 else "pmc",
                    "published_year": 2018,
                    "embedding": [0.1] * 1024,
                }
            )
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return tmp


def test_stage3_5_passes_on_good_jsonl():
    path = _make_ok_jsonl(60)
    assert stage3_5_validate(path) is True


def test_stage3_5_fails_on_bad_jsonl():
    path = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_index": 0}) + "\n")  # 키 통째 누락
    assert stage3_5_validate(path) is False


# --------------------------------------------------------------------------- #
# Stage 4 retry — load_embeddings.load_api와 동일 패턴(502/503/504 + ConnectionError
# + exponential backoff) 이식 검증. 2,500만 청크 × 1,250~2,100 _post 호출 중
# transient 5xx 1회로 stage4 abort + 수동 재실행 비용을 차단.
# --------------------------------------------------------------------------- #


def _make_minimal_jsonl(n: int = 1) -> Path:
    """retry 테스트용 최소 jsonl (validation 게이트는 거치지 않음)."""
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for i in range(n):
            r = {
                "chunk_index": i,
                "paper_pmid": "pmid1",
                "paper_title": "T",
                "section_name": "Methods",
                "token_count": 300,
                "search_categories": [],
                "paper_doi": "10.1/x",
                "publication_types": ["Review"],
                "evidence_weight": 0.5,
                "fulltext_source": "pmc",
                "published_year": 2020,
                "content": "abc",
                "embedding": [0.1] * 1024,
            }
            f.write(json.dumps(r) + "\n")
    return tmp


def _fake_resp(status: int, body=None):
    """resp.raise_for_status / resp.json 흉내내는 MagicMock factory."""
    m = MagicMock()
    m.status_code = status
    if status >= 400:
        err = requests.exceptions.HTTPError(response=m)
        m.raise_for_status.side_effect = err
    else:
        m.raise_for_status.return_value = None
        m.json.return_value = body or {"data": {"upserted": 1}}
    return m


def _patch_env(monkeypatch):
    """ADMIN_API_TOKEN / API_BASE_URL 둘 다 stage4_upsert 함수 내부 import 대상에 패치.

    함수가 `from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL`을
    호출 시점에 수행하므로 모듈 attr를 교체한다.
    """
    monkeypatch.setattr("mlops.pipeline.config.API_BASE_URL", "http://stub")
    monkeypatch.setattr("mlops.pipeline.config.ADMIN_API_TOKEN", "stub-tok")
    # backoff sleep 가속 — 실제 sleep 회피
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)


def test_stage4_upsert_retries_on_5xx(monkeypatch, tmp_path):
    """502 → 200 시퀀스에서 retry 후 성공."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)
    monkeypatch.setattr("mlops.scripts.full_reingest.DATA_DIR", tmp_path)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_resp(502)
        return _fake_resp(200, {"data": {"upserted": 1}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2")
    assert total == 1
    assert calls["n"] == 2  # 1차 502 + 2차 성공


def test_stage4_upsert_retries_on_connection_error(monkeypatch, tmp_path):
    """ConnectionError → 200 시퀀스에서도 retry."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)
    monkeypatch.setattr("mlops.scripts.full_reingest.DATA_DIR", tmp_path)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ConnectionError("transient")
        return _fake_resp(200, {"data": {"upserted": 1}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2")
    assert total == 1
    assert calls["n"] == 2


def test_stage4_upsert_raises_after_max_retries(monkeypatch, tmp_path):
    """5번 연속 502 → max_retries(5) 초과로 HTTPError raise."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)
    monkeypatch.setattr("mlops.scripts.full_reingest.DATA_DIR", tmp_path)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(502)

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(requests.exceptions.HTTPError):
        stage4_upsert(path, "papers_v2")
    assert calls["n"] == 5  # 정확히 max_retries 만큼 호출


def test_stage4_upsert_does_not_retry_on_4xx(monkeypatch, tmp_path):
    """400/401/404 등 4xx는 retry 없이 즉시 raise — 운영자 개입 신호 보존."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)
    monkeypatch.setattr("mlops.scripts.full_reingest.DATA_DIR", tmp_path)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(401)

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(requests.exceptions.HTTPError):
        stage4_upsert(path, "papers_v2")
    assert calls["n"] == 1  # 4xx는 1회로 끝


# --------------------------------------------------------------------------- #
# Stage 4 resumable — batch 단위 manifest로 완료된 batch 자동 skip.
# 실패 후 재실행 시 0~실패batch 중복 처리 비용 차단.
# --------------------------------------------------------------------------- #


def _patch_data_dir(monkeypatch, tmp_path):
    """upsert progress manifest가 DATA_DIR에 쓰여지므로 tmp_path로 redirect."""
    monkeypatch.setattr("mlops.scripts.full_reingest.DATA_DIR", tmp_path)


def test_stage4_upsert_custom_batch_size(monkeypatch, tmp_path):
    """batch_size 인자가 _post 호출 횟수에 정확히 반영."""
    path = _make_minimal_jsonl(7)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    calls = {"n": 0, "sizes": []}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        calls["sizes"].append(len(json["chunks"]))
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2", batch_size=3, batch_tag="t1")
    # 7청크 / batch_size 3 → 3 + 3 + 1 (마지막 잔여)
    assert total == 7
    assert calls["n"] == 3
    assert calls["sizes"] == [3, 3, 1]


def test_stage4_upsert_creates_progress_manifest(monkeypatch, tmp_path):
    """첫 실행에서 완료된 batch_idx가 progress manifest에 atomic write."""
    path = _make_minimal_jsonl(6)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    def fake_post(url, json=None, headers=None, timeout=None):
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    stage4_upsert(path, "papers_v2", batch_size=2, batch_tag="run1")

    manifest = tmp_path / "upsert_progress_run1_papers_v2.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["batch_tag"] == "run1"
    assert data["collection"] == "papers_v2"
    assert data["batch_size"] == 2
    # 6청크 / batch 2 → 0,1,2 batch_idx 모두 완료
    assert data["completed_batches"] == [0, 1, 2]


def test_stage4_upsert_skips_completed_batches_on_resume(monkeypatch, tmp_path):
    """재실행 시 manifest의 completed_batches는 _post 호출 안 함."""
    path = _make_minimal_jsonl(6)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    # 사전 manifest: batch_idx 0, 1 완료 가정 (batch_size 2 → 4청크 적재됨)
    manifest = tmp_path / "upsert_progress_run2_papers_v2.json"
    manifest.write_text(
        json.dumps(
            {
                "batch_tag": "run2",
                "collection": "papers_v2",
                "batch_size": 2,
                "completed_batches": [0, 1],
            }
        )
    )

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2", batch_size=2, batch_tag="run2")
    # batch 0, 1은 skip → batch 2(잔여 2청크)만 _post
    assert calls["n"] == 1
    assert total == 2  # skip된 batch는 total 누적 대상 아님 (재시작 시점 기록 X)

    # manifest는 batch 2까지 누적
    data = json.loads(manifest.read_text())
    assert data["completed_batches"] == [0, 1, 2]


def test_stage4_upsert_recovers_from_corrupted_manifest(monkeypatch, tmp_path):
    """깨진 JSON manifest는 경고 후 처음부터 시작 (fail-safe)."""
    path = _make_minimal_jsonl(2)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    manifest = tmp_path / "upsert_progress_run3_papers_v2.json"
    manifest.write_text("{ not valid json")

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2", batch_size=2, batch_tag="run3")
    # 손상 manifest → 처음부터 시작 → 1 batch 처리
    assert calls["n"] == 1
    assert total == 2
    # manifest는 정상 형태로 재기록됨
    data = json.loads(manifest.read_text())
    assert data["completed_batches"] == [0]


def test_stage4_upsert_invalidates_manifest_on_batch_size_mismatch(monkeypatch, tmp_path):
    """이전 실행과 다른 batch_size로 재실행 시 manifest 무시 — codex MAJOR [1] guard.

    batch_size가 다르면 batch_idx가 가리키는 record 범위가 어긋나 데이터 누락
    위험이 있으므로 manifest를 처음부터 다시 작성해야 한다.
    """
    path = _make_minimal_jsonl(4)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    # 사전 manifest: 이전 batch_size=2로 batch 0 완료
    manifest = tmp_path / "upsert_progress_run_mismatch_papers_v2.json"
    manifest.write_text(
        json.dumps(
            {
                "batch_tag": "run_mismatch",
                "collection": "papers_v2",
                "batch_size": 2,
                "completed_batches": [0],
            }
        )
    )

    calls = {"n": 0, "sizes": []}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        calls["sizes"].append(len(json["chunks"]))
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    # 현재 batch_size=4로 재실행 → 이전 batch_size=2 manifest 무시 + 처음부터
    total = stage4_upsert(path, "papers_v2", batch_size=4, batch_tag="run_mismatch")
    # manifest 무시 → 모든 4청크가 1 batch로 처리됨
    assert calls["n"] == 1
    assert calls["sizes"] == [4]
    assert total == 4

    # manifest는 새 batch_size=4 + completed_batches=[0]으로 덮어쓰기
    data = json.loads(manifest.read_text())
    assert data["batch_size"] == 4
    assert data["completed_batches"] == [0]


def test_stage4_upsert_progress_atomic_no_tmp_leftover(monkeypatch, tmp_path):
    """atomic write 후 .tmp.<pid>.<uuid> 파일이 남지 않음 — 부분 write 방지 검증."""
    path = _make_minimal_jsonl(4)
    _patch_env(monkeypatch)
    _patch_data_dir(monkeypatch, tmp_path)

    def fake_post(url, json=None, headers=None, timeout=None):
        return _fake_resp(200, {"data": {"upserted": len(json["chunks"])}})

    monkeypatch.setattr("requests.post", fake_post)
    stage4_upsert(path, "papers_v2", batch_size=2, batch_tag="run4")

    leftover = list(tmp_path.glob("upsert_progress_*.tmp.*"))
    assert leftover == [], f".tmp 잔여물: {leftover}"


# ──────────────────────────────────────────────────────────────────────────────
# stage1_fetch phase2_full — local PDF publication_types 보강 wiring
# local PDF는 DOI는 있으나 publication_types가 비어 있어, crawl_papers 밖에서
# 합쳐지는 PDF paper도 chunk 전에 보강돼야 validate fill rate 희석을 막는다.
# ──────────────────────────────────────────────────────────────────────────────


def test_phase2_full_backfills_local_pdf_publication_types(monkeypatch, tmp_path):
    """phase2_full은 통합 set(크롤+local PDF)에 publication_types 보강을 적용해야 한다."""
    import json as _json

    import mlops.scripts.full_reingest as fr
    from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

    monkeypatch.setattr(fr, "DATA_DIR", tmp_path)
    pdf_root = tmp_path / "local_pdfs"
    pdf_root.mkdir(parents=True)
    (pdf_root / "manifest.json").write_text(
        _json.dumps({"papers": [{"doi": "10.1/pdf", "title": "P", "filename": "p.pdf"}]}),
        encoding="utf-8",
    )

    jats = PaperFull(
        meta=PaperMeta(pmid="1", title="J", doi="10.1/jats", publication_types=["Review"]),
        sections=[PaperSection(name="s", content="x")],
    )
    pdf = PaperFull(
        meta=PaperMeta(pmid="", title="P", doi="10.1/pdf"),  # 빈 publication_types
        sections=[PaperSection(name="s", content="y")],
    )

    monkeypatch.setattr("mlops.pipeline.crawler.crawl_papers", lambda **kw: [jats])
    monkeypatch.setattr("mlops.scripts.ingest_local_pdfs.build_paperfull", lambda entry, pdf_dir: pdf)

    def fake_backfill(metas):
        n = 0
        for m in metas:
            if not m.publication_types and m.doi:
                m.publication_types = ["Randomized Controlled Trial"]
                n += 1
        return n

    monkeypatch.setattr("mlops.pipeline.crawler.backfill_publication_types_from_pubmed", fake_backfill)

    captured: dict = {}

    def fake_chunk(papers):
        captured["pub_types"] = {p.meta.doi: list(p.meta.publication_types) for p in papers}
        return []

    monkeypatch.setattr("mlops.pipeline.chunker.chunk_papers", fake_chunk)
    monkeypatch.setattr("mlops.scripts.export_embeddings._chunks_path", lambda tag: tmp_path / f"{tag}.jsonl.gz")
    monkeypatch.setattr("mlops.scripts.export_embeddings._save_chunks_atomic", lambda *a, **k: None)
    monkeypatch.setattr("mlops.scripts.export_embeddings._write_meta_sidecar", lambda *a, **k: None)
    monkeypatch.setattr("mlops.pipeline.config.MANIFEST_PATH", tmp_path / "pipeline_manifest.json")

    fr.stage1_fetch(batch_tag="dry_test", mode="phase2_full", max_per_category=1)

    # local PDF가 chunk 시점에 publication_types를 보유해야 한다 (보강 wiring)
    assert captured["pub_types"]["10.1/pdf"] == ["Randomized Controlled Trial"]
    # 이미 보유한 JATS는 그대로 (멱등)
    assert captured["pub_types"]["10.1/jats"] == ["Review"]


# --------------------------------------------------------------------------- #
# --categories wiring — main → stage1_fetch → crawl_papers 전달 검증.
# --------------------------------------------------------------------------- #


class TestCategoriesWiring:
    """--categories 인자가 stage1_fetch까지 올바르게 전달되는지 검증."""

    def _common_patches(self, monkeypatch, tmp_path, captured: dict):
        """main 실행에 필요한 모든 stage를 stub으로 교체."""
        import mlops.scripts.full_reingest as fr

        # stage1_fetch를 가짜로 교체해 categories 수신 여부 확인
        def fake_stage1(
            batch_tag,
            mode,
            max_per_category,
            categories=None,
            skip_local_pdf=False,
            resume_from_manifest=False,
        ):
            captured["categories"] = categories
            captured["skip_local_pdf"] = skip_local_pdf
            captured["resume_from_manifest"] = resume_from_manifest
            return tmp_path / "manifest.json"

        monkeypatch.setattr(fr, "stage1_fetch", fake_stage1)
        monkeypatch.setattr(fr, "stage1_5_manifest_sanity", lambda p: True)
        monkeypatch.setattr(fr, "stage2_3_chunk_embed", lambda tag: tmp_path / "emb.jsonl.gz")
        monkeypatch.setattr(fr, "stage3_5_validate", lambda p: True)
        monkeypatch.setattr(fr, "stage4_upsert", lambda *a, **kw: 0)

    def test_categories_passed_to_stage1(self, monkeypatch, tmp_path):
        """--categories volume,intensity → stage1_fetch(categories=['volume','intensity'])."""
        import mlops.scripts.full_reingest as fr

        captured: dict = {}
        self._common_patches(monkeypatch, tmp_path, captured)

        fr.main(
            [
                "--mode",
                "phase2_full",
                "--batch-tag",
                "test-batch",
                "--categories",
                "volume,intensity",
                "--skip-stages",
                "chunk_embed",
                "validate",
                "upsert",
            ]
        )

        assert captured["categories"] == ["volume", "intensity"]

    def test_no_categories_passes_none(self, monkeypatch, tmp_path):
        """--categories 미지정 시 stage1_fetch에 categories=None 전달."""
        import mlops.scripts.full_reingest as fr

        captured: dict = {}
        self._common_patches(monkeypatch, tmp_path, captured)

        fr.main(
            [
                "--mode",
                "phase2_full",
                "--batch-tag",
                "test-batch",
                "--skip-stages",
                "chunk_embed",
                "validate",
                "upsert",
            ]
        )

        assert captured["categories"] is None
        # --skip-local-pdf 미지정 시 기본 False
        assert captured["skip_local_pdf"] is False

    def test_skip_local_pdf_passed_to_stage1(self, monkeypatch, tmp_path):
        """--skip-local-pdf 지정 시 stage1_fetch에 skip_local_pdf=True 전달."""
        import mlops.scripts.full_reingest as fr

        captured: dict = {}
        self._common_patches(monkeypatch, tmp_path, captured)

        fr.main(
            [
                "--mode",
                "phase2_full",
                "--batch-tag",
                "test-batch",
                "--skip-local-pdf",
                "--skip-stages",
                "chunk_embed",
                "validate",
                "upsert",
            ]
        )

        assert captured["skip_local_pdf"] is True

    def test_resume_from_manifest_passed_to_stage1(self, monkeypatch, tmp_path):
        """--resume-from-manifest 지정 시 stage1_fetch에 resume_from_manifest=True 전달."""
        import mlops.scripts.full_reingest as fr

        captured: dict = {}
        self._common_patches(monkeypatch, tmp_path, captured)

        fr.main(
            [
                "--mode",
                "phase2_full",
                "--batch-tag",
                "test-batch",
                "--resume-from-manifest",
                "--skip-stages",
                "chunk_embed",
                "validate",
                "upsert",
            ]
        )

        assert captured["resume_from_manifest"] is True

    def test_categories_strips_whitespace(self, monkeypatch, tmp_path):
        """콤마 구분 값의 앞뒤 공백이 제거되어 전달됨."""
        import mlops.scripts.full_reingest as fr

        captured: dict = {}
        self._common_patches(monkeypatch, tmp_path, captured)

        fr.main(
            [
                "--mode",
                "phase2_full",
                "--batch-tag",
                "test-batch",
                "--categories",
                " volume , intensity , frequency ",
                "--skip-stages",
                "chunk_embed",
                "validate",
                "upsert",
            ]
        )

        assert captured["categories"] == ["volume", "intensity", "frequency"]
