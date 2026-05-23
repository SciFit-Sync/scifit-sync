"""curated helper 단위 테스트."""
import pytest
from mlops.pipeline.curated import normalize_doi


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

    def test_idempotent(self):
        first = normalize_doi("HTTPS://DOI.ORG/10.1080/JSC.001;")
        second = normalize_doi(first)
        assert first == second


import requests
from unittest.mock import MagicMock, patch
from mlops.pipeline.curated import ncbi_pmid_to_doi


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


from mlops.pipeline.curated import openalex_doi_lookup


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
    def test_returns_none_on_404(self, mock_get):
        mock_resp = MagicMock(status_code=404)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = mock_resp

        assert openalex_doi_lookup("10.1080/notfound") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        assert openalex_doi_lookup("10.1080/x") is None


from mlops.pipeline.curated import title_keyword_overlap


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
