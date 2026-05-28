"""efetch_pubmed_batch / crawler.fetch_paper_metadata publication_types 추출 회귀 테스트.

문제: 5/22·5/26 export에서 publication_types 0% 추출.
      - scripts 경로(efetch_pubmed_batch)는 정상
      - crawler 경로(_parse_pubmed_article)는 PublicationTypeList 파싱 누락 (Scenario B)

검증:
  A) efetch_pubmed_batch — 알려진 PMID 3개(Meta-Analysis/RCT/Review)에 대해 정확한 type 반환
  B) crawler.fetch_paper_metadata — 동일 PMID에 대해 PaperMeta.publication_types 채워지는지
     (A4 픽스 전: FAIL / A4 픽스 후: PASS)
"""

from __future__ import annotations

import pytest

# 알려진 PMID — efetch 실호출로 타입 확정된 논문 3건
# 아래 PMID는 실제 NCBI efetch 응답에서 확인된 값 (2026-05-28)
KNOWN_PMIDS: dict[str, str] = {
    "27433992": "Meta-Analysis",  # Schoenfeld 2017 — weekly training volume meta-analysis
    "40366729": "Randomized Controlled Trial",  # 2025 RCT — range of motion training
    "20847704": "Review",  # Schoenfeld 2010 — mechanisms of muscle hypertrophy review
}


# ──────────────────────────────────────────────────────────────────────────────
# A) scripts 경로: efetch_pubmed_batch (이미 정상 — PASS 기대)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("pmid,expected_type", KNOWN_PMIDS.items())
def test_efetch_extracts_publication_types(pmid: str, expected_type: str) -> None:
    """알려진 PMID에 대해 efetch_pubmed_batch가 publication_types를 정확히 파싱해야 한다.

    scripts/ 경로는 PublicationTypeList 파싱이 구현돼 있으므로 PASS 기대.
    이 테스트가 실패하면 NCBI 서비스 장애 또는 반환 키 변경을 의심.
    """
    from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch

    result = efetch_pubmed_batch([pmid])

    assert pmid in result, f"efetch가 {pmid}를 반환하지 않음 (NCBI 장애 가능성)"
    pub_types = result[pmid].get("publication_types", [])
    assert pub_types, f"{pmid}: publication_types 비어있음 (S5 회귀 — scripts 경로 깨짐)"
    assert expected_type in pub_types, f"{pmid}: expected {expected_type!r} not in {pub_types!r}"


# ──────────────────────────────────────────────────────────────────────────────
# B) crawler 경로: fetch_paper_metadata (Scenario B — A4 픽스 후 PASS 예정)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.parametrize("pmid,expected_type", KNOWN_PMIDS.items())
def test_crawler_fetch_paper_metadata_extracts_publication_types(pmid: str, expected_type: str) -> None:
    """crawler.fetch_paper_metadata도 publication_types를 채워야 한다.

    A1 조사에서 _parse_pubmed_article이 PublicationTypeList를 파싱하지 않음을 확인.
    A4 픽스 후 xfail 마커 제거 시 이 테스트가 회귀 잠금 역할을 한다.
    """
    from mlops.pipeline.crawler import fetch_paper_metadata

    metas = fetch_paper_metadata([pmid])

    assert metas, f"crawler가 {pmid}를 반환하지 않음 (NCBI 장애 가능성)"
    meta = metas[0]
    assert meta.publication_types, f"{pmid}: crawler PaperMeta.publication_types 비어있음 (Scenario B)"
    assert expected_type in meta.publication_types, (
        f"{pmid}: expected {expected_type!r} not in {meta.publication_types!r}"
    )
