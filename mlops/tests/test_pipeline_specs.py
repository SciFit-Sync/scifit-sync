"""mlops.pipeline.specs registry 단위 테스트.

외부 의존성 없음 — dataclass + dict 검증만.
"""

from dataclasses import FrozenInstanceError

import pytest
from mlops.pipeline.specs import (
    DEFAULT_MODEL_KEY,
    EMBEDDING_MODELS,
    EmbeddingModelSpec,
    get_spec,
    list_test_targets,
)


def test_default_model_key_resolves():
    """DEFAULT_MODEL_KEY는 registry에 존재해야 한다 — get_spec이 안전하게 동작."""
    spec = get_spec(DEFAULT_MODEL_KEY)
    assert spec.key == DEFAULT_MODEL_KEY


def test_get_spec_returns_known_model():
    spec = get_spec("bge-large")
    assert isinstance(spec, EmbeddingModelSpec)
    assert spec.hf_name == "BAAI/bge-large-en-v1.5"
    assert spec.dim == 1024


def test_get_spec_unknown_key_raises_keyerror_with_available_list():
    """invalid key는 KeyError + 메시지에 가용 key 목록 노출."""
    with pytest.raises(KeyError) as exc_info:
        get_spec("nonexistent-model")
    msg = str(exc_info.value)
    # 가용 key가 메시지에 포함되어야 사용자가 즉시 정정 가능
    for known_key in EMBEDDING_MODELS:
        assert known_key in msg


def test_list_test_targets_returns_all_models():
    targets = list_test_targets()
    assert len(targets) == 3
    keys = {spec.key for spec in targets}
    assert keys == {"bge-large", "bge-base", "pubmedbert-msmarco"}


def test_all_specs_have_positive_dim():
    for spec in EMBEDDING_MODELS.values():
        assert spec.dim > 0, f"{spec.key}: dim must be positive"


def test_bge_models_have_query_prefix():
    """BGE 모델은 asymmetric encoding — query 측에 prefix 필수."""
    assert get_spec("bge-large").query_prefix != ""
    assert get_spec("bge-base").query_prefix != ""


def test_pubmedbert_has_empty_query_prefix():
    """PubMedBERT-MS-MARCO는 symmetric — query/passage 동일 처리."""
    assert get_spec("pubmedbert-msmarco").query_prefix == ""


def test_all_specs_normalize_true():
    """정규화 정책: cosine 의미 보존을 위해 corpus/query 양쪽 정규화 강제."""
    for spec in EMBEDDING_MODELS.values():
        assert spec.normalize is True, f"{spec.key}: normalize must be True"


def test_spec_is_frozen_dataclass():
    """spec은 runtime 변경 불가 — 실수로 mutation 방지."""
    spec = get_spec("bge-large")
    with pytest.raises(FrozenInstanceError):
        spec.dim = 999  # type: ignore[misc]


def test_default_batch_size_positive():
    for spec in EMBEDDING_MODELS.values():
        assert spec.default_batch_size > 0
