"""mlops.pipeline.embedder spec API 단위 테스트.

SentenceTransformer를 mock해서 모델 캐시 / 정규화 / spec 위임 동작을 검증한다.
실제 HF 다운로드/torch GPU 의존 없음.
"""

import sys
import types

import numpy as np
import pytest
from mlops.pipeline import embedder
from mlops.pipeline.models import Chunk
from mlops.pipeline.specs import DEFAULT_MODEL_KEY, EmbeddingModelSpec, get_spec

# ── Fake SentenceTransformer ────────────────────────────────────────────────


class _FakeSentenceTransformer:
    """결정론적 encode — 텍스트 해시 기반 random vector."""

    instances_created: list[tuple[str, str]] = []  # (hf_name, device)
    encode_calls: list[dict] = []  # 각 호출의 인자 capture

    def __init__(self, hf_name: str, device: str = "cpu"):
        self.hf_name = hf_name
        self.device = device
        self.__class__.instances_created.append((hf_name, device))
        # spec.dim을 알아내려면 registry 조회 — fake는 hf_name으로 역추적
        dim_lookup = {
            "BAAI/bge-large-en-v1.5": 1024,
            "BAAI/bge-base-en-v1.5": 768,
            "pritamdeka/S-PubMedBert-MS-MARCO": 768,
        }
        self.dim = dim_lookup.get(hf_name, 1024)

    def encode(
        self,
        texts,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = False,
    ):
        self.__class__.encode_calls.append(
            {
                "texts": list(texts) if isinstance(texts, list) else [texts],
                "batch_size": batch_size,
                "show_progress_bar": show_progress_bar,
                "normalize_embeddings": normalize_embeddings,
                "hf_name": self.hf_name,
            }
        )
        # texts는 list 또는 단일 str
        items = texts if isinstance(texts, list) else [texts]
        rng = np.random.default_rng(seed=hash(self.hf_name) & 0xFFFFFFFF)
        out = rng.standard_normal((len(items), self.dim)).astype(np.float32)
        if normalize_embeddings:
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            out = out / norms
        # 단일 str 입력일 경우 1D ndarray 반환 (실제 ST 동작 흉내)
        if not isinstance(texts, list):
            return out[0]
        return out


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """각 테스트마다 모델 캐시/encode call 기록 초기화 + ST 모킹."""
    embedder._model_cache.clear()
    _FakeSentenceTransformer.instances_created = []
    _FakeSentenceTransformer.encode_calls = []

    # sentence_transformers를 fake로 교체 (embedder._get_model_by_spec 내부 lazy import 시점에 잡힘)
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    # device는 항상 cpu로 결정론적 고정
    monkeypatch.setenv("MLOPS_EMBED_DEVICE", "cpu")
    yield


# ── _get_model_by_spec 캐시 동작 ────────────────────────────────────────────


def test_get_model_by_spec_caches_same_spec():
    spec = get_spec("bge-large")
    m1 = embedder._get_model_by_spec(spec)
    m2 = embedder._get_model_by_spec(spec)
    assert m1 is m2
    # SentenceTransformer 생성자 1회만 호출
    assert len(_FakeSentenceTransformer.instances_created) == 1


def test_get_model_by_spec_loads_different_specs_separately():
    s1 = get_spec("bge-large")
    s2 = get_spec("bge-base")
    embedder._get_model_by_spec(s1)
    embedder._get_model_by_spec(s2)
    assert len(_FakeSentenceTransformer.instances_created) == 2
    hf_names = {hf for hf, _ in _FakeSentenceTransformer.instances_created}
    assert hf_names == {s1.hf_name, s2.hf_name}


# ── embed_texts_with_spec 정규화 / 차원 / batch_size 위임 ─────────────────────


def test_embed_texts_with_spec_returns_unit_vectors_when_normalize_true():
    spec = get_spec("bge-large")
    vectors = embedder.embed_texts_with_spec(["hello", "world"], spec)
    arr = np.asarray(vectors)
    assert arr.shape == (2, spec.dim)
    norms = np.linalg.norm(arr, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_embed_texts_with_spec_uses_spec_default_batch_size():
    spec = get_spec("bge-base")
    embedder.embed_texts_with_spec(["a"], spec)
    call = _FakeSentenceTransformer.encode_calls[-1]
    assert call["batch_size"] == spec.default_batch_size


def test_embed_texts_with_spec_explicit_batch_size_overrides_default():
    spec = get_spec("bge-base")
    embedder.embed_texts_with_spec(["a"], spec, batch_size=7)
    call = _FakeSentenceTransformer.encode_calls[-1]
    assert call["batch_size"] == 7


def test_embed_texts_with_spec_passes_normalize_to_encode():
    spec = get_spec("pubmedbert-msmarco")
    embedder.embed_texts_with_spec(["a"], spec)
    call = _FakeSentenceTransformer.encode_calls[-1]
    assert call["normalize_embeddings"] is True


def test_embed_texts_with_spec_does_not_prepend_query_prefix():
    """passage(corpus) 측에는 BGE query prefix를 붙이지 않는다 — asymmetric encoding."""
    spec = get_spec("bge-large")
    embedder.embed_texts_with_spec(["passage content"], spec)
    call = _FakeSentenceTransformer.encode_calls[-1]
    assert call["texts"] == ["passage content"]
    assert not call["texts"][0].startswith(spec.query_prefix)


def test_embed_texts_with_spec_dim_matches_spec():
    for key in ("bge-large", "bge-base", "pubmedbert-msmarco"):
        embedder._model_cache.clear()
        spec = get_spec(key)
        vectors = embedder.embed_texts_with_spec(["x"], spec)
        assert len(vectors[0]) == spec.dim


# ── embed_chunks_with_spec ─────────────────────────────────────────────────


def _chunk(pmid: str, content: str = "x") -> Chunk:
    return Chunk(
        paper_pmid=pmid,
        paper_title=f"title-{pmid}",
        section_name="abstract",
        chunk_index=0,
        content=content,
        token_count=10,
    )


def test_embed_chunks_with_spec_returns_pairs():
    spec = get_spec("bge-large")
    chunks = [_chunk("100"), _chunk("200")]
    pairs = embedder.embed_chunks_with_spec(chunks, spec)
    assert len(pairs) == 2
    for chunk, vec in pairs:
        assert isinstance(chunk, Chunk)
        assert len(vec) == spec.dim


def test_embed_chunks_with_spec_empty_returns_empty():
    spec = get_spec("bge-large")
    assert embedder.embed_chunks_with_spec([], spec) == []


# ── Backward-compat: 기존 embed_chunks/embed_texts ──────────────────────────


def test_legacy_embed_texts_delegates_to_default_spec():
    """기존 호출자: embed_texts(texts)는 default spec(bge-large)으로 위임."""
    vectors = embedder.embed_texts(["a", "b"])
    arr = np.asarray(vectors)
    default_spec = get_spec(DEFAULT_MODEL_KEY)
    assert arr.shape == (2, default_spec.dim)
    # 정규화 강제됨
    np.testing.assert_allclose(np.linalg.norm(arr, axis=1), 1.0, atol=1e-5)
    # 모델 로드는 default spec의 hf_name으로 1회만
    assert len(_FakeSentenceTransformer.instances_created) == 1
    assert _FakeSentenceTransformer.instances_created[0][0] == default_spec.hf_name


def test_legacy_embed_chunks_delegates_to_default_spec():
    """기존 호출자: embed_chunks(chunks)는 default spec(bge-large)으로 위임."""
    chunks = [_chunk("100"), _chunk("200")]
    pairs = embedder.embed_chunks(chunks)
    assert len(pairs) == 2
    default_spec = get_spec(DEFAULT_MODEL_KEY)
    for _, vec in pairs:
        assert len(vec) == default_spec.dim


def test_legacy_get_model_delegates_to_default_spec():
    model = embedder._get_model()
    default_spec = get_spec(DEFAULT_MODEL_KEY)
    assert isinstance(model, _FakeSentenceTransformer)
    assert model.hf_name == default_spec.hf_name


def test_legacy_embed_texts_explicit_batch_size_preserved():
    """기존 batch_size=32 인자 호출도 그대로 전달되어야 한다 (시그니처 유지)."""
    embedder.embed_texts(["a"], batch_size=32)
    call = _FakeSentenceTransformer.encode_calls[-1]
    assert call["batch_size"] == 32


def test_isinstance_check_for_spec_type():
    """EmbeddingModelSpec 임포트가 깨지지 않는지 sanity check."""
    spec = get_spec("bge-large")
    assert isinstance(spec, EmbeddingModelSpec)
