# Phase 2 실행 Runbook — RAG 데이터 정상화 전면 재처리

> 운영 가이드. design spec `docs/superpowers/specs/2026-05-28-rag-data-normalization-design.md` §3 + plan `docs/superpowers/plans/2026-05-28-rag-data-normalization-plan.md` F1~F8을 단일 명령 시퀀스로 정리.

**소요 시간**: 1~2주 (5/20 batch 재크롤이 critical path)
**다운타임 목표**: alias swap 시점 ≤ 5분
**실행 위치**: GPU 서버 `cscloud.gpu3.hufs.ac.kr` (crawler/chunk/embed) + AWS ECS (papers_v2 적재 + alias swap)

---

## 0. 사전 점검 체크리스트

본 runbook 진입 전 모두 ✅ 확인:

### 0.1 PR 머지 상태

```bash
# develop이 다음 PR 모두 포함하는지 확인
gh pr view 179 --json mergedAt -q '.mergedAt'  # PR-α efetch
gh pr view 181 --json mergedAt -q '.mergedAt'  # PR-β JATS 파서
gh pr view 182 --json mergedAt -q '.mergedAt'  # PR-δ+ε alias-swap + admin
gh pr view 184 --json mergedAt -q '.mergedAt'  # PR-γ full_reingest
```

4개 모두 머지 타임스탬프가 있어야 진행.

### 0.2 인프라 접근 권한

- [ ] GPU 서버 SSH (`ssh gpu` 알리아스 동작)
- [ ] AWS CLI `ecs execute-command` 권한 (IAM `AmazonECSExecAccess`)
- [ ] ECS task `enable-execute-command: true`
- [ ] CloudWatch 로그 그룹 `/ecs/scifit-sync` 접근
- [ ] `ADMIN_API_TOKEN` 시크릿 보유 (Secrets Manager 또는 .env)
- [ ] PubMed E-utilities 무인증 quota (IP 기반)
- [ ] (선택) `OPENALEX_API_KEY` env 설정 — rate limit 완화

### 0.3 데이터/스크립트 검증

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  git fetch && git checkout develop && git pull && \
  git log --oneline -5'
```

기대: 최근 5 커밋에 본 사이클의 PR 머지 commit 보임. GPU 서버 코드가 develop 최신.

### 0.4 prod ChromaDB 현 상태 백업

> **destructive 작업 전 필수**

```bash
TASK_ID=$(aws ecs list-tasks --cluster scifit-sync --service-name scifit-sync-api \
            --query 'taskArns[0]' --output text | awk -F/ '{print $NF}')
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "
import chromadb, json, gzip
from datetime import datetime
c = chromadb.PersistentClient(\"/chroma-data\")
col = c.get_collection(\"papers\")  # 또는 \"paper_chunks\" — 운영 컬렉션명 확인
data = col.get(include=[\"embeddings\", \"metadatas\", \"documents\"])
ts = datetime.utcnow().strftime(\"%Y%m%dT%H%M%SZ\")
out = f\"/chroma-data/backup_papers_{ts}.jsonl.gz\"
with gzip.open(out, \"wt\") as f:
    for i, did in enumerate(data[\"ids\"]):
        f.write(json.dumps({\"id\": did, \"document\": data[\"documents\"][i], \"metadata\": data[\"metadatas\"][i], \"embedding\": data[\"embeddings\"][i]}, ensure_ascii=False) + \"\n\")
print(\"backup:\", out, \"chunks:\", len(data[\"ids\"]))
"'
```

기대: `backup: /chroma-data/backup_papers_<ts>.jsonl.gz chunks: <N>` 출력.

---

## 1. Stage 1 — Phase 1 smoke (선택)

> Phase 1(local_pdf 즉시 적재)이 이미 수행됐다면 skip. 새로 검증하려면 진행.

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.full_reingest \
    --mode phase1_local_pdf --batch-tag smoke_phase1 \
    --skip-stages upsert validate 2>&1 | tee /mnt/data/scifit-sync/smoke_phase1.log'
```

기대 산출물:
- `mlops/data/chunks/smoke_phase1.jsonl.gz`
- `mlops/data/emb_bge-large/smoke_phase1.jsonl.gz`

검증:
```bash
ssh gpu '.venv-gpu/bin/python3 -m mlops.scripts.validate_embeddings \
  --input mlops/data/emb_bge-large/smoke_phase1.jsonl.gz --fail-fast'
```
expected verdict: `✅ PASS` (10개 임계 모두 충족).

---

## 2. Stage 2 — Phase 2 fetch + chunk + embed (1~2주)

### 2.1 본 실행

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  nohup .venv-gpu/bin/python3 -m mlops.scripts.full_reingest \
    --mode phase2_full --batch-tag refeed_v2 \
    --collection-suffix _v2 \
    --max-per-category 500 \
    --skip-stages upsert validate \
    > /mnt/data/scifit-sync/phase2_refeed_v2.log 2>&1 &'
```

(Stage 4 upsert와 Stage 3.5 validate는 별도 단계 — fetch + chunk + embed만 nohup으로 진행)

### 2.2 진행 모니터링

```bash
ssh gpu 'tail -f /mnt/data/scifit-sync/phase2_refeed_v2.log'
```

기대 로그 패턴:
- `Phase 2 JATS: 시도 N, 본문 확보 M` (Stage 1 fetch)
- `Phase 2 local_pdf: K papers`
- `chunks 저장: ... (X chunks from Y papers)`
- `[streaming] shard P/Q 완료`
- `임베딩 완료: X chunks → ...jsonl.gz` (Stage 3 끝)

### 2.3 Stage 1.5 manifest sanity (자동)

orchestrator가 자동 검증. abort 시 로그에 `Stage 1.5 manifest sanity 실패`. PR-α의 `_parse_pubmed_article` 픽스로 90% 임계 충족 예상.

---

## 3. Stage 3 — Pre-Upsert Validation (chunk-level)

```bash
ssh gpu '.venv-gpu/bin/python3 -m mlops.scripts.validate_embeddings \
  --input mlops/data/emb_bge-large/refeed_v2.jsonl.gz \
  --fail-fast 2>&1 | tee /mnt/data/scifit-sync/refeed_v2_validation.log'
```

**합격 임계 (10항목)**:

| 항목 | 임계 |
|---|---|
| 스키마 12 키 존재 | 100% |
| `(paper_doi OR paper_pmid)` 식별자 fill | 100% |
| `paper_doi` 단독 fill (정보용) | ≥ 99% |
| `publication_types` 비어있지 않음 | ≥ 90% |
| `evidence_weight` distinct | ≥ 5종, 0.5 비율 < 50% |
| 평균 토큰 | 300~450 |
| p99 토큰 | ≤ 660 |
| > 512 토큰 비율 | ≤ 5% |
| 청크/논문 비율 | 20~60 |
| PDF 서브셋 평균 토큰 | 150~250 (또는 PDF 없음) |
| 임베딩 차원 | 1024 |

**FAIL 시 분기 (design spec §3.6 의사결정 트리)**:
- `publication_types < 90%` → PR-α 디버그 재방문 (efetch 추출 문제)
- `publication_types ≥ 90% AND 평균 토큰 범위 외` → chunker 분포 이슈
- 그 외 → 별도 핫픽스 PR

---

## 4. Stage 4 — papers_v2 적재

> Stage 3 PASS 확인 후 진행.

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  nohup .venv-gpu/bin/python3 -m mlops.scripts.full_reingest \
    --mode phase2_full --batch-tag refeed_v2 \
    --collection-suffix _v2 \
    --skip-stages fetch manifest_check chunk_embed validate \
    > /mnt/data/scifit-sync/phase2_upsert.log 2>&1 &'
```

(fetch/chunk/embed/validate는 이미 끝났으니 skip. Stage 4 upsert만 실행)

진행 모니터링:
```bash
ssh gpu 'tail -f /mnt/data/scifit-sync/phase2_upsert.log'
```

기대 패턴:
- `upsert: 200 chunks (collection=papers_v2)` 반복 (batch_size=200)
- 약 6~12시간 소요 (청크 수에 따라)
- 마지막: `Stage 4 upsert 완료: N chunks → papers_v2`

### 4.1 Retry 동작 (PR #184 commit `46b77e6` 이식)

`stage4_upsert._post`는 `load_embeddings.load_api`의 검증된 retry 패턴을 그대로 사용한다 — 2,500만 청크 / 1,250~2,100 배치 호출 중 transient 5xx 한 번에 abort + 운영자 수동 재실행을 차단하기 위한 한 줄짜리 안전망.

| 항목 | 동작 |
|---|---|
| max_retries | 5 |
| 재시도 대상 | HTTP **502 / 503 / 504**, `requests.exceptions.ConnectionError` |
| 즉시 raise | **4xx 전체** (운영자 개입 신호 보존) + 5회 초과 5xx |
| backoff | `min(2**attempt, 30)` 초 (2 → 4 → 8 → 16 → 30) |
| 단일 호출 timeout | 300s (ALB 한도 안전) |

**단발 5xx 흡수 시 로그**:
```
API 502 에러 (attempt 1/5), 2s 후 재시도
upsert: 200 chunks 누적 (collection=papers_v2)
```
→ retry 흡수됐고 진행 정상. 별도 액션 불필요.

**5xx 5회 초과 abort 시 로그**:
```
API 502 에러 (attempt 5/5), 30s 후 재시도
... (raise HTTPError)
```
→ ALB / ECS task 상태 확인 (CloudWatch `/ecs/scifit-sync` 5xx 비율 + task health). 회복 후 §4 명령 그대로 재실행 — manifest 기반 resumable이라 기존 진행분 skip.

### 4.2 적재 검증

```bash
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "
import chromadb
c = chromadb.PersistentClient(\"/chroma-data\")
print(\"papers:\", c.get_collection(\"papers\").count())
print(\"papers_v2:\", c.get_collection(\"papers_v2\").count())
"'
```

기대: `papers_v2` 청크 수가 jsonl 파일 청크 수와 일치.

---

## 5. Stage 5 — recall@10 A/B 평가 게이트

### 5.1 baseline (papers) 평가

```bash
ssh gpu '.venv-gpu/bin/python3 -m mlops.eval.run_eval \
  --goldset mlops/eval/goldset.jsonl \
  --output mlops/eval/reports/baseline_papers.md \
  --retriever chroma --collection papers'
```

(주: `run_eval.py`가 `--collection` 옵션 미지원이면 환경변수 또는 직접 코드 수정 필요)

### 5.2 refeed_v2 (papers_v2) 평가

```bash
ssh gpu '.venv-gpu/bin/python3 -m mlops.eval.run_eval \
  --goldset mlops/eval/goldset.jsonl \
  --output mlops/eval/reports/refeed_v2_papers_v2.md \
  --retriever chroma --collection papers_v2'
```

### 5.3 회귀 검증

```bash
ssh gpu 'diff -u mlops/eval/reports/baseline_papers.md mlops/eval/reports/refeed_v2_papers_v2.md | head -40'
```

**합격 임계 (design spec C5)**:
- recall@10 회귀 폭 ≤ 2pp (절댓값)
- 가능하면 향상

FAIL 시 design spec §3.6 의사결정 트리 따름.

---

## 6. Stage 6 — alias swap + post-swap 검증

> Stage 5 합격 후 진행.

### 6.1 다운타임 측정 시작 (T0)

```bash
T0=$(date -u +%FT%TZ)
echo "T0=$T0" | tee -a /mnt/data/scifit-sync/swap_audit.log
```

### 6.2 alias swap 호출

```bash
curl -X POST \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "papers_v2"}' \
  https://scifit-sync.com/api/v1/admin/rag/collection-swap
```

기대 응답:
```json
{"success": true, "data": {"current": "papers_v2", "swapped_at": "2026-05-..."}}
```

### 6.3 post-swap 헬스체크 (T1)

```bash
# health
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  "https://scifit-sync.com/api/v1/admin/rag/pmids?limit=10"
T1=$(date -u +%FT%TZ)
echo "T1=$T1" | tee -a /mnt/data/scifit-sync/swap_audit.log

# 다운타임 계산
python3 -c "
from datetime import datetime
t0 = datetime.fromisoformat('$T0'.replace('Z','+00:00'))
t1 = datetime.fromisoformat('$T1'.replace('Z','+00:00'))
print(f'다운타임: {(t1-t0).total_seconds():.1f}초 (목표 ≤ 300초)')
"
```

기대: 다운타임 ≤ 5분 (design spec C7).

### 6.4 chat smoke test

```bash
# chat endpoint 호출 또는 앱에서 수동 확인
# 응답 score 분포가 다양화됐는지 (evidence_weight 차등화 확인):
# Meta-Analysis 청크 → score = sim × 1.0
# RCT 청크 → score = sim × 0.9
# Review 청크 → score = sim × 0.4
```

### 6.5 CloudWatch 5xx 모니터링 (10분 윈도우)

```bash
aws logs filter-log-events --log-group-name /ecs/scifit-sync \
  --start-time $(($(date -u +%s) * 1000 - 600000)) \
  --filter-pattern "5xx OR ERROR" | jq '.events | length'
```

기대: 5xx 비율 < 1%. 초과 시 §7 롤백.

---

## 7. 롤백 절차 (시나리오별)

### 7.1 Stage 4 적재 실패

```bash
# papers_v2 폐기 후 Stage 4 재실행
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "import chromadb; c=chromadb.PersistentClient(\"/chroma-data\"); c.delete_collection(\"papers_v2\"); print(\"deleted papers_v2\")"'
# 그 후 Stage 4 재실행
```

### 7.2 Stage 5 회귀 (recall@10 하락 > 2pp)

papers_v2 폐기 + 원인 분석. alias swap 진입 금지.

### 7.3 alias swap 후 회귀

```bash
# 즉시 원복 (다운타임 < 1분)
curl -X POST \
  -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "papers"}' \
  https://scifit-sync.com/api/v1/admin/rag/collection-swap
```

검증: chat smoke test 정상 회복 확인.

### 7.4 ChromaDB HNSW partial-write 재발

```bash
# papers_v2만 와이프 (papers는 무관 — alias swap 전이라 안전)
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "import chromadb; c=chromadb.PersistentClient(\"/chroma-data\"); c.delete_collection(\"papers_v2\")"'
# Stage 4 재실행
```

PR-ε(`feat/jingyu/chroma-stability`)의 graceful shutdown hook이 1차 방어선.

---

## 8. Stage 7 — 옛 컬렉션 정리 (1주 후)

> alias swap + 운영 모니터링 정상 확인 후 1주 안정 운영 후 진행.

```bash
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "import chromadb; c=chromadb.PersistentClient(\"/chroma-data\"); c.delete_collection(\"papers\"); print(\"deleted old papers\")"'
```

---

## 9. 운영 모니터링 / 알림 (지속)

### 9.1 CloudWatch metrics 추적

- ALB 5xx 비율 (10분 window)
- ECS task CPU/메모리 사용률
- ChromaDB 컬렉션 size

### 9.2 RAG 응답 품질 sanity

주기적으로 (예: 일 1회):
```bash
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"resistance training hypertrophy"}' \
  https://scifit-sync.com/api/v1/admin/rag/debug-search 2>&1 | jq '.data.chunks[] | {pmid: .pmid, score, evidence_weight: .metadata.evidence_weight}'
```

기대: score 분포가 다양화 (0.5 단일값 아님), evidence_weight가 0.3~1.0 분포.

---

## 10. 트러블슈팅 FAQ

### Q1. Stage 1 fetch가 NCBI rate limit ban으로 멈춤

A. NCBI/EuropePMC 병렬 호출 절대 금지. 백오프 후 재실행. `existing_dois` manifest로 재개 시 이미 fetch된 paper skip.

### Q2. validate_embeddings.py가 publication_types < 90%로 abort

A. PR-α의 `_parse_pubmed_article` 픽스가 develop에 정확히 머지됐는지 확인. 픽스 후에도 90% 미달이면 efetch raw XML 직접 검사 — `<PublicationTypeList>` 누락 paper 비율 확인.

### Q3. ALB 300초 timeout으로 upsert 실패

A. `batch_size=200`은 ALB 300초 한도 안전. 단발 5xx는 `stage4_upsert._post`의 retry(§4.1 표 참조)가 자동 흡수 — max 5회, exponential backoff. 5회 초과로 abort했다면 ALB / ECS 자체 장애 가능성이 높으므로 인프라 상태 점검 후 §4 명령 그대로 재실행 (manifest resumable). 운영 보수가 필요하면 `--batch-size 100`까지 낮추는 follow-up도 검토 가능 — 단 현재 orchestrator는 200 하드코딩이므로 코드 수정 필요.

### Q4. alias swap 후 검색 결과가 빈 청크 반환

A. `rag._get_collection`이 새 alias를 못 읽음. `_collection_cache.clear()` 자동 호출 확인. ECS task 재시작이 필요할 수 있음 (`aws ecs update-service --force-new-deployment`).

### Q5. Phase 2 중 GPU 서버 SSH disconnect로 진행 중단

A. nohup으로 띄웠으면 백그라운드 진행 지속. `tail -f /mnt/data/scifit-sync/phase2_*.log`로 재접속. manifest 기반 resumable이라 중단 후 재실행 시 완료 stage skip.

---

## 참조

- Design spec: `docs/superpowers/specs/2026-05-28-rag-data-normalization-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-28-rag-data-normalization-plan.md`
- 관련 PR: #179 (PR-α efetch), #181 (PR-β JATS), #182 (PR-δ+ε alias-swap), #184 (PR-γ orchestrator + `_post` retry 이식 commit `46b77e6`)
- 메모리: `project_prod_rag_full_reload_20260528.md`, `project_evidence_weight_data_gap.md`
- 운영 환경 정보 (메모리 #12461): AWS ALB idle timeout 300초

---

**문서 갱신 정책**: Phase 2 실행 사이클마다 운영 일지 + 다운타임 기록 + 회귀 분석을 본 문서에 누적 또는 별도 `docs/guides/phase2-runs/YYYY-MM-DD.md`로 분리.
