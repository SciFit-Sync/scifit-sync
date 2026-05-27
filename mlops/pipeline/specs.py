"""임베딩 모델 registry — A/B 평가용 모델 metadata 단일 출처.

CLI(`export_embeddings.py`, `run_eval.py`)는 짧은 ``key``로 모델을 참조하고,
spec에서 ``hf_name`` / ``dim`` / ``query_prefix`` / ``normalize`` /
``default_batch_size`` 를 조회한다.

`normalize=True` 정책: 세 모델 모두 정규화 강제. BGE는 카드에서 cosine 검색 시
정규화 권장이며, PubMedBERT-MS-MARCO는 명시는 없지만 cosine 의미 보존을 위해
일괄 True. corpus(export) 와 query(retriever) 양쪽에 동일 적용되어야 점수가
왜곡되지 않는다.

위치: pipeline 레이어. embedder(pipeline)와 retriever(eval) 양쪽이 의존하지만,
의존 방향은 항상 pipeline 쪽으로 향한다(eval → pipeline).
"""

from dataclasses import dataclass

# BGE-v1.5 query prefix — passage 측에는 prepend하지 않는다(asymmetric encoding).
_BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """단일 임베딩 모델의 metadata."""

    key: str
    hf_name: str
    dim: int
    query_prefix: str
    normalize: bool = True
    default_batch_size: int = 64
    revision: str | None = None


EMBEDDING_MODELS: dict[str, EmbeddingModelSpec] = {
    "bge-large": EmbeddingModelSpec(
        key="bge-large",
        hf_name="BAAI/bge-large-en-v1.5",
        dim=1024,
        query_prefix=_BGE_QUERY_PREFIX,
        default_batch_size=64,
    ),
    "bge-base": EmbeddingModelSpec(
        key="bge-base",
        hf_name="BAAI/bge-base-en-v1.5",
        dim=768,
        query_prefix=_BGE_QUERY_PREFIX,
        default_batch_size=128,
    ),
    "pubmedbert-msmarco": EmbeddingModelSpec(
        key="pubmedbert-msmarco",
        hf_name="pritamdeka/S-PubMedBert-MS-MARCO",
        dim=768,
        query_prefix="",
        default_batch_size=128,
        revision="9504c2b4961c21fc92fcf3dbb800b8d7aaed4ceb",
    ),
}

DEFAULT_MODEL_KEY = "bge-large"


def get_spec(key: str) -> EmbeddingModelSpec:
    """key로 spec 조회. 미등록 key는 KeyError + 가용 key 목록."""
    try:
        return EMBEDDING_MODELS[key]
    except KeyError as e:
        available = ", ".join(sorted(EMBEDDING_MODELS.keys()))
        raise KeyError(f"등록되지 않은 모델 key={key!r}. 가용 key: [{available}]") from e


def list_test_targets() -> list[EmbeddingModelSpec]:
    """A/B test 모드에서 평가할 전체 모델 목록."""
    return list(EMBEDDING_MODELS.values())
