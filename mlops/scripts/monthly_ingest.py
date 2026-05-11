"""월간 증분 논문 적재 스크립트.

GitHub Actions cron (매월 1일)에 의해 실행된다.
최근 35일간 발행된 논문만 수집하여 증분 처리.

사용법:
    python mlops/scripts/monthly_ingest.py
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.chunker import chunk_papers
from mlops.pipeline.config import (
    ADMIN_API_TOKEN,
    API_BASE_URL,
    DATA_DIR,
    MANIFEST_PATH,
    MAX_PAPERS_PER_RUN,
)
from mlops.pipeline.crawler import crawl_papers
from mlops.pipeline.embedder import embed_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def load_manifest() -> set[str]:
    if MANIFEST_PATH.exists():
        data = json.loads(MANIFEST_PATH.read_text())
        return set(data.get("pmids", []))
    return set()


def save_manifest(pmids: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {"pmids": sorted(pmids), "count": len(pmids)}
    MANIFEST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    logger.info("Manifest 저장: %d건 → %s", len(pmids), MANIFEST_PATH)


def api_ingest(chunk_vectors: list[tuple]) -> int:
    """청크+임베딩을 서버 /admin/rag/ingest API로 전송한다."""
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


def main() -> None:
    now = datetime.now()
    min_date = (now - timedelta(days=35)).strftime("%Y/%m/%d")
    max_date = now.strftime("%Y/%m/%d")

    logger.info("=== 월간 증분 적재 시작 (%s ~ %s) ===", min_date, max_date)

    existing = load_manifest()
    logger.info("기존 적재: %d건", len(existing))

    # 1. 크롤링 (최근 35일)
    papers = crawl_papers(
        max_results=MAX_PAPERS_PER_RUN,
        min_date=min_date,
        max_date=max_date,
        existing_pmids=existing,
    )

    if not papers:
        logger.info("신규 논문 없음. 종료.")
        print(json.dumps({"status": "no_new_papers", "existing_count": len(existing)}))
        return

    # 2. 청킹
    chunks = chunk_papers(papers)
    if not chunks:
        logger.info("청크 없음. 종료.")
        return

    logger.info("크롤링 %d편 → 청크 %d개", len(papers), len(chunks))

    # 3. 임베딩
    chunk_vectors = embed_chunks(chunks)

    # 4. API 호출로 ChromaDB 적재
    count = api_ingest(chunk_vectors)

    # 5. Manifest 업데이트
    new_pmids = {p.meta.pmid for p in papers}
    save_manifest(existing | new_pmids)

    result = {
        "status": "success",
        "new_papers": len(papers),
        "new_chunks": len(chunks),
        "upserted": count,
        "total_papers": len(existing | new_pmids),
        "date_range": f"{min_date} ~ {max_date}",
    }
    logger.info("=== 월간 적재 완료 ===")
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
