# Handoff — A/B Embedding Pipeline (구현 재개 가이드)

> 작성일: 2026-05-20
> 작성자: jingyu (with Claude)
> 단계: **설계 완료, 구현 미시작**. 이 문서는 나중에 새 브랜치에서 구현을 시작할 때 컨텍스트를 잃지 않도록 준비된 핸드오프.

---

## 1. 현재 상태 (이 브랜치)

**브랜치**: `docs/jingyu/ab-test-embedding-design` (현재 작업 중인 브랜치)

**브랜치 상태**:
- 베이스: `develop` (commit 799f711)
- 추가 산출물 (커밋 예정):
  - `docs/superpowers/specs/2026-05-20-ab-test-embedding-pipeline-design.md` — 설계 + Codex 리뷰 반영
  - `tasks/plan-ab-test-embedding.md` — Phase별 implementation plan
  - `tasks/handoff-ab-test-embedding.md` — 이 문서

**관련 sibling 브랜치**: `fix/jingyu/mlops-embedder-gpu-device` (origin push 완료, 별개 PR 가능)
- 내용: embedder.py에 device 명시 + CPU fallback WARNING (GPU 서버 임베딩 가속 fix)
- 이 sibling 브랜치는 구현 시 develop에 머지되어 있어야 Phase 2의 baseline이 됨

---

## 2. 구현을 시작할 때 — 새 브랜치 생성 절차

```bash
# 0) 작업 디렉토리: /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync
cd /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync

# 1) 최신 develop으로 동기화
git fetch origin --prune
git checkout develop
git pull origin develop --ff-only

# 2) sibling 브랜치(GPU device fix)가 develop에 머지되었는지 확인
git log --oneline | grep "mlops 임베더 device" | head -1
# 없으면 PR 머지 후 다시 develop pull
# 있으면 다음으로

# 3) 구현용 새 브랜치 생성
git checkout -b feature/jingyu/mlops-ab-test-embedding

# 4) 설계서/플랜 가져오기 (docs 브랜치에서 cherry-pick OR PR이 develop에 머지됐다면 자동 포함)
#    이 docs 브랜치가 머지 안됐다면:
git cherry-pick <docs/jingyu/ab-test-embedding-design HEAD commit hash>
# 또는 docs 브랜치를 PR로 먼저 develop에 머지 → 새 브랜치는 자동으로 docs 포함
```

---

## 3. 컨텍스트 재로드 체크리스트

새 세션에서 시작할 때 다음 파일들을 순서대로 읽어서 컨텍스트를 복원:

1. **설계서 (필수)**: `docs/superpowers/specs/2026-05-20-ab-test-embedding-pipeline-design.md`
   - § 1~2: 배경과 핵심 결정 사항
   - § 12: Codex 리뷰에서 발견된 critical 이슈와 해결 방향
2. **구현 plan (필수)**: `tasks/plan-ab-test-embedding.md`
   - Phase별 변경/테스트/검증 기준 + 커밋 메시지 템플릿
3. **CLAUDE.md** (자동 로드됨): 프로젝트 규약, snake_case, ruff, mock API 등
4. **기존 코드 reference**:
   - `mlops/scripts/export_embeddings.py` — 가장 많이 수정될 파일
   - `mlops/pipeline/embedder.py` — 리팩토링 대상
   - `mlops/eval/run_eval.py` — 확장 대상
   - `mlops/tests/test_eval_run_eval.py` — 기존 테스트 패턴 참고
   - `mlops/pipeline/models.py` — Chunk 모델 구조

---

## 4. 시작 전 환경 검증

```bash
# 로컬 (개발용)
cd /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync
python3 -m pytest mlops/tests -v --co 2>&1 | tail -5    # 테스트 collection 깨지지 않는지
# (전체 실행은 시간 소요 — collection만 빠르게 확인)

# GPU 서버 (Phase 6에서 사용 — 미리 환경 준비)
ssh gpu-server   # 또는 직접 접속
cd /mnt/data/scifit-sync/scifit-sync
git fetch origin
git checkout develop && git pull
# venv는 이미 GPU torch 설치된 상태 (sibling 브랜치 fix 적용된 후 만든 .venv-gpu)
source .venv-gpu/bin/activate
python3 -c "import torch; assert torch.cuda.is_available(); print('OK')"
```

---

## 5. 구현 Phase 진행 가이드

Plan 문서의 Phase 1 → 7 순서대로 진행. 각 Phase 완료 시:

1. 해당 Phase의 테스트 통과 확인 (`pytest mlops/tests/test_<관련> -v`)
2. ruff format/lint (`ruff format mlops/ && ruff check mlops/`)
3. 커밋 (plan의 커밋 메시지 템플릿 사용, 자동 커밋 — CLAUDE.md 규칙)
4. 다음 Phase로 진행

**중요한 검증 포인트**:
- Phase 2 완료 후: 기존 `embed_chunks()` 호출자가 깨지지 않는지 (backward-compat)
- Phase 4 완료 후: 기존 `run_local_2k.sh`는 아직 옛 CLI를 호출하므로 Phase 5까지 같이 진행해야 함 — 둘을 한 PR로 묶거나 Phase 4+5 후 한 번에 머지
- Phase 6: GPU 서버에서 small batch(100편) 운영 검증 통과 후 정식 머지

---

## 6. 알려진 미해결 / 별도 작업

- **gold_set.jsonl 작성**: 도메인 큐레이션 필요. Phase 7 실행 전에 별도 작업으로 진행 (Plan § Phase 7 참조).
- **server/app/services/rag.py 모델 교체**: Phase 7 결과로 모델 확정되면 server 측 query embedding도 같은 registry 사용하도록 마이그레이션 (이번 PR 비범위).
- **chunks corpus PMID coverage**: Phase 6 검증 후 chunks corpus의 PMID 목록을 추출해 두면, gold_set 큐레이션 시 "이 corpus에 있는 PMID만" 골라 expected_pmids로 사용 가능.

---

## 7. 리스크와 주의 사항

1. **Phase 2 (embedder 리팩토링)** — 가장 위험. 기존 호출자 회귀를 반드시 테스트.
   - 회귀 발생 시: `embed_chunks(chunks)` / `embed_texts(texts)` 시그니처/동작 확인
2. **HF 모델 첫 다운로드**: PubMedBERT-MS-MARCO는 약 ~400MB. GPU 서버에 캐시 디렉토리 확보(`~/.cache/huggingface/`). 사전 다운로드 권장.
3. **정규화 정책 변경**: Phase 2에서 export 단계 정규화가 강제됨. 만약 ChromaDB 기존 데이터가 비정규화 상태로 적재되어 있다면, A/B 평가용 inmem retriever는 영향 없지만 운영 retrieval에서는 영향 있을 수 있음.
   - 영향 확인: 운영 retrieval 점수 분포가 [0, 1] 범위인지 모니터링. 이상 있으면 ChromaDB 재적재 필요(이번 PR 비범위).
4. **batch-tag 충돌**: 같은 tag로 여러 번 실행할 때 fail-fast 정책이 동작. 디버깅 시에는 `--overwrite` 또는 다른 tag 사용.

---

## 8. 새 세션 시작 시 첫 메시지 템플릿 (사용자 → Claude)

새로운 Claude 세션을 열어 구현을 시작할 때 다음 메시지로 시작하면 컨텍스트가 가장 빠르게 복원됨:

```
A/B 임베딩 파이프라인 구현 시작.
- 설계서: docs/superpowers/specs/2026-05-20-ab-test-embedding-pipeline-design.md
- Plan: tasks/plan-ab-test-embedding.md
- Handoff: tasks/handoff-ab-test-embedding.md

handoff 문서의 § 2 절차대로 새 브랜치 feature/jingyu/mlops-ab-test-embedding 생성 후 Phase 1부터 진행.
```

---

## 9. 참조 PR / 이슈

- (현재까지) 관련 PR 없음
- 관련 sibling 브랜치: `fix/jingyu/mlops-embedder-gpu-device` (GPU device fix)
- 관련 메모리/observation: claude-mem S2860, S2867 (elink-sanitize 작업 직후 진행됨)
