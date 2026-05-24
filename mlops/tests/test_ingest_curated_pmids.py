"""ingest_curated_pmids 단위 테스트."""

import json
from unittest.mock import MagicMock, patch

import pytest

_FAKE_PMC_CLIENT = MagicMock()
_FAKE_EUROPEPMC_CLIENT = MagicMock()


class TestLockAcquisition:
    def test_acquires_lock_when_free(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock

        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path) as lock_fd:
            assert lock_fd is not None
        # 락 해제 후 파일 존재 OK (lock 파일은 reuse)
        assert lock_path.exists()

    def test_lock_fails_when_held(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock

        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path):  # noqa: SIM117
            # 이미 잡힌 락은 두 번째 호출에서 BlockingIOError
            with pytest.raises(BlockingIOError), acquire_lock(lock_path):
                pass


SAMPLE_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>35291645</PMID>
      <Article>
        <ArticleTitle>Test Paper Title One</ArticleTitle>
        <Abstract><AbstractText>Sample abstract one.</AbstractText></Abstract>
        <PublicationTypeList>
          <PublicationType>Meta-Analysis</PublicationType>
        </PublicationTypeList>
        <Journal><JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.2478/hukin-2022-0017</ArticleId>
        <ArticleId IdType="pmc">PMC8884877</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


class TestEfetchBatch:
    @patch("mlops.scripts.ingest_curated_pmids.requests.get")
    def test_parses_efetch_batch_response(self, mock_get):
        from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch

        mock_resp = MagicMock(status_code=200, content=SAMPLE_EFETCH_XML.encode())
        mock_get.return_value = mock_resp

        result = efetch_pubmed_batch(["35291645"])
        assert "35291645" in result
        meta = result["35291645"]
        assert meta["doi"] == "10.2478/hukin-2022-0017"
        assert meta["pmcid"] == "PMC8884877"
        assert meta["title"] == "Test Paper Title One"
        assert meta["publication_year"] == 2022
        assert "Meta-Analysis" in meta["publication_types"]

    @patch("mlops.scripts.ingest_curated_pmids.requests.get")
    def test_returns_empty_dict_on_error(self, mock_get):
        import requests as _r  # noqa: PLC0415
        from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch  # noqa: PLC0415

        mock_get.side_effect = _r.RequestException("timeout")

        result = efetch_pubmed_batch(["35291645"])
        assert result == {}


class TestResolveIdentifier:
    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_pmid_with_doi_from_efetch(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_efetch.return_value = {
            "12345": {
                "doi": "10.1080/test",
                "pmcid": "PMC1",
                "title": "T",
                "abstract": "A",
                "publication_types": ["RCT"],
                "publication_year": 2020,
            }
        }
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["hypertrophy"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="hypertrophy volume")

        p = resolved[0]
        assert p["resolved_pmid"] == "12345"
        assert p["resolved_doi"] == "10.1080/test"
        assert p["resolved_title"] == "T"
        assert p["failure_reason"] is None
        assert p["metadata"]["publication_types"] == ["RCT"]

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    @patch("mlops.scripts.ingest_curated_pmids.ncbi_pmid_to_doi")
    def test_branch_a_efetch_no_doi_converter_succeeds(self, mock_conv, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_efetch.return_value = {
            "12345": {
                "doi": "",
                "pmcid": "",
                "title": "T",
                "abstract": "",
                "publication_types": [],
                "publication_year": 2020,
            }
        }
        mock_conv.return_value = "10.1080/converted"
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_doi"] == "10.1080/converted"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    @patch("mlops.scripts.ingest_curated_pmids.ncbi_pmid_to_doi")
    def test_branch_a_both_fail(self, mock_conv, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_efetch.return_value = {
            "12345": {
                "doi": "",
                "pmcid": "",
                "title": "T",
                "abstract": "",
                "publication_types": [],
                "publication_year": 2020,
            }
        }
        mock_conv.return_value = ""
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "doi_resolution_failed"
        assert resolved[0]["indexed"] is False

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_efetch_not_found(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        # PMID 12345 was requested but not in efetch response
        mock_efetch.return_value = {}
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        # Patch single re-fetch to also miss
        with patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch", return_value={}):
            resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "efetch_not_found"

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_single_retry_succeeds(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        # First call: batch returns empty (PMID missing)
        # Second call: single re-fetch returns the metadata
        mock_efetch.side_effect = [
            {},  # initial batch miss
            {
                "12345": {
                    "doi": "10.1080/test",
                    "pmcid": "",
                    "title": "T",
                    "abstract": "",
                    "publication_types": [],
                    "publication_year": 2020,
                }
            },
        ]
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "already_in_corpus": None,
                "fulltext_ok": None,
                "failure_reason": None,
                "is_typo_autofixed": False,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] is None
        assert resolved[0]["resolved_doi"] == "10.1080/test"
        assert resolved[0]["resolved_pmid"] == "12345"

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_doi_only_success(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_lookup.return_value = {
            "doi": "10.1080/test",
            "pmid": "99999",
            "title": "OA Title",
            "publication_year": 2021,
            "type": "journal-article",
        }
        papers = [
            {
                "raw_id": "DOI:10.1080/test",
                "raw_pmid": None,
                "raw_doi": "10.1080/test",
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_pmid"] == "99999"
        assert resolved[0]["resolved_doi"] == "10.1080/test"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_doi_only_no_pmid(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_lookup.return_value = {"doi": "10.1080/x", "pmid": "", "title": "T", "publication_year": None, "type": ""}
        papers = [
            {
                "raw_id": "DOI:10.1080/x",
                "raw_pmid": None,
                "raw_doi": "10.1080/x",
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "no_pmid_from_openalex"

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_openalex_not_found(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_lookup.return_value = None
        papers = [
            {
                "raw_id": "DOI:10.1080/x",
                "raw_pmid": None,
                "raw_doi": "10.1080/x",
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": False,
                "fulltext_ok": None,
                "search_categories": ["x"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "openalex_not_found"

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_title_mismatch_skip(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_efetch.return_value = {
            "12345": {
                "doi": "10.1080/test",
                "pmcid": "",
                "title": "Robotic Cardiology Cybernetics",
                "abstract": "",
                "publication_types": [],
                "publication_year": 2020,
            }
        }
        papers = [
            {
                "raw_id": "PMID:12345",
                "raw_pmid": "12345",
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "failure_reason": None,
                "already_in_corpus": None,
                "is_typo_autofixed": True,
                "fulltext_ok": None,  # ← typo flag
                "search_categories": ["hypertrophy"],
            }
        ]
        resolved = resolve_papers(papers, qid="Q001", query_context="hypertrophy weekly set volume")
        assert resolved[0]["failure_reason"] == "title_mismatch"


class TestAlreadyInCorpus:
    def test_marks_already_in_corpus_after_resolution(self):
        from mlops.scripts.ingest_curated_pmids import mark_already_in_corpus

        existing_dois = {"10.1080/test"}
        papers = [
            {
                "resolved_doi": "10.1080/test",
                "resolved_pmid": "12345",
                "indexed": None,
                "already_in_corpus": None,
                "failure_reason": None,
            },
            {
                "resolved_doi": "10.1080/new",
                "resolved_pmid": "99999",
                "indexed": None,
                "already_in_corpus": None,
                "failure_reason": None,
            },
        ]
        mark_already_in_corpus(papers, existing_dois)

        assert papers[0]["already_in_corpus"] is True
        assert papers[0]["indexed"] is True
        assert papers[1]["already_in_corpus"] is False
        assert papers[1]["indexed"] is None  # not yet processed

    def test_does_not_touch_failed_papers(self):
        from mlops.scripts.ingest_curated_pmids import mark_already_in_corpus

        existing_dois = {"10.1080/anything"}
        papers = [
            {
                "resolved_doi": "10.1080/anything",
                "resolved_pmid": "1",
                "indexed": False,
                "already_in_corpus": None,
                "failure_reason": "doi_resolution_failed",
            }
        ]
        mark_already_in_corpus(papers, existing_dois)
        # 이미 실패한 paper는 변경하지 않음
        assert papers[0]["already_in_corpus"] is None

    def test_marks_resolution_failure_when_doi_missing_and_no_failure(self):
        from mlops.scripts.ingest_curated_pmids import mark_already_in_corpus

        papers = [
            {
                "resolved_doi": None,
                "resolved_pmid": "1",
                "indexed": None,
                "already_in_corpus": None,
                "failure_reason": None,
            }
        ]
        mark_already_in_corpus(papers, set())
        assert papers[0]["failure_reason"] == "doi_resolution_failed"
        assert papers[0]["indexed"] is False


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import atomic_write_json

        path = tmp_path / "out.json"
        atomic_write_json(path, {"k": "v"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"k": "v"}

    def test_atomic_write_replaces_existing(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import atomic_write_json

        path = tmp_path / "out.json"
        path.write_text('{"old": true}')
        atomic_write_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
        # tmp 파일은 남지 않아야 함
        assert not list(tmp_path.glob("*.tmp"))


class TestLoadExistingDois:
    def test_combines_manifest_and_server(self):
        from mlops.scripts.ingest_curated_pmids import load_existing_dois

        manifest = MagicMock()
        manifest.papers = {
            "10.1080/testA": MagicMock(fulltext_source="pmc", tried_sources=["pmc"]),
            "10.1080/TESTB": MagicMock(fulltext_source=None, tried_sources=["pmc", "europepmc"]),
        }
        with patch("mlops.scripts.ingest_curated_pmids._fetch_server_dois") as mock_srv:
            mock_srv.return_value = {"10.1080/TESTC", "10.1080/TESTD"}
            result = load_existing_dois(manifest)
            assert "10.1080/testa" in result  # normalized (lowercase)
            assert "10.1080/testb" in result  # fully-tried → included
            assert "10.1080/testc" in result  # from server
            assert "10.1080/testd" in result


class TestBuildPaperFulls:
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_builds_paperfull_with_fulltext(self, mock_fetch):
        from mlops.pipeline.models import PaperSection
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_fetch.return_value = MagicMock(
            sections=[PaperSection(name="Methods", content="...")], fulltext_source="pmc"
        )
        papers = [
            {
                "resolved_pmid": "12345",
                "resolved_doi": "10.1080/test",
                "resolved_title": "T",
                "metadata": {
                    "abstract": "abs",
                    "pmcid": "PMC1",
                    "publication_types": ["RCT"],
                    "publication_year": 2020,
                },
                "search_categories": ["hypertrophy"],
                "indexed": None,
                "already_in_corpus": False,
                "fulltext_ok": None,
                "failure_reason": None,
            }
        ]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert len(result) == 1
        paperfull = result[0]
        assert paperfull.meta.pmid == "12345"
        assert paperfull.meta.doi == "10.1080/test"
        assert paperfull.meta.publication_types == ["RCT"]
        assert paperfull.meta.search_categories == ["hypertrophy"]
        assert papers[0]["fulltext_ok"] is True

    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_marks_no_fulltext_when_fetch_returns_empty(self, mock_fetch):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_fetch.return_value = MagicMock(sections=[], fulltext_source=None)
        papers = [
            {
                "resolved_pmid": "12345",
                "resolved_doi": "10.1080/test",
                "resolved_title": "T",
                "metadata": {"abstract": "", "pmcid": "", "publication_types": [], "publication_year": 2020},
                "search_categories": ["x"],
                "indexed": None,
                "already_in_corpus": False,
                "fulltext_ok": None,
                "failure_reason": None,
            }
        ]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)
        # paper는 result에서 빠짐 (sections=[])
        assert len(result) == 0
        # invariant: failure_reason과 indexed=False 동시 기록
        assert papers[0]["fulltext_ok"] is False
        assert papers[0]["failure_reason"] == "no_fulltext"
        assert papers[0]["indexed"] is False

    def test_skips_failed_and_already_in_corpus_papers(self):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        papers = [
            {
                "resolved_pmid": "1",
                "indexed": True,
                "already_in_corpus": True,
                "failure_reason": None,
                "fulltext_ok": None,
            },
            {
                "resolved_pmid": "2",
                "indexed": False,
                "already_in_corpus": False,
                "failure_reason": "doi_resolution_failed",
                "fulltext_ok": None,
            },
        ]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)
        assert result == []


class TestOAFallback:
    """OpenAlex OA fallback 통합 테스트 (build_paperfulls_for_ingest 레벨)."""

    def _make_paper(self):
        return {
            "resolved_pmid": "12345",
            "resolved_doi": "10.1080/test",
            "resolved_title": "T",
            "metadata": {
                "abstract": "abs",
                "pmcid": None,
                "publication_types": [],
                "publication_year": 2022,
            },
            "search_categories": ["hypertrophy"],
            "indexed": None,
            "already_in_corpus": False,
            "fulltext_ok": None,
            "failure_reason": None,
        }

    @patch("mlops.scripts.ingest_curated_pmids.fetch_pdf_sections")
    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_oa_pdf_fallback_fills_sections(self, mock_cascade, mock_oa_url, mock_pdf):
        from mlops.pipeline.models import PaperSection
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        # cascading returns empty
        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        # OpenAlex returns OA with PDF URL
        mock_oa_url.return_value = {
            "is_oa": True,
            "pdf_url": "https://example.com/paper.pdf",
            "landing_page_url": "https://example.com/paper",
        }
        mock_pdf.return_value = [PaperSection(name="Full Text", content="paper body text")]

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert len(result) == 1
        assert result[0].meta.fulltext_source == "openalex_pdf"
        assert result[0].sections[0].content == "paper body text"
        assert papers[0]["fulltext_ok"] is True
        assert papers[0].get("failure_reason") is None
        mock_pdf.assert_called_once_with("https://example.com/paper.pdf")

    @patch("mlops.scripts.ingest_curated_pmids.fetch_html_sections")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_pdf_sections")
    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_oa_html_fallback_when_pdf_fails(self, mock_cascade, mock_oa_url, mock_pdf, mock_html):
        from mlops.pipeline.models import PaperSection
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        mock_oa_url.return_value = {
            "is_oa": True,
            "pdf_url": "https://example.com/paper.pdf",
            "landing_page_url": "https://example.com/paper",
        }
        mock_pdf.return_value = []  # PDF fetch failed
        mock_html.return_value = [PaperSection(name="Full Text", content="html body text")]

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert len(result) == 1
        assert result[0].meta.fulltext_source == "openalex_html"
        assert result[0].sections[0].content == "html body text"
        assert papers[0]["fulltext_ok"] is True
        mock_html.assert_called_once_with("https://example.com/paper")

    @patch("mlops.scripts.ingest_curated_pmids.fetch_html_sections")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_pdf_sections")
    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_oa_html_only_no_pdf_url(self, mock_cascade, mock_oa_url, mock_pdf, mock_html):
        from mlops.pipeline.models import PaperSection
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        mock_oa_url.return_value = {
            "is_oa": True,
            "pdf_url": None,
            "landing_page_url": "https://example.com/paper",
        }
        mock_html.return_value = [PaperSection(name="Full Text", content="html only text")]

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert len(result) == 1
        assert result[0].meta.fulltext_source == "openalex_html"
        mock_pdf.assert_not_called()

    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_no_fulltext_when_openalex_returns_none(self, mock_cascade, mock_oa_url):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        mock_oa_url.return_value = None  # OpenAlex lookup failed

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert result == []
        assert papers[0]["fulltext_ok"] is False
        assert papers[0]["failure_reason"] == "no_fulltext"
        assert papers[0]["indexed"] is False

    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_no_fulltext_when_not_oa(self, mock_cascade, mock_oa_url):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        mock_oa_url.return_value = {
            "is_oa": False,
            "pdf_url": None,
            "landing_page_url": "https://example.com/paper",
        }

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert result == []
        assert papers[0]["failure_reason"] == "no_fulltext"

    @patch("mlops.scripts.ingest_curated_pmids.fetch_pdf_sections")
    @patch("mlops.scripts.ingest_curated_pmids.unpaywall_oa_locations")
    @patch("mlops.scripts.ingest_curated_pmids.openalex_oa_url")
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_unpaywall_fallback_when_openalex_fails(self, mock_cascade, mock_oa_url, mock_unp, mock_pdf):
        from mlops.pipeline.models import PaperSection
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest

        # cascade + OpenAlex both fail
        mock_cascade.return_value = MagicMock(sections=[], fulltext_source=None)
        mock_oa_url.return_value = {"is_oa": False, "pdf_url": None, "landing_page_url": None}
        # Unpaywall returns one mirror with a PDF URL
        mock_unp.return_value = [{"pdf_url": "https://unpaywall.example.com/paper.pdf", "landing_url": None}]
        mock_pdf.return_value = [PaperSection(name="Full Text", content="unpaywall full text content")]

        papers = [self._make_paper()]
        result = build_paperfulls_for_ingest(papers, _FAKE_PMC_CLIENT, _FAKE_EUROPEPMC_CLIENT)

        assert len(result) == 1
        assert result[0].meta.fulltext_source == "unpaywall_pdf"
        assert result[0].sections[0].content == "unpaywall full text content"
        assert papers[0]["fulltext_ok"] is True
        assert papers[0].get("failure_reason") is None
        mock_pdf.assert_called_once_with("https://unpaywall.example.com/paper.pdf")


class TestMainFlow:
    @patch("mlops.scripts.ingest_curated_pmids.ADMIN_API_TOKEN", "test-token")
    @patch("mlops.scripts.ingest_curated_pmids.API_BASE_URL", "http://localhost:8000")
    @patch("mlops.scripts.ingest_curated_pmids.api_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.embed_chunks")
    @patch("mlops.scripts.ingest_curated_pmids.chunk_papers")
    @patch("mlops.scripts.ingest_curated_pmids.build_paperfulls_for_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.resolve_papers")
    @patch("mlops.scripts.ingest_curated_pmids.load_existing_dois")
    @patch("mlops.scripts.ingest_curated_pmids.Manifest")
    def test_main_end_to_end_happy_path(
        self, mock_manifest_cls, mock_existing, mock_resolve, mock_build, mock_chunk, mock_embed, mock_api, tmp_path
    ):
        from mlops.scripts.ingest_curated_pmids import run

        # Setup provenance fixture
        prov = {
            "Q001": {
                "category": "hypertrophy",
                "papers": [
                    {
                        "raw_id": "PMID:12345",
                        "raw_pmid": "12345",
                        "raw_doi": None,
                        "resolved_pmid": None,
                        "resolved_doi": None,
                        "resolved_title": None,
                        "indexed": None,
                        "already_in_corpus": None,
                        "fulltext_ok": None,
                        "failure_reason": None,
                        "is_typo_autofixed": False,
                        "search_categories": ["hypertrophy"],
                    }
                ],
            }
        }
        prov_path = tmp_path / "prov.json"
        prov_path.write_text(json.dumps(prov))

        mock_manifest_cls.load.return_value = MagicMock(papers={})
        mock_existing.return_value = set()

        # resolve_papers: PMID 12345 successfully resolved
        def resolve_side(papers, qid, query_context):
            for p in papers:
                p["resolved_pmid"] = "12345"
                p["resolved_doi"] = "10.1080/test"
                p["resolved_title"] = "T"
                p["metadata"] = {"abstract": "", "pmcid": "", "publication_types": [], "publication_year": 2020}
            return papers

        mock_resolve.side_effect = resolve_side

        from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

        paperfull = PaperFull(
            meta=PaperMeta(
                doi="10.1080/test",
                pmid="12345",
                pmcid="",
                openalex_id="",
                title="T",
                abstract="",
                publication_types=[],
                published_year=2020,
                search_categories=["hypertrophy"],
                evidence_weight=0.5,
                fulltext_source="pmc",
            ),
            sections=[PaperSection(name="M", content="...")],
        )

        def build_side(papers, pmc_client, europepmc_client):
            for p in papers:
                if not p.get("failure_reason") and not p.get("already_in_corpus"):
                    p["fulltext_ok"] = True
            return [paperfull]

        mock_build.side_effect = build_side
        mock_chunk.return_value = ["fake_chunk"]
        mock_embed.return_value = [("fake_chunk", [0.0] * 1024)]
        mock_api.return_value = 1  # 1 upserted

        run(prov_path, dry_run=False, limit=None, lock_path=tmp_path / ".lock")

        # provenance updated to indexed=True for the resolved paper
        updated = json.loads(prov_path.read_text())
        paper = updated["Q001"]["papers"][0]
        assert paper["resolved_pmid"] == "12345"
        assert paper["indexed"] is True
        # api_ingest was called with 1 chunk
        mock_api.assert_called_once()

    @patch("mlops.scripts.ingest_curated_pmids.ADMIN_API_TOKEN", "test-token")
    @patch("mlops.scripts.ingest_curated_pmids.API_BASE_URL", "http://localhost:8000")
    @patch("mlops.scripts.ingest_curated_pmids.api_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.embed_chunks")
    @patch("mlops.scripts.ingest_curated_pmids.chunk_papers")
    @patch("mlops.scripts.ingest_curated_pmids.build_paperfulls_for_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.resolve_papers")
    @patch("mlops.scripts.ingest_curated_pmids.load_existing_dois")
    @patch("mlops.scripts.ingest_curated_pmids.Manifest")
    def test_dry_run_skips_embed_and_api_ingest(
        self, mock_manifest_cls, mock_existing, mock_resolve, mock_build, mock_chunk, mock_embed, mock_api, tmp_path
    ):
        from mlops.scripts.ingest_curated_pmids import run

        prov = {
            "Q001": {
                "category": "x",
                "papers": [
                    {
                        "raw_id": "PMID:12345",
                        "raw_pmid": "12345",
                        "raw_doi": None,
                        "resolved_pmid": None,
                        "resolved_doi": None,
                        "resolved_title": None,
                        "indexed": None,
                        "already_in_corpus": None,
                        "fulltext_ok": None,
                        "failure_reason": None,
                        "is_typo_autofixed": False,
                        "search_categories": ["x"],
                    }
                ],
            }
        }
        prov_path = tmp_path / "prov.json"
        prov_path.write_text(json.dumps(prov))

        mock_manifest_cls.load.return_value = MagicMock(papers={})
        mock_existing.return_value = set()

        def resolve_side(papers, qid, query_context):
            for p in papers:
                p["resolved_pmid"] = "12345"
                p["resolved_doi"] = "10.1080/test"
                p["resolved_title"] = "T"
                p["metadata"] = {"abstract": "", "pmcid": "", "publication_types": [], "published_year": 2020}
            return papers

        mock_resolve.side_effect = resolve_side

        from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

        mock_build.return_value = [
            PaperFull(
                meta=PaperMeta(
                    doi="10.1080/test",
                    pmid="12345",
                    pmcid="",
                    openalex_id="",
                    title="T",
                    abstract="",
                    publication_types=[],
                    published_year=2020,
                    search_categories=["x"],
                    evidence_weight=0.5,
                    fulltext_source="pmc",
                ),
                sections=[PaperSection(name="M", content="...")],
            )
        ]
        mock_chunk.return_value = ["fake_chunk"]

        run(prov_path, dry_run=True, limit=None, lock_path=tmp_path / ".lock")

        mock_chunk.assert_called_once()  # chunking DID happen
        mock_embed.assert_not_called()  # embedding skipped (dry-run)
        mock_api.assert_not_called()  # API call skipped (dry-run)


class TestSaveChunksAndEmbeddings:
    """save_chunks_and_embeddings 단위 테스트."""

    def _make_chunk(self):
        from mlops.pipeline.models import Chunk  # noqa: PLC0415

        return Chunk(
            paper_pmid="12345",
            paper_doi="10.1080/test",
            paper_title="Test Paper",
            section_name="Full Text",
            chunk_index=0,
            content="sample content",
            token_count=10,
            search_categories=["hypertrophy"],
        )

    def test_export_batch_writes_chunks_file(self, tmp_path):
        import gzip  # noqa: PLC0415
        import json  # noqa: PLC0415

        from mlops.scripts.ingest_curated_pmids import save_chunks_and_embeddings  # noqa: PLC0415

        chunk = self._make_chunk()
        save_chunks_and_embeddings([chunk], [(chunk, [0.1] * 10)], batch_tag="test_tag", data_dir=tmp_path)

        chunks_file = tmp_path / "chunks" / "test_tag.jsonl.gz"
        assert chunks_file.exists()
        with gzip.open(chunks_file, "rt", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0]["paper_pmid"] == "12345"

    def test_export_batch_writes_embeddings_file(self, tmp_path):
        import gzip  # noqa: PLC0415
        import json  # noqa: PLC0415

        from mlops.scripts.ingest_curated_pmids import save_chunks_and_embeddings  # noqa: PLC0415

        chunk = self._make_chunk()
        vec = [0.5] * 1024
        save_chunks_and_embeddings(
            [chunk], [(chunk, vec)], batch_tag="test_tag", model_key="bge-large", data_dir=tmp_path
        )

        emb_file = tmp_path / "emb_bge-large" / "test_tag.jsonl.gz"
        assert emb_file.exists()
        with gzip.open(emb_file, "rt", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert "embedding" in lines[0]
        assert lines[0]["embedding"] == vec

    def test_export_batch_appends_on_repeated_calls(self, tmp_path):
        import gzip  # noqa: PLC0415
        import json  # noqa: PLC0415

        from mlops.scripts.ingest_curated_pmids import save_chunks_and_embeddings  # noqa: PLC0415

        chunk = self._make_chunk()
        # Call twice — should accumulate 2 lines
        save_chunks_and_embeddings([chunk], [(chunk, [0.1])], batch_tag="append_tag", data_dir=tmp_path)
        save_chunks_and_embeddings([chunk], [(chunk, [0.2])], batch_tag="append_tag", data_dir=tmp_path)

        chunks_file = tmp_path / "chunks" / "append_tag.jsonl.gz"
        with gzip.open(chunks_file, "rt", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2


class TestExportBatch:
    """--export-batch 모드 통합 테스트 (run() 레벨)."""

    def _make_provenance(self, tmp_path):
        prov = {
            "Q001": {
                "category": "hypertrophy",
                "papers": [
                    {
                        "raw_id": "PMID:12345",
                        "raw_pmid": "12345",
                        "raw_doi": None,
                        "resolved_pmid": None,
                        "resolved_doi": None,
                        "resolved_title": None,
                        "indexed": None,
                        "already_in_corpus": None,
                        "fulltext_ok": None,
                        "failure_reason": None,
                        "is_typo_autofixed": False,
                        "search_categories": ["hypertrophy"],
                    }
                ],
            }
        }
        prov_path = tmp_path / "prov.json"
        prov_path.write_text(json.dumps(prov))
        return prov_path

    @patch("mlops.scripts.ingest_curated_pmids.save_chunks_and_embeddings")
    @patch("mlops.scripts.ingest_curated_pmids.embed_chunks")
    @patch("mlops.scripts.ingest_curated_pmids.chunk_papers")
    @patch("mlops.scripts.ingest_curated_pmids.build_paperfulls_for_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.resolve_papers")
    @patch("mlops.scripts.ingest_curated_pmids.load_existing_dois")
    @patch("mlops.scripts.ingest_curated_pmids.Manifest")
    def test_export_batch_skips_api_ingest(
        self, mock_manifest_cls, mock_existing, mock_resolve, mock_build, mock_chunk, mock_embed, mock_save, tmp_path
    ):
        from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection
        from mlops.scripts.ingest_curated_pmids import run

        prov_path = self._make_provenance(tmp_path)
        mock_manifest_cls.load.return_value = MagicMock(papers={})
        mock_existing.return_value = set()

        def resolve_side(papers, qid, query_context):
            for p in papers:
                p["resolved_pmid"] = "12345"
                p["resolved_doi"] = "10.1080/test"
                p["resolved_title"] = "T"
                p["metadata"] = {"abstract": "", "pmcid": "", "publication_types": [], "publication_year": 2020}
            return papers

        mock_resolve.side_effect = resolve_side

        paperfull = PaperFull(
            meta=PaperMeta(
                doi="10.1080/test",
                pmid="12345",
                pmcid="",
                openalex_id="",
                title="T",
                abstract="",
                publication_types=[],
                published_year=2020,
                search_categories=["hypertrophy"],
                evidence_weight=0.5,
                fulltext_source="pmc",
            ),
            sections=[PaperSection(name="M", content="...")],
        )

        def build_side(papers, pmc_client, europepmc_client):
            for p in papers:
                if not p.get("failure_reason") and not p.get("already_in_corpus"):
                    p["fulltext_ok"] = True
            return [paperfull]

        mock_build.side_effect = build_side
        mock_chunk.return_value = ["fake_chunk"]
        mock_embed.return_value = [("fake_chunk", [0.0] * 1024)]

        with patch("mlops.scripts.ingest_curated_pmids.api_ingest") as mock_api:
            run(
                prov_path,
                dry_run=False,
                limit=None,
                lock_path=tmp_path / ".lock",
                export_batch="test_export_tag",
                embed_model="bge-large",
            )
            mock_api.assert_not_called()

        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs.kwargs.get("batch_tag") == "test_export_tag" or call_kwargs.args[2] == "test_export_tag"

    @patch("mlops.scripts.ingest_curated_pmids.embed_chunks")
    @patch("mlops.scripts.ingest_curated_pmids.chunk_papers")
    @patch("mlops.scripts.ingest_curated_pmids.build_paperfulls_for_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.resolve_papers")
    @patch("mlops.scripts.ingest_curated_pmids.load_existing_dois")
    @patch("mlops.scripts.ingest_curated_pmids.Manifest")
    def test_export_batch_no_credentials_required(
        self, mock_manifest_cls, mock_existing, mock_resolve, mock_build, mock_chunk, mock_embed, tmp_path
    ):
        """export-batch 모드는 API_BASE_URL/ADMIN_API_TOKEN 없어도 정상 동작."""
        from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection
        from mlops.scripts.ingest_curated_pmids import run

        prov_path = self._make_provenance(tmp_path)
        mock_manifest_cls.load.return_value = MagicMock(papers={})
        mock_existing.return_value = set()

        def resolve_side(papers, qid, query_context):
            for p in papers:
                p["resolved_pmid"] = "12345"
                p["resolved_doi"] = "10.1080/test"
                p["resolved_title"] = "T"
                p["metadata"] = {"abstract": "", "pmcid": "", "publication_types": [], "publication_year": 2020}
            return papers

        mock_resolve.side_effect = resolve_side

        paperfull = PaperFull(
            meta=PaperMeta(
                doi="10.1080/test",
                pmid="12345",
                pmcid="",
                openalex_id="",
                title="T",
                abstract="",
                publication_types=[],
                published_year=2020,
                search_categories=["hypertrophy"],
                evidence_weight=0.5,
                fulltext_source="pmc",
            ),
            sections=[PaperSection(name="M", content="...")],
        )

        def build_side(papers, pmc_client, europepmc_client):
            for p in papers:
                if not p.get("failure_reason") and not p.get("already_in_corpus"):
                    p["fulltext_ok"] = True
            return [paperfull]

        mock_build.side_effect = build_side
        mock_chunk.return_value = ["fake_chunk"]
        mock_embed.return_value = [("fake_chunk", [0.0] * 1024)]

        with (
            patch("mlops.scripts.ingest_curated_pmids.API_BASE_URL", ""),
            patch("mlops.scripts.ingest_curated_pmids.ADMIN_API_TOKEN", ""),
            patch("mlops.scripts.ingest_curated_pmids.save_chunks_and_embeddings") as mock_save,
        ):
            # Should NOT sys.exit(1) even with no credentials
            run(
                prov_path,
                dry_run=False,
                limit=None,
                lock_path=tmp_path / ".lock",
                export_batch="nocred_tag",
            )

        mock_save.assert_called_once()
