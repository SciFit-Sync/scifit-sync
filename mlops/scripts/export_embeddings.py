"""크롤링 → 청킹 → 임베딩까지 실행 후 결과를 JSON Lines 파일로 export.

클라우드 서버에서 실행해서 임베딩 결과만 파일로 뽑아낸 뒤,
별도로 ChromaDB에 적재할 때 사용한다 (load_embeddings.py로 적재).

사용법:
    python mlops/scripts/export_embeddings.py \
        --max-papers 100 \
        --output mlops/data/embeddings.jsonl

    # 압축 출력 (.jsonl.gz)
    python mlops/scripts/export_embeddings.py --output mlops/data/embeddings.jsonl.gz --gzip

    # 크롤링+청킹만 (임베딩 생략, 사이즈 점검용)
    python mlops/scripts/export_embeddings.py --dry-run

JSON Lines 출력 포맷 (1청크당 1줄):
    {
      "paper_doi": "10.1234/example",
      "paper_pmid": "12345678",
      "paper_title": "Effects of ...",
      "section_name": "Methods",
      "chunk_index": 0,
      "content": "...",
      "token_count": 487,
      "publication_types": ["Randomized Controlled Trial"],
      "evidence_weight": 0.90,
      "fulltext_source": "pmc",
      "published_year": 2022,
      "embedding": [0.012, -0.034, ...]   # 1024개 float (BGE-large-en-v1.5)
    }
"""

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.chunker import chunk_papers
from mlops.pipeline.config import DATA_DIR, MANIFEST_PATH, MAX_PAPERS_PER_RUN
from mlops.pipeline.crawler import crawl_papers
from mlops.pipeline.embedder import embed_chunks, log_device_status
from mlops.pipeline.manifest import Manifest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_SOURCES: set[str] = {"pmc", "europepmc"}  # Phase 1


def _open_writer(path: Path, use_gzip: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    if use_gzip:
        return gzip.open(path, "wt", encoding="utf-8")
    return path.open("w", encoding="utf-8")


def main(
    max_papers: int,
    output: Path,
    use_gzip: bool,
    dry_run: bool,
    min_date: str | None,
    max_date: str | None,
    update_manifest: bool,
    max_per_category: int | None = None,
) -> None:
    logger.info("=== Embedding Export 시작 ===")
    logger.info(
        "max_papers=%d, max_per_category=%s, output=%s, gzip=%s, dry_run=%s",
        max_papers,
        max_per_category if max_per_category is not None else "source-defaults",
        output,
        use_gzip,
        dry_run,
    )

    # 크롤링/청킹은 길어서 디바이스 문제 발견이 늦다 → 시작 직후 사전 확인.
    log_device_status(logger)

    manifest = Manifest.load(MANIFEST_PATH)

    # 이미 indexed된 DOI + 모든 active source를 시도한 fail DOI는 skip
    existing_dois: set[str] = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            existing_dois.add(doi)
    logger.info("기존 manifest: %d건 (indexed + fully-tried)", len(existing_dois))

    papers = crawl_papers(
        max_total=max_papers,
        max_per_category=max_per_category,
        min_date=min_date,
        max_date=max_date,
        existing_dois=existing_dois,
    )
    if not papers:
        logger.info("신규 논문 없음. 종료.")
        return

    indexed_papers = [p for p in papers if p.sections]
    logger.info("크롤링: 시도 %d, 본문 확보 %d", len(papers), len(indexed_papers))

    chunks = chunk_papers(indexed_papers) if indexed_papers else []
    if not chunks:
        logger.info("청크 없음. 종료.")
        return

    logger.info("크롤링 %d편 → 청크 %d개", len(indexed_papers), len(chunks))

    if dry_run:
        logger.info("[DRY RUN] 임베딩/파일 출력 생략")
        for c in chunks[:3]:
            logger.info("  샘플: PMID=%s, 섹션=%s, 토큰=%d", c.paper_pmid, c.section_name, c.token_count)
        return

    chunk_vectors = embed_chunks(chunks)

    written = 0
    with _open_writer(output, use_gzip) as f:
        for chunk, vec in chunk_vectors:
            record = chunk.model_dump()
            record["embedding"] = vec
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
            written += 1

    size_mb = output.stat().st_size / (1024 * 1024)
    logger.info("Export 완료: %d청크 → %s (%.2f MB)", written, output, size_mb)

    if update_manifest:
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

    logger.info("=== Export 완료: %d편 → %d청크 ===", len(indexed_papers), written)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SciFit-Sync 임베딩 결과 export")
    parser.add_argument("--max-papers", type=int, default=MAX_PAPERS_PER_RUN)
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        help="카테고리당 후보 풀 cap. 명시 시 OpenAlex/PubMed 양쪽에 동일 적용. "
        "생략 시 소스별 기본값 사용 (OPENALEX_MAX_PER_CATEGORY=500 / "
        "PUBMED_MAX_PER_CATEGORY=50). 후보 풀이 클수록 round-robin이 부족 카테고리를 "
        "다른 카테고리에서 흡수할 여유가 커진다.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_DIR / "embeddings.jsonl",
        help="출력 파일 경로 (확장자 .jsonl 또는 .jsonl.gz)",
    )
    parser.add_argument("--gzip", action="store_true", help="gzip 압축 출력")
    parser.add_argument("--dry-run", action="store_true", help="크롤링+청킹만 수행")
    parser.add_argument("--min-date", default=None, help="YYYY/MM/DD")
    parser.add_argument("--max-date", default=None, help="YYYY/MM/DD")
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        default=False,
        help="export 완료 후 manifest.json 즉시 갱신 "
        "(기본 OFF — 적재 검증 완료 후 별도로 갱신하는 것이 안전. "
        "적재 도중 실패해도 manifest가 깨끗하면 동일 DOI로 재시도 가능)",
    )
    args = parser.parse_args()

    out_path: Path = args.output
    use_gzip = args.gzip or out_path.suffix == ".gz"

    main(
        max_papers=args.max_papers,
        output=out_path,
        use_gzip=use_gzip,
        dry_run=args.dry_run,
        min_date=args.min_date,
        max_date=args.max_date,
        update_manifest=args.update_manifest,
        max_per_category=args.max_per_category,
    )
