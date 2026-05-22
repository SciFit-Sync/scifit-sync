"""crawler 모듈 단위 테스트.

PubMed/OpenAlex API 호출은 mock 처리하여 외부 의존성 없이 테스트한다.
"""

import json
import logging
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest
import requests
from mlops.pipeline.crawler import (
    CATEGORY_OPENALEX_MAPPING,
    SEARCH_QUERY_CATEGORIES,
    _fetch_pmc_sections,
    _get_text,
    _merge_by_doi,
    _parse_pmc_sections,
    _parse_pubmed_article,
    _request_with_rate_limit,
    _resolve_pmc_id,
    _round_robin_dedup,
    _round_robin_dedup_metas,
    fetch_pmc_fulltext,
    search_pmids,
)
from mlops.pipeline.models import PaperMeta

SAMPLE_PUBMED_ARTICLE_XML = """
<PubmedArticle>
  <MedlineCitation>
    <PMID>12345678</PMID>
    <Article>
      <ArticleTitle>Effects of resistance training on muscle strength</ArticleTitle>
      <Journal>
        <Title>Journal of Sports Science</Title>
        <JournalIssue>
          <PubDate><Year>2024</Year></PubDate>
        </JournalIssue>
      </Journal>
      <AuthorList>
        <Author><LastName>Kim</LastName><ForeName>Minho</ForeName></Author>
        <Author><LastName>Lee</LastName><ForeName>Jina</ForeName></Author>
      </AuthorList>
      <Abstract>
        <AbstractText Label="BACKGROUND">Resistance training is widely used.</AbstractText>
        <AbstractText Label="RESULTS">We found significant improvements.</AbstractText>
      </Abstract>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="doi">10.1234/test.2024</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
"""

SAMPLE_PMC_XML = """
<pmc-articleset>
  <article>
    <body>
      <sec>
        <title>Introduction</title>
        <p>This study investigates the effects of progressive overload.</p>
        <p>Previous research has shown benefits of strength training.</p>
      </sec>
      <sec>
        <title>Methods</title>
        <p>We recruited 50 healthy adults aged 18-35.</p>
      </sec>
    </body>
  </article>
</pmc-articleset>
"""


class TestParsePubmedArticle:
    def test_parse_complete_article(self):
        root = ET.fromstring(SAMPLE_PUBMED_ARTICLE_XML)
        meta = _parse_pubmed_article(root)

        assert isinstance(meta, PaperMeta)
        assert meta.pmid == "12345678"
        assert "resistance training" in meta.title.lower()
        assert meta.journal == "Journal of Sports Science"
        assert meta.published_year == 2024
        assert meta.doi == "10.1234/test.2024"
        assert "Kim Minho" in meta.authors
        assert "Lee Jina" in meta.authors
        assert "BACKGROUND" in meta.abstract
        assert "RESULTS" in meta.abstract

    def test_parse_missing_medline(self):
        root = ET.fromstring("<PubmedArticle></PubmedArticle>")
        assert _parse_pubmed_article(root) is None


class TestParsePmcSections:
    def test_parse_sections(self):
        root = ET.fromstring(SAMPLE_PMC_XML)
        sections = _parse_pmc_sections(root)

        assert len(sections) == 2
        assert sections[0].name == "Introduction"
        assert "progressive overload" in sections[0].content
        assert sections[1].name == "Methods"
        assert "50 healthy adults" in sections[1].content

    def test_parse_no_body(self):
        root = ET.fromstring("<pmc-articleset><article></article></pmc-articleset>")
        sections = _parse_pmc_sections(root)
        assert sections == []


class TestGetText:
    def test_simple_text(self):
        el = ET.fromstring("<p>Hello world</p>")
        assert _get_text(el) == "Hello world"

    def test_nested_tags(self):
        el = ET.fromstring("<p>Hello <b>bold</b> world</p>")
        assert _get_text(el) == "Hello bold world"

    def test_none(self):
        assert _get_text(None) == ""


class TestSearchPmids:
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_search_returns_pmids(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "esearchresult": {
                "count": "3",
                "idlist": ["111", "222", "333"],
            }
        }
        mock_request.return_value = mock_resp

        result = search_pmids("test query", max_results=10)
        assert result == ["111", "222", "333"]

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_search_empty_results(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"count": "0", "idlist": []}}
        mock_request.return_value = mock_resp

        result = search_pmids("nonexistent topic")
        assert result == []


class TestRoundRobinDedup:
    """카테고리별 PMID 리스트를 round-robin 방식으로 dedup하면서
    cap에 도달할 때까지 누적하는 헬퍼 함수 검증.

    핵심 보장 사항:
    1. 카테고리 다양성 — cap이 카테고리 수 이상이면 모든 카테고리가 최소 1개씩 신규 PMID를 등록받음
    2. 동일 PMID 다중 카테고리 매칭 시 카테고리 메타 합집합으로 누적
    3. cap 도달 후에도 기존 PMID에 대한 카테고리 메타 추가는 계속됨 (신규 PMID만 거부)
    4. existing_pmids 안의 PMID는 어떤 경우에도 제외
    """

    def test_distributes_across_categories_in_round_robin(self):
        per_category = [
            ("volume", ["P1", "P2", "P3"]),
            ("intensity", ["P4", "P5", "P6"]),
            ("frequency", ["P7", "P8", "P9"]),
        ]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=9)
        # round 0 → P1, P4, P7 / round 1 → P2, P5, P8 / round 2 → P3, P6, P9
        assert order == ["P1", "P4", "P7", "P2", "P5", "P8", "P3", "P6", "P9"]
        assert all(len(cats) == 1 for cats in mapping.values())

    def test_cap_does_not_starve_later_categories(self):
        # 30개 카테고리 × 5 PMID, cap 30.
        # FIFO cap이면 앞 6개 카테고리에서만 5개씩 가져가 30이 차고 뒤 24개는 0건.
        # round-robin이면 30개 카테고리가 round 0에서 각 1건씩 = 30건.
        per_category = [(f"cat{i}", [f"P{i}_{j}" for j in range(5)]) for i in range(30)]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=30)

        assert len(order) == 30
        registered_cats = {next(iter(mapping[pmid])) for pmid in order}
        assert len(registered_cats) == 30, "모든 카테고리가 신규 PMID를 1건 이상 등록받아야 한다"

    def test_dedup_merges_categories_on_overlap(self):
        per_category = [
            ("volume", ["P1", "P_SHARED"]),
            ("intensity", ["P_SHARED", "P2"]),
        ]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=10)
        # round 0 → P1(volume), P_SHARED(intensity)
        # round 1 → P_SHARED(volume 메타 추가), P2(intensity)
        assert order == ["P1", "P_SHARED", "P2"]
        assert mapping["P_SHARED"] == {"volume", "intensity"}
        assert mapping["P1"] == {"volume"}
        assert mapping["P2"] == {"intensity"}

    def test_meta_accumulates_after_cap_for_existing_pmids(self):
        # cap 도달 후에도 기존 PMID에 대한 카테고리 메타 추가는 계속되어야 한다.
        per_category = [
            ("volume", ["P1", "P_SHARED"]),
            ("intensity", ["P_SHARED"]),
        ]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=2)
        assert order == ["P1", "P_SHARED"]
        # P_SHARED는 round 0에서 등록(intensity). round 1에서 volume의 P_SHARED 만남 → 메타 추가
        assert mapping["P_SHARED"] == {"volume", "intensity"}

    def test_excludes_existing_pmids(self):
        per_category = [
            ("volume", ["P1", "P2"]),
            ("intensity", ["P2", "P3"]),
        ]
        order, mapping = _round_robin_dedup(per_category, existing={"P2"}, max_total=10)
        assert "P2" not in order
        assert "P2" not in mapping
        assert order == ["P1", "P3"]

    def test_empty_per_category(self):
        order, mapping = _round_robin_dedup([], existing=set(), max_total=10)
        assert order == []
        assert mapping == {}

    def test_asymmetric_categories(self):
        # 카테고리 별 PMID 개수가 다를 때 짧은 카테고리는 자동 skip.
        per_category = [
            ("volume", ["P1"]),
            ("intensity", ["P2", "P3", "P4"]),
        ]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=10)
        # round 0 → P1, P2 / round 1 → (volume 소진) P3 / round 2 → P4
        assert order == ["P1", "P2", "P3", "P4"]

    def test_cap_zero(self):
        per_category = [("volume", ["P1", "P2"])]
        order, mapping = _round_robin_dedup(per_category, existing=set(), max_total=0)
        assert order == []
        assert mapping == {}


class TestRequestWithRateLimit:
    """`_request_with_rate_limit`의 transient 에러 재시도 동작 검증.

    실제 환경에서 NCBI eutils API는 가끔 ChunkedEncodingError(HTTP body 도중 끊김),
    Timeout, ConnectionError를 반환한다. 재시도 없이 즉시 실패하면 PMC fulltext
    수집 성공률이 떨어지므로 (실측: dry-run 3편 중 0편 성공, 재호출 시 1편 성공),
    HTTP layer에서 transient 에러에 한해 N회 재시도가 필요하다.

    4xx 같은 영구 에러는 retry하지 않는다 (PMID 없음 등 재시도 의미 없음).
    """

    @patch("mlops.pipeline.crawler.time.sleep")  # 테스트 속도 위해 sleep 무력화
    @patch("mlops.pipeline.crawler.requests.get")
    def test_succeeds_on_first_try(self, mock_get, _mock_sleep):
        mock_resp = MagicMock()
        mock_resp.content = b'{"ok": true}'
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = _request_with_rate_limit("http://x", {})
        assert result is mock_resp
        assert mock_get.call_count == 1

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_retries_on_chunked_encoding_error_then_succeeds(self, mock_get, _mock_sleep):
        good_resp = MagicMock()
        good_resp.content = b'{"ok": true}'
        good_resp.raise_for_status = MagicMock()
        # 첫 2번 ChunkedEncodingError, 3번째 성공
        mock_get.side_effect = [
            requests.exceptions.ChunkedEncodingError("body truncated"),
            requests.exceptions.ChunkedEncodingError("body truncated"),
            good_resp,
        ]
        result = _request_with_rate_limit("http://x", {})
        assert result is good_resp
        assert mock_get.call_count == 3

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_retries_on_connection_error(self, mock_get, _mock_sleep):
        good_resp = MagicMock()
        good_resp.content = b'{"ok": true}'
        good_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("refused"),
            good_resp,
        ]
        result = _request_with_rate_limit("http://x", {})
        assert result is good_resp
        assert mock_get.call_count == 2

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_retries_on_timeout(self, mock_get, _mock_sleep):
        good_resp = MagicMock()
        good_resp.content = b"ok"
        good_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [
            requests.exceptions.Timeout("read timeout"),
            good_resp,
        ]
        result = _request_with_rate_limit("http://x", {})
        assert result is good_resp
        assert mock_get.call_count == 2

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_raises_after_max_retries(self, mock_get, _mock_sleep):
        mock_get.side_effect = requests.exceptions.ChunkedEncodingError("persistent")
        # 명시적 max_retries=3로 동작 검증 (default는 5로 상향)
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            _request_with_rate_limit("http://x", {}, max_retries=3)
        assert mock_get.call_count == 3

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_default_max_retries_is_five(self, mock_get, _mock_sleep):
        """fulltext 회수율을 위해 HTTP layer 기본 retry 횟수를 5로 상향한 상태."""
        mock_get.side_effect = requests.exceptions.ChunkedEncodingError("persistent")
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            _request_with_rate_limit("http://x", {})
        assert mock_get.call_count == 5

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_backoff_is_capped(self, mock_get, _mock_sleep):
        """지수 백오프가 무한 증가하지 않고 NCBI_HTTP_MAX_BACKOFF로 cap된다."""
        from mlops.pipeline import crawler as _crawler

        mock_get.side_effect = requests.exceptions.ChunkedEncodingError("persistent")
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            _request_with_rate_limit("http://x", {})
        # attempt 1+ 의 sleep 호출들 (attempt 0은 NCBI_RATE_LIMIT만 sleep)
        # 모든 backoff sleep이 NCBI_HTTP_MAX_BACKOFF 이하인지 확인
        backoff_sleeps = [
            call.args[0] for call in _mock_sleep.call_args_list if call.args and call.args[0] > _crawler.NCBI_RATE_LIMIT
        ]
        assert backoff_sleeps  # 적어도 1개 이상의 backoff sleep이 있어야 함
        assert all(s <= _crawler.NCBI_HTTP_MAX_BACKOFF for s in backoff_sleeps)

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_does_not_retry_on_4xx_http_error(self, mock_get, _mock_sleep):
        bad_resp = MagicMock()
        bad_resp.status_code = 404
        bad_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found", response=bad_resp)
        mock_get.return_value = bad_resp

        with pytest.raises(requests.exceptions.HTTPError):
            _request_with_rate_limit("http://x", {})
        # 4xx는 영구 에러라 retry 안 함 (한 번만 시도)
        assert mock_get.call_count == 1

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler.requests.get")
    def test_retries_on_5xx_http_error(self, mock_get, _mock_sleep):
        bad_resp = MagicMock()
        bad_resp.status_code = 503
        bad_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "503 Service Unavailable", response=bad_resp
        )
        good_resp = MagicMock()
        good_resp.content = b"ok"
        good_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [bad_resp, good_resp]

        result = _request_with_rate_limit("http://x", {})
        assert result is good_resp
        assert mock_get.call_count == 2


class TestResolvePmcId:
    """`_resolve_pmc_id` 동작 검증.

    NCBI elink는 PMC 미존재 시 가끔 ERROR 필드에 raw control character가 포함된
    malformed JSON을 반환한다(결정론적 server-side 버그). sanitize 후 한 번만
    재파싱하고 그래도 실패하면 PMC 미존재로 간주해 None 반환. transient HTTP
    에러만 함수 레벨에서 재시도한다.
    """

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_returns_pmc_id_on_success(self, mock_request, _mock_sleep):
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"linksets": [{"linksetdbs": [{"dbto": "pmc", "links": [99999]}]}]})
        mock_request.return_value = mock_resp

        result = _resolve_pmc_id("12345")
        assert result == "99999"
        assert mock_request.call_count == 1

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_returns_none_when_no_pmc_version(self, mock_request, _mock_sleep):
        """PMC 버전이 없으면 None 반환 — retry 안 함."""
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({"linksets": [{"linksetdbs": []}]})
        mock_request.return_value = mock_resp

        result = _resolve_pmc_id("12345")
        assert result is None
        assert mock_request.call_count == 1  # retry 무의미하므로 1번만 호출

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_sanitizes_malformed_ncbi_error_response_with_retry(self, mock_request, _mock_sleep):
        """NCBI ERROR 응답(raw \\n control char 포함)을 sanitize 후 파싱하고,
        ERROR 필드가 있으면 transient 가능성(실측 33%)을 위해 1회만 재시도한다.

        실제 PMID=27226389 응답 재현. 두 호출 모두 ERROR면 PMC 미존재로 처리.
        """
        malformed_body = (
            '{"header":{"type":"elink","version":"0.3"},"linksets":[],'
            '"ERROR":"NCBI C++ Exception:\n    Error: TXCLIENT(CException::eUnknown)"}'
        )
        bad_resp = MagicMock()
        bad_resp.text = malformed_body
        mock_request.return_value = bad_resp

        result = _resolve_pmc_id("27226389")
        assert result is None
        assert mock_request.call_count == 2  # ERROR 응답 → 1회만 재시도

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_retries_once_on_error_field_then_succeeds(self, mock_request, _mock_sleep):
        """ERROR 응답(transient)이 다음 호출에서 정상 응답으로 복구되는 케이스 — 1회 retry 효과."""
        error_resp = MagicMock()
        error_resp.text = '{"linksets":[],"ERROR":"NCBI C++ Exception: transient"}'
        good_resp = MagicMock()
        good_resp.text = json.dumps({"linksets": [{"linksetdbs": [{"dbto": "pmc", "links": [55555]}]}]})
        mock_request.side_effect = [error_resp, good_resp]

        result = _resolve_pmc_id("12345")
        assert result == "55555"
        assert mock_request.call_count == 2  # 1번째 ERROR → 1번 retry → 성공

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_returns_none_when_response_unparseable_even_after_sanitize(self, mock_request, _mock_sleep):
        """sanitize 후에도 파싱 불가하면 PMC 미존재로 처리 — retry 안 함."""
        bad_resp = MagicMock()
        bad_resp.text = "not a json at all{{{"
        mock_request.return_value = bad_resp

        result = _resolve_pmc_id("12345")
        assert result is None
        assert mock_request.call_count == 1  # JSON parsing 실패는 결정론적 → retry 안 함

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_retries_on_http_failure_then_succeeds(self, mock_request, _mock_sleep):
        """HTTP layer가 모든 retry 실패해 RequestException 던지면 함수 레벨에서 한 번 더 시도."""
        good_resp = MagicMock()
        good_resp.text = json.dumps({"linksets": [{"linksetdbs": [{"dbto": "pmc", "links": [77777]}]}]})
        mock_request.side_effect = [
            requests.exceptions.ChunkedEncodingError("body cut"),
            good_resp,
        ]

        result = _resolve_pmc_id("12345")
        assert result == "77777"
        assert mock_request.call_count == 2

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_raises_runtime_error_when_all_http_retries_fail(self, mock_request, _mock_sleep):
        """HTTP 에러가 max_attempts 내내 지속되면 RuntimeError."""
        mock_request.side_effect = requests.exceptions.ChunkedEncodingError("body cut")

        with pytest.raises(RuntimeError, match="elink 재시도 한도 초과"):
            _resolve_pmc_id("12345", max_attempts=3)
        assert mock_request.call_count == 3

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_retry_log_distinguishes_error_vs_http(self, mock_request, _mock_sleep, caplog):
        """ERROR retry 로그는 '1회 한정', HTTP retry 로그는 'N/max' 형식이어야 한다.

        같은 'N/5' 포맷이면 사용자가 ERROR도 5회 시도되는 줄 오해. 한도가 다르면
        로그 메시지도 달라야 한다.
        """
        # 케이스 1: ERROR 응답 → ERROR transient retry 로그
        error_resp = MagicMock()
        error_resp.text = '{"linksets":[],"ERROR":"NCBI C++ Exception: transient"}'
        mock_request.side_effect = [error_resp, error_resp]
        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            _resolve_pmc_id("12345")
        error_retry_logs = [r.message for r in caplog.records if "ERROR transient 재시도" in r.message]
        assert error_retry_logs, "ERROR retry 로그가 'ERROR transient 재시도 (1회 한정)' 형식이어야 한다"
        assert "1회 한정" in error_retry_logs[0]
        caplog.clear()
        mock_request.reset_mock()

        # 케이스 2: HTTP 에러 → HTTP retry 로그 (N/max)
        good_resp = MagicMock()
        good_resp.text = json.dumps({"linksets": [{"linksetdbs": [{"dbto": "pmc", "links": [9]}]}]})
        mock_request.side_effect = [
            requests.exceptions.ChunkedEncodingError("body cut"),
            good_resp,
        ]
        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            _resolve_pmc_id("12345")
        http_retry_logs = [r.message for r in caplog.records if "HTTP 재시도" in r.message]
        assert http_retry_logs, "HTTP retry 로그가 'HTTP 재시도 N/max' 형식이어야 한다"


class TestFetchPmcSections:
    """`_fetch_pmc_sections` 함수 레벨 재시도 동작 검증.

    HTTP 200인데 XML body가 깨진 케이스 — `ET.ParseError`로 함수 레벨 retry.
    """

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_returns_sections_on_success(self, mock_request, _mock_sleep):
        good_resp = MagicMock()
        good_resp.content = SAMPLE_PMC_XML.strip().encode()
        mock_request.return_value = good_resp

        sections = _fetch_pmc_sections("12345", "PMC99999")
        assert len(sections) == 2
        assert sections[0].name == "Introduction"
        assert mock_request.call_count == 1

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_retries_on_xml_parse_error_then_succeeds(self, mock_request, _mock_sleep):
        bad_resp = MagicMock()
        bad_resp.content = b"<malformed xml<<>"
        good_resp = MagicMock()
        good_resp.content = SAMPLE_PMC_XML.strip().encode()
        mock_request.side_effect = [bad_resp, good_resp]

        sections = _fetch_pmc_sections("12345", "PMC99999")
        assert len(sections) == 2
        assert mock_request.call_count == 2

    @patch("mlops.pipeline.crawler.time.sleep")
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_raises_runtime_error_after_exhausting_retries(self, mock_request, _mock_sleep):
        bad_resp = MagicMock()
        bad_resp.content = b"<malformed xml<<>"
        mock_request.return_value = bad_resp

        with pytest.raises(RuntimeError, match="efetch 재시도 한도 초과"):
            _fetch_pmc_sections("12345", "PMC99999", max_attempts=3)
        assert mock_request.call_count == 3


class TestFetchPmcFulltext:
    """`fetch_pmc_fulltext` end-to-end 흐름: PMC 버전 없음 vs 정상 vs 실패."""

    @patch("mlops.pipeline.crawler._fetch_pmc_sections")
    @patch("mlops.pipeline.crawler._resolve_pmc_id")
    def test_returns_empty_when_no_pmc_version(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = None

        result = fetch_pmc_fulltext("12345")
        assert result == []
        mock_fetch.assert_not_called()

    @patch("mlops.pipeline.crawler._fetch_pmc_sections")
    @patch("mlops.pipeline.crawler._resolve_pmc_id")
    def test_full_pipeline_success(self, mock_resolve, mock_fetch):
        from mlops.pipeline.models import PaperSection

        mock_resolve.return_value = "PMC99999"
        mock_fetch.return_value = [PaperSection(name="Introduction", content="test")]

        result = fetch_pmc_fulltext("12345")
        assert len(result) == 1
        assert result[0].name == "Introduction"
        mock_fetch.assert_called_once_with("12345", "PMC99999")


# ─────────────────────────────────────────────────────────────────────────────
# Task 10: OpenAlex 통합 + DOI 기반 dedup + 필터 토글
# ─────────────────────────────────────────────────────────────────────────────


class TestMergeByDoi:
    """`_merge_by_doi`: 동일 DOI는 OpenAlex 메타 우선 + PubMed로 pmid/publication_types 보강."""

    def test_merge_by_doi_prefers_openalex(self):
        oa = PaperMeta(
            pmid="",
            title="oa",
            authors="",
            journal="oa-journal",
            published_year=2020,
            doi="10.1/x",
            abstract="oa-abs",
            publication_types=["Randomized Controlled Trial"],
        )
        pm = PaperMeta(
            pmid="99",
            title="pm",
            authors="",
            journal="pm-journal",
            published_year=2020,
            doi="10.1/x",
            abstract="pm-abs",
            publication_types=[],
        )

        merged = _merge_by_doi([oa], [pm])
        assert len(merged) == 1
        assert merged[0].title == "oa"
        assert merged[0].journal == "oa-journal"
        assert merged[0].pmid == "99"  # PubMed가 PMID 보강
        assert merged[0].publication_types == ["Randomized Controlled Trial"]

    def test_merge_by_doi_pubmed_fills_publication_types(self):
        """OpenAlex가 publication_types 비어있으면 PubMed 값으로 보강."""
        oa = PaperMeta(
            pmid="",
            title="oa",
            authors="",
            journal="",
            published_year=2020,
            doi="10.1/x",
            abstract="",
            publication_types=[],
        )
        pm = PaperMeta(
            pmid="99",
            title="pm",
            authors="",
            journal="",
            published_year=2020,
            doi="10.1/x",
            abstract="",
            publication_types=["Meta-Analysis"],
        )

        merged = _merge_by_doi([oa], [pm])
        assert len(merged) == 1
        assert merged[0].publication_types == ["Meta-Analysis"]

    def test_merge_by_doi_pubmed_only_paper_passes_through(self):
        """OpenAlex에 없는 DOI는 PubMed 메타가 그대로 통과."""
        pm = PaperMeta(
            pmid="99",
            title="pm",
            authors="",
            journal="",
            published_year=2020,
            doi="10.1/y",
            abstract="",
            publication_types=["Meta-Analysis"],
        )
        merged = _merge_by_doi([], [pm])
        assert len(merged) == 1
        assert merged[0].doi == "10.1/y"
        assert merged[0].pmid == "99"

    def test_merge_by_doi_skips_pubmed_without_doi(self):
        """DOI 없는 PubMed 메타는 폐기 (DOI primary key 정책)."""
        pm = PaperMeta(pmid="99", title="pm", doi="", abstract="")
        merged = _merge_by_doi([], [pm])
        assert merged == []


class TestRoundRobinDedupMetas:
    """`_round_robin_dedup_metas`: DOI 기반 round-robin dedup."""

    @staticmethod
    def _m(doi: str) -> PaperMeta:
        return PaperMeta(
            pmid="",
            title="t",
            authors="",
            journal="",
            published_year=2020,
            doi=doi,
            abstract="",
        )

    def test_round_robin_keeps_category_diversity(self):
        per_cat = [
            ("volume", [self._m("10.1/a"), self._m("10.1/b"), self._m("10.1/c")]),
            ("intensity", [self._m("10.1/d"), self._m("10.1/a")]),
        ]
        order, by_cat, by_doi = _round_robin_dedup_metas(per_cat, set(), 10)

        assert "10.1/a" in by_doi
        # round 0 → volume에서 a, intensity에서 d / round 1 → b, intensity의 a(메타 추가)
        assert by_cat["10.1/a"] == {"volume", "intensity"}
        assert order == ["10.1/a", "10.1/d", "10.1/b", "10.1/c"]

    def test_round_robin_respects_max_total(self):
        per_cat = [
            ("volume", [self._m("10.1/a"), self._m("10.1/b"), self._m("10.1/c")]),
            ("intensity", [self._m("10.1/d"), self._m("10.1/e")]),
        ]
        order, _, by_doi = _round_robin_dedup_metas(per_cat, set(), 3)
        assert len(by_doi) == 3
        assert len(order) == 3

    def test_round_robin_excludes_existing_dois(self):
        per_cat = [("volume", [self._m("10.1/a"), self._m("10.1/b")])]
        order, _, by_doi = _round_robin_dedup_metas(per_cat, {"10.1/a"}, 10)
        assert "10.1/a" not in by_doi
        assert "10.1/b" in by_doi
        assert order == ["10.1/b"]

    def test_round_robin_skips_metas_without_doi(self):
        """DOI 없는 메타는 무조건 폐기."""
        per_cat = [("volume", [self._m(""), self._m("10.1/a")])]
        order, _, by_doi = _round_robin_dedup_metas(per_cat, set(), 10)
        assert order == ["10.1/a"]
        assert "" not in by_doi

    def test_round_robin_empty(self):
        order, by_cat, by_doi = _round_robin_dedup_metas([], set(), 10)
        assert order == []
        assert by_cat == {}
        assert by_doi == {}


class TestCategoryOpenAlexMapping:
    def test_mapping_covers_all_search_query_categories(self):
        """SEARCH_QUERY_CATEGORIES의 모든 카테고리가 CATEGORY_OPENALEX_MAPPING에 존재해야 함."""
        sq_names = {name for name, _, _ in SEARCH_QUERY_CATEGORIES}
        mapping_names = set(CATEGORY_OPENALEX_MAPPING.keys())
        missing = sq_names - mapping_names
        assert not missing, f"누락 카테고리: {missing}"

    def test_mapping_entries_have_required_keys(self):
        """모든 매핑 엔트리는 concept_ids + keywords 키를 가져야 함."""
        for name, cfg in CATEGORY_OPENALEX_MAPPING.items():
            assert "concept_ids" in cfg, f"{name}에 concept_ids 누락"
            assert "keywords" in cfg, f"{name}에 keywords 누락"
            assert isinstance(cfg["concept_ids"], list)
            assert isinstance(cfg["keywords"], list)
            # 적어도 keyword 1개는 있어야 검색이 의미 있다
            assert cfg["keywords"], f"{name}에 keyword 1개도 없음"


class TestPublicationFilterToggle:
    """STRICT_PUBLICATION_FILTER 환경변수 토글."""

    def test_filter_toggle_off_returns_empty(self):
        import mlops.pipeline.crawler as crawler_mod

        with patch.object(crawler_mod, "STRICT_PUBLICATION_FILTER", False):
            assert crawler_mod.get_publication_filter() == ""

    def test_filter_toggle_on_returns_strict(self):
        import mlops.pipeline.crawler as crawler_mod

        with patch.object(crawler_mod, "STRICT_PUBLICATION_FILTER", True):
            result = crawler_mod.get_publication_filter()
            assert "randomized controlled trial" in result.lower()
            assert "meta-analysis" in result.lower()
            assert "free full text" in result.lower()


class TestAttachFulltext:
    """_attach_fulltext가 cascading 결과를 PaperMeta에 정확히 반영하는지."""

    def test_success_path_sets_source_and_sections(self, monkeypatch):
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta, PaperSection

        called_with = {}

        def fake_fetch_cascading(*, pmcid, pmid, doi, pmc_client, europepmc_client):
            called_with.update(pmcid=pmcid, pmid=pmid, doi=doi)
            return CascadingFulltextResult(
                fulltext_source="pmc",
                tried_sources=["pmc"],
                sections=[PaperSection(name="Intro", content="x" * 50)],
                had_transient_error=False,
            )

        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_fetch_cascading)
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="999",
                title="t",
                authors="",
                journal="",
                published_year=2020,
                doi="10.1/abc",
                abstract="",
                pmcid="PMC1",
            )
        ]
        papers = _attach_fulltext(metas)

        assert called_with == {"pmcid": "PMC1", "pmid": "999", "doi": "10.1/abc"}
        assert len(papers) == 1
        assert papers[0].meta.fulltext_source == "pmc"
        assert len(papers[0].sections) == 1
        assert papers[0].sections[0].name == "Intro"

    def test_all_sources_fail_keeps_none(self, monkeypatch):
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta

        def fake_fetch_cascading(**_):
            return CascadingFulltextResult(
                fulltext_source=None,
                tried_sources=["pmc", "europepmc"],
                sections=[],
                had_transient_error=False,
            )

        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_fetch_cascading)
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="1",
                title="t",
                authors="",
                journal="",
                published_year=2020,
                doi="10.1/x",
                abstract="",
            )
        ]
        papers = _attach_fulltext(metas)
        assert papers[0].meta.fulltext_source is None
        assert papers[0].sections == []

    def test_empty_metas_returns_empty(self, monkeypatch):
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext

        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        assert _attach_fulltext([]) == []

    def test_pmcid_none_with_pmid_triggers_elink(self, monkeypatch):
        """meta.pmcid가 None이지만 PMID가 있으면 _resolve_pmc_id로 보강 시도.

        _resolve_pmc_id가 None을 반환하면(PMC 미존재) 그대로 None을 fetch_cascading에 전달.
        """
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta

        captured = {}
        resolve_calls = []

        def fake_resolve(pmid):
            resolve_calls.append(pmid)
            return None  # PMC 미존재 시뮬레이션

        def fake_fetch_cascading(*, pmcid, pmid, doi, **_):
            captured["pmcid"] = pmcid
            return CascadingFulltextResult(
                fulltext_source=None,
                tried_sources=[],
                sections=[],
                had_transient_error=False,
            )

        monkeypatch.setattr("mlops.pipeline.crawler._resolve_pmc_id", fake_resolve)
        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_fetch_cascading)
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="1", title="t", authors="", journal="", published_year=2020, doi="10.1/x", abstract="", pmcid=None
            )
        ]
        _attach_fulltext(metas)
        assert resolve_calls == ["1"]
        assert captured["pmcid"] is None

    def test_pmcid_resolved_from_pmid_via_elink(self, monkeypatch):
        """meta.pmcid가 None일 때 _resolve_pmc_id로 보강해 cascading에 PMCID 전달.

        multi-source ingest 도입 후 누락됐던 PMC 회수 경로의 회귀 fix 검증.
        """
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta

        captured = {}

        monkeypatch.setattr("mlops.pipeline.crawler._resolve_pmc_id", lambda pmid: "1234567")

        def fake_fetch_cascading(*, pmcid, pmid, doi, **_):
            captured["pmcid"] = pmcid
            return CascadingFulltextResult(
                fulltext_source="pmc", tried_sources=["pmc"], sections=[], had_transient_error=False
            )

        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_fetch_cascading)
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="42",
                title="t",
                authors="",
                journal="",
                published_year=2020,
                doi="10.1/x",
                abstract="",
                pmcid=None,
            )
        ]
        _attach_fulltext(metas)
        assert captured["pmcid"] == "1234567"
        # 후속 manifest 기록에도 반영되도록 meta.pmcid도 갱신되는지 확인
        assert metas[0].pmcid == "1234567"

    def test_resolve_runtime_error_falls_through_to_europepmc(self, monkeypatch):
        """_resolve_pmc_id가 RuntimeError(재시도 한도 초과)를 raise해도 cascading은 진행."""
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta

        captured = {}

        def raising_resolve(pmid):
            raise RuntimeError("PMC elink 재시도 한도 초과")

        monkeypatch.setattr("mlops.pipeline.crawler._resolve_pmc_id", raising_resolve)

        def fake_fetch_cascading(*, pmcid, pmid, doi, **_):
            captured["pmcid"] = pmcid
            return CascadingFulltextResult(
                fulltext_source=None, tried_sources=["europepmc"], sections=[], had_transient_error=False
            )

        monkeypatch.setattr("mlops.pipeline.crawler.fetch_cascading", fake_fetch_cascading)
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="9",
                title="t",
                authors="",
                journal="",
                published_year=2020,
                doi="10.1/x",
                abstract="",
                pmcid=None,
            )
        ]
        _attach_fulltext(metas)
        assert captured["pmcid"] is None  # RuntimeError 시 cascading은 None으로 진행

    def test_resolve_not_called_when_pmid_empty(self, monkeypatch):
        """OpenAlex-only paper처럼 PMID가 빈 문자열이면 _resolve_pmc_id 호출하지 않음."""
        from unittest.mock import MagicMock

        from mlops.pipeline.crawler import _attach_fulltext
        from mlops.pipeline.fulltext import CascadingFulltextResult
        from mlops.pipeline.models import PaperMeta

        resolve_calls = []

        def fake_resolve(pmid):
            resolve_calls.append(pmid)
            return "X"

        monkeypatch.setattr("mlops.pipeline.crawler._resolve_pmc_id", fake_resolve)
        monkeypatch.setattr(
            "mlops.pipeline.crawler.fetch_cascading",
            lambda **_: CascadingFulltextResult(
                fulltext_source=None, tried_sources=[], sections=[], had_transient_error=False
            ),
        )
        monkeypatch.setattr("mlops.pipeline.crawler.PMCClient", MagicMock())
        monkeypatch.setattr("mlops.pipeline.crawler.EuropePMCClient", MagicMock())

        metas = [
            PaperMeta(
                pmid="",
                title="t",
                authors="",
                journal="",
                published_year=2020,
                doi="10.1/x",
                abstract="",
                pmcid=None,
            )
        ]
        _attach_fulltext(metas)
        assert resolve_calls == []


class TestMaxPerCategoryOverride:
    """max_per_category 명시 시 OpenAlex/PubMed cap 양쪽에 적용되는지 검증."""

    def test_max_per_category_overrides_default(self, monkeypatch):
        import mlops.pipeline.crawler as crawler_mod

        captured = {}

        def fake_oa(name, max_results):
            captured["openalex_max"] = max_results
            return []

        def fake_pmid(query, retmax, *_):
            captured["pubmed_max"] = retmax
            return []

        monkeypatch.setattr(crawler_mod, "search_openalex_by_category", fake_oa)
        monkeypatch.setattr(crawler_mod, "search_pmids", fake_pmid)
        monkeypatch.setattr(crawler_mod, "fetch_paper_metadata", lambda _: [])
        monkeypatch.setattr(crawler_mod, "_attach_fulltext", lambda metas: [])

        crawler_mod.crawl_papers(max_per_category=7, fetch_fulltext=False)
        assert captured["openalex_max"] == 7
        assert captured["pubmed_max"] == 7


class TestAttachFulltextProgressLog:
    """_attach_fulltext의 진행 표시 로그 검증.

    실제 호출은 fetch_cascading + _resolve_pmc_id mock으로 차단.
    """

    def _mk_meta(self, pmid: str) -> PaperMeta:
        return PaperMeta(pmid=pmid, title=f"t-{pmid}", doi=f"10.x/{pmid}")

    def _mk_result(self, source: str | None):
        """fetch_cascading 반환을 흉내내는 가벼운 객체."""
        from types import SimpleNamespace

        from mlops.pipeline.models import PaperSection

        sections = [PaperSection(name="abstract", content="x")] if source else []
        return SimpleNamespace(fulltext_source=source, sections=sections)

    def test_progress_log_every_n_papers(self, monkeypatch, caplog):
        """50편마다 + 마지막 1편에서 progress 로그 출력."""
        import mlops.pipeline.crawler as crawler_mod

        monkeypatch.setattr(crawler_mod, "_resolve_pmc_id", lambda pmid: None)
        # 모든 paper가 PMC로 성공한다고 가정
        monkeypatch.setattr(
            crawler_mod,
            "fetch_cascading",
            lambda **kw: self._mk_result("pmc"),
        )
        # 클라이언트 생성자 가짜 — 네트워크 차단
        monkeypatch.setattr(crawler_mod, "PMCClient", lambda **kw: object())
        monkeypatch.setattr(crawler_mod, "EuropePMCClient", lambda **kw: object())

        metas = [self._mk_meta(str(i)) for i in range(120)]
        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            papers = crawler_mod._attach_fulltext(metas)

        assert len(papers) == 120
        progress_lines = [r for r in caplog.records if "PMC 본문 수집 진행" in r.getMessage()]
        # 50, 100, 120 (마지막) → 3회
        assert len(progress_lines) == 3
        # 마지막 줄은 120/120 + 확보 120 + 미확보 0
        last_msg = progress_lines[-1].getMessage()
        assert "120/120" in last_msg
        assert "확보 120" in last_msg
        assert "미확보 0" in last_msg
        assert "pmc 120" in last_msg

    def test_progress_log_counts_failed_papers_in_missed(self, monkeypatch, caplog):
        """본문 미확보(sections=[])는 미확보로 카운트."""
        import mlops.pipeline.crawler as crawler_mod

        monkeypatch.setattr(crawler_mod, "_resolve_pmc_id", lambda pmid: None)

        # 짝수만 성공, 홀수는 실패
        def fake_fetch(**kw):
            pmid = kw.get("pmid") or ""
            success = pmid.isdigit() and int(pmid) % 2 == 0
            return self._mk_result("europepmc" if success else None)

        monkeypatch.setattr(crawler_mod, "fetch_cascading", fake_fetch)
        monkeypatch.setattr(crawler_mod, "PMCClient", lambda **kw: object())
        monkeypatch.setattr(crawler_mod, "EuropePMCClient", lambda **kw: object())

        metas = [self._mk_meta(str(i)) for i in range(10)]
        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            crawler_mod._attach_fulltext(metas)

        progress_lines = [r for r in caplog.records if "PMC 본문 수집 진행" in r.getMessage()]
        # total=10이라 마지막 1회만 (PROGRESS_EVERY=50보다 작음)
        assert len(progress_lines) == 1
        msg = progress_lines[0].getMessage()
        assert "10/10" in msg
        assert "확보 5" in msg  # 짝수 0,2,4,6,8 → 5편
        assert "미확보 5" in msg
        assert "europepmc 5" in msg

    def test_progress_log_skipped_on_empty_input(self, monkeypatch, caplog):
        """입력이 비어있으면 progress 로그 출력 안 됨 (루프 미진입)."""
        import mlops.pipeline.crawler as crawler_mod

        monkeypatch.setattr(crawler_mod, "PMCClient", lambda **kw: object())
        monkeypatch.setattr(crawler_mod, "EuropePMCClient", lambda **kw: object())

        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            papers = crawler_mod._attach_fulltext([])
        assert papers == []
        assert not [r for r in caplog.records if "PMC 본문 수집 진행" in r.getMessage()]

    def test_progress_log_handles_mixed_sources(self, monkeypatch, caplog):
        """다중 source 카운트가 src_summary에 정렬되어 노출되는지."""
        import mlops.pipeline.crawler as crawler_mod

        monkeypatch.setattr(crawler_mod, "_resolve_pmc_id", lambda pmid: None)

        def fake_fetch(**kw):
            pmid = kw.get("pmid") or ""
            idx = int(pmid)
            if idx < 30:
                return self._mk_result("pmc")
            if idx < 50:
                return self._mk_result("europepmc")
            return self._mk_result(None)

        monkeypatch.setattr(crawler_mod, "fetch_cascading", fake_fetch)
        monkeypatch.setattr(crawler_mod, "PMCClient", lambda **kw: object())
        monkeypatch.setattr(crawler_mod, "EuropePMCClient", lambda **kw: object())

        metas = [self._mk_meta(str(i)) for i in range(60)]
        with caplog.at_level(logging.INFO, logger="mlops.pipeline.crawler"):
            crawler_mod._attach_fulltext(metas)

        progress_lines = [r for r in caplog.records if "PMC 본문 수집 진행" in r.getMessage()]
        # 50, 60 → 2회
        assert len(progress_lines) == 2
        last_msg = progress_lines[-1].getMessage()
        # 정렬: europepmc → pmc (알파벳 순)
        assert "europepmc 20" in last_msg
        assert "pmc 30" in last_msg
        assert "확보 50" in last_msg
        assert "미확보 10" in last_msg
