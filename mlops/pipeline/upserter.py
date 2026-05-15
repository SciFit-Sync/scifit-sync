"""ChromaDB Upsert 모듈.

PersistentClient로 청크+임베딩을 ChromaDB에 저장한다.
document ID는 `{pmid}_{chunk_index}`로 중복 방지.
"""

import logging

import chromadb
from mlops.pipeline.config import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_PATH
from mlops.pipeline.models import Chunk

logger = logging.getLogger(__name__)

_client = None
_collection = None


def _get_collection() -> chromadb.Collection:
    """ChromaDB collection을 싱글턴으로 반환한다."""
    global _client, _collection
    if _collection is None:
        logger.info("ChromaDB 연결: path=%s, collection=%s", CHROMA_PERSIST_PATH, CHROMA_COLLECTION_NAME)
        _client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        _collection = _client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("ChromaDB collection 준비 완료 (기존 문서 수: %d)", _collection.count())
    return _collection


def _make_doc_id(chunk: Chunk) -> str:
    """청크의 고유 document ID를 생성한다."""
    return f"{chunk.paper_pmid}_{chunk.chunk_index}"


def upsert_chunks(
    chunk_vector_pairs: list[tuple[Chunk, list[float]]],
    batch_size: int = 100,
) -> int:
    """청크+벡터를 ChromaDB에 upsert한다.

    Args:
        chunk_vector_pairs: (Chunk, embedding_vector) 튜플 리스트
        batch_size: 배치 크기

    Returns:
        upsert된 총 문서 수
    """
    if not chunk_vector_pairs:
        return 0

    collection = _get_collection()
    total = 0

    for i in range(0, len(chunk_vector_pairs), batch_size):
        batch = chunk_vector_pairs[i : i + batch_size]

        ids = [_make_doc_id(chunk) for chunk, _ in batch]
        documents = [chunk.content for chunk, _ in batch]
        embeddings = [vec for _, vec in batch]
        metadatas = [
            {
                "paper_pmid": chunk.paper_pmid,
                "paper_title": chunk.paper_title,
                "section_name": chunk.section_name,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "search_categories": ",".join(chunk.search_categories),
            }
            for chunk, _ in batch
        ]

        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        total += len(batch)
        logger.info("ChromaDB upsert: %d/%d", total, len(chunk_vector_pairs))

    logger.info("upsert 완료: %d개 문서 (전체 collection: %d개)", total, collection.count())
    return total
