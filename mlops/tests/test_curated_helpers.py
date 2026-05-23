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
