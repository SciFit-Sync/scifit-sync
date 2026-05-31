"""PMC fulltext 어댑터 및 PMID→PMCID 변환 단위 테스트."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from mlops.pipeline.crawler import (
    _resolve_pmc_id,
    _resolve_pmc_id_via_idconv,
)
from mlops.pipeline.europepmc import FulltextStatus
from mlops.pipeline.pmc import PMCClient
from requests.exceptions import HTTPError


def test_fetch_success():
    xml = b"<article><body><sec><title>Intro</title><p>Content here for the test.</p></sec></body></article>"

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
    xml = b"<article><front/></article>"
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
    xml = b"<article><body><sec><title>Intro</title><p>Body content text here.</p></sec></body></article>"
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


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_pmc_id_via_idconv 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────


class TestResolvePmcIdViaIdconv:
    """`_resolve_pmc_id_via_idconv` 동작 검증 (전부 mock, 네트워크 불요)."""

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_success_strips_pmc_prefix(self, mock_request):
        """idconv 성공 → pmcid "PMC5447067" 응답 → "5447067" 반환 (접두 제거)."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps(
            {
                "status": "ok",
                "records": [
                    {
                        "pmid": 28611677,
                        "pmcid": "PMC5447067",
                        "doi": "10.1038/s41598-017-02498-6",
                        "requested-id": "28611677",
                    }
                ],
            }
        )
        mock_request.return_value = mock_resp

        result = _resolve_pmc_id_via_idconv("28611677")
        assert result == "5447067"

    @patch("mlops.pipeline.crawler._resolve_pmc_id_via_elink")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_no_pmc_returns_none_without_elink_fallback(self, mock_request, mock_elink):
        """idconv 권위적 no-PMC (errmsg만 있음) → None 반환 + elink fallback 호출 안 됨."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps(
            {
                "status": "ok",
                "records": [
                    {
                        "pmid": 12345,
                        "errmsg": "Record not found",
                        "requested-id": "12345",
                    }
                ],
            }
        )
        mock_request.return_value = mock_resp

        result = _resolve_pmc_id("12345")
        assert result is None
        mock_elink.assert_not_called()

    @patch("mlops.pipeline.crawler._resolve_pmc_id_via_elink")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_transport_failure_falls_back_to_elink(self, mock_request, mock_elink):
        """idconv 전송 실패 (RequestException) → _resolve_pmc_id_via_elink 호출됨."""
        mock_request.side_effect = requests.exceptions.ConnectionError("refused")
        mock_elink.return_value = "9999999"

        result = _resolve_pmc_id("12345")
        assert result == "9999999"
        mock_elink.assert_called_once_with("12345", 5)

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_malformed_json_raises_runtimeerror(self, mock_request):
        """파싱 불가 JSON은 PMC 부재 증명이 아님 → RuntimeError (transient, fallback 유도)."""
        mock_resp = MagicMock()
        mock_resp.text = "not-json{{"
        mock_request.return_value = mock_resp

        with pytest.raises(RuntimeError):
            _resolve_pmc_id_via_idconv("12345")

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_non_ok_status_raises_runtimeerror(self, mock_request):
        """status != 'ok' 는 서버 이상 → RuntimeError (fallback 유도)."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"status": "error", "message": "bad request"})
        mock_request.return_value = mock_resp

        with pytest.raises(RuntimeError):
            _resolve_pmc_id_via_idconv("12345")

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_empty_records_raises_runtimeerror(self, mock_request):
        """records 비어있음 = 변환 미확정 → RuntimeError (fallback 유도)."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"status": "ok", "records": []})
        mock_request.return_value = mock_resp

        with pytest.raises(RuntimeError):
            _resolve_pmc_id_via_idconv("12345")

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_non_digit_pmcid_raises_runtimeerror(self, mock_request):
        """비정상 PMCID 포맷은 efetch에 넘기기 전 차단 → RuntimeError."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"status": "ok", "records": [{"pmid": 1, "pmcid": "PMCabc"}]})
        mock_request.return_value = mock_resp

        with pytest.raises(RuntimeError):
            _resolve_pmc_id_via_idconv("1")

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_http_4xx_raises_runtimeerror(self, mock_request):
        """idconv 4xx도 RuntimeError로 묶어 fallback 유도 (crash 방지). 상태는 로그에 기록."""
        resp = MagicMock()
        resp.status_code = 400
        err = requests.exceptions.HTTPError("400")
        err.response = resp
        mock_request.side_effect = err

        with pytest.raises(RuntimeError):
            _resolve_pmc_id_via_idconv("12345")

    @patch("mlops.pipeline.crawler._resolve_pmc_id_via_elink")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_dispatcher_falls_back_to_elink_on_transient(self, mock_request, mock_elink):
        """idconv transient(파싱 실패) → dispatcher가 elink fallback 호출."""
        mock_resp = MagicMock()
        mock_resp.text = "garbage{{"
        mock_request.return_value = mock_resp
        mock_elink.return_value = "5555555"

        result = _resolve_pmc_id("12345")
        assert result == "5555555"
        mock_elink.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_pmc_id_via_idconv live integration 테스트 (네트워크 필요)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_idconv_live_pmid_28611677():
    """실제 PMC ID Converter API 호출: PMID 28611677 → PMCID 5447067.

    네트워크가 필요하며 API key 불요. CI에서는 -m "not integration"으로 제외.
    """
    result = _resolve_pmc_id_via_idconv("28611677")
    assert result == "5447067", f"예상 '5447067', 실제 {result!r}"
