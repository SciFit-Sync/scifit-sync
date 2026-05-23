"""oa_fetcher chain + source 단위 테스트."""

from unittest.mock import MagicMock

from mlops.pipeline.models import PaperSection
from mlops.pipeline.oa_fetcher import (
    FulltextResult,
    FulltextStatus,
    PaperRef,
    PMCSource,
    fetch_chain,
)


def _make_source(name: str, status: FulltextStatus, sections=None):
    src = MagicMock()
    src.name = name
    result = FulltextResult(status=status, sections=sections or [])
    src.try_fetch.return_value = result
    return src


class TestFetchChain:
    def test_returns_first_success(self):
        s1 = _make_source("s1", FulltextStatus.NOT_AVAILABLE)
        s2 = _make_source("s2", FulltextStatus.SUCCESS, sections=[PaperSection(name="M", content="x")])
        s3 = _make_source("s3", FulltextStatus.SUCCESS, sections=[PaperSection(name="X", content="never")])

        ref = PaperRef(doi="10.1/a")
        result = fetch_chain(ref, [s1, s2, s3])

        assert result.fulltext_source == "s2"
        assert len(result.sections) == 1
        # s3는 호출 안 됨 (stop on first success)
        s3.try_fetch.assert_not_called()
        # tried log: s1 NOT_AVAILABLE, s2 SUCCESS
        assert result.tried == [("s1", FulltextStatus.NOT_AVAILABLE), ("s2", FulltextStatus.SUCCESS)]
        assert result.had_transient_error is False

    def test_all_not_available_returns_no_source(self):
        s1 = _make_source("s1", FulltextStatus.NOT_AVAILABLE)
        s2 = _make_source("s2", FulltextStatus.NOT_AVAILABLE)
        result = fetch_chain(PaperRef(doi="10.1/a"), [s1, s2])

        assert result.fulltext_source is None
        assert result.sections == []
        assert result.had_transient_error is False

    def test_transient_falls_through_and_flags(self):
        s1 = _make_source("s1", FulltextStatus.TRANSIENT_ERROR)
        s2 = _make_source("s2", FulltextStatus.SUCCESS, sections=[PaperSection(name="M", content="x")])
        result = fetch_chain(PaperRef(doi="10.1/a"), [s1, s2])

        assert result.fulltext_source == "s2"
        assert result.had_transient_error is True

    def test_empty_chain_returns_no_source(self):
        result = fetch_chain(PaperRef(doi="10.1/a"), [])
        assert result.fulltext_source is None
        assert result.sections == []
        assert result.tried == []


class TestPMCSource:
    def _make_pmc_client(self, sections=None, had_transient_error=False):
        client = MagicMock()
        client_result = MagicMock()
        client_result.sections = sections or []
        client_result.had_transient_error = had_transient_error
        client.fetch.return_value = client_result
        return client

    def test_no_pmcid_returns_not_available(self):
        client = self._make_pmc_client()
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid=None)

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.NOT_AVAILABLE
        client.fetch.assert_not_called()

    def test_transient_error_propagates(self):
        client = self._make_pmc_client(had_transient_error=True)
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC123")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.TRANSIENT_ERROR

    def test_sections_present_returns_success(self):
        sections = [PaperSection(name="Methods", content="text")]
        client = self._make_pmc_client(sections=sections)
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC456")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.SUCCESS
        assert result.sections == sections

    def test_empty_sections_returns_not_available(self):
        client = self._make_pmc_client(sections=[])
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC789")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.NOT_AVAILABLE
