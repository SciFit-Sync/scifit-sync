"""crawler 모듈 단위 테스트.

PubMed API 호출은 mock 처리하여 외부 의존성 없이 테스트한다.
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest
import requests
from mlops.pipeline.crawler import (
    _get_text,
    _parse_pmc_sections,
    _parse_pubmed_article,
    _request_with_rate_limit,
    _round_robin_dedup,
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
        # max_retries=3 (default) → 3회 시도 후 마지막 예외 raise
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            _request_with_rate_limit("http://x", {})
        assert mock_get.call_count == 3

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
