"""최초 전체 논문 적재 스크립트 (일회성).

사용법:
    python mlops/scripts/initial_ingest.py [--dry-run] [--max-papers 100]
                                           [--http-retries N] [--fulltext-attempts N]

retry 관련 옵션은 환경변수로도 조정 가능 (CLI 인자가 우선):
    NCBI_HTTP_MAX_RETRIES      HTTP layer transient 에러 재시도 횟수 (기본: 5)
    NCBI_HTTP_MAX_BACKOFF      HTTP backoff 상한 초 (기본: 10.0)
    NCBI_HTTP_TIMEOUT          HTTP read timeout 초 (기본: 60)
    PMC_FULLTEXT_MAX_ATTEMPTS  fulltext parse 실패 시 함수 layer 재시도 횟수 (기본: 3)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_SOURCES: set[str] = {"pmc", "europepmc"}  # Phase 1
CHECKPOINT_INTERVAL = 100


def _apply_retry_overrides(http_retries: int | None, fulltext_attempts: int | None) -> None:
    """CLI 인자를 환경변수로 주입. config.py가 import 시점에 읽으므로 main() 진입 전에 호출."""
    if http_retries is not None:
        os.environ["NCBI_HTTP_MAX_RETRIES"] = str(http_retries)
    if fulltext_attempts is not None:
        os.environ["PMC_FULLTEXT_MAX_ATTEMPTS"] = str(fulltext_attempts)


def _build_payload(chunk_vectors: list[tuple]) -> dict:
    """확장된 ingest payload — Task 11 §11-3 schema."""
    return {
        "chunks": [
            {
                "paper_doi": chunk.paper_doi,
                "paper_pmid": chunk.paper_pmid or "",
                "paper_title": chunk.paper_title,
                "section_name": chunk.section_name,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "embedding": vec,
                "search_categories": chunk.search_categories,
                "publication_types": chunk.publication_types,
                "evidence_weight": chunk.evidence_weight,
                "fulltext_source": chunk.fulltext_source or "",
                "published_year": chunk.published_year or 0,
            }
            for chunk, vec in chunk_vectors
        ]
    }


def api_ingest(chunk_vectors: list[tuple]) -> int:
    """청크+임베딩을 백엔드 admin API로 적재한다."""
    from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL

    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.error("API_BASE_URL 또는 ADMIN_API_TOKEN 환경변수가 설정되지 않았습니다")
        sys.exit(1)

    payload = _build_payload(chunk_vectors)
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"
    resp = requests.post(
        url,
        json=payload,
        headers={"X-Admin-Token": ADMIN_API_TOKEN},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["data"]["upserted"]


def main(
    max_papers: int | None = None,
    max_per_category: int | None = None,
    dry_run: bool = False,
) -> None:
    """retry 환경변수 override는 이 함수 호출 전에 적용되어야 한다."""
    from mlops.pipeline.chunker import chunk_papers
    from mlops.pipeline.config import (
        MANIFEST_PATH,
        MAX_PAPERS_PER_CATEGORY,
        MAX_PAPERS_PER_RUN,
        NCBI_HTTP_MAX_RETRIES,
        PMC_FULLTEXT_MAX_ATTEMPTS,
    )
    from mlops.pipeline.crawler import crawl_papers
    from mlops.pipeline.embedder import embed_chunks
    from mlops.pipeline.manifest import Manifest

    if max_papers is None:
        max_papers = MAX_PAPERS_PER_RUN
    if max_per_category is None:
        max_per_category = MAX_PAPERS_PER_CATEGORY

    logger.info(
        "=== 초기 적재 시작 (max_papers=%d, max_per_category=%d, dry_run=%s,"
        " http_retries=%d, fulltext_attempts=%d) ===",
        max_papers,
        max_per_category,
        dry_run,
        NCBI_HTTP_MAX_RETRIES,
        PMC_FULLTEXT_MAX_ATTEMPTS,
    )

    manifest = Manifest.load(MANIFEST_PATH)

    # 이미 indexed된 DOI + 모든 active source를 시도한 fail DOI는 skip
    existing_dois: set[str] = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            existing_dois.add(doi)
    logger.info("이미 처리된 DOI: %d개 (indexed + fully-tried failures)", len(existing_dois))

    papers = crawl_papers(
        max_total=max_papers,
        max_per_category=max_per_category,
        existing_dois=existing_dois,
    )
    if not papers:
        logger.info("신규 논문 없음. 종료.")
        return

    # 본문 있는 paper만 청킹/적재 대상
    indexed_papers = [p for p in papers if p.sections]
    logger.info("크롤링: 시도 %d, 본문 확보 %d", len(papers), len(indexed_papers))

    chunks = chunk_papers(indexed_papers) if indexed_papers else []
    logger.info("청크 %d개", len(chunks))

    if dry_run:
        logger.info("[DRY RUN] 임베딩/적재 생략")
        for p in papers:
            manifest.record_attempt(
                doi=p.meta.doi,
                pmid=p.meta.pmid or None,
                pmcid=p.meta.pmcid,
                openalex_id=p.meta.openalex_id,
                fulltext_source=p.meta.fulltext_source,
                tried_sources=list(ACTIVE_SOURCES),
            )
        manifest.save(MANIFEST_PATH)
        return

    if chunks:
        chunk_vectors = embed_chunks(chunks)
        count = api_ingest(chunk_vectors)
        logger.info("적재 완료: %d 청크 → %d upsert", len(chunks), count)

    # manifest 기록 (100편 체크포인트)
    for i, p in enumerate(papers, start=1):
        manifest.record_attempt(
            doi=p.meta.doi,
            pmid=p.meta.pmid or None,
            pmcid=p.meta.pmcid,
            openalex_id=p.meta.openalex_id,
            fulltext_source=p.meta.fulltext_source,
            tried_sources=list(ACTIVE_SOURCES),
        )
        if i % CHECKPOINT_INTERVAL == 0:
            manifest.save(MANIFEST_PATH)
            logger.info("체크포인트: %d/%d → manifest flush", i, len(papers))

    manifest.save(MANIFEST_PATH)
    logger.info(
        "=== 초기 적재 완료: %d편 → %d청크 ===",
        len(papers),
        len(chunks),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SciFit-Sync 초기 논문 적재")
    parser.add_argument("--max-papers", type=int, default=None, help="크롤링 상한 (기본: MAX_PAPERS_PER_RUN)")
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        help="카테고리당 esearch 후보 풀 cap (기본: MAX_PAPERS_PER_CATEGORY=20).",
    )
    parser.add_argument("--dry-run", action="store_true", help="크롤링+청킹만 실행, 임베딩/적재 생략 (manifest는 기록)")
    parser.add_argument(
        "--http-retries",
        type=int,
        default=None,
        help="NCBI HTTP layer transient 에러 재시도 횟수 (기본: 5, env: NCBI_HTTP_MAX_RETRIES)",
    )
    parser.add_argument(
        "--fulltext-attempts",
        type=int,
        default=None,
        help="PMC fulltext 함수 layer parse 실패 재시도 횟수 (기본: 3, env: PMC_FULLTEXT_MAX_ATTEMPTS)",
    )
    args = parser.parse_args()

    _apply_retry_overrides(args.http_retries, args.fulltext_attempts)
    main(
        max_papers=args.max_papers,
        max_per_category=args.max_per_category,
        dry_run=args.dry_run,
    )
