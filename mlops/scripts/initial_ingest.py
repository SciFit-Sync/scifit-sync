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

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _apply_retry_overrides(http_retries: int | None, fulltext_attempts: int | None) -> None:
    """CLI 인자를 환경변수로 주입. config.py가 import 시점에 읽으므로 main() 진입 전에 호출."""
    if http_retries is not None:
        os.environ["NCBI_HTTP_MAX_RETRIES"] = str(http_retries)
    if fulltext_attempts is not None:
        os.environ["PMC_FULLTEXT_MAX_ATTEMPTS"] = str(fulltext_attempts)


def load_manifest() -> set[str]:
    """기 적재된 PMID 집합을 manifest 파일에서 읽는다.

    config.py는 lazy import — _apply_retry_overrides가 env를 set한 뒤
    호출되도록 모듈 상단이 아닌 함수 본문에서 import한다.
    """
    from mlops.pipeline.config import MANIFEST_PATH

    if MANIFEST_PATH.exists():
        data = json.loads(MANIFEST_PATH.read_text())
        return set(data.get("pmids", []))
    return set()


def save_manifest(pmids: set[str]) -> None:
    """PMID 집합을 manifest 파일에 저장한다."""
    from mlops.pipeline.config import DATA_DIR, MANIFEST_PATH

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"pmids": sorted(pmids), "count": len(pmids)}
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Manifest 저장: %d건 → %s", len(pmids), MANIFEST_PATH)


def api_ingest(chunk_vectors: list[tuple]) -> int:
    """청크+임베딩을 백엔드 admin API로 적재한다."""
    import requests
    from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL

    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.error("API_BASE_URL 또는 ADMIN_API_TOKEN 환경변수가 설정되지 않았습니다")
        sys.exit(1)
    payload = {
        "chunks": [
            {
                "paper_pmid": chunk.paper_pmid,
                "paper_title": chunk.paper_title,
                "section_name": chunk.section_name,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "embedding": vec,
                "search_categories": chunk.search_categories,
            }
            for chunk, vec in chunk_vectors
        ]
    }
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"
    resp = requests.post(
        url,
        json=payload,
        headers={"X-Admin-Token": ADMIN_API_TOKEN},
        timeout=300,
    )
    resp.raise_for_status()
    result = resp.json()
    return result["data"]["upserted"]


def main(
    max_papers: int | None = None,
    max_per_category: int | None = None,
    dry_run: bool = False,
) -> None:
    """retry 환경변수 override는 이 함수 호출 전에 적용되어야 한다.

    config/crawler 모듈을 lazy import해서 _apply_retry_overrides가 먼저 env를 set하면
    그 값이 모듈 로드 시 반영되도록 한다.
    """
    from mlops.pipeline.chunker import chunk_papers
    from mlops.pipeline.config import (
        MAX_PAPERS_PER_CATEGORY,
        MAX_PAPERS_PER_RUN,
        NCBI_HTTP_MAX_RETRIES,
        PMC_FULLTEXT_MAX_ATTEMPTS,
    )
    from mlops.pipeline.crawler import crawl_papers
    from mlops.pipeline.embedder import embed_chunks

    if max_papers is None:
        max_papers = MAX_PAPERS_PER_RUN
    if max_per_category is None:
        max_per_category = MAX_PAPERS_PER_CATEGORY

    logger.info(
        "=== 초기 적재 시작 (max_papers=%d, max_per_category=%d, dry_run=%s, http_retries=%d, fulltext_attempts=%d) ===",
        max_papers,
        max_per_category,
        dry_run,
        NCBI_HTTP_MAX_RETRIES,
        PMC_FULLTEXT_MAX_ATTEMPTS,
    )

    existing = load_manifest()
    logger.info("기존 적재: %d건", len(existing))

    papers = crawl_papers(
        max_total=max_papers,
        max_per_category=max_per_category,
        existing_pmids=existing,
    )
    if not papers:
        logger.info("신규 논문 없음. 종료.")
        return

    chunks = chunk_papers(papers)
    if not chunks:
        logger.info("청크 없음. 종료.")
        return

    logger.info("크롤링 %d편 → 청크 %d개", len(papers), len(chunks))

    if dry_run:
        logger.info("[DRY RUN] 임베딩/적재 생략")
        for c in chunks[:3]:
            logger.info("  샘플: PMID=%s, 섹션=%s, 토큰=%d", c.paper_pmid, c.section_name, c.token_count)
        return

    chunk_vectors = embed_chunks(chunks)
    count = api_ingest(chunk_vectors)

    new_pmids = {p.meta.pmid for p in papers}
    save_manifest(existing | new_pmids)

    logger.info("=== 초기 적재 완료: %d편 → %d청크 → %d upsert ===", len(papers), len(chunks), count)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SciFit-Sync 초기 논문 적재")
    parser.add_argument("--max-papers", type=int, default=None, help="크롤링 상한 (기본: MAX_PAPERS_PER_RUN)")
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        help="카테고리당 esearch 후보 풀 cap (기본: MAX_PAPERS_PER_CATEGORY=20). "
        "100 카테고리 × cap = 전체 후보 풀. cap이 클수록 PMID 다중 카테고리 매칭이 늘어 RAG 가중치 다양성 ↑",
    )
    parser.add_argument("--dry-run", action="store_true", help="크롤링+청킹만 실행, 임베딩/적재 생략")
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
