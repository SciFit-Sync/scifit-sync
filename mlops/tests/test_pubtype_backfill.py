"""OpenAlex-only 논문 publication_types PubMed 보강 (Fix A) 테스트.

배경 (dry_15_v2 validate FAIL root cause):
  OpenAlex API는 publication_types를 거의 비워서 반환한다. crawl_papers의
  _merge_by_doi는 동일 DOI에 대해서만 PubMed publication_types로 보강하므로,
  PubMed 카테고리 검색에 걸리지 않은 OpenAlex-only 논문은 publication_types=[]로
  남아 evidence_weight=0.5 fallback에 갇힌다 (validate publication_types 18.5%).

Fix A: dedup 이후 잔여 OpenAlex-only 논문에 대해
  DOI → PMID(esearch [AID]) → efetch(publication_types) → DOI 매칭 보강.

NCBI 호출은 mock 처리 (단위). live [AID] 필드 동작은 integration 마커로 별도 검증.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from mlops.pipeline.crawler import (
    _resolve_dois_to_pmids,
    backfill_publication_types_from_pubmed,
)
from mlops.pipeline.models import PaperMeta


def _meta(doi: str = "", publication_types: list[str] | None = None, pmid: str = "") -> PaperMeta:
    return PaperMeta(
        pmid=pmid,
        title="t",
        doi=doi,
        publication_types=publication_types or [],
    )


# ──────────────────────────────────────────────────────────────────────────────
# _resolve_dois_to_pmids — DOI → PMID (PubMed esearch [AID])
# ──────────────────────────────────────────────────────────────────────────────


class TestResolveDoisToPmids:
    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_queries_aid_field_and_returns_idlist(self, mock_request):
        """DOI를 [AID] 필드 OR 쿼리로 묶어 esearch 후 idlist를 반환해야 한다."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": ["111", "222"]}}
        mock_request.return_value = mock_resp

        result = _resolve_dois_to_pmids(["10.1000/aaa", "10.1000/bbb"])

        assert result == ["111", "222"]
        params = mock_request.call_args.args[1]
        assert params["db"] == "pubmed"
        assert '"10.1000/aaa"[AID]' in params["term"]
        assert '"10.1000/bbb"[AID]' in params["term"]

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_empty_input_makes_no_request(self, mock_request):
        """빈 DOI 목록이면 NCBI 호출을 하지 않고 빈 리스트를 반환한다."""
        result = _resolve_dois_to_pmids([])

        assert result == []
        mock_request.assert_not_called()

    @patch("mlops.pipeline.crawler._request_with_rate_limit")
    def test_batches_large_doi_list(self, mock_request):
        """배치 크기를 초과하는 DOI 목록은 여러 번 나눠 호출한다."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"esearchresult": {"idlist": []}}
        mock_request.return_value = mock_resp

        from mlops.pipeline.crawler import DOI_PMID_BATCH_SIZE

        dois = [f"10.1/{i}" for i in range(DOI_PMID_BATCH_SIZE + 1)]
        _resolve_dois_to_pmids(dois)

        assert mock_request.call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# backfill_publication_types_from_pubmed — 보강 오케스트레이션
# ──────────────────────────────────────────────────────────────────────────────


class TestBackfillPublicationTypes:
    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_only_targets_empty_pubtype_with_doi(self, mock_resolve, mock_fetch):
        """publication_types가 비어 있고 DOI가 있는 메타만 조회 대상이다."""
        mock_resolve.return_value = []
        mock_fetch.return_value = []

        metas = [
            _meta(doi="10.1/target"),  # 대상: 빈 PT + DOI
            _meta(doi="10.2/has", publication_types=["Meta-Analysis"]),  # 제외: 이미 PT 있음
            _meta(doi="", publication_types=[]),  # 제외: DOI 없음
        ]
        backfill_publication_types_from_pubmed(metas)

        mock_resolve.assert_called_once_with(["10.1/target"])

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_fills_types_and_recomputes_evidence_weight(self, mock_resolve, mock_fetch):
        """DOI 매칭 시 publication_types 보강 + evidence_weight 재계산."""
        mock_resolve.return_value = ["111"]
        mock_fetch.return_value = [
            _meta(doi="10.1/target", publication_types=["Randomized Controlled Trial"], pmid="111"),
        ]

        target = _meta(doi="10.1/target")
        assert target.evidence_weight == 0.50  # 보강 전 fallback

        n = backfill_publication_types_from_pubmed([target])

        assert n == 1
        assert target.publication_types == ["Randomized Controlled Trial"]
        assert target.evidence_weight == 0.90  # RCT weight

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_leaves_unmatched_paper_empty(self, mock_resolve, mock_fetch):
        """DOI가 efetch 결과와 매칭되지 않으면 publication_types는 [] 그대로 유지."""
        mock_resolve.return_value = ["999"]
        mock_fetch.return_value = [
            _meta(doi="10.9/other", publication_types=["Review"], pmid="999"),
        ]

        target = _meta(doi="10.1/target")
        n = backfill_publication_types_from_pubmed([target])

        assert n == 0
        assert target.publication_types == []
        assert target.evidence_weight == 0.50

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_no_targets_skips_all_api(self, mock_resolve, mock_fetch):
        """보강 대상이 없으면 esearch/efetch 모두 호출하지 않는다."""
        metas = [_meta(doi="10.1/a", publication_types=["Review"])]
        n = backfill_publication_types_from_pubmed(metas)

        assert n == 0
        mock_resolve.assert_not_called()
        mock_fetch.assert_not_called()

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_no_pmids_resolved_skips_efetch(self, mock_resolve, mock_fetch):
        """DOI→PMID 역조회가 0건이면 efetch를 호출하지 않는다."""
        mock_resolve.return_value = []

        target = _meta(doi="10.1/target")
        n = backfill_publication_types_from_pubmed([target])

        assert n == 0
        mock_fetch.assert_not_called()
        assert target.publication_types == []

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_matches_doi_case_insensitively(self, mock_resolve, mock_fetch):
        """OpenAlex(소문자)와 PubMed(원문 대소문자) DOI 표기가 달라도 매칭돼야 한다.

        OpenAlex는 prefix만 제거(소문자화 안 함), PubMed efetch는 게재 원문
        대소문자 그대로 반환 → 정확 문자열 비교는 보강을 놓친다. DOI 규격상
        대소문자는 비구분이므로 lower 정규화로 매칭한다.
        """
        mock_resolve.return_value = ["111"]
        mock_fetch.return_value = [
            _meta(doi="10.1/mss.123", publication_types=["Meta-Analysis"], pmid="111"),
        ]

        target = _meta(doi="10.1/MSS.123")  # 대문자 표기 (PubMed efetch와 표기차)
        n = backfill_publication_types_from_pubmed([target])

        assert n == 1
        assert target.publication_types == ["Meta-Analysis"]
        assert target.evidence_weight == 1.00  # Meta-Analysis weight

    @patch("mlops.pipeline.crawler.fetch_paper_metadata")
    @patch("mlops.pipeline.crawler._resolve_dois_to_pmids")
    def test_warns_when_resolution_yields_nothing(self, mock_resolve, mock_fetch, caplog):
        """보강 대상이 있는데 DOI→PMID가 0건이면 운영자에게 WARNING으로 알린다.

        1.5h 파이프라인에서 backfill이 조용히 0건이면 끝에서야 validate FAIL로
        드러난다 — 중간 신호가 필요.
        """
        mock_resolve.return_value = []

        target = _meta(doi="10.1/target")
        with caplog.at_level(logging.WARNING, logger="mlops.pipeline.crawler"):
            backfill_publication_types_from_pubmed([target])

        assert "보강" in caplog.text


# ──────────────────────────────────────────────────────────────────────────────
# crawl_papers wiring — dedup 이후 OpenAlex-only 메타가 보강 함수로 전달되는지
# ──────────────────────────────────────────────────────────────────────────────


class TestCrawlPapersWiring:
    def test_crawl_papers_invokes_backfill_on_deduped_metas(self, monkeypatch):
        """crawl_papers는 dedup된 메타(OpenAlex-only 포함)를 보강 함수에 넘겨야 한다."""
        import mlops.pipeline.crawler as crawler_mod

        oa_only = PaperMeta(pmid="", title="oa-only", doi="10.1/oaonly")  # 빈 publication_types
        monkeypatch.setattr(crawler_mod, "search_openalex_by_category", lambda name, max_results: [oa_only])
        monkeypatch.setattr(crawler_mod, "search_pmids", lambda *a, **k: [])  # PubMed 무매칭
        monkeypatch.setattr(crawler_mod, "fetch_paper_metadata", lambda pmids: [])

        seen: dict[str, list[str]] = {}

        def spy_backfill(metas):
            seen["dois"] = [m.doi for m in metas]
            return 0

        monkeypatch.setattr(crawler_mod, "backfill_publication_types_from_pubmed", spy_backfill)

        crawler_mod.crawl_papers(
            queries=[("strength", "strength training", True)],
            max_per_category=5,
            fetch_fulltext=False,
        )

        assert seen.get("dois") == ["10.1/oaonly"]


# ──────────────────────────────────────────────────────────────────────────────
# Integration (live NCBI) — [AID] 필드가 실제로 DOI를 PMID로 역조회하는지
# mock으로는 못 잡는 field/schema drift 감지용. CI 제외(integration 마커).
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_resolve_dois_to_pmids_live_roundtrip():
    """알려진 PMID의 DOI를 [AID]로 역조회하면 같은 PMID가 나와야 한다.

    PMID 27433992 (Schoenfeld 2017 meta-analysis) → efetch로 DOI 확보 →
    그 DOI를 _resolve_dois_to_pmids로 역조회 → 원 PMID 포함 확인.
    """
    from mlops.pipeline.crawler import fetch_paper_metadata

    known_pmid = "27433992"
    metas = fetch_paper_metadata([known_pmid])
    assert metas and metas[0].doi, "기준 PMID efetch 실패 또는 DOI 없음 (NCBI 장애 가능성)"

    doi = metas[0].doi
    pmids = _resolve_dois_to_pmids([doi])

    assert known_pmid in pmids, f"DOI {doi!r} → PMID 역조회 실패 ([AID] 필드 미동작?): got {pmids!r}"
