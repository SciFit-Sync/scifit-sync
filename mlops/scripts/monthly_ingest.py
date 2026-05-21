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
    MANIFEST_PATH,
    MAX_PAPERS_PER_RUN,
    OPENALEX_MAX_PER_CATEGORY,
    PUBMED_MAX_PER_CATEGORY,
)
from mlops.pipeline.crawler import crawl_papers
from mlops.pipeline.embedder import embed_chunks
from mlops.pipeline.manifest import Manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_SOURCES: set[str] = {"pmc", "europepmc"}  # Phase 1
CHECKPOINT_INTERVAL = 100


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
    """청크+임베딩을 서버 /admin/rag/ingest API로 전송한다."""
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


def _fetch_indexed_dois_from_server() -> set[str]:
    """서버 papers 테이블의 모든 DOI를 가져온다.

    manifest는 GitHub Actions runner의 임시 디스크에 저장되어 매 cron 실행마다 빈
    상태로 시작한다. 서버를 dedup의 primary source로 사용하고 manifest는 보조
    (paper별 tried_sources 같은 부가 정보 보존)로 두기 위한 보완.

    env 미설정/네트워크 실패 등 어느 경우든 빈 set을 반환해 호출자가 manifest 단독으로
    fallback하게 한다 — 새 케이스 실패가 기존 manifest 흐름을 깨지 않도록.
    """
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.warning("API_BASE_URL/ADMIN_API_TOKEN 미설정 — 서버 dedup 생략, manifest 단독 사용")
        return set()
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/dois"
    try:
        resp = requests.get(url, headers={"X-Admin-Token": ADMIN_API_TOKEN}, timeout=30)
        resp.raise_for_status()
        return set(resp.json()["data"]["dois"])
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("서버 DOI fetch 실패, manifest 단독 fallback: %s", e)
        return set()


def main(
    max_papers: int | None = None,
    max_per_category: int | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
) -> None:
    if max_papers is None:
        max_papers = MAX_PAPERS_PER_RUN
    # max_per_category=None이면 crawl_papers가 소스별 기본값 (OpenAlex/PubMed) 적용.
    cap_display = (
        f"{max_per_category}"
        if max_per_category is not None
        else f"openalex={OPENALEX_MAX_PER_CATEGORY}/pubmed={PUBMED_MAX_PER_CATEGORY}"
    )

    now = datetime.now()
    if min_date is None:
        min_date = (now - timedelta(days=35)).strftime("%Y/%m/%d")
    if max_date is None:
        max_date = now.strftime("%Y/%m/%d")

    logger.info(
        "=== 월간 증분 적재 시작 (%s ~ %s, max_papers=%d, max_per_category=%s) ===",
        min_date,
        max_date,
        max_papers,
        cap_display,
    )

    manifest = Manifest.load(MANIFEST_PATH)

    # 이미 indexed된 DOI + 모든 active source를 시도한 fail DOI는 skip
    existing_dois: set[str] = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            existing_dois.add(doi)
    manifest_count = len(existing_dois)

    # 서버 papers 테이블의 DOI도 union — manifest 임시디스크 손실 보완.
    server_dois = _fetch_indexed_dois_from_server()
    existing_dois |= server_dois
    logger.info(
        "Existing DOI: %d (manifest %d + server %d, union)",
        len(existing_dois),
        manifest_count,
        len(server_dois),
    )

    # 크롤링 (최근 35일)
    papers = crawl_papers(
        max_total=max_papers,
        max_per_category=max_per_category,
        min_date=min_date,
        max_date=max_date,
        existing_dois=existing_dois,
    )

    if not papers:
        logger.info("신규 논문 없음. 종료.")
        print(json.dumps({"status": "no_new_papers", "existing_count": len(manifest.papers)}))
        return

    # 본문 있는 paper만 청킹/적재 대상
    indexed_papers = [p for p in papers if p.sections]
    logger.info("크롤링: 시도 %d, 본문 확보 %d", len(papers), len(indexed_papers))

    chunks = chunk_papers(indexed_papers) if indexed_papers else []
    logger.info("청크 %d개", len(chunks))

    upserted = 0
    if chunks:
        chunk_vectors = embed_chunks(chunks)
        upserted = api_ingest(chunk_vectors)

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

    result = {
        "status": "success",
        "new_papers": len(papers),
        "indexed_papers": len(indexed_papers),
        "new_chunks": len(chunks),
        "upserted": upserted,
        "total_attempted": len(manifest.papers),
        "date_range": f"{min_date} ~ {max_date}",
    }
    logger.info("=== 월간 적재 완료 ===")
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SciFit-Sync 월간 증분 적재")
    parser.add_argument(
        "--max-papers",
        type=int,
        default=None,
        help="크롤링 상한 (기본: MAX_PAPERS_PER_RUN)",
    )
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        help="카테고리당 후보 풀 cap. 명시 시 OpenAlex/PubMed 양쪽에 동일 적용. "
        "생략 시 소스별 기본값 사용 (OPENALEX_MAX_PER_CATEGORY=500 / "
        "PUBMED_MAX_PER_CATEGORY=50).",
    )
    parser.add_argument("--min-date", default=None, help="YYYY/MM/DD (기본: 35일 전)")
    parser.add_argument("--max-date", default=None, help="YYYY/MM/DD (기본: 오늘)")
    args = parser.parse_args()
    main(
        max_papers=args.max_papers,
        max_per_category=args.max_per_category,
        min_date=args.min_date,
        max_date=args.max_date,
    )
