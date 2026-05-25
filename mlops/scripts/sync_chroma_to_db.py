"""로컬 ChromaDB → Postgres papers 테이블 동기화 (일회성, 로컬 테스트용).

initial_ingest.py는 서버 API를 경유해 Postgres + ChromaDB를 동시에 채운다.
반면 upserter.py로 ChromaDB만 직접 채운 경우 papers 테이블이 비어 있는 문제가 생긴다.
이 스크립트는 그 간극을 메우기 위한 보완 스크립트다.

사용법:
    # server/.env의 DATABASE_URL이 필요하다.
    # 레포 루트에서 실행:
    mlops\\.venv\\Scripts\\activate
    python mlops/scripts/sync_chroma_to_db.py
"""

import asyncio
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / "mlops" / ".env")
load_dotenv(REPO_ROOT / "server" / ".env", override=True)

import chromadb  # noqa: E402
from mlops.pipeline.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_PATH  # noqa: E402
from sqlalchemy import func  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s")
logger = logging.getLogger(__name__)


def _split_meta_list(val) -> list[str]:
    """ChromaDB metadata의 comma-joined 문자열 또는 리스트를 list[str]로 변환."""
    if isinstance(val, list):
        return [s for s in val if s]
    if isinstance(val, str):
        return [s for s in val.split(",") if s]
    return []


async def sync_chroma_to_db() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL 환경변수가 없습니다. server/.env를 확인하세요.")
        sys.exit(1)

    # 1. 로컬 ChromaDB에서 전체 메타데이터 읽기
    logger.info("ChromaDB 연결: path=%s, collection=%s", CHROMA_PERSIST_PATH, CHROMA_COLLECTION_NAME)
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
    try:
        collection = client.get_collection(CHROMA_COLLECTION_NAME)
    except Exception as e:
        logger.error("ChromaDB collection 없음: %s", e)
        sys.exit(1)

    data = collection.get(include=["metadatas"])
    metas = data.get("metadatas") or []
    logger.info("ChromaDB 총 청크 수: %d", len(metas))

    # 2. DOI 기준으로 unique papers 수집 (첫 번째 청크의 메타 사용)
    papers_by_doi: dict[str, dict] = {}
    skipped = 0
    for m in metas:
        if not m:
            continue
        doi = m.get("paper_doi")
        if not doi:
            skipped += 1
            continue
        if doi in papers_by_doi:
            continue

        raw_year = m.get("published_year")
        papers_by_doi[doi] = {
            "doi": doi,
            "pmid": m.get("paper_pmid") or None,
            "title": m.get("paper_title") or "",
            "publication_types": _split_meta_list(m.get("publication_types")),
            "evidence_weight": Decimal(str(m.get("evidence_weight", "0.50"))),
            "fulltext_source": m.get("fulltext_source") or "unknown",
            "search_categories": _split_meta_list(m.get("search_categories")),
            "published_year": int(raw_year) if raw_year else None,
        }

    logger.info("Unique papers: %d편 (DOI 없는 청크 skip: %d)", len(papers_by_doi), skipped)
    if not papers_by_doi:
        logger.info("삽입할 데이터가 없습니다. 종료.")
        return

    # 3. SQLAlchemy async로 Postgres papers 테이블에 UPSERT
    from app.models.paper import Paper

    engine = create_async_engine(database_url, echo=False)
    async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session_factory() as session:
        stmt = pg_insert(Paper).values(list(papers_by_doi.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["doi"],
            set_={
                "pmid": stmt.excluded.pmid,
                "title": stmt.excluded.title,
                "publication_types": stmt.excluded.publication_types,
                "evidence_weight": stmt.excluded.evidence_weight,
                "fulltext_source": stmt.excluded.fulltext_source,
                "search_categories": stmt.excluded.search_categories,
                "published_year": stmt.excluded.published_year,
                "updated_at": func.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()

    await engine.dispose()
    logger.info("완료: papers 테이블에 %d편 UPSERT", len(papers_by_doi))
    logger.info("이제 루틴 생성 시 RoutinePaper가 정상적으로 연결됩니다.")


if __name__ == "__main__":
    asyncio.run(sync_chroma_to_db())
