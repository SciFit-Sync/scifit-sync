"""BAAI/bge-large-en-v1.5 임베딩 모듈.

sentence-transformers로 논문 청크를 1024차원 벡터로 변환한다.
BGE 모델은 instruction prefix가 필요하다.
"""

import logging

from mlops.pipeline.config import EMBEDDING_DIM, EMBEDDING_MODEL
from mlops.pipeline.models import Chunk

logger = logging.getLogger(__name__)

BGE_INSTRUCTION = "Represent this document for retrieval: "

_model = None


def _get_model():
    """sentence-transformers 모델을 싱글턴으로 로딩한다 (2GB+, lazy load)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("임베딩 모델 로딩: %s", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("모델 로딩 완료 (dim=%d)", EMBEDDING_DIM)
    return _model


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """텍스트 리스트를 임베딩 벡터로 변환한다.

    Args:
        texts: 임베딩할 텍스트 리스트
        batch_size: 배치 크기 (메모리 효율)

    Returns:
        1024차원 float 벡터 리스트
    """
    model = _get_model()
    prefixed = [BGE_INSTRUCTION + t for t in texts]
    embeddings = model.encode(prefixed, batch_size=batch_size, show_progress_bar=len(texts) > 100)
    return embeddings.tolist()


def embed_chunks(chunks: list[Chunk], batch_size: int = 32) -> list[tuple[Chunk, list[float]]]:
    """Chunk 리스트를 임베딩하여 (Chunk, vector) 튜플 리스트를 반환한다."""
    if not chunks:
        return []

    texts = [c.content for c in chunks]
    vectors = embed_texts(texts, batch_size=batch_size)

    logger.info("임베딩 완료: %d개 청크 → %d차원 벡터", len(chunks), EMBEDDING_DIM)
    return list(zip(chunks, vectors, strict=True))
