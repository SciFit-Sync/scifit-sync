"""crawler 모듈 단위 테스트.

PubMed API 호출은 mock 처리하여 외부 의존성 없이 테스트한다.
"""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

from mlops.pipeline.crawler import (
    _get_text,
    _parse_pmc_sections,
    _parse_pubmed_article,
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
