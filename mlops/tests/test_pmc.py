"""PMC fulltext 어댑터 단위 테스트."""
from unittest.mock import MagicMock, patch

from mlops.pipeline.europepmc import FulltextStatus
from mlops.pipeline.pmc import PMCClient
from requests.exceptions import HTTPError


def test_fetch_success():
    xml = b'<article><body><sec><title>Intro</title><p>Content here for the test.</p></sec></body></article>'

    client = PMCClient(base_url="https://example.com", rate_limit=0)
    with patch("mlops.pipeline.pmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = xml
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.fetch("PMC123")

    assert result.status == FulltextStatus.SUCCESS
    assert len(result.sections) == 1
    assert result.sections[0].name == "Intro"


def test_fetch_no_body_returns_not_available():
    xml = b'<article><front/></article>'
    client = PMCClient(base_url="https://example.com", rate_limit=0)
    with patch("mlops.pipeline.pmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = xml
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = client.fetch("PMC123")

    assert result.status == FulltextStatus.NOT_AVAILABLE


def test_fetch_pmcid_with_prefix_strips_PMC():
    """PMCID 'PMC123' 또는 '123' 둘 다 처리."""
    xml = b'<article><body><sec><title>Intro</title><p>Body content text here.</p></sec></body></article>'
    client = PMCClient(base_url="https://example.com", rate_limit=0)
    captured_params = {}

    def capture(*args, **kwargs):
        captured_params.update(kwargs.get("params", {}))
        mock_resp = MagicMock()
        mock_resp.content = xml
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("mlops.pipeline.pmc.requests.get", side_effect=capture):
        client.fetch("PMC6520849")

    assert captured_params["id"] == "6520849"


def test_fetch_404_returns_not_available():
    client = PMCClient(base_url="https://example.com", rate_limit=0)

    with patch("mlops.pipeline.pmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        err = HTTPError("404")
        err.response = mock_resp
        mock_resp.raise_for_status.side_effect = err
        mock_get.return_value = mock_resp

        result = client.fetch("PMC999")

    assert result.status == FulltextStatus.NOT_AVAILABLE


def test_fetch_5xx_transient_error_after_retries():
    client = PMCClient(base_url="https://example.com", rate_limit=0, max_retries=1)

    with patch("mlops.pipeline.pmc.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        err = HTTPError("503")
        err.response = mock_resp
        mock_resp.raise_for_status.side_effect = err
        mock_get.return_value = mock_resp

        result = client.fetch("PMC123")

    assert result.status == FulltextStatus.TRANSIENT_ERROR
