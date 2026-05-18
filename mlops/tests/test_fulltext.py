"""Cascading fulltext orchestrator 단위 테스트."""
from unittest.mock import MagicMock

from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
from mlops.pipeline.fulltext import fetch_cascading
from mlops.pipeline.models import PaperSection


def _success(name: str = "Intro") -> FulltextResult:
    return FulltextResult(
        status=FulltextStatus.SUCCESS,
        sections=[PaperSection(name=name, content="content")],
    )


def _not_available() -> FulltextResult:
    return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


def _transient() -> FulltextResult:
    return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error="oops")


def test_pmc_success_stops_cascade():
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_success("PMC-Intro"))
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_success("EPMC-Intro"))

    result = fetch_cascading(pmcid="PMC1", pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    assert result.fulltext_source == "pmc"
    assert result.tried_sources == ["pmc"]
    assert result.sections[0].name == "PMC-Intro"
    europepmc.fetch_by_pmid.assert_not_called()


def test_pmc_not_available_falls_through_to_europepmc():
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_not_available())
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_success("EPMC-Intro"))

    result = fetch_cascading(pmcid="PMC1", pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    assert result.fulltext_source == "europepmc"
    assert result.tried_sources == ["pmc", "europepmc"]


def test_all_not_available_returns_null_source():
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_not_available())
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_not_available())

    result = fetch_cascading(pmcid="PMC1", pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    assert result.fulltext_source is None
    assert result.tried_sources == ["pmc", "europepmc"]
    assert result.sections == []
    assert result.had_transient_error is False


def test_pmc_transient_then_europepmc_success_resets_flag():
    """PMC transient여도 후속 success면 had_transient_error=False."""
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_transient())
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_success("EPMC-Intro"))

    result = fetch_cascading(pmcid="PMC1", pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    assert result.fulltext_source == "europepmc"
    assert result.had_transient_error is False


def test_all_transient_marks_had_transient_error():
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_transient())
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_transient())

    result = fetch_cascading(pmcid="PMC1", pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    assert result.fulltext_source is None
    assert result.had_transient_error is True


def test_no_pmcid_skips_pmc_step():
    pmc = MagicMock()
    pmc.fetch = MagicMock()
    europepmc = MagicMock()
    europepmc.fetch_by_pmid = MagicMock(return_value=_success())

    result = fetch_cascading(pmcid=None, pmid="12", doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    pmc.fetch.assert_not_called()
    assert "pmc" not in result.tried_sources
    assert result.fulltext_source == "europepmc"


def test_europepmc_pmid_fallback_to_doi_lookup():
    """PMID 없으면 EuropePMC도 fetch_by_doi 경로 사용."""
    pmc = MagicMock()
    pmc.fetch = MagicMock(return_value=_not_available())
    europepmc = MagicMock()
    europepmc.fetch_by_doi = MagicMock(return_value=_success("EPMC-Intro"))
    europepmc.fetch_by_pmid = MagicMock()

    result = fetch_cascading(pmcid="PMC1", pmid=None, doi="10.1/x",
                             pmc_client=pmc, europepmc_client=europepmc)

    europepmc.fetch_by_pmid.assert_not_called()
    europepmc.fetch_by_doi.assert_called_once_with("10.1/x")
    assert result.fulltext_source == "europepmc"
