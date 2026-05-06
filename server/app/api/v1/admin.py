"""Admin API — MLOps 파이프라인 연동용.

GitHub Actions에서 실행된 논문 임베딩 결과를 서버 ChromaDB로 수신하는 엔드포인트.
ADMIN_API_TOKEN으로 인증.
"""

import logging

import chromadb
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_chroma_client: chromadb.PersistentClient | None = None


def _get_collection() -> chromadb.Collection:
    global _chroma_client
    settings = get_settings()
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
    return _chroma_client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def _verify_admin_token(x_admin_token: str = Header(...)) -> None:
    settings = get_settings()
    if not settings.ADMIN_API_TOKEN or x_admin_token != settings.ADMIN_API_TOKEN:
        raise ForbiddenError(message="Admin 인증이 필요합니다")


class ChunkItem(BaseModel):
    paper_pmid: str
    paper_title: str
    section_name: str
    chunk_index: int
    content: str
    token_count: int
    embedding: list[float]


class IngestRequest(BaseModel):
    chunks: list[ChunkItem]


@router.post("/rag/ingest")
async def ingest_papers(
    body: IngestRequest,
    _: None = Depends(_verify_admin_token),
) -> dict:
    """MLOps 파이프라인에서 처리된 논문 청크+임베딩을 ChromaDB에 적재한다."""
    if not body.chunks:
        return {"success": True, "data": {"upserted": 0}}

    collection = _get_collection()
    batch_size = 100
    total = 0

    for i in range(0, len(body.chunks), batch_size):
        batch = body.chunks[i : i + batch_size]
        collection.upsert(
            ids=[f"{c.paper_pmid}_{c.chunk_index}" for c in batch],
            documents=[c.content for c in batch],
            embeddings=[c.embedding for c in batch],
            metadatas=[
                {
                    "paper_pmid": c.paper_pmid,
                    "paper_title": c.paper_title,
                    "section_name": c.section_name,
                    "chunk_index": c.chunk_index,
                    "token_count": c.token_count,
                }
                for c in batch
            ],
        )
        total += len(batch)
        logger.info("ChromaDB upsert: %d/%d", total, len(body.chunks))

    logger.info("ingest 완료: %d청크 (collection 전체: %d)", total, collection.count())
    return {"success": True, "data": {"upserted": total, "total_collection": collection.count()}}
