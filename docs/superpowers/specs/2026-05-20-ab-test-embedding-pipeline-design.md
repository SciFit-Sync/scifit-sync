# 임베딩 모델 A/B 비교 파이프라인 설계 (2026-05-20)

## 1. 배경과 목적

현재 운영 중인 RAG retrieval 품질 문제의 원인 후보 중 "임베딩 모델 한계"를 확정 또는 배제하기 위해 동일 corpus 위에서 3개 임베딩 모델을 동일 골드셋으로 측정한다.

**비교 대상**

| key | HuggingFace ID | dim | 비고 |
|---|---|---|---|
| bge-large | BAAI/bge-large-en-v1.5 | 1024 | 현재 운영 모델 |
| bge-base | BAAI/bge-base-en-v1.5 | 768 | 속도 비교용 |
| pubmedbert-msmarco | pritamdeka/S-PubMedBert-MS-MARCO | 768 | 의학 도메인 특화 |

**측정 지표**: recall@5, recall@10, MRR (기존 `mlops/eval/run_eval.py`가 산출), 모델별 임베딩 소요 시간 (신규 timing.json 사이드카).

## 2. 핵심 결정 사항 (브레인스토밍 합의)

1. **단일 진입점 + `--test` 플래그**: 운영용(default)과 품질 비교용(test)을 한 스크립트에서 처리. 운영 경로는 가볍게 유지.
2. **chunks 산출물 항상 별도 저장**: default 모드에서도 chunks JSONL을 분리 저장하여 추후 모델 비교 시 재크롤 없이 회수 가능.
3. **Python registry로 모델 metadata 관리**: `mlops/eval/models.py`에 dataclass + dict. CLI는 짧은 key로 참조.
4. **batch-tag 기반 산출물 경로**: 모든 산출물 파일명에 `<batch-tag>`를 일관 적용. 모델 디렉토리는 `emb_<model-key>/` 형태로 분리.
5. **기존 `run_eval.py` 스켈레톤 재사용**: Retriever 인터페이스가 이미 decouple되어 있어 `_build_inmem_retriever()` 추가만으로 모델 swap 가능.
6. **fail-fast + 산출물 overwrite 보호**: 같은 batch-tag 산출물이 있으면 명시적 `--overwrite` 없이는 거부.

## 3. 아키텍처

### 기존 embedder.py 리팩토링 (critical)

현재 `mlops/pipeline/embedder.py`의 `_get_model()`은 `config.EMBEDDING_MODEL` 전역 + `_model` 싱글턴을 사용해서 한 프로세스에서 한 모델만 다룬다(`embedder.py:16-28`). test 모드의 모델 N개 순회는 이 구조에서 불가능하다.

**변경 범위**:

```python
# mlops/pipeline/embedder.py (수정)

_model_cache: dict[str, SentenceTransformer] = {}   # hf_name → model

def _get_model_by_spec(spec: EmbeddingModelSpec) -> SentenceTransformer:
    """spec 기반 모델 로드 + 캐시. 기존 _get_model은 default spec으로 위임."""
    if spec.hf_name not in _model_cache:
        device = _resolve_device()
        _model_cache[spec.hf_name] = SentenceTransformer(spec.hf_name, device=device)
    return _model_cache[spec.hf_name]


def embed_texts_with_spec(
    texts: list[str],
    spec: EmbeddingModelSpec,
    batch_size: int | None = None,
) -> list[list[float]]:
    """spec.normalize=True면 normalize_embeddings=True로 인코딩. corpus/query 정규화 일관성 보장."""
    model = _get_model_by_spec(spec)
    bs = batch_size or spec.default_batch_size
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
) -> list[tuple[Chunk, list[float]]]: ...

# 기존 embed_chunks(chunks) / embed_texts(texts)는 default spec(bge-large)으로 위임 — backward-compat
```

`config.EMBEDDING_DIM` 전역 사용도 같이 정리한다 (spec.dim으로 대체). `config.EMBEDDING_MODEL`은 default spec 결정용으로만 남기거나 registry의 `DEFAULT_MODEL_KEY`로 대체.

### 진입점과 모듈 의존성

```
mlops/scripts/export_embeddings.py    ←── 단일 진입점 (default + test)
       │
       ├─ default 모드: --model <key> 필수
       │     crawl → chunk → save_chunks → embed(model) → save_embeddings
       │
       └─ --test 모드: --goldset 필수
             crawl → chunk → save_chunks
             for each model in selected_targets:
                 embed → save_embeddings
                 run_eval.main() → save_report
             stderr summary

mlops/eval/models.py                  ←── 신규 registry
mlops/eval/run_eval.py                ←── 확장 (inmem retriever + CLI 플래그)
mlops/eval/reports/                   ←── 기존 디렉토리
```

**의존 방향**: `export_embeddings`가 `eval.models`와 `eval.run_eval`을 import. 역방향 의존 없음.

### 산출물 경로 (자동 결정)

```
mlops/data/
├── chunks/
│   └── <batch-tag>.jsonl.gz                    # 모델 간 공유 입력
│
├── emb_<model-key>/
│   ├── <batch-tag>.jsonl.gz                    # Chunk 메타 + embedding
│   └── <batch-tag>_timing.json                 # 모델/시간/디바이스 사이드카
│
└── manifest.json                               # 기존 그대로

mlops/eval/reports/
└── <batch-tag>_<model-key>.md                  # test 모드에서만
```

**timing.json 스키마**
```json
{
  "model_key": "bge-large",
  "hf_name": "BAAI/bge-large-en-v1.5",
  "dim": 1024,
  "n_chunks": 48732,
  "batch_size": 64,
  "device": "cuda",
  "total_sec": 1083.41,
  "sec_per_batch_mean": 0.34,
  "sec_per_batch_p95": 0.51,
  "query_prefix": "Represent this sentence for searching relevant passages: ",
  "normalize_embeddings": true,
  "started_at": "2026-05-20T12:00:00Z",
  "finished_at": "2026-05-20T12:18:03Z"
}
```

## 4. 모델 Registry 스키마

```python
# mlops/eval/models.py
from dataclasses import dataclass

@dataclass(frozen=True)
class EmbeddingModelSpec:
    key: str                   # CLI 짧은 이름
    hf_name: str               # HuggingFace 모델 ID
    dim: int                   # 임베딩 차원
    query_prefix: str          # query 측 prepend (빈 문자열이면 대칭 인코딩)
    normalize: bool = True     # encode 시 normalize_embeddings
    default_batch_size: int = 64

EMBEDDING_MODELS: dict[str, EmbeddingModelSpec] = {
    "bge-large": EmbeddingModelSpec(
        key="bge-large",
        hf_name="BAAI/bge-large-en-v1.5",
        dim=1024,
        query_prefix="Represent this sentence for searching relevant passages: ",
        default_batch_size=64,
    ),
    "bge-base": EmbeddingModelSpec(
        key="bge-base",
        hf_name="BAAI/bge-base-en-v1.5",
        dim=768,
        query_prefix="Represent this sentence for searching relevant passages: ",
        default_batch_size=128,
    ),
    "pubmedbert-msmarco": EmbeddingModelSpec(
        key="pubmedbert-msmarco",
        hf_name="pritamdeka/S-PubMedBert-MS-MARCO",
        dim=768,
        query_prefix="",
        default_batch_size=128,
    ),
}

DEFAULT_MODEL_KEY = "bge-large"

def get_spec(key: str) -> EmbeddingModelSpec: ...
def list_test_targets() -> list[EmbeddingModelSpec]: ...   # 전체 registry 반환
```

**`normalize=True` 정책 결정**: 세 모델 모두 `normalize=True`로 고정한다. BGE 모델은 HF 카드에서 cosine 검색 시 정규화 권장. PubMedBERT-MS-MARCO는 카드에 명시 없음 → cosine 의미가 보존되도록 일괄 정규화로 통일. corpus(export)와 query(retriever) 양쪽 모두에 동일 적용되어야 점수 왜곡 없음. 이 정책 변경은 위 `embedder.py` 리팩토링에서 강제된다.

## 5. CLI 표면

```bash
# Default 모드 — 단일 모델 임베딩 파일 생성
python -m mlops.scripts.export_embeddings \
  --model bge-large \
  --batch-tag 2k_round1 \
  --max-papers 2000 \
  --update-manifest

# Test 모드 — 멀티 모델 임베딩 + 자동 평가
python -m mlops.scripts.export_embeddings \
  --test \
  --batch-tag 2k_round1 \
  --max-papers 2000 \
  --goldset mlops/eval/gold_set.jsonl
# --models a,b 로 부분 선택, 생략 시 registry 전체
```

### 인자 매트릭스

| 인자 | default 모드 | test 모드 | 비고 |
|---|---|---|---|
| `--model <key>` | 필수 | 무시 (지정 시 경고) | registry key |
| `--models a,b,c` | 무시 | 선택 (생략=전체) | |
| `--test` | — | 트리거 | |
| `--goldset <path>` | 무시 | 선택 (default: `mlops/eval/gold_set.jsonl`) | 파일 없으면 fail-fast |
| `--batch-tag <str>` | 필수 | 필수 | 산출물 식별자 |
| `--max-papers` | 기존 | 기존 | |
| `--max-per-category` | 기존 | 기존 | |
| `--min-date` / `--max-date` | 기존 | 기존 | |
| `--update-manifest` | 기존 | 기존 | |
| `--reuse-chunks` | chunks 있으면 재사용 | 동일 | |
| `--chunks-only` | 임베딩 skip | 무시 | Stage 1만 실행 |
| `--batch-size <int>` | spec.default_batch_size override | 동일 | |
| `--overwrite` | 산출물 덮어쓰기 허용 | 동일 | 기본은 거부 |
| `--require-gpu` | cuda 없으면 error | 동일 | 긴 작업 보호 |
| `--strict-goldset` | 무시 | 누락 PMID 1개라도 있으면 error | |
| `--output` | **제거** | — | batch-tag 기반 자동 경로 |

### 기존 호출자 영향

- `mlops/run_local_2k.sh`: `--output` 인자 제거 + `--batch-tag` + `--model` 추가하도록 동시 업데이트.

## 6. 에러/예외 정책

### 시작 전 fail-fast

1. `--batch-tag` 미지정 → error
2. default 모드 + `--model` 미지정 → error
3. `--model` / `--models` registry에 없음 → error + 가용 key 목록 출력
4. `--test` + goldset 파일 없음 → error
5. `--test` + goldset JSON 파싱 실패 → error
6. 산출물 경로 이미 존재 + `--overwrite` 없음 → error
7. `--require-gpu` + cuda False → error

### 중간 실패 격리

| 단계 | default | test |
|---|---|---|
| 크롤링 전체 실패 | 즉시 종료 | 즉시 종료 |
| 청킹 실패 | 즉시 종료 | 즉시 종료 |
| chunks JSONL 쓰기 실패 | 즉시 종료 | 즉시 종료 |
| 모델 로드 실패 | 즉시 종료 | 해당 모델 skip + stderr 기록, 다음 모델 진행 |
| 임베딩 도중 OOM | 즉시 종료 | 동일 (해당 모델 skip) |
| eval retriever 실패 | — | 해당 모델 리포트 skip, 다른 모델 진행 |
| eval 개별 query 실패 | — | 기존 `run_evaluation` 패턴 그대로 (해당 query skip) |

### Overwrite 조합 매트릭스

```
                  chunks 있음                chunks 없음
--reuse-chunks    chunks skip + embed        crawl + chunk + embed
없음              error (overwrite 충돌)     crawl + chunk + embed
--overwrite       chunks 재생성 + embed      동일
```

embeddings/reports 충돌도 동일 정책: 기본은 거부, `--overwrite`로 허용.

**test 모드 모델별 충돌 처리**: test 모드에서 N개 모델 중 일부 모델의 산출물(`emb_<key>/<tag>.jsonl.gz`)만 이미 있을 경우, `--overwrite` 없으면 전체 실행 중단(fail-fast). 부분 진행 후 일관성 깨지는 상태를 만들지 않는다. 부분 재실행을 원하면 사용자가 해당 디렉토리를 수동 삭제 후 재실행하거나 `--overwrite` 명시.

**`--update-manifest` 동작 (기존 안전장치 유지)**: 기본 OFF. 사용자가 명시할 때만 chunks JSONL 작성 직후 1회 갱신. **기본 OFF 정책은 기존 `export_embeddings.py:170-175`의 의도와 일치** — 임베딩/적재 도중 실패해도 manifest가 깨끗하면 동일 DOI로 재시도 가능. test 모드에서도 동일.

**Eval 행렬 메모리 정책**: in-memory retriever는 `(N_chunks, dim) float32` 행렬을 한 번에 적재. 2k papers ≈ 50k chunks × 1024d × 4B = **약 200MB**로 16GB+ RAM 환경에서 안전. 코퍼스가 10k papers 이상으로 커지면 GB 단위 적재가 되므로 별도 정책 필요 (mmap 또는 청크 streaming) — **본 PR 비범위**. 현재 사용 corpus 규모(2k)에서는 단순 적재가 정답.

### Goldset coverage 자동 검증 (test 모드)

- chunks 생성 직후 `expected_pmids` ⊈ corpus PMIDs 차집합 계산.
- 누락 PMID 있으면 WARNING + 리포트 footer에 명시: "주의: 골드셋 N문항 중 PMID K개가 corpus에 없음 → recall@10 상한 자연 감소".
- `--strict-goldset` 시 누락 1개라도 있으면 error.

### Test 모드 종료 summary (stderr)

```
=== Test 결과 (batch-tag=2k_round1) ===
  bge-large            : 임베딩 18m / eval recall@10=0.62 mrr=0.41
  bge-base             : 임베딩  7m / eval recall@10=0.58 mrr=0.38
  pubmedbert-msmarco   : 임베딩  9m / eval recall@10=0.71 mrr=0.49
리포트: mlops/eval/reports/2k_round1_*.md
```

## 7. `run_eval.py` 확장

### A/B 평가 의미론 — `evidence_weight` 의도적 배제

운영 `server/app/services/rag.py::search_chunks()`는 `similarity × evidence_weight`로 청크를 재정렬한다(RCT/Review 등 publication_types 가중치). 그러나 이번 A/B의 목적은 **임베딩 모델의 순수 의미 검색 품질** 비교이므로, in-memory retriever는 `evidence_weight`를 **반영하지 않는다**.

영향: in-memory retriever 결과는 운영 production retrieval과 다를 수 있다. 본 A/B에서는 이 차이가 의도된 isolation이며, 만약 모델 교체 후 production parity를 검증하려면 별도 단계(현재 본 PR 비범위)에서 `evidence_weight` 재정렬을 입힌 retriever로 추가 평가가 필요하다.

### `_build_inmem_retriever`

```python
def _build_inmem_retriever(
    embeddings_path: Path,
    model_key: str,
) -> Retriever:
    """JSONL.gz에서 청크 메타+embedding 로드 → 메모리 cosine retrieval.

    모델별 dim이 달라도 Chroma 재적재 없이 즉시 검증 가능.
    """
    spec = get_spec(model_key)
    # _resolve_device는 기존 mlops/pipeline/embedder.py의 함수를 재사용.
    # 두 파일에서 import 가능하도록 mlops/pipeline/_device.py (또는 동일 모듈)로 노출.
    from mlops.pipeline.embedder import _resolve_device
    model = SentenceTransformer(spec.hf_name, device=_resolve_device())

    # 1) embeddings.jsonl.gz 한 번에 로드 → (N, dim) float32 matrix + metas
    matrix, metas = _load_embeddings_jsonl(embeddings_path, expected_dim=spec.dim)
    # normalize 가정: spec.normalize=True면 이미 단위 벡터. 아니면 여기서 정규화.

    def _retrieve(query: str, top_k: int) -> list[dict]:
        q = (spec.query_prefix + query) if spec.query_prefix else query
        qvec = model.encode(q, normalize_embeddings=spec.normalize)
        # cosine = dot product (벡터들이 정규화됨)
        scores = matrix @ qvec
        top_idx = scores.argsort()[::-1][:top_k]
        return [
            {
                "pmid": metas[i].get("paper_pmid", ""),
                "title": metas[i].get("paper_title", ""),
                "section": metas[i].get("section_name", ""),
                "score": float(scores[i]),
            }
            for i in top_idx
        ]

    return _retrieve
```

### `run_eval.py` CLI 추가

```bash
python -m mlops.eval.run_eval \
  --goldset mlops/eval/gold_set.jsonl \
  --retriever inmem \
  --embeddings-file mlops/data/emb_bge-large/2k_round1.jsonl.gz \
  --model-key bge-large \
  --output mlops/eval/reports/2k_round1_bge-large.md
```

- `--retriever {chroma,inmem}` (default: chroma, 기존 호환)
- `--embeddings-file` (inmem 시 필수)
- `--model-key` (inmem 시 필수, registry에서 query_prefix/normalize 조회)

기존 `_build_chroma_retriever` 흐름은 그대로 유지.

## 8. 테스트 전략

### 신규/수정 테스트 파일

| 파일 | 종류 | 범위 |
|---|---|---|
| `mlops/tests/test_eval_models.py` | 신규 | get_spec / KeyError / list_test_targets / 모든 spec dim>0 / **BGE 두 모델은 query_prefix 비어있지 않음 / PubMedBERT는 비어있음** / **모든 spec.normalize == True** |
| `mlops/tests/test_eval_run_eval.py` | 확장 | `_build_inmem_retriever` 단위 (numpy mock + 작은 fixture). **fixture에 1줄 malformed 포함 → ValueError raise 검증**. **query_prefix 적용 여부 검증 (BGE에 prefix prepend 되는지, PubMedBERT는 안 붙는지)** |
| `mlops/tests/test_export_embeddings.py` | 신규 | CLI 분기, fail-fast 9가지, 산출물 경로, overwrite/reuse-chunks 흐름. **추가 케이스: ① N 모델 중 일부만 emb_<key>/<tag>.jsonl.gz 존재 시 --overwrite 없으면 fail-fast / ② --strict-goldset + 누락 PMID 있으면 error / ③ 정규화 일관성: export된 embedding이 unit vector인지 검증 (norm ≈ 1.0)** |
| `mlops/tests/test_embedder_spec.py` | 신규 | 새 `embed_chunks_with_spec` / `embed_texts_with_spec` 단위. **spec.normalize=True 적용 시 결과 norm ≈ 1.0** / 모델 캐시 동작 (같은 spec 2회 호출 시 1회만 로드) |

### Mock 전략 (외부 의존성 차단)

- `crawl_papers`, `chunk_papers`: monkeypatch → 픽스처 반환
- `mlops.pipeline.embedder._get_model`: fake model.encode → 결정론적 random (seed 고정)
- `run_eval.main`: export_embeddings 측에서 monkeypatch (호출 카운트/인자 검증), eval 자체는 자기 테스트로 격리
- HuggingFace 다운로드: 위 _get_model mock으로 차단

### Fixture

```
mlops/tests/fixtures/
├── chunks_tiny.jsonl              # 5 chunks (PMID 100×2, 200×2, 300×1)
└── gold_set_tiny.jsonl            # 2 queries (Q1→100, Q2→200,300)
```

### Integration test (end-to-end with all mocks)

`test_export_embeddings.py::test_test_mode_end_to_end`
- 임시 디렉토리 + fixture chunks 사전 배치 + gold_set fixture
- `main(["--test", "--batch-tag", "tiny", "--goldset", "...", "--reuse-chunks"])` 실행
- 검증:
  - `tmpdir/chunks/tiny.jsonl.gz` 존재
  - `tmpdir/emb_<key>/tiny.jsonl.gz` × 3 존재
  - `tmpdir/emb_<key>/tiny_timing.json` × 3 존재, 키 완비
  - `mlops/eval/reports/tiny_<key>.md` × 3 존재, "recall@" 포함
  - stderr summary에 3 모델 라인

### 커버리지 목표

- `mlops/eval/models.py` 100%
- `mlops/eval/run_eval.py::_build_inmem_retriever` 100%
- `mlops/scripts/export_embeddings.py` 변경 영역 90%+

### CI 영향

- mock 기반이라 GPU/HF/NCBI 미접근 → 기존 CI 통과 보장
- ruff format/lint 통과 필수
- `.gitignore`에 `mlops/data/chunks/`, `mlops/data/emb_*/` 패턴 추가

## 9. 산출물 크기 예상

| 산출물 | 추정 크기 (2000 papers, ~50k chunks) |
|---|---|
| `chunks/<tag>.jsonl.gz` | ~50~80 MB |
| `emb_bge-large/<tag>.jsonl.gz` (1024d) | ~250 MB |
| `emb_bge-base/<tag>.jsonl.gz` (768d) | ~180 MB |
| `emb_pubmedbert-msmarco/<tag>.jsonl.gz` (768d) | ~180 MB |
| **test 모드 1회 합계** | **~660 MB** |

git LFS 미사용 — `.gitignore`로 모두 제외하고 GPU 서버 보관.

## 10. 비범위 (이번 PR에서 안 다룸)

- **gold_set.jsonl 작성**: 도메인 큐레이션 작업. 이 설계서의 인프라 머지 후 별도 진행.
- **server/app/services/rag.py의 모델 교체**: test 결과로 모델이 확정되면 후속 PR에서 server 측 query embedding 코드도 같은 registry를 import하도록 마이그레이션.
- **ChromaDB 재적재**: in-memory retriever를 쓰므로 Chroma는 운영 retrieval에만 사용. test 모드는 Chroma 우회.
- **batch-tag 자동 생성**: 명시적 필수 인자로 유지. 사용자가 의미있는 이름을 부여하는 것이 산출물 추적에 유리.

## 11. 작업 순서 요약

1. `mlops/eval/models.py` 신규 (registry) — 다른 단계의 import 의존
2. `mlops/pipeline/embedder.py` 리팩토링 (spec 기반 multi-model + 정규화 강제) — registry import
3. `mlops/eval/run_eval.py` 확장 (`_build_inmem_retriever` + `--retriever` CLI 플래그)
4. `mlops/scripts/export_embeddings.py` 대규모 수정 (CLI 재설계, --test 분기, 산출물 경로, registry 사용)
5. `mlops/run_local_2k.sh` 업데이트 (`--batch-tag` + `--model` 사용)
6. 테스트 추가 (models / embedder_spec / run_eval inmem / export_embeddings)
7. `.gitignore` 패턴 추가 (`mlops/data/chunks/`, `mlops/data/emb_*/`)
8. ruff format + 전체 테스트 통과 확인
9. GPU 서버에서 default 모드로 운영 검증 (bge-large + 2000 papers 1회)
10. (golden set 완성 후) test 모드 1회 실행 → 비교 리포트 생성

## 12. Codex 리뷰 반영 이력 (2026-05-20)

초안 작성 후 codex 외부 리뷰 1회 진행. 다음 critical/significant 이슈를 본 문서에 반영함:

- **(Critical)** `embedder.py` 싱글턴 + 전역 `EMBEDDING_MODEL`/`EMBEDDING_DIM` 구조 → 다중 모델 순회 불가. § 3에 리팩토링 범위 명시.
- **(Critical)** corpus 정규화 누락 → query만 정규화되면 cosine 점수 왜곡. § 3 리팩토링과 § 4에서 `spec.normalize=True` 일괄 적용 정책 명시.
- **(Critical)** HF 모델 ID 오타 `PubMedBERT-MS-MARCO` → 실제 `S-PubMedBert-MS-MARCO`로 정정 (curl 200/401 검증 완료).
- **(Significant)** `evidence_weight` 미반영 → A/B는 임베딩 의미 비교에 한정, 운영 retrieval과 의도적 isolation. § 7에 명시.
- **(Significant)** `--update-manifest` 기본 OFF 유지 — 적재 실패 시 재시도 안전장치. § 6 명시.
- **(Significant)** eval 행렬 OOM — 2k corpus는 ~200MB로 안전. 10k+ 확장 시 별도 정책. § 6 명시.
- **(Significant)** PubMedBERT normalize 정책 근거 — 카드 명시 없음. cosine 의미 보존 위해 일괄 True 적용. § 4 명시.
- **(Nit)** 테스트 누락: prefix/normalize 계약, malformed embedding line, --strict-goldset, partial-output fail-fast → § 8에 추가.

코덱스 nit 중 "별도 `run_inmem_eval.py` vs `--retriever` 플래그" 의견은 **플래그 채택 유지** — 신규 파일과 별도 테스트 모듈을 만드는 비용보다 플래그 30LOC 추가가 단순. 단 기존 chroma 흐름의 기본 동작은 그대로 유지하여 backward-compat 보장.
