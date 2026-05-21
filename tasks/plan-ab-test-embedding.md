# Implementation Plan — A/B Embedding Pipeline

> 대응 설계서: [`docs/superpowers/specs/2026-05-20-ab-test-embedding-pipeline-design.md`](../docs/superpowers/specs/2026-05-20-ab-test-embedding-pipeline-design.md)
> 작성일: 2026-05-20
> 대상 브랜치 (구현 시): `feature/jingyu/mlops-ab-test-embedding` (아직 미생성 — handoff 문서 참조)

## 진행 원칙

- 각 Phase는 **테스트와 함께 커밋 1개**로 구성 (atomic commit).
- 모든 Phase는 ruff format/lint + `pytest mlops/tests -v` 통과 후 다음으로 진행.
- 외부 API/HF 다운로드/GPU는 mock으로 차단 (CLAUDE.md CI 규칙).
- 절대 금지: backward-compat 깨기, 임의 산출물 덮어쓰기, manifest 자동 갱신 기본화.

---

## Phase 1 — Model Registry

**목표**: 모델 metadata 한 곳에서 관리. 다른 Phase의 import 의존이므로 가장 먼저.

### 변경
- 신규: `mlops/eval/models.py`
  - `EmbeddingModelSpec` dataclass (key, hf_name, dim, query_prefix, normalize, default_batch_size)
  - `EMBEDDING_MODELS` dict — bge-large / bge-base / pubmedbert-msmarco (HF ID: `pritamdeka/S-PubMedBert-MS-MARCO`)
  - `DEFAULT_MODEL_KEY = "bge-large"`
  - `get_spec(key) -> EmbeddingModelSpec` — invalid key 시 KeyError + 메시지에 가용 key 목록
  - `list_test_targets() -> list[EmbeddingModelSpec]` — registry 전체

### 테스트
- 신규: `mlops/tests/test_eval_models.py`
  - `get_spec` 정상/KeyError
  - `list_test_targets` 길이 == 3
  - 모든 spec dim > 0
  - BGE 두 모델 query_prefix 비어있지 않음
  - PubMedBERT query_prefix == ""
  - **모든 spec.normalize == True**

### 검증
- `pytest mlops/tests/test_eval_models.py -v` 100% 통과
- 커버리지 `mlops/eval/models.py` 100%

### 커밋 메시지
```
feat: mlops 임베딩 모델 registry 추가

- EmbeddingModelSpec dataclass + EMBEDDING_MODELS dict
- BGE-large / BGE-base / PubMedBERT-MS-MARCO 3개 등록
- query_prefix·normalize·default_batch_size를 spec에 일원화
```

---

## Phase 2 — embedder.py 리팩토링 (multi-model + 정규화)

**목표**: 한 프로세스에서 여러 모델을 캐싱하며 사용 + corpus/query 정규화 일관성.

### 변경
- 수정: `mlops/pipeline/embedder.py`
  - 기존 `_model` 단일 싱글턴 → `_model_cache: dict[str, SentenceTransformer]`
  - 신규 `_get_model_by_spec(spec: EmbeddingModelSpec)` — hf_name으로 캐시
  - 신규 `embed_texts_with_spec(texts, spec, batch_size=None)` — `normalize_embeddings=spec.normalize` 적용
  - 신규 `embed_chunks_with_spec(chunks, spec, batch_size=None)`
  - 기존 `embed_chunks(chunks)` / `embed_texts(texts)` → default spec(bge-large)으로 위임 (backward-compat)
  - `_resolve_device()`는 그대로 사용
- 수정: `mlops/pipeline/config.py` (필요 시)
  - `EMBEDDING_MODEL` 환경변수는 default spec 결정용으로만 사용. registry의 DEFAULT_MODEL_KEY로 대체 검토.

### 테스트
- 신규: `mlops/tests/test_embedder_spec.py`
  - `SentenceTransformer` mock (encode → 결정론적 random)
  - 같은 spec 2회 호출 시 모델 로드 1회만 (캐시 검증)
  - 다른 spec 호출 시 새로 로드
  - `embed_texts_with_spec` 결과 norm ≈ 1.0 (normalize=True인 spec)
  - `embed_texts_with_spec` 결과 dim == spec.dim
- 기존 `mlops/tests/test_embedder*` 있다면 회귀 통과 확인

### 검증
- ruff + pytest 통과
- 기존 호출자(`mlops/scripts/export_embeddings.py`의 `embed_chunks` 호출)가 깨지지 않음 — 회귀 테스트 확인

### 커밋 메시지
```
refactor: embedder spec 기반 multi-model 지원

- _model_cache: hf_name → SentenceTransformer 캐싱
- embed_texts_with_spec / embed_chunks_with_spec 신규
- normalize_embeddings를 spec.normalize 기준으로 강제 — corpus/query 일관성
- 기존 embed_chunks/embed_texts는 default spec 위임 (backward-compat)
```

---

## Phase 3 — run_eval.py 확장 (in-memory retriever)

**목표**: Chroma 우회 인메모리 cosine retriever 추가. 모델별 dim이 달라도 즉시 평가 가능.

### 변경
- 수정: `mlops/eval/run_eval.py`
  - 신규 `_load_embeddings_jsonl(path, expected_dim) -> (matrix, metas)` — (N, dim) float32 + list of metadata dicts. malformed 줄 1개라도 발견 시 ValueError.
  - 신규 `_build_inmem_retriever(embeddings_path, model_key) -> Retriever`
    - spec = `get_spec(model_key)`
    - device = `_resolve_device()` (embedder에서 import)
    - 모델 로드 + matrix 로드 + cosine retrieval closure 반환
    - query에 `spec.query_prefix` prepend (있는 경우만)
    - `normalize_embeddings=spec.normalize` 적용
  - CLI 추가:
    - `--retriever {chroma,inmem}` (default: chroma)
    - `--embeddings-file <path>` (inmem 시 필수)
    - `--model-key <key>` (inmem 시 필수)
  - `main()` 분기 추가 (chroma는 기존 그대로)

### 테스트
- 수정: `mlops/tests/test_eval_run_eval.py`
  - 소규모 fixture 작성: `mlops/tests/fixtures/embeddings_tiny.jsonl` (5 청크, 미리 정규화된 벡터)
  - `_build_inmem_retriever` 단위 — query embedding mock + 결과가 cosine 순서대로 정렬되는지
  - query_prefix 적용 검증: BGE spec → encode 시 prefix 붙음 / PubMedBERT spec → 안 붙음 (encode 호출 인자 capture)
  - malformed JSONL 1줄 포함 → ValueError 발생
  - 기존 16개 테스트 모두 회귀 통과

### 검증
- ruff + pytest 통과
- 커버리지 `_build_inmem_retriever` 100%

### 커밋 메시지
```
feat: run_eval 인메모리 retriever + --retriever 플래그 추가

- _load_embeddings_jsonl + _build_inmem_retriever
- query prefix·normalize는 spec(registry)에서 조회
- CLI --retriever {chroma,inmem} --embeddings-file --model-key
- 기존 chroma 경로는 default 유지 (backward-compat)
```

---

## Phase 4 — export_embeddings.py 대규모 수정

**목표**: 단일 진입점에서 default 모드(단일 모델) / --test 모드(멀티 모델 + auto eval) 분기.

### 변경
- 수정: `mlops/scripts/export_embeddings.py`
  - CLI 추가/변경: `--model`, `--test`, `--models`, `--goldset`, `--batch-tag`, `--reuse-chunks`, `--chunks-only`, `--batch-size`, `--overwrite`, `--require-gpu`, `--strict-goldset`. `--output` 제거.
  - 산출물 경로 자동 결정: `mlops/data/chunks/<tag>.jsonl.gz`, `mlops/data/emb_<key>/<tag>.jsonl.gz`, `mlops/data/emb_<key>/<tag>_timing.json`
  - 시작 전 fail-fast 9가지 체크 (설계서 § 6)
  - default 모드: chunks 저장 → embed_chunks_with_spec(spec) → JSONL + timing.json
  - test 모드: chunks 저장 → for spec in selected: embed → run_eval.main() 호출하여 리포트 생성 → 마지막 stderr summary
  - goldset coverage 자동 검증 (test 모드, --strict-goldset)
  - `--update-manifest` 기본 OFF 유지

### 테스트
- 신규: `mlops/tests/test_export_embeddings.py`
  - `crawl_papers` / `chunk_papers` / `_get_model_by_spec` 모두 monkeypatch
  - default 모드 — 산출물 경로 검증, embedding norm ≈ 1.0
  - test 모드 — 3 모델 산출물 + 리포트 3개 + timing.json 3개 생성
  - fail-fast 9가지 — 각각 sys.exit / argparse error 검증
  - overwrite 보호: 기존 emb_<key>/<tag>.jsonl.gz 1개라도 있으면 --overwrite 없이 fail-fast
  - reuse-chunks: 기존 chunks 있으면 crawl 호출 안 됨 (monkeypatch 인자 capture)
  - --strict-goldset: 누락 PMID 있으면 error

### 검증
- ruff + pytest 통과
- 커버리지 변경 영역 90%+
- 기존 `test_crawler.py` 등 다른 테스트 회귀 통과

### 커밋 메시지
```
feat: export_embeddings --test 모드 + batch-tag 산출물 경로

- 단일 진입점에서 default 모드(단일 모델)/--test 모드(멀티+auto eval) 분기
- batch-tag 기반 산출물 경로 자동 결정 (chunks/ + emb_<key>/)
- fail-fast 9가지 사전 체크 + overwrite/reuse-chunks 정책
- registry(spec) 사용으로 정규화·prefix 일관 적용
- --update-manifest 기본 OFF 유지
```

---

## Phase 5 — run_local_2k.sh 업데이트 + .gitignore

**목표**: 기존 운영 스크립트가 새 CLI에 맞게 동작 + 대용량 산출물 git 격리.

### 변경
- 수정: `mlops/run_local_2k.sh`
  - 각 batch 호출 시 `--batch-tag local_batch${i} --model bge-large` 추가
  - `--output` 인자 제거
  - manifest 파일 처리 동일 (`--update-manifest`)
- 수정: `.gitignore`
  - `mlops/data/chunks/`
  - `mlops/data/emb_*/`
  - `mlops/eval/reports/*.md` (단, `mlops/eval/reports/README.md`는 유지 — 명시적 `!` 패턴)

### 테스트
- 셸 스크립트는 lint(shellcheck)만 가벼운 통과 — 단위 테스트 없음

### 검증
- 수동: shellcheck 통과
- 수동: `bash mlops/run_local_2k.sh --help` 같은 더미 호출이 깨지지 않음 (또는 --dry-run 옵션 있다면 활용)

### 커밋 메시지
```
chore: run_local_2k.sh를 batch-tag 기반 CLI에 맞춤 + 산출물 gitignore

- --output 제거, --batch-tag/--model 추가
- mlops/data/chunks/, mlops/data/emb_*/, eval/reports/*.md 제외
- README는 유지하도록 ! 패턴
```

---

## Phase 6 — GPU 서버 운영 검증

**목표**: default 모드가 GPU에서 정상 가동 + 산출물 무결.

### 절차
1. GPU 서버에서 `feature/jingyu/mlops-ab-test-embedding` 브랜치로 전환
2. venv는 [이전 결정 sibling 브랜치 `fix/jingyu/mlops-embedder-gpu-device`](https://github.com/SciFit-Sync/scifit-sync/tree/fix/jingyu/mlops-embedder-gpu-device) 머지된 develop 기반에서 CUDA torch 설치 완료된 상태여야 함
3. 실행:
   ```bash
   python -m mlops.scripts.export_embeddings \
     --model bge-large \
     --batch-tag verify_run1 \
     --max-papers 100 \
     --update-manifest
   ```
4. 검증:
   - `mlops/data/chunks/verify_run1.jsonl.gz` 생성
   - `mlops/data/emb_bge-large/verify_run1.jsonl.gz` 생성
   - `mlops/data/emb_bge-large/verify_run1_timing.json`에 `device: "cuda"` + `total_sec < 60` (100 papers 기준)
   - 첫 줄 embedding norm ≈ 1.0 (정규화 확인)
5. 산출물 정합성 통과하면 정식 운영 규모(2000편) 실행 진행

### 산출물
- 검증 로그를 `tasks/verify-ab-test-phase6.md`에 기록

---

## Phase 7 — Test 모드 실행 (gold_set 완성 후 별도 시점)

**전제**: `mlops/eval/gold_set.jsonl` 작성 완료 + 코퍼스 PMID coverage 검증.

### 실행
```bash
python -m mlops.scripts.export_embeddings \
  --test \
  --batch-tag abtest_v1 \
  --max-papers 2000 \
  --goldset mlops/eval/gold_set.jsonl \
  --reuse-chunks                       # 이미 chunks 있으면
```

### 산출물
- `mlops/data/chunks/abtest_v1.jsonl.gz`
- `mlops/data/emb_{bge-large,bge-base,pubmedbert-msmarco}/abtest_v1.jsonl.gz` × 3
- `mlops/data/emb_{bge-large,bge-base,pubmedbert-msmarco}/abtest_v1_timing.json` × 3
- `mlops/eval/reports/abtest_v1_{bge-large,bge-base,pubmedbert-msmarco}.md` × 3

### 분석 산출물
- `mlops/eval/reports/abtest_v1_summary.md` — 사람이 작성. 3 모델 recall@10/MRR/임베딩 시간 비교 + 결론 ("임베딩 한계" 확정/배제 + 권장 모델)

---

## 전체 의존성 그래프

```
Phase 1 (registry)
   └→ Phase 2 (embedder spec)
        └→ Phase 3 (run_eval inmem)   ─┐
        └→ Phase 4 (export_embeddings) ─┴→ Phase 5 (sh + gitignore) → Phase 6 (GPU 검증) → Phase 7 (test 모드)
```

Phase 3과 4는 Phase 2 완료 후 병렬 가능. 단 commit 단위는 분리.

## 예상 소요 시간

- Phase 1: 30분 (간단)
- Phase 2: 1.5시간 (caching + test mock)
- Phase 3: 2시간 (numpy retrieval + fixture)
- Phase 4: 3~4시간 (CLI 재설계가 가장 큰 변경)
- Phase 5: 30분
- Phase 6: 30분 + GPU 실행 시간
- Phase 7: gold_set 작성 시간 별도

**구현 1~5만 합산하면 약 1일치 작업.**
