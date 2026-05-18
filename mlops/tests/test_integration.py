"""Phase 1 통합 시나리오 — cascading fulltext + manifest end-to-end mock."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mlops.pipeline.crawler import _attach_fulltext
from mlops.pipeline.fulltext import CascadingFulltextResult
from mlops.pipeline.manifest import Manifest
from mlops.pipeline.models import (
    PaperMeta,
    PaperSection,
)


def _meta(doi: str, pmid: str = "1", pmcid: str | None = None) -> PaperMeta:
    return PaperMeta(
        pmid=pmid,
        title=f"Paper {doi}",
        authors="",
        journal="",
        published_year=2020,
        doi=doi,
        abstract="",
        pmcid=pmcid,
        publication_types=["Randomized Controlled Trial"],
        evidence_weight=0.90,
    )


@pytest.fixture
def mock_clients(monkeypatch):
    """PMC, EuropePMC 클라이언트 mock."""
    monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
    monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())


class TestCascadingScenarios:
    """cascading fulltext의 네 가지 시나리오 검증."""

    def test_pmc_success(self, monkeypatch, mock_clients):
        """PMC 본문 확보 성공 → fulltext_source='pmc'."""
        def fake_cascading(**_):
            return CascadingFulltextResult(
                fulltext_source="pmc",
                tried_sources=["pmc"],
                sections=[PaperSection(name="Intro", content="content")],
                had_transient_error=False,
            )
        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_cascading)

        papers = _attach_fulltext([_meta("10.1/a", pmcid="PMC1")])
        assert papers[0].meta.fulltext_source == "pmc"
        assert len(papers[0].sections) == 1

    def test_europepmc_fallback(self, monkeypatch, mock_clients):
        """PMC 실패 → EuropePMC 성공 → fulltext_source='europepmc'."""
        def fake_cascading(**_):
            return CascadingFulltextResult(
                fulltext_source="europepmc",
                tried_sources=["pmc", "europepmc"],
                sections=[PaperSection(name="Intro", content="content")],
                had_transient_error=False,
            )
        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_cascading)

        papers = _attach_fulltext([_meta("10.1/b", pmcid="PMC2")])
        assert papers[0].meta.fulltext_source == "europepmc"

    def test_all_sources_fail(self, monkeypatch, mock_clients):
        """PMC + EuropePMC 모두 not_available → paper 폐기 (sections=[])."""
        def fake_cascading(**_):
            return CascadingFulltextResult(
                fulltext_source=None,
                tried_sources=["pmc", "europepmc"],
                sections=[],
                had_transient_error=False,
            )
        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_cascading)

        papers = _attach_fulltext([_meta("10.1/c", pmcid="PMC3")])
        assert papers[0].meta.fulltext_source is None
        assert papers[0].sections == []

    def test_all_transient_keeps_open(self, monkeypatch, mock_clients):
        """모든 소스 transient → fulltext_source=None, had_transient_error=True 시그널."""
        def fake_cascading(**_):
            return CascadingFulltextResult(
                fulltext_source=None,
                tried_sources=["pmc", "europepmc"],
                sections=[],
                had_transient_error=True,
            )
        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_cascading)

        papers = _attach_fulltext([_meta("10.1/d", pmcid="PMC4")])
        # _attach_fulltext 자체는 transient 신호를 propagate하지 않음 — manifest 호출 흐름에서 사용.
        # 본 테스트는 paper structure가 cascading 결과를 충실히 반영하는지만 검증.
        assert papers[0].meta.fulltext_source is None


class TestManifestIntegration:
    """manifest record_attempt이 success/fail 분리 정확히 처리하는지."""

    def test_success_paper_marked_indexed(self, tmp_path: Path):
        m = Manifest.load(tmp_path / "manifest.json")
        m.record_attempt(
            doi="10.1/x",
            pmid="1",
            pmcid="PMC1",
            openalex_id="W1",
            fulltext_source="pmc",
            tried_sources=["pmc"],
        )
        m.save(tmp_path / "manifest.json")

        m2 = Manifest.load(tmp_path / "manifest.json")
        assert m2.is_indexed("10.1/x")

    def test_failed_paper_retry_candidate_when_new_source(self, tmp_path: Path):
        """fulltext_source=None paper는 새 active source 추가 시 retry 후보."""
        m = Manifest.load(tmp_path / "manifest.json")
        m.record_attempt(
            doi="10.1/fail",
            pmid="2",
            pmcid=None,
            openalex_id=None,
            fulltext_source=None,
            tried_sources=["pmc", "europepmc"],
        )
        m.save(tmp_path / "manifest.json")

        m2 = Manifest.load(tmp_path / "manifest.json")
        # Phase 1 active sources만이면 skip
        assert "10.1/fail" not in m2.retry_candidates({"pmc", "europepmc"})
        # Phase 2 unpaywall 추가되면 retry 후보
        assert "10.1/fail" in m2.retry_candidates({"pmc", "europepmc", "unpaywall"})


class TestEndToEndPayload:
    """ingest payload 빌더가 cascading 후 paper meta를 올바르게 직렬화하는지."""

    def test_payload_propagates_fulltext_source(self):
        from mlops.pipeline.models import Chunk
        from mlops.scripts.initial_ingest import _build_payload

        chunk = Chunk(
            paper_pmid="123",
            paper_doi="10.1/ok",
            paper_title="T",
            section_name="Intro",
            chunk_index=0,
            content="body",
            token_count=10,
            publication_types=["Meta-Analysis"],
            evidence_weight=1.00,
            fulltext_source="europepmc",
            published_year=2021,
        )
        payload = _build_payload([(chunk, [0.1] * 1024)])
        c = payload["chunks"][0]
        assert c["fulltext_source"] == "europepmc"
        assert c["publication_types"] == ["Meta-Analysis"]
        assert c["evidence_weight"] == 1.00
        assert c["published_year"] == 2021
