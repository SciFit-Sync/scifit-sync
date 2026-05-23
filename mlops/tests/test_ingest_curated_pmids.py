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
