"""최초 전체 논문 적재 스크립트 (일회성).

사용법:
    python mlops/scripts/initial_ingest.py [--dry-run] [--max-papers 100]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.chunker import chunk_papers
from mlops.pipeline.config import DATA_DIR, MANIFEST_PATH, MAX_PAPERS_PER_RUN
from mlops.pipeline.crawler import crawl_papers
from mlops.pipeline.embedder import embed_chunks
from mlops.pipeline.upserter import upsert_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def load_manifest() -> set[str]:
    """기존 manifest에서 적재된 PMID 집합을 로딩한다."""
    if MANIFEST_PATH.exists():
        data = json.loads(MANIFEST_PATH.read_text())
        return set(data.get("pmids", []))
    return set()


def save_manifest(pmids: set[str]) -> None:
    """적재된 PMID 집합을 manifest에 저장한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"pmids": sorted(pmids), "count": len(pmids)}
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Manifest 저장: %d건 → %s", len(pmids), MANIFEST_PATH)


def main(max_papers: int = MAX_PAPERS_PER_RUN, dry_run: bool = False) -> None:
    """초기 적재 파이프라인 실행."""
    logger.info("=== 초기 적재 시작 (max_papers=%d, dry_run=%s) ===", max_papers, dry_run)

    existing = load_manifest()
    logger.info("기존 적재: %d건", len(existing))

    # 1. 크롤링
    papers = crawl_papers(max_results=max_papers, existing_pmids=existing)
    if not papers:
        logger.info("신규 논문 없음. 종료.")
        return

    # 2. 청킹
    chunks = chunk_papers(papers)
    if not chunks:
        logger.info("청크 없음. 종료.")
        return

    logger.info("크롤링 %d편 → 청크 %d개", len(papers), len(chunks))

    if dry_run:
        logger.info("[DRY RUN] 임베딩/upsert 생략")
        for c in chunks[:3]:
            logger.info("  샘플: PMID=%s, 섹션=%s, 토큰=%d", c.paper_pmid, c.section_name, c.token_count)
        return

    # 3. 임베딩
    chunk_vectors = embed_chunks(chunks)

    # 4. ChromaDB upsert
    count = upsert_chunks(chunk_vectors)

    # 5. Manifest 업데이트
    new_pmids = {p.meta.pmid for p in papers}
    save_manifest(existing | new_pmids)

    logger.info("=== 초기 적재 완료: %d편 → %d청크 → %d upsert ===", len(papers), len(chunks), count)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SciFit-Sync 초기 논문 적재")
    parser.add_argument("--max-papers", type=int, default=MAX_PAPERS_PER_RUN)
    parser.add_argument("--dry-run", action="store_true", help="크롤링+청킹만 실행, 임베딩/upsert 생략")
    args = parser.parse_args()
    main(max_papers=args.max_papers, dry_run=args.dry_run)
