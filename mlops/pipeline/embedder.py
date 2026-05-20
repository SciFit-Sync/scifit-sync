"""임베딩 모듈 — spec(registry) 기반 multi-model 지원.

운영 default는 BGE-large(1024d). A/B test 모드는 한 프로세스에서 여러 모델을 캐싱해서
순회한다. corpus(export)와 query(retriever) 양쪽이 동일 정규화 정책을 따르도록
`spec.normalize`가 인코딩 호출에 강제된다.

BGE-v1.5: passage(document) 측에는 prefix 없이 임베딩한다.
query prefix("Represent this sentence for searching relevant passages: ")는
검색 시 query 측에만 적용한다 (retriever 측 책임).
"""

import logging
import os
from typing import TYPE_CHECKING

from mlops.pipeline.models import Chunk
from mlops.pipeline.specs import DEFAULT_MODEL_KEY, EmbeddingModelSpec, get_spec

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# hf_name → SentenceTransformer. test 모드에서 동일 spec 재호출 시 모델 재로딩 방지.
_model_cache: dict[str, "SentenceTransformer"] = {}


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


def _get_model_by_spec(spec: EmbeddingModelSpec) -> "SentenceTransformer":
    """spec.hf_name을 키로 SentenceTransformer 캐싱 (lazy load)."""
    if spec.hf_name not in _model_cache:
        from sentence_transformers import SentenceTransformer

        device = _resolve_device()
        if device == "cpu":
            logger.warning(
                "GPU 미감지 → CPU 추론. %s는 CPU에서 매우 느립니다. "
                "GPU 서버라면 CUDA torch 재설치 필요: "
                "pip install torch --index-url https://download.pytorch.org/whl/cu121",
                spec.key,
            )
        logger.info("임베딩 모델 로딩: %s (key=%s, device=%s)", spec.hf_name, spec.key, device)
        _model_cache[spec.hf_name] = SentenceTransformer(spec.hf_name, device=device)
        logger.info("모델 로딩 완료 (key=%s, dim=%d, device=%s)", spec.key, spec.dim, device)
    return _model_cache[spec.hf_name]


def embed_texts_with_spec(
    texts: list[str],
    spec: EmbeddingModelSpec,
    batch_size: int | None = None,
) -> list[list[float]]:
    """spec 기반 corpus 임베딩 — `spec.normalize`가 인코딩에 적용된다.

    query 측 prefix는 retriever가 책임지므로 여기서는 prepend하지 않는다.
    (passage 측에 prefix를 붙이면 BGE asymmetric encoding이 깨진다.)
    """
    model = _get_model_by_spec(spec)
    bs = batch_size if batch_size is not None else spec.default_batch_size
    embeddings = model.encode(
        texts,
        batch_size=bs,
        show_progress_bar=len(texts) > 100,
        normalize_embeddings=spec.normalize,
    )
    return embeddings.tolist()


def embed_chunks_with_spec(
    chunks: list[Chunk],
    spec: EmbeddingModelSpec,
    batch_size: int | None = None,
) -> list[tuple[Chunk, list[float]]]:
    """spec 기반 Chunk 임베딩."""
    if not chunks:
        return []

    texts = [c.content for c in chunks]
    vectors = embed_texts_with_spec(texts, spec, batch_size=batch_size)

    logger.info(
        "임베딩 완료: %d개 청크 → %d차원 벡터 (key=%s)",
        len(chunks),
        spec.dim,
        spec.key,
    )
    return list(zip(chunks, vectors, strict=True))


# ── Backward-compat thin wrappers — default spec 위임 ──────────────────────────
# 기존 호출자(export_embeddings/initial_ingest/monthly_ingest)는 시그니처 변경 없이
# 그대로 동작한다. 단 spec.normalize=True 강제로 출력 벡터는 단위벡터.


def _get_model() -> "SentenceTransformer":
    """default spec 모델 로드 — 기존 호출자 backward-compat."""
    return _get_model_by_spec(get_spec(DEFAULT_MODEL_KEY))


def embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """텍스트 → 임베딩 벡터 (default spec=BGE-large 1024d, normalized)."""
    return embed_texts_with_spec(texts, get_spec(DEFAULT_MODEL_KEY), batch_size=batch_size)


def embed_chunks(chunks: list[Chunk], batch_size: int = 32) -> list[tuple[Chunk, list[float]]]:
    """Chunk → (Chunk, vector) 튜플 (default spec=BGE-large 1024d, normalized)."""
    return embed_chunks_with_spec(chunks, get_spec(DEFAULT_MODEL_KEY), batch_size=batch_size)
