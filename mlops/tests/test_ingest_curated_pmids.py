"""ingest_curated_pmids 단위 테스트."""

import json
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
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest
        from mlops.pipeline.models import PaperSection

        mock_fetch.return_value = MagicMock(sections=[PaperSection(name="Methods", content="...")], fulltext_source="pmc")
        papers = [{
            "resolved_pmid": "12345",
            "resolved_doi": "10.1080/test",
            "resolved_title": "T",
            "metadata": {"abstract": "abs", "pmcid": "PMC1", "publication_types": ["RCT"],
                          "publication_year": 2020},
            "search_categories": ["hypertrophy"],
            "indexed": None, "already_in_corpus": False, "fulltext_ok": None,
            "failure_reason": None,
        }]
        result = build_paperfulls_for_ingest(papers)

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
        papers = [{
            "resolved_pmid": "12345", "resolved_doi": "10.1080/test", "resolved_title": "T",
            "metadata": {"abstract": "", "pmcid": "", "publication_types": [],
                          "publication_year": 2020},
            "search_categories": ["x"],
            "indexed": None, "already_in_corpus": False, "fulltext_ok": None,
            "failure_reason": None,
        }]
        result = build_paperfulls_for_ingest(papers)
        # paper는 result에서 빠짐 (sections=[])
        assert len(result) == 0
        # invariant: failure_reason과 indexed=False 동시 기록
        assert papers[0]["fulltext_ok"] is False
        assert papers[0]["failure_reason"] == "no_fulltext"
        assert papers[0]["indexed"] is False

    def test_skips_failed_and_already_in_corpus_papers(self):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest
        papers = [
            {"resolved_pmid": "1", "indexed": True, "already_in_corpus": True,
             "failure_reason": None, "fulltext_ok": None},
            {"resolved_pmid": "2", "indexed": False, "already_in_corpus": False,
             "failure_reason": "doi_resolution_failed", "fulltext_ok": None},
        ]
        result = build_paperfulls_for_ingest(papers)
        assert result == []
