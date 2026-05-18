"""initial_ingest.py 핵심 함수 단위 테스트."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.models import Chunk
from mlops.scripts.initial_ingest import ACTIVE_SOURCES, _build_payload


def test_active_sources_phase1():
    """Phase 1 ACTIVE_SOURCES = {pmc, europepmc}."""
    assert {"pmc", "europepmc"} == ACTIVE_SOURCES


def test_build_payload_includes_evidence_meta():
    """payload chunks에 doi/publication_types/evidence_weight/fulltext_source/published_year 포함."""
    chunk = Chunk(
        paper_pmid="123",
        paper_doi="10.1/x",
        paper_title="T",
        section_name="Intro",
        chunk_index=0,
        content="body",
        token_count=10,
        search_categories=["volume"],
        publication_types=["Randomized Controlled Trial"],
        evidence_weight=0.90,
        fulltext_source="pmc",
        published_year=2020,
    )
    payload = _build_payload([(chunk, [0.1] * 1024)])
    c = payload["chunks"][0]
    assert c["paper_doi"] == "10.1/x"
    assert c["publication_types"] == ["Randomized Controlled Trial"]
    assert c["evidence_weight"] == 0.90
    assert c["fulltext_source"] == "pmc"
    assert c["published_year"] == 2020


def test_build_payload_handles_none_fulltext_source():
    """fulltext_source=None인 청크도 빈 문자열로 변환되어 payload에 포함."""
    chunk = Chunk(
        paper_pmid="0",
        paper_doi="10.1/y",
        paper_title="T",
        section_name="s",
        chunk_index=0,
        content="x",
        token_count=1,
        fulltext_source=None,
        published_year=None,
    )
    payload = _build_payload([(chunk, [0.0])])
    c = payload["chunks"][0]
    assert c["fulltext_source"] == ""
    assert c["published_year"] == 0


def test_build_payload_paper_pmid_none_becomes_empty_string():
    """paper_pmid=None(DOI-only paper)인 경우 빈 문자열로 변환."""
    chunk = Chunk(
        paper_pmid="",
        paper_doi="10.1/z",
        paper_title="No PMID Paper",
        section_name="abstract",
        chunk_index=0,
        content="content",
        token_count=5,
    )
    payload = _build_payload([(chunk, [0.0] * 3)])
    c = payload["chunks"][0]
    assert c["paper_pmid"] == ""
    assert c["paper_doi"] == "10.1/z"


def test_build_payload_multiple_chunks():
    """여러 청크가 모두 payload에 포함된다."""
    chunks = [
        Chunk(
            paper_pmid=str(i),
            paper_doi=f"10.1/{i}",
            paper_title=f"Paper {i}",
            section_name="Methods",
            chunk_index=i,
            content=f"content {i}",
            token_count=10 + i,
            publication_types=["Meta-Analysis"],
            evidence_weight=0.80,
            fulltext_source="europepmc",
            published_year=2021 + i,
        )
        for i in range(3)
    ]
    chunk_vectors = [(c, [float(i)] * 4) for i, c in enumerate(chunks)]
    payload = _build_payload(chunk_vectors)
    assert len(payload["chunks"]) == 3
    for i, c in enumerate(payload["chunks"]):
        assert c["paper_doi"] == f"10.1/{i}"
        assert c["published_year"] == 2021 + i
        assert c["fulltext_source"] == "europepmc"
