"""export_embeddings.py로 만든 JSON Lines 파일을 ChromaDB에 적재.

사용법:
    # 로컬 ChromaDB(PersistentClient)에 직접 적재
    python mlops/scripts/load_embeddings.py \
        --input mlops/data/embeddings.jsonl \
        --mode local

    # 서버 admin API로 적재 (X-Admin-Token 인증)
    python mlops/scripts/load_embeddings.py \
        --input mlops/data/embeddings.jsonl \
        --mode api

    # gzip 압축 파일도 그대로 지원
    python mlops/scripts/load_embeddings.py --input embeddings.jsonl.gz --mode local

    # 오염 라인을 건너뛰고 계속 진행 (운영 시 부분 적재 허용)
    python mlops/scripts/load_embeddings.py --input embeddings.jsonl --mode local --skip-errors

JSON Lines 입력 포맷은 export_embeddings.py의 출력과 동일하다.

오류 처리 정책:
    기본은 fail-fast — 단일 라인 파싱 실패(JSON 깨짐, 임베딩 차원 불일치,
    `embedding` 키 누락, Chunk 스키마 위반 등)가 발견되면 즉시 raise해서
    적재를 중단한다. 데이터 정합성을 우선시하는 안전한 기본 동작이다.

    `--skip-errors`를 명시하면 실패한 라인을 WARNING 로그로 남기고 다음
    라인으로 진행하며, 종료 시 skip된 라인 수를 요약한다. 수천 청크 중
    소수가 오염되어도 나머지를 적재해야 하는 운영 상황에서 사용한다.
"""

import argparse
import gzip
import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.config import (
    ADMIN_API_TOKEN,
    API_BASE_URL,
    EMBEDDING_DIM,
)
from mlops.pipeline.models import Chunk
from mlops.pipeline.upserter import upsert_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _open_reader(path: Path):
    if path.suffix == ".gz" or path.name.endswith(".jsonl.gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def iter_records(
    path: Path,
    skip_errors: bool = False,
) -> Iterator[tuple[Chunk, list[float]]]:
    """JSON Lines에서 (Chunk, embedding) 튜플 stream.

    Args:
        path: 입력 파일 경로 (.jsonl 또는 .jsonl.gz).
        skip_errors: False(기본) → 첫 파싱 실패에서 즉시 raise (fail-fast).
            True → 실패 라인을 WARNING 로그로 남기고 건너뜀.
            루프 종료 시 skip된 총 라인 수를 요약한다.
    """
    skipped = 0
    with _open_reader(path) as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                embedding = data.pop("embedding")
                if len(embedding) != EMBEDDING_DIM:
                    raise ValueError(f"임베딩 차원 불일치: {len(embedding)} ≠ {EMBEDDING_DIM}")
                chunk = Chunk(**data)
                yield chunk, embedding
            except Exception as e:
                if skip_errors:
                    logger.warning("라인 %d skip: %s", line_no, e)
                    skipped += 1
                    continue
                logger.error("라인 %d 파싱 실패: %s", line_no, e)
                raise
    if skipped:
        logger.warning("총 %d라인 skip됨 (--skip-errors)", skipped)


def load_local(input_path: Path, batch_size: int, skip_errors: bool = False) -> int:
    """로컬 ChromaDB(PersistentClient)에 직접 적재."""
    logger.info("로컬 ChromaDB 적재 시작: %s (skip_errors=%s)", input_path, skip_errors)
    buffer: list[tuple[Chunk, list[float]]] = []
    total = 0
    for record in iter_records(input_path, skip_errors=skip_errors):
        buffer.append(record)
        if len(buffer) >= batch_size:
            total += upsert_chunks(buffer, batch_size=batch_size)
            buffer = []
    if buffer:
        total += upsert_chunks(buffer, batch_size=batch_size)
    return total


def load_api(input_path: Path, batch_size: int, skip_errors: bool = False) -> int:
    """서버 admin endpoint로 HTTP 전송."""
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.error("API_BASE_URL 또는 ADMIN_API_TOKEN 환경변수가 설정되지 않았습니다")
        sys.exit(1)

    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"
    headers = {"X-Admin-Token": ADMIN_API_TOKEN}
    logger.info("서버 API 적재 시작: POST %s (skip_errors=%s)", url, skip_errors)

    def _post(batch: list[tuple[Chunk, list[float]]]) -> int:
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
                for chunk, vec in batch
            ]
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        return result["data"]["upserted"]

    buffer: list[tuple[Chunk, list[float]]] = []
    total = 0
    for record in iter_records(input_path, skip_errors=skip_errors):
        buffer.append(record)
        if len(buffer) >= batch_size:
            total += _post(buffer)
            logger.info("API 적재: %d청크 누적", total)
            buffer = []
    if buffer:
        total += _post(buffer)
        logger.info("API 적재: %d청크 누적", total)
    return total


def main(input_path: Path, mode: str, batch_size: int, skip_errors: bool = False) -> None:
    if not input_path.exists():
        logger.error("입력 파일 없음: %s", input_path)
        sys.exit(1)

    if mode == "local":
        total = load_local(input_path, batch_size, skip_errors=skip_errors)
    elif mode == "api":
        total = load_api(input_path, batch_size, skip_errors=skip_errors)
    else:
        logger.error("알 수 없는 모드: %s", mode)
        sys.exit(1)

    logger.info("=== 적재 완료: %d청크 (mode=%s) ===", total, mode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SciFit-Sync 임베딩 파일 → ChromaDB 적재")
    parser.add_argument("--input", type=Path, required=True, help="export_embeddings.py 출력 파일")
    parser.add_argument(
        "--mode",
        choices=["local", "api"],
        default="local",
        help="local=PersistentClient 직접, api=서버 admin endpoint",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        default=False,
        help="오염된 라인을 WARNING 로그로 남기고 건너뜀 (기본 OFF — 단일 파싱 실패에서 즉시 raise하여 fail-fast)",
    )
    args = parser.parse_args()
    main(args.input, args.mode, args.batch_size, skip_errors=args.skip_errors)
