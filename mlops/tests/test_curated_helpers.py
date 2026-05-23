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
