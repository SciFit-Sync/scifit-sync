"""ChromaDB의 search_categories 메타를 현재 SEARCH_QUERY_CATEGORIES 기준으로 재계산.

카테고리 추가/삭제/어휘 변경이 있을 때 RAG 검색 가중치를 동기화하기 위해 사용한다.
임베딩/문서는 건드리지 않으므로 빠르고 안전하다 (esearch + 메타 update만).

운영 흐름:
  1. crawler.py의 SEARCH_QUERY_CATEGORIES를 변경 후
  2. 이 스크립트 실행 (CI 또는 수동)
  3. ChromaDB의 모든 청크 메타가 새 카테고리 셋으로 갱신됨

사용법:
    # 환경변수 필요: API_BASE_URL, ADMIN_API_TOKEN
    python -m mlops.scripts.refresh_search_categories
    python -m mlops.scripts.refresh_search_categories --dry-run
    python -m mlops.scripts.refresh_search_categories --max-per-category 5000
    python -m mlops.scripts.refresh_search_categories --clear-unmatched
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

import requests
from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL
from mlops.pipeline.crawler import (
    SEARCH_QUERY_CATEGORIES,
    filter_for_level,
    search_pmids,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


# NCBI esearch retmax 한도. PubMed 공식 문서:
# https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ESearch — `retmax`는 9,999가 상한.
# 단일 카테고리가 이를 초과하는 hit을 가질 가능성은 매우 낮지만(어휘 광범위 시),
# 그 경우 페이지네이션이 필요하다 (현재는 단순 cap).
ESEARCH_RETMAX_HARD_LIMIT = 9999


def _check_env() -> None:
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.error("API_BASE_URL 또는 ADMIN_API_TOKEN 환경변수가 설정되지 않았습니다")
        sys.exit(1)


def fetch_existing_pmids() -> set[str]:
    """ChromaDB에 적재된 모든 unique PMID를 admin API로 조회한다."""
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/pmids"
    resp = requests.get(url, headers={"X-Admin-Token": ADMIN_API_TOKEN}, timeout=120)
    resp.raise_for_status()
    data = resp.json()["data"]
    logger.info(
        "ChromaDB 현황: PMID %d개, 청크 %d개",
        data["count"],
        data.get("total_chunks", -1),
    )
    return set(data["pmids"])


def build_pmid_to_categories(
    queries: list[tuple[str, str, str]],
    max_per_category: int,
) -> dict[str, set[str]]:
    """카테고리 쿼리를 모두 esearch 재실행해 PMID → 매칭 카테고리 set 매핑 빌드."""
    pmid_to_cats: dict[str, set[str]] = defaultdict(set)
    for i, (name, query, level) in enumerate(queries, 1):
        full_query = query + filter_for_level(level)
        try:
            pmids = search_pmids(full_query, max_results=max_per_category)
        except Exception as e:
            logger.warning("카테고리 '%s' esearch 실패: %s (스킵)", name, e)
            continue
        for pmid in pmids:
            pmid_to_cats[pmid].add(name)
        logger.info("[%3d/%d] %-30s %d hits", i, len(queries), name, len(pmids))
    return pmid_to_cats


def post_refresh(mapping: dict[str, list[str]]) -> dict:
    """admin API에 PMID → 카테고리 매핑 전송."""
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/refresh-categories"
    resp = requests.post(
        url,
        json={"mapping": mapping},
        headers={"X-Admin-Token": ADMIN_API_TOKEN},
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def main(*, max_per_category: int, dry_run: bool, clear_unmatched: bool) -> int:
    _check_env()
    if max_per_category > ESEARCH_RETMAX_HARD_LIMIT:
        logger.warning(
            "max_per_category=%d → NCBI esearch retmax 한도 %d로 clamp",
            max_per_category,
            ESEARCH_RETMAX_HARD_LIMIT,
        )
        max_per_category = ESEARCH_RETMAX_HARD_LIMIT

    logger.info(
        "=== search_categories 메타 동기화 시작 (카테고리 %d개, max_per_category=%d, "
        "clear_unmatched=%s, dry_run=%s) ===",
        len(SEARCH_QUERY_CATEGORIES),
        max_per_category,
        clear_unmatched,
        dry_run,
    )

    existing = fetch_existing_pmids()
    if not existing:
        logger.info("ChromaDB가 비어있음. 종료.")
        return 0

    pmid_to_cats = build_pmid_to_categories(SEARCH_QUERY_CATEGORIES, max_per_category)
    if not pmid_to_cats:
        logger.warning("어떤 카테고리도 PMID를 반환하지 않음. 종료.")
        return 1

    avg_cats = sum(len(v) for v in pmid_to_cats.values()) / len(pmid_to_cats)
    logger.info(
        "esearch 결과: 전체 PMID %d개, 평균 %.2f 카테고리/논문",
        len(pmid_to_cats),
        avg_cats,
    )

    relevant = {pmid: sorted(cats) for pmid, cats in pmid_to_cats.items() if pmid in existing}
    logger.info("ChromaDB와 매칭된 PMID: %d / %d", len(relevant), len(existing))

    unmatched_in_db = sorted(existing - set(pmid_to_cats.keys()))
    if unmatched_in_db:
        if clear_unmatched:
            # 빈 list로 mapping에 포함시켜 backend가 메타를 빈 string으로 덮도록 한다.
            # (deprecated 카테고리 메타가 RAG 검색에 잔존하는 것을 방지)
            for pmid in unmatched_in_db:
                relevant[pmid] = []
            logger.info(
                "unmatched PMID %d개를 빈 카테고리로 clear (--clear-unmatched 적용)",
                len(unmatched_in_db),
            )
        else:
            logger.info(
                "주의: ChromaDB에 있지만 어떤 카테고리에도 매칭되지 않은 PMID %d개 — "
                "옛 카테고리 메타 그대로 유지됨. 모두 비우려면 --clear-unmatched 사용",
                len(unmatched_in_db),
            )

    if dry_run:
        logger.info("[DRY RUN] API 호출 생략. 샘플 (상위 5건):")
        for pmid, cats in list(relevant.items())[:5]:
            logger.info("  PMID=%s -> %s", pmid, cats)
        return 0

    result = post_refresh(relevant)
    logger.info(
        "=== 동기화 완료: %d청크 갱신 (전체 %d청크, %d PMID 매핑) ===",
        result["updated_chunks"],
        result["total_chunks"],
        result["total_pmids_in_mapping"],
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChromaDB search_categories 메타 동기화")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 매핑만 계산")
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=2000,
        help="카테고리당 esearch retmax (기본 2000, 최대 9999). 큰 카테고리의 깊이를 결정",
    )
    parser.add_argument(
        "--clear-unmatched",
        action="store_true",
        help="ChromaDB에 있지만 현재 카테고리 매핑에 없는 PMID의 search_categories를 빈 값으로 clear "
        "(deprecated 카테고리 메타 잔존 방지). 미지정 시 옛 메타 유지.",
    )
    args = parser.parse_args()
    sys.exit(
        main(
            max_per_category=args.max_per_category,
            dry_run=args.dry_run,
            clear_unmatched=args.clear_unmatched,
        )
    )
