"""ingest_curated_pmids 단위 테스트."""
import fcntl
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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
        with acquire_lock(lock_path):
            # 이미 잡힌 락은 두 번째 호출에서 BlockingIOError
            with pytest.raises(BlockingIOError):
                with acquire_lock(lock_path):
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
        mock_resp = MagicMock(status_code=200, text=SAMPLE_EFETCH_XML)
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
        from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch
        import requests as _r
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
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["hypertrophy"]}]
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
            "12345": {"doi": "", "pmcid": "", "title": "T", "abstract": "",
                      "publication_types": [], "publication_year": 2020}
        }
        mock_conv.return_value = "10.1080/converted"
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_doi"] == "10.1080/converted"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    @patch("mlops.scripts.ingest_curated_pmids.ncbi_pmid_to_doi")
    def test_branch_a_both_fail(self, mock_conv, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_efetch.return_value = {"12345": {"doi": "", "pmcid": "", "title": "T", "abstract": "",
                                              "publication_types": [], "publication_year": 2020}}
        mock_conv.return_value = ""
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "doi_resolution_failed"
        assert resolved[0]["indexed"] is False

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_efetch_not_found(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        # PMID 12345 was requested but not in efetch response
        mock_efetch.return_value = {}
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        # Patch single re-fetch to also miss
        with patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch", return_value={}):
            resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "efetch_not_found"

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
        papers = [{"raw_id": "DOI:10.1080/test", "raw_pmid": None, "raw_doi": "10.1080/test",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_pmid"] == "99999"
        assert resolved[0]["resolved_doi"] == "10.1080/test"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_doi_only_no_pmid(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_lookup.return_value = {"doi": "10.1080/x", "pmid": "", "title": "T",
                                     "publication_year": None, "type": ""}
        papers = [{"raw_id": "DOI:10.1080/x", "raw_pmid": None, "raw_doi": "10.1080/x",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "no_pmid_from_openalex"

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_openalex_not_found(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_lookup.return_value = None
        papers = [{"raw_id": "DOI:10.1080/x", "raw_pmid": None, "raw_doi": "10.1080/x",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "openalex_not_found"

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_title_mismatch_skip(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_efetch.return_value = {
            "12345": {"doi": "10.1080/test", "pmcid": "", "title": "Robotic Cardiology Cybernetics",
                      "abstract": "", "publication_types": [], "publication_year": 2020}
        }
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": True, "fulltext_ok": None,  # ← typo flag
                   "search_categories": ["hypertrophy"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="hypertrophy weekly set volume")
        assert resolved[0]["failure_reason"] == "title_mismatch"
