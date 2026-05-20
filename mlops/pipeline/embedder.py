"""BAAI/bge-large-en-v1.5 임베딩 모듈.

sentence-transformers로 논문 청크를 1024차원 벡터로 변환한다.
BGE-v1.5: document(passage)는 prefix 없이 임베딩한다.
query prefix("Represent this sentence for searching relevant passages: ")는
서버 RAG 검색 시 query 측에만 적용한다.
"""

import logging
import os

from mlops.pipeline.config import EMBEDDING_DIM, EMBEDDING_MODEL
from mlops.pipeline.models import Chunk

logger = logging.getLogger(__name__)

_model = None


def _resolve_device() -> str:
    override = os.environ.get("MLOPS_EMBED_DEVICE")
    if override:
        return override
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def log_device_status(logger_: logging.Logger | None = None) -> str:
    """추론 device를 미리 결정하고 로깅한다.

    스크립트 시작 직후(크롤링 전)에 호출해 CPU fallback 경고를 조기에 노출한다.
    모델 로드까지 기다리지 않고 사용자가 즉시 환경 문제를 발견할 수 있다.

    Returns:
        해석된 device 문자열.
    """
    log = logger_ or logger
    device = _resolve_device()
    if device == "cpu":
        log.warning(
            "GPU 미감지 → CPU 추론 예정. BGE-large는 CPU에서 매우 느립니다(20s/batch+). "
            "GPU 서버라면 CUDA torch 재설치 필요: "
            "pip install torch --index-url https://download.pytorch.org/whl/cu121"
        )
    else:
        log.info("임베딩 device 사전 확인: %s", device)
    return device


def _get_model():
    """sentence-transformers 모델을 싱글턴으로 로딩한다 (2GB+, lazy load)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        device = _resolve_device()
        if device == "cpu":
            logger.warning(
                "GPU 미감지 → CPU 추론. BGE-large는 CPU에서 매우 느립니다(20s/batch+). "
                "GPU 서버라면 CUDA torch 재설치 필요: "
                "pip install torch --index-url https://download.pytorch.org/whl/cu121"
            )
        logger.info("임베딩 모델 로딩: %s (device=%s)", EMBEDDING_MODEL, device)
        _model = SentenceTransformer(EMBEDDING_MODEL, device=device)
        logger.info("모델 로딩 완료 (dim=%d, device=%s)", EMBEDDING_DIM, device)
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
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=len(texts) > 100)
    return embeddings.tolist()


def embed_chunks(chunks: list[Chunk], batch_size: int = 32) -> list[tuple[Chunk, list[float]]]:
    """Chunk 리스트를 임베딩하여 (Chunk, vector) 튜플 리스트를 반환한다."""
    if not chunks:
        return []

    texts = [c.content for c in chunks]
    vectors = embed_texts(texts, batch_size=batch_size)

    logger.info("임베딩 완료: %d개 청크 → %d차원 벡터", len(chunks), EMBEDDING_DIM)
    return list(zip(chunks, vectors, strict=True))
