"""Europe PMC fulltext 어댑터 단위 테스트."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mlops.pipeline.europepmc import (
    EuropePMCClient,
    FulltextStatus,
    parse_sections,
)
from requests.exceptions import HTTPError

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fulltext_xml() -> bytes:
    return (FIXTURE_DIR / "europepmc_fulltext.xml").read_bytes()


def test_parse_sections_extracts_named_sections(fulltext_xml):
    sections = parse_sections(fulltext_xml)
    names = [s.name for s in sections]
    assert "Introduction" in names
    assert "Methods" in names
    assert "Results" in names


def test_parse_sections_concatenates_paragraphs(fulltext_xml):
    sections = parse_sections(fulltext_xml)
    intro = next(s for s in sections if s.name == "Introduction")
    assert "Resistance training" in intro.content
    assert "volume protocols" in intro.content


def test_parse_empty_body_returns_empty():
    xml = b'<?xml version="1.0"?><article><front/><body/></article>'
    assert parse_sections(xml) == []


def test_client_fetch_by_pmid_success(fulltext_xml):
    client = EuropePMCClient(base_url="https://example.com", rate_limit=0)

    with patch("mlops.pipeline.europepmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = fulltext_xml
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        result = client.fetch_by_pmid("12345678")

    assert result.status == FulltextStatus.SUCCESS
    assert len(result.sections) > 0


def test_client_fetch_by_pmid_404_returns_not_available():
    client = EuropePMCClient(base_url="https://example.com", rate_limit=0)

    with patch("mlops.pipeline.europepmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        err = HTTPError("404")
        err.response = mock_resp
        mock_resp.raise_for_status.side_effect = err
        mock_get.return_value = mock_resp

        result = client.fetch_by_pmid("99999999")

    assert result.status == FulltextStatus.NOT_AVAILABLE
    assert result.sections == []


def test_client_fetch_5xx_returns_transient_error_after_retries():
    """5xx에서 max_retries 소진 후 transient_error 반환."""
    client = EuropePMCClient(base_url="https://example.com", rate_limit=0, max_retries=1)

    with patch("mlops.pipeline.europepmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        err = HTTPError("503")
        err.response = mock_resp
        mock_resp.raise_for_status.side_effect = err
        mock_get.return_value = mock_resp

        result = client.fetch_by_pmid("11111111")

    assert result.status == FulltextStatus.TRANSIENT_ERROR
    assert result.error is not None


def test_5xx_then_success_succeeds(fulltext_xml):
    """5xx → 200 retry로 성공."""
    client = EuropePMCClient(base_url="https://example.com", rate_limit=0, max_retries=3)

    fail = MagicMock()
    fail.status_code = 503
    err = HTTPError("503")
    err.response = fail
    fail.raise_for_status.side_effect = err

    ok = MagicMock()
    ok.content = fulltext_xml
    ok.raise_for_status = MagicMock()
    ok.status_code = 200

    with patch("mlops.pipeline.europepmc.requests.get", side_effect=[fail, ok]):
        result = client.fetch_by_pmid("12345678")

    assert result.status == FulltextStatus.SUCCESS
