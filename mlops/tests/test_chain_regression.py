"""Phase 1 회수율 회귀 가드.

known-OA paper fixture에 대해 chain이 SUCCESS 반환하는지 검증.
chain 변경 후 이 테스트가 깨지면 회수율 회귀 시그널.

Phase 2 (OpenAlex/Unpaywall)에서 fixture 추가 예정.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mlops.pipeline.europepmc import FulltextStatus as ClientFulltextStatus
from mlops.pipeline.models import PaperSection
from mlops.pipeline.oa_fetcher import (
    EuropePMCSource,
    FulltextStatus,
    PaperRef,
    PMCSource,
    fetch_chain,
)

# Phase 1 fixture: known-OA paper, expected_source.
# (doi, pmid, pmcid, expected_source)
PHASE1_KNOWN_OA = [
    ("10.2478/hukin-2022-0017", "35291645", "PMC8884877", "pmc"),
    ("10.1519/JSC.0000000000003566", "32004204", None, "europepmc"),
]


class TestChainPhase1Regression:
    """Phase 1 chain (PMC + EuropePMC)의 known-OA paper 회수 검증."""

    @pytest.mark.parametrize("doi,pmid,pmcid,expected_source", PHASE1_KNOWN_OA)
    def test_known_oa_paper_resolves(self, doi, pmid, pmcid, expected_source):
        pmc_client = MagicMock()
        epmc_client = MagicMock()

        success = MagicMock(
            status=ClientFulltextStatus.SUCCESS,
            sections=[PaperSection(name="Methods", content="...")],
            error=None,
        )
        not_available = MagicMock(
            status=ClientFulltextStatus.NOT_AVAILABLE,
            sections=[],
            error=None,
        )

        if expected_source == "pmc":
            pmc_client.fetch.return_value = success
            epmc_client.fetch_by_pmid.return_value = not_available
            epmc_client.fetch_by_doi.return_value = not_available
        elif expected_source == "europepmc":
            pmc_client.fetch.return_value = not_available
            epmc_client.fetch_by_pmid.return_value = success
            epmc_client.fetch_by_doi.return_value = success

        chain = [PMCSource(pmc_client), EuropePMCSource(epmc_client)]
        result = fetch_chain(PaperRef(doi=doi, pmid=pmid, pmcid=pmcid), chain)

        assert result.fulltext_source == expected_source, (
            f"Regression: {doi} (expected {expected_source}, "
            f"got {result.fulltext_source})"
        )
        assert len(result.sections) > 0
        assert result.had_transient_error is False

    def test_all_sources_unavailable_returns_none(self):
        """모든 source가 NOT_AVAILABLE이면 chain은 fulltext_source=None."""
        pmc_client = MagicMock()
        pmc_client.fetch.return_value = MagicMock(
            status=ClientFulltextStatus.NOT_AVAILABLE,
            sections=[],
            error=None,
        )
        epmc_client = MagicMock()
        epmc_client.fetch_by_pmid.return_value = MagicMock(
            status=ClientFulltextStatus.NOT_AVAILABLE,
            sections=[],
            error=None,
        )

        chain = [PMCSource(pmc_client), EuropePMCSource(epmc_client)]
        result = fetch_chain(
            PaperRef(doi="10.0/missing", pmid="000", pmcid="PMC0"), chain
        )

        assert result.fulltext_source is None
        assert result.sections == []
        assert result.had_transient_error is False

    def test_pmc_transient_then_europepmc_success(self):
        """PMC transient → EuropePMC success → chain은 SUCCESS 반환 + transient flag."""
        pmc_client = MagicMock()
        pmc_client.fetch.return_value = MagicMock(
            status=ClientFulltextStatus.TRANSIENT_ERROR,
            sections=[],
            error="timeout",
        )
        epmc_client = MagicMock()
        epmc_client.fetch_by_pmid.return_value = MagicMock(
            status=ClientFulltextStatus.SUCCESS,
            sections=[PaperSection(name="M", content="x")],
            error=None,
        )

        chain = [PMCSource(pmc_client), EuropePMCSource(epmc_client)]
        result = fetch_chain(
            PaperRef(doi="10.1/x", pmid="123", pmcid="PMC1"), chain
        )

        assert result.fulltext_source == "europepmc"
        assert result.had_transient_error is True
        # tried: [(pmc, TRANSIENT), (europepmc, SUCCESS)]
        statuses = [s for _, s in result.tried]
        assert FulltextStatus.TRANSIENT_ERROR in statuses
        assert FulltextStatus.SUCCESS in statuses
