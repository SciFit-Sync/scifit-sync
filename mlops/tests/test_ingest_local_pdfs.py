"""ingest_local_pdfs 단위 테스트.

pypdf 자체 파싱은 monkeypatch로 stub. 통합 흐름(metadata enrich +
build_paperfull + dry-run 분기)을 검증한다.
"""

from __future__ import annotations

import json

from mlops.pipeline.models import PaperSection
from mlops.scripts import ingest_local_pdfs


def _touch_pdf(path) -> None:
    path.write_bytes(b"%PDF-1.4 stub")


def _stub_parse_pdf(monkeypatch, content: str = "word " * 1000) -> None:
    monkeypatch.setattr(
        ingest_local_pdfs,
        "parse_pdf",
        lambda p: [PaperSection(name="Full Text", content=content)],
    )


def _block_external(monkeypatch) -> None:
    monkeypatch.setattr(ingest_local_pdfs, "efetch_pubmed_batch", lambda pmids: {})
    monkeypatch.setattr(ingest_local_pdfs, "openalex_doi_lookup", lambda doi: None)


def test_build_paperfull_uses_manifest_overrides(tmp_path, monkeypatch):
    """manifest에 명시된 메타가 외부 lookup보다 우선한다."""
    _touch_pdf(tmp_path / "x.pdf")
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)

    entry = {
        "filename": "x.pdf",
        "doi": "10.1000/test",
        "pmid": "12345",
        "search_categories": ["hypertrophy"],
        "publication_types": ["Meta-Analysis"],
        "title": "manual title",
        "published_year": 2024,
    }
    result = ingest_local_pdfs.build_paperfull(entry, tmp_path)
    assert result is not None
    assert result.meta.doi == "10.1000/test"
    assert result.meta.pmid == "12345"
    assert result.meta.title == "manual title"
    assert result.meta.published_year == 2024
    assert result.meta.evidence_weight == 1.00  # Meta-Analysis
    assert result.meta.fulltext_source == "local_pdf"
    assert result.meta.search_categories == ["hypertrophy"]


def test_build_paperfull_requires_doi_or_pmid(tmp_path, monkeypatch):
    _touch_pdf(tmp_path / "x.pdf")
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)

    entry = {"filename": "x.pdf", "search_categories": ["hypertrophy"]}
    assert ingest_local_pdfs.build_paperfull(entry, tmp_path) is None


def test_build_paperfull_missing_pdf_file(tmp_path, monkeypatch):
    _block_external(monkeypatch)
    entry = {
        "filename": "missing.pdf",
        "doi": "10.1000/test",
        "search_categories": ["hypertrophy"],
    }
    assert ingest_local_pdfs.build_paperfull(entry, tmp_path) is None


def test_build_paperfull_efetch_fills_missing_metadata(tmp_path, monkeypatch):
    """manifest에 메타 없으면 PMID efetch로 채운다."""
    _touch_pdf(tmp_path / "x.pdf")
    _stub_parse_pdf(monkeypatch)
    monkeypatch.setattr(
        ingest_local_pdfs,
        "efetch_pubmed_batch",
        lambda pmids: {
            "12345": {
                "doi": "10.1000/fromefetch",
                "pmcid": "",
                "title": "From efetch",
                "abstract": "efetch abstract",
                "publication_types": ["Randomized Controlled Trial"],
                "publication_year": 2020,
            }
        },
    )
    monkeypatch.setattr(ingest_local_pdfs, "openalex_doi_lookup", lambda doi: None)

    entry = {"filename": "x.pdf", "pmid": "12345", "search_categories": ["strength"]}
    result = ingest_local_pdfs.build_paperfull(entry, tmp_path)
    assert result is not None
    assert result.meta.title == "From efetch"
    assert result.meta.doi == "10.1000/fromefetch"
    assert result.meta.evidence_weight == 0.90  # RCT
    assert result.meta.published_year == 2020


def test_build_paperfull_openalex_fills_pmid(tmp_path, monkeypatch):
    """DOI만 있고 PMID 누락 시 OpenAlex로 PMID 자동 보강 → 골드셋 PMID 매칭 가능."""
    _touch_pdf(tmp_path / "x.pdf")
    _stub_parse_pdf(monkeypatch)
    monkeypatch.setattr(ingest_local_pdfs, "efetch_pubmed_batch", lambda pmids: {})
    monkeypatch.setattr(
        ingest_local_pdfs,
        "openalex_doi_lookup",
        lambda doi: {
            "doi": doi,
            "pmid": "99999",
            "title": "from openalex",
            "publication_year": 2019,
            "type": "article",
        },
    )

    entry = {
        "filename": "x.pdf",
        "doi": "10.1000/openalex",
        "search_categories": ["hypertrophy"],
    }
    result = ingest_local_pdfs.build_paperfull(entry, tmp_path)
    assert result is not None
    assert result.meta.pmid == "99999"
    assert result.meta.title == "from openalex"


def _write_manifest_entries(tmp_path, entries: list[dict]):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"papers": entries}), encoding="utf-8")
    return path


def _stub_pipeline_manifest(monkeypatch, indexed_dois: set[str]) -> None:
    """Manifest.load + load_existing_dois를 stub해 corpus DOI를 강제로 주입."""
    monkeypatch.setattr(
        ingest_local_pdfs,
        "load_existing_dois",
        lambda m: set(indexed_dois),
    )

    class _FakeManifest:
        def record_attempt(self, **kwargs):
            pass

        def save(self, path):
            pass

    monkeypatch.setattr(ingest_local_pdfs.Manifest, "load", lambda path: _FakeManifest())


def test_run_dedup_skips_doi_already_in_corpus(tmp_path, monkeypatch):
    """--skip-existing(기본): 이미 corpus에 있는 DOI는 건너뛴다."""
    _touch_pdf(tmp_path / "a.pdf")
    _touch_pdf(tmp_path / "b.pdf")
    manifest = _write_manifest_entries(
        tmp_path,
        [
            {"filename": "a.pdf", "doi": "10.1000/existing", "search_categories": ["x"]},
            {"filename": "b.pdf", "doi": "10.1000/fresh", "search_categories": ["x"]},
        ],
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    _stub_pipeline_manifest(monkeypatch, indexed_dois={"10.1000/existing"})

    captured: dict = {}

    def _embed(chunks):
        captured["embed_count"] = len(chunks)
        return [(c, [0.0] * 1024) for c in chunks]

    def _ingest(cv):
        captured["ingest_count"] = len(cv)
        return len(cv)

    monkeypatch.setattr(ingest_local_pdfs, "embed_chunks", _embed)
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", _ingest)
    # API 자격증명 가드 우회
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=True,
    )
    assert exit_code == 0
    # existing은 skip되고 fresh만 embed/ingest 됨 — fresh paper의 청크 수만큼만
    assert captured["embed_count"] > 0
    assert captured["ingest_count"] == captured["embed_count"]


def test_run_dedup_skips_duplicate_doi_within_batch(tmp_path, monkeypatch):
    """같은 manifest 안에서 DOI가 겹치면 두 번째는 skip."""
    _touch_pdf(tmp_path / "a.pdf")
    _touch_pdf(tmp_path / "b.pdf")
    manifest = _write_manifest_entries(
        tmp_path,
        [
            {"filename": "a.pdf", "doi": "10.1000/same", "search_categories": ["x"]},
            {"filename": "b.pdf", "doi": "10.1000/same", "search_categories": ["x"]},
        ],
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    _stub_pipeline_manifest(monkeypatch, indexed_dois=set())

    captured_papers: list = []

    def _embed(chunks):
        # 청크의 paper_doi 추적
        captured_papers.extend({c.paper_doi for c in chunks})
        return [(c, [0.0] * 1024) for c in chunks]

    monkeypatch.setattr(ingest_local_pdfs, "embed_chunks", _embed)
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: len(cv))
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=True,
    )
    assert exit_code == 0
    # 같은 DOI는 한 번만 적재
    assert set(captured_papers) == {"10.1000/same"}


def test_run_no_skip_existing_allows_reembed(tmp_path, monkeypatch):
    """--no-skip-existing: 이미 있어도 다시 적재한다."""
    _touch_pdf(tmp_path / "a.pdf")
    manifest = _write_manifest_entries(
        tmp_path,
        [{"filename": "a.pdf", "doi": "10.1000/existing", "search_categories": ["x"]}],
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    _stub_pipeline_manifest(monkeypatch, indexed_dois={"10.1000/existing"})

    captured: dict = {}
    monkeypatch.setattr(
        ingest_local_pdfs,
        "embed_chunks",
        lambda chunks: captured.update(n=len(chunks)) or [(c, [0.0] * 1024) for c in chunks],
    )
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: len(cv))
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=False,
    )
    assert exit_code == 0
    assert captured["n"] > 0  # skip되지 않음


def test_safe_pdf_path_blocks_traversal(tmp_path):
    """절대 경로 / `..` traversal / 비-string은 차단된다."""
    (tmp_path / "ok.pdf").write_bytes(b"%PDF-1.4")

    assert ingest_local_pdfs._safe_pdf_path(tmp_path, "ok.pdf") is not None
    assert ingest_local_pdfs._safe_pdf_path(tmp_path, "../etc/passwd") is None
    assert ingest_local_pdfs._safe_pdf_path(tmp_path, "/etc/passwd") is None
    assert ingest_local_pdfs._safe_pdf_path(tmp_path, "") is None
    assert ingest_local_pdfs._safe_pdf_path(tmp_path, None) is None  # type: ignore[arg-type]
    assert ingest_local_pdfs._safe_pdf_path(tmp_path, 123) is None  # type: ignore[arg-type]


def test_build_paperfull_rejects_traversal_filename(tmp_path, monkeypatch):
    """manifest의 path traversal filename은 build 단계에서 차단."""
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    entry = {"filename": "../escape.pdf", "doi": "10.1000/x", "search_categories": ["x"]}
    assert ingest_local_pdfs.build_paperfull(entry, tmp_path) is None


def test_run_dedup_skips_pmid_only_duplicate_in_batch(tmp_path, monkeypatch):
    """PMID-only 입력에서 DOI 해결 실패해도 in-batch PMID 중복은 잡혀야 한다."""
    _touch_pdf(tmp_path / "a.pdf")
    _touch_pdf(tmp_path / "b.pdf")
    manifest = _write_manifest_entries(
        tmp_path,
        [
            {"filename": "a.pdf", "pmid": "99999", "search_categories": ["x"]},
            {"filename": "b.pdf", "pmid": "99999", "search_categories": ["x"]},
        ],
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)  # OpenAlex 실패 → DOI 미해결 → PMID-only 경로
    _stub_pipeline_manifest(monkeypatch, indexed_dois=set())

    captured: dict = {}

    def _embed(chunks):
        captured["pmids"] = {c.paper_pmid for c in chunks}
        return [(c, [0.0] * 1024) for c in chunks]

    monkeypatch.setattr(ingest_local_pdfs, "embed_chunks", _embed)
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: len(cv))
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=True,
    )
    assert exit_code == 0
    # 같은 PMID는 한 번만 적재
    assert captured["pmids"] == {"99999"}


def test_run_skips_non_dict_manifest_entry(tmp_path, monkeypatch):
    """manifest['papers'] 안에 dict가 아닌 값이 섞여 있으면 그 entry만 skip."""
    _touch_pdf(tmp_path / "a.pdf")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "papers": [
                    "string_not_dict",
                    None,
                    {"filename": "a.pdf", "doi": "10.1000/x", "search_categories": ["x"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    _stub_pipeline_manifest(monkeypatch, indexed_dois=set())
    monkeypatch.setattr(ingest_local_pdfs, "embed_chunks", lambda cs: [(c, [0.0] * 1024) for c in cs])
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: len(cv))
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    # AttributeError 없이 0으로 종료해야 함 (dict entry 1개만 처리)
    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=True,
    )
    assert exit_code == 0


def test_run_dedup_skips_duplicate_filename(tmp_path, monkeypatch):
    """같은 filename이 manifest에 두 번 있으면 두 번째는 skip."""
    _touch_pdf(tmp_path / "a.pdf")
    manifest = _write_manifest_entries(
        tmp_path,
        [
            {"filename": "a.pdf", "doi": "10.1000/x1", "search_categories": ["x"]},
            {"filename": "a.pdf", "doi": "10.1000/x2", "search_categories": ["x"]},
        ],
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)
    _stub_pipeline_manifest(monkeypatch, indexed_dois=set())

    captured: dict = {}
    monkeypatch.setattr(
        ingest_local_pdfs,
        "embed_chunks",
        lambda chunks: captured.update(dois={c.paper_doi for c in chunks}) or [(c, [0.0] * 1024) for c in chunks],
    )
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: len(cv))
    monkeypatch.setattr(ingest_local_pdfs, "API_BASE_URL", "http://stub")
    monkeypatch.setattr(ingest_local_pdfs, "ADMIN_API_TOKEN", "stub")

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=False,
        export_batch=None,
        embed_model="bge-large",
        skip_existing=True,
    )
    assert exit_code == 0
    # 같은 filename 두 번째 entry(다른 DOI)는 skip → 첫 DOI만 적재됨
    assert captured["dois"] == {"10.1000/x1"}


def test_run_dry_run_skips_embed_and_ingest(tmp_path, monkeypatch):
    _touch_pdf(tmp_path / "x.pdf")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "filename": "x.pdf",
                        "doi": "10.1000/test",
                        "search_categories": ["hypertrophy"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _stub_parse_pdf(monkeypatch)
    _block_external(monkeypatch)

    calls = {"embed": 0, "ingest": 0}
    monkeypatch.setattr(ingest_local_pdfs, "embed_chunks", lambda chunks: calls.update(embed=calls["embed"] + 1) or [])
    monkeypatch.setattr(ingest_local_pdfs, "api_ingest", lambda cv: calls.update(ingest=calls["ingest"] + 1) or 0)

    exit_code = ingest_local_pdfs.run(
        manifest_path=manifest,
        pdf_dir=tmp_path,
        dry_run=True,
        export_batch=None,
        embed_model="bge-large",
    )
    assert exit_code == 0
    assert calls == {"embed": 0, "ingest": 0}
