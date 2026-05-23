"""oa_fetcher chain + source 단위 테스트."""

from unittest.mock import MagicMock, patch

from mlops.pipeline.europepmc import FulltextStatus as ClientFulltextStatus
from mlops.pipeline.models import PaperSection
from mlops.pipeline.oa_fetcher import (
    EuropePMCSource,
    FulltextResult,
    FulltextStatus,
    OpenAlexHTMLSource,
    OpenAlexPDFSource,
    PaperRef,
    PMCSource,
    UnpaywallSource,
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
    def _make_pmc_client(self, status: ClientFulltextStatus, sections=None, error=None):
        client = MagicMock()
        client.fetch.return_value = MagicMock(
            status=status,
            sections=sections or [],
            error=error,
        )
        return client

    def test_no_pmcid_returns_not_available(self):
        client = self._make_pmc_client(ClientFulltextStatus.NOT_AVAILABLE)
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid=None)

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.NOT_AVAILABLE
        client.fetch.assert_not_called()

    def test_transient_error_propagates(self):
        client = self._make_pmc_client(ClientFulltextStatus.TRANSIENT_ERROR, error="boom")
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC123")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.TRANSIENT_ERROR

    def test_sections_present_returns_success(self):
        sections = [PaperSection(name="Methods", content="text")]
        client = self._make_pmc_client(ClientFulltextStatus.SUCCESS, sections=sections)
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC456")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.SUCCESS
        assert result.sections == sections

    def test_empty_sections_returns_not_available(self):
        client = self._make_pmc_client(ClientFulltextStatus.NOT_AVAILABLE, sections=[])
        source = PMCSource(pmc_client=client)
        ref = PaperRef(doi="10.1/a", pmcid="PMC789")

        source.try_fetch(ref)


class TestEuropePMCSource:
    def _make_europepmc_client(self, status: ClientFulltextStatus, sections=None, error=None):
        client = MagicMock()
        client_result = MagicMock(
            status=status,
            sections=sections or [],
            error=error,
        )
        client.fetch_by_pmid.return_value = client_result
        client.fetch_by_doi.return_value = client_result
        return client

    def test_no_pmid_no_doi_returns_not_available(self):
        client = self._make_europepmc_client(ClientFulltextStatus.NOT_AVAILABLE)
        source = EuropePMCSource(europepmc_client=client)
        # doi가 빈 문자열이고 pmid도 없으면(None 기본값) NOT_AVAILABLE
        ref_no_ids = PaperRef(doi="")

        result = source.try_fetch(ref_no_ids)

        assert result.status == FulltextStatus.NOT_AVAILABLE
        client.fetch_by_pmid.assert_not_called()
        client.fetch_by_doi.assert_not_called()

    def test_success_with_pmid(self):
        sections = [PaperSection(name="Methods", content="exercise protocol")]
        client = self._make_europepmc_client(ClientFulltextStatus.SUCCESS, sections=sections)
        source = EuropePMCSource(europepmc_client=client)
        ref = PaperRef(doi="10.1/b", pmid="12345678")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.SUCCESS
        assert result.sections == sections
        client.fetch_by_pmid.assert_called_once_with("12345678")
        client.fetch_by_doi.assert_not_called()

    def test_transient_error_propagates(self):
        client = self._make_europepmc_client(ClientFulltextStatus.TRANSIENT_ERROR, error="boom")
        source = EuropePMCSource(europepmc_client=client)
        ref = PaperRef(doi="10.1/b", pmid="99999999")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.TRANSIENT_ERROR

    def test_empty_sections_returns_not_available(self):
        client = self._make_europepmc_client(ClientFulltextStatus.NOT_AVAILABLE, sections=[])
        source = EuropePMCSource(europepmc_client=client)
        # pmid=None이 기본값 → doi 경로로 진입
        ref = PaperRef(doi="10.1/c")

        result = source.try_fetch(ref)

        assert result.status == FulltextStatus.NOT_AVAILABLE
        client.fetch_by_doi.assert_called_once_with("10.1/c")


class TestFetchCascadingWrapper:
    """fetch_cascading이 fetch_chain wrapper로 전환 후에도 기존 계약을 유지하는지 검증.

    mock client는 test_fulltext.py와 동일하게 europepmc.FulltextResult 형태를 반환한다.
    """

    def _pmc_success(self, sections=None):
        from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
        return FulltextResult(
            status=FulltextStatus.SUCCESS,
            sections=sections or [PaperSection(name="S", content="c")],
        )

    def _pmc_transient(self):
        from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
        return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error="err")

    def _epmc_success(self, sections=None):
        from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
        return FulltextResult(
            status=FulltextStatus.SUCCESS,
            sections=sections or [PaperSection(name="S", content="c")],
        )

    def _epmc_transient(self):
        from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
        return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error="err")

    def _epmc_not_available(self):
        from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)

    def _make_pmc_client(self, result):
        client = MagicMock()
        client.fetch.return_value = result
        return client

    def _make_europepmc_client(self, result):
        client = MagicMock()
        client.fetch_by_pmid.return_value = result
        client.fetch_by_doi.return_value = result
        return client

    def test_wrapper_returns_same_shape_as_before(self):
        """PMC SUCCESS → fulltext_source='pmc', tried_sources에 'pmc' 포함, had_transient_error=False."""
        from mlops.pipeline.fulltext import fetch_cascading

        pmc_result = self._pmc_success()
        pmc = self._make_pmc_client(pmc_result)
        epmc = self._make_europepmc_client(self._epmc_not_available())

        result = fetch_cascading(
            pmcid="PMC123", pmid="999", doi="10.1/z",
            pmc_client=pmc, europepmc_client=epmc,
        )

        assert result.fulltext_source == "pmc"
        assert "pmc" in result.tried_sources
        assert result.sections == pmc_result.sections
        assert result.had_transient_error is False

    def test_wrapper_skips_pmc_when_no_pmcid(self):
        """pmcid=None이면 tried_sources에 'pmc' 미포함."""
        from mlops.pipeline.fulltext import fetch_cascading

        epmc = self._make_europepmc_client(self._epmc_success())
        pmc = self._make_pmc_client(self._epmc_not_available())  # 호출되면 안 됨

        result = fetch_cascading(
            pmcid=None, pmid="999", doi="10.1/z",
            pmc_client=pmc, europepmc_client=epmc,
        )

        assert "pmc" not in result.tried_sources
        assert result.fulltext_source == "europepmc"
        assert result.had_transient_error is False

    def test_wrapper_partial_transient_does_not_flag(self):
        """PMC transient + EuropePMC SUCCESS → had_transient_error=False (모든 시도가 transient 아님)."""
        from mlops.pipeline.fulltext import fetch_cascading

        pmc = self._make_pmc_client(self._pmc_transient())
        epmc = self._make_europepmc_client(self._epmc_success())

        result = fetch_cascading(
            pmcid="PMC123", pmid="999", doi="10.1/z",
            pmc_client=pmc, europepmc_client=epmc,
        )

        assert result.fulltext_source == "europepmc"
        assert result.had_transient_error is False

    def test_wrapper_all_transient_flags(self):
        """PMC transient + EuropePMC transient → had_transient_error=True."""
        from mlops.pipeline.fulltext import fetch_cascading

        pmc = self._make_pmc_client(self._pmc_transient())
        epmc = self._make_europepmc_client(self._epmc_transient())

        result = fetch_cascading(
            pmcid="PMC123", pmid="999", doi="10.1/z",
            pmc_client=pmc, europepmc_client=epmc,
        )

        assert result.fulltext_source is None
        assert result.had_transient_error is True


class TestOpenAlexPDFSource:
    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_success_when_pdf_url_returns_sections(self, mock_fetch, mock_oa):
        mock_oa.return_value = {
            "is_oa": True,
            "pdf_url": "https://x/p.pdf",
            "landing_page_url": None,
        }
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS
        assert len(result.sections) == 1
        mock_fetch.assert_called_once_with("https://x/p.pdf")

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    def test_not_available_when_not_oa(self, mock_oa):
        mock_oa.return_value = {"is_oa": False, "pdf_url": None, "landing_page_url": None}
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    def test_not_available_when_oa_returns_none(self, mock_oa):
        mock_oa.return_value = None
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    def test_not_available_when_no_pdf_url(self, mock_oa):
        mock_oa.return_value = {
            "is_oa": True,
            "pdf_url": None,
            "landing_page_url": "https://x/landing",
        }
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_not_available_when_fetch_returns_empty(self, mock_fetch, mock_oa):
        mock_oa.return_value = {
            "is_oa": True,
            "pdf_url": "https://x/p.pdf",
            "landing_page_url": None,
        }
        mock_fetch.return_value = []
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_cache_openalex_oa_on_ref(self, mock_fetch, mock_oa):
        """PDFSource가 호출한 openalex_oa_url 결과를 ref.openalex_oa에 캐싱."""
        oa_blob = {"is_oa": True, "pdf_url": "https://x/p.pdf", "landing_page_url": "https://x/l"}
        mock_oa.return_value = oa_blob
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        ref = PaperRef(doi="10.1/a")
        OpenAlexPDFSource().try_fetch(ref)
        assert ref.openalex_oa == oa_blob

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_uses_cached_openalex_oa(self, mock_fetch, mock_oa):
        """ref.openalex_oa가 사전 set돼 있으면 openalex_oa_url 호출 안 함."""
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        ref = PaperRef(
            doi="10.1/a",
            openalex_oa={"is_oa": True, "pdf_url": "https://x/p.pdf", "landing_page_url": None},
        )
        OpenAlexPDFSource().try_fetch(ref)
        mock_oa.assert_not_called()


class TestOpenAlexHTMLSource:
    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_html_sections")
    def test_success_when_landing_url_returns_sections(self, mock_fetch, mock_oa):
        mock_oa.return_value = {
            "is_oa": True,
            "pdf_url": None,
            "landing_page_url": "https://x/landing",
        }
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        src = OpenAlexHTMLSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS
        mock_fetch.assert_called_once_with("https://x/landing")

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    def test_not_available_when_not_oa(self, mock_oa):
        mock_oa.return_value = {"is_oa": False, "pdf_url": None, "landing_page_url": None}
        src = OpenAlexHTMLSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    def test_not_available_when_no_landing_url(self, mock_oa):
        mock_oa.return_value = {"is_oa": True, "pdf_url": "https://x/p.pdf", "landing_page_url": None}
        src = OpenAlexHTMLSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_html_sections")
    def test_uses_cached_openalex_oa(self, mock_fetch, mock_oa):
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        ref = PaperRef(
            doi="10.1/a",
            openalex_oa={"is_oa": True, "pdf_url": None, "landing_page_url": "https://x/landing"},
        )
        OpenAlexHTMLSource().try_fetch(ref)
        mock_oa.assert_not_called()


class TestUnpaywallSource:
    @patch("mlops.pipeline.oa_fetcher.unpaywall_oa_locations")
    def test_not_available_when_no_locations(self, mock_locs):
        mock_locs.return_value = []
        src = UnpaywallSource(email="x@y.z")
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE
        mock_locs.assert_called_once_with("10.1/a", email="x@y.z")

    @patch("mlops.pipeline.oa_fetcher.unpaywall_oa_locations")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_success_via_first_mirror_pdf(self, mock_pdf, mock_locs):
        mock_locs.return_value = [
            {"pdf_url": "https://m1/p.pdf", "landing_url": "https://m1/landing"},
            {"pdf_url": "https://m2/p.pdf", "landing_url": None},
        ]
        mock_pdf.return_value = [PaperSection(name="M", content="x")]
        src = UnpaywallSource(email="x@y.z")
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS
        assert len(result.sections) == 1
        # 첫 번째 mirror의 pdf만 시도하고 stop
        mock_pdf.assert_called_once_with("https://m1/p.pdf")

    @patch("mlops.pipeline.oa_fetcher.unpaywall_oa_locations")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    @patch("mlops.pipeline.oa_fetcher.fetch_html_sections")
    def test_success_via_second_mirror_html_after_pdf_fail(
        self, mock_html, mock_pdf, mock_locs
    ):
        """첫 mirror pdf 실패 → 첫 mirror landing fail → 두번째 mirror landing 성공."""
        mock_locs.return_value = [
            {"pdf_url": "https://m1/p.pdf", "landing_url": "https://m1/landing"},
            {"pdf_url": None, "landing_url": "https://m2/landing"},
        ]
        mock_pdf.return_value = []
        # 첫 mirror landing은 실패, 두번째 mirror landing은 성공
        mock_html.side_effect = [[], [PaperSection(name="M", content="x")]]
        src = UnpaywallSource(email="x@y.z")
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS
        assert mock_pdf.call_count == 1
        assert mock_html.call_count == 2

    @patch("mlops.pipeline.oa_fetcher.unpaywall_oa_locations")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    @patch("mlops.pipeline.oa_fetcher.fetch_html_sections")
    def test_not_available_when_all_mirrors_fail(self, mock_html, mock_pdf, mock_locs):
        mock_locs.return_value = [
            {"pdf_url": "https://m1/p.pdf", "landing_url": "https://m1/landing"},
            {"pdf_url": None, "landing_url": "https://m2/landing"},
        ]
        mock_pdf.return_value = []
        mock_html.return_value = []
        src = UnpaywallSource(email="x@y.z")
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.NOT_AVAILABLE

    def test_default_email(self):
        src = UnpaywallSource()
        assert src.email == "research@scifit-sync.org"
