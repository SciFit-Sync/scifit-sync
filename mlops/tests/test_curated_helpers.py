"""curated helper 단위 테스트."""

from unittest.mock import MagicMock, patch

import requests
from mlops.pipeline.curated import (
    fetch_html_sections,
    fetch_pdf_sections,
    ncbi_pmid_to_doi,
    normalize_doi,
    openalex_doi_lookup,
    openalex_oa_url,
    title_keyword_overlap,
    unpaywall_oa_locations,
)


class TestNormalizeDoi:
    def test_lowercases_doi(self):
        assert normalize_doi("10.1080/02640414.2016.1210197") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("10.1519/JSC.0000000000002776") == "10.1519/jsc.0000000000002776"

    def test_strips_url_prefix(self):
        assert normalize_doi("https://doi.org/10.1080/02640414.2016.1210197") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("http://dx.doi.org/10.1080/02640414") == "10.1080/02640414"

    def test_strips_whitespace_and_punctuation(self):
        assert normalize_doi("  10.1080/02640414.2016.1210197.  ") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("10.1080/02640414;") == "10.1080/02640414"

    def test_returns_empty_for_invalid(self):
        assert normalize_doi("") == ""
        assert normalize_doi("not-a-doi") == ""
        assert normalize_doi(None) == ""

    def test_rejects_doi_with_url_metacharacters(self):
        assert normalize_doi("10.1080/test?injection=1") == ""
        assert normalize_doi("10.1080/test#fragment") == ""
        assert normalize_doi("10.1080/test space") == ""

    def test_idempotent(self):
        first = normalize_doi("HTTPS://DOI.ORG/10.1080/JSC.001;")
        second = normalize_doi(first)
        assert first == second


class TestNcbiPmidToDoi:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_doi_when_present(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345", "doi": "10.1080/test"}]}
        mock_get.return_value = mock_resp

        result = ncbi_pmid_to_doi("12345")
        assert result == "10.1080/test"

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_when_doi_missing(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345"}]}
        mock_get.return_value = mock_resp

        assert ncbi_pmid_to_doi("12345") == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_http_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("503")
        assert ncbi_pmid_to_doi("12345") == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_normalizes_returned_doi(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345", "doi": "10.1080/TEST.001;"}]}
        mock_get.return_value = mock_resp

        assert ncbi_pmid_to_doi("12345") == "10.1080/test.001"


class TestOpenalexDoiLookup:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_metadata_with_pmid(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1080/test",
            "title": "Sample Paper",
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345"},
            "publication_year": 2023,
            "type": "journal-article",
        }
        mock_get.return_value = mock_resp

        result = openalex_doi_lookup("10.1080/test")
        assert result is not None
        assert result["pmid"] == "12345"
        assert result["title"] == "Sample Paper"
        assert result["doi"] == "10.1080/test"
        assert result["publication_year"] == 2023

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_metadata_without_pmid(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"doi": "https://doi.org/10.1080/x", "title": "X", "ids": {}}
        mock_get.return_value = mock_resp

        result = openalex_doi_lookup("10.1080/x")
        assert result is not None
        assert result["pmid"] == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_404_status_code(self, mock_get):
        mock_resp = MagicMock(status_code=404)
        # note: no side_effect needed - production code returns before raise_for_status
        mock_get.return_value = mock_resp
        assert openalex_doi_lookup("10.1080/notfound") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_non_404_http_error(self, mock_get):
        mock_resp = MagicMock(status_code=429)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("429")
        mock_get.return_value = mock_resp
        assert openalex_doi_lookup("10.1080/x") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        assert openalex_doi_lookup("10.1080/x") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_handles_null_ids_field(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"doi": "https://doi.org/10.1080/x", "title": "X", "ids": None}
        mock_get.return_value = mock_resp
        result = openalex_doi_lookup("10.1080/x")
        assert result is not None
        assert result["pmid"] == ""


class TestTitleKeywordOverlap:
    def test_high_overlap(self):
        title = "Effects of weekly training volume on muscle hypertrophy"
        context = "weekly set volume per muscle group hypertrophy"
        ratio = title_keyword_overlap(title, context)
        assert ratio >= 0.5  # significant overlap

    def test_low_overlap(self):
        title = "Hammer Strength Cybernetics for Robotic Cardiology"
        context = "weekly set volume per muscle group hypertrophy"
        ratio = title_keyword_overlap(title, context)
        assert ratio < 0.2

    def test_empty_inputs(self):
        assert title_keyword_overlap("", "anything") == 0.0
        assert title_keyword_overlap("anything", "") == 0.0

    def test_stopwords_ignored(self):
        title = "The Effect of A Variable on The Outcome"
        context = "Outcome"
        ratio = title_keyword_overlap(title, context)
        assert ratio > 0.0  # "outcome" matches, stopwords excluded


class TestOpenalexOaUrl:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_oa_info_with_pdf_url(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "open_access": {"is_oa": True},
            "best_oa_location": {
                "pdf_url": "https://example.com/paper.pdf",
                "landing_page_url": "https://example.com/paper",
            },
        }
        mock_get.return_value = mock_resp

        result = openalex_oa_url("10.1080/test")
        assert result is not None
        assert result["is_oa"] is True
        assert result["pdf_url"] == "https://example.com/paper.pdf"
        assert result["landing_page_url"] == "https://example.com/paper"

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_not_oa_when_is_oa_false(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "open_access": {"is_oa": False},
            "best_oa_location": None,
        }
        mock_get.return_value = mock_resp

        result = openalex_oa_url("10.1080/test")
        assert result is not None
        assert result["is_oa"] is False
        assert result["pdf_url"] is None
        assert result["landing_page_url"] is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_404(self, mock_get):
        mock_resp = MagicMock(status_code=404)
        mock_get.return_value = mock_resp

        result = openalex_oa_url("10.1080/notfound")
        assert result is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        assert openalex_oa_url("10.1080/test") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_handles_null_best_oa_location(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "open_access": {"is_oa": True},
            "best_oa_location": None,
        }
        mock_get.return_value = mock_resp

        result = openalex_oa_url("10.1080/test")
        assert result is not None
        assert result["is_oa"] is True
        assert result["pdf_url"] is None
        assert result["landing_page_url"] is None

    def test_returns_none_for_invalid_doi(self):
        result = openalex_oa_url("not-a-doi")
        assert result is None


class TestFetchPdfSections:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_when_pypdf_not_installed(self, mock_get):
        with patch.dict("sys.modules", {"pypdf": None}):
            result = fetch_pdf_sections("https://example.com/paper.pdf")
        assert result == []
        mock_get.assert_not_called()

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_http_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("connection error")
        result = fetch_pdf_sections("https://example.com/paper.pdf")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_for_non_pdf_content_type(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.raise_for_status.return_value = None
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        result = fetch_pdf_sections("https://example.com/page")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_for_large_pdf_via_content_length(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {
            "Content-Type": "application/pdf",
            "Content-Length": str(60 * 1024 * 1024),  # 60 MB > 50 MB limit
        }
        mock_resp.raise_for_status.return_value = None
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        result = fetch_pdf_sections("https://example.com/big.pdf")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_extracts_text_from_pdf(self, mock_get):
        import sys  # noqa: PLC0415

        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"fake pdf bytes"]
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is the paper full text content."
        mock_reader_instance = MagicMock()
        mock_reader_instance.pages = [mock_page]

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader_instance

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            result = fetch_pdf_sections("https://example.com/paper.pdf")

        assert len(result) == 1
        assert result[0].name == "Full Text"
        assert "paper full text" in result[0].content

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_pypdf_parse_error(self, mock_get):
        import sys  # noqa: PLC0415

        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "application/pdf"}
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content.return_value = [b"corrupted"]
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        mock_pypdf = MagicMock()
        mock_pypdf.PdfReader.side_effect = Exception("parse error")

        with patch.dict(sys.modules, {"pypdf": mock_pypdf}):
            result = fetch_pdf_sections("https://example.com/paper.pdf")

        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_streaming_oversized_pdf_no_content_length(self, mock_get):
        """Content-Length 없이 streaming으로 50MB 초과 시 빈 list."""
        from mlops.pipeline.curated import _PDF_MAX_BYTES  # noqa: PLC0415

        big_chunk = b"x" * (1024 * 1024)  # 1MB per chunk
        n_chunks = (_PDF_MAX_BYTES // (1024 * 1024)) + 2  # over the limit

        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "application/pdf"}  # no Content-Length
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_content = lambda chunk_size: (big_chunk for _ in range(n_chunks))
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_resp

        result = fetch_pdf_sections("https://example.com/big.pdf")

        assert result == []


class TestFetchHtmlSections:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_http_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        result = fetch_html_sections("https://example.com/paper")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_when_body_too_short(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = "<html><body><article>Short</article></body></html>"
        mock_get.return_value = mock_resp

        result = fetch_html_sections("https://example.com/paper")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_extracts_text_from_article_tag(self, mock_get):
        long_text = "This is a detailed paper about muscle hypertrophy. " * 20  # > 500 chars
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = f"<html><body><article>{long_text}</article></body></html>"
        mock_get.return_value = mock_resp

        result = fetch_html_sections("https://example.com/paper")
        assert len(result) == 1
        assert result[0].name == "Full Text"
        assert len(result[0].content) >= 500

    @patch("mlops.pipeline.curated.requests.get")
    def test_fallback_regex_when_bs4_unavailable(self, mock_get):
        long_text = "Detailed research paper about progressive overload training. " * 15
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = f"<html><body><p>{long_text}</p></body></html>"
        mock_get.return_value = mock_resp

        with patch.dict("sys.modules", {"bs4": None}):
            result = fetch_html_sections("https://example.com/paper")

        assert len(result) == 1
        assert result[0].name == "Full Text"
        assert len(result[0].content) >= 500


class TestUnpaywallOaLocations:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_best_and_extra_locations(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "is_oa": True,
            "best_oa_location": {
                "url_for_pdf": "https://best.example.com/paper.pdf",
                "url_for_landing_page": "https://best.example.com/paper",
                "url": None,
            },
            "oa_locations": [
                {
                    "url_for_pdf": "https://repo.example.edu/paper.pdf",
                    "url_for_landing_page": "https://repo.example.edu/paper",
                    "url": None,
                },
            ],
        }
        mock_get.return_value = mock_resp

        result = unpaywall_oa_locations("10.1080/test")

        assert len(result) == 2
        assert result[0]["pdf_url"] == "https://best.example.com/paper.pdf"
        assert result[0]["landing_url"] == "https://best.example.com/paper"
        assert result[1]["pdf_url"] == "https://repo.example.edu/paper.pdf"

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_404(self, mock_get):
        mock_resp = MagicMock(status_code=404)
        mock_get.return_value = mock_resp

        result = unpaywall_oa_locations("10.1080/notfound")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_when_not_oa(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "is_oa": False,
            "best_oa_location": None,
            "oa_locations": [],
        }
        mock_get.return_value = mock_resp

        result = unpaywall_oa_locations("10.1080/closed")
        assert result == []

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("connection error")

        result = unpaywall_oa_locations("10.1080/test")
        assert result == []

    def test_returns_empty_for_invalid_doi(self):
        result = unpaywall_oa_locations("not-a-doi")
        assert result == []
