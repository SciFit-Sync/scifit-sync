# RAG 데이터 정상화 및 자동화 파이프라인 — Design Spec

**작성일**: 2026-05-28
**작성자**: jingyu (with Claude Code brainstorming)
**상태**: Draft — 사용자 review 대기

---

## §1 목표 / 범위 / 성공 기준

### 1.1 목표

SciFit-Sync RAG 검색 파이프라인의 **데이터 정상화 및 재현 가능한 ingestion 자동화**. 한 번 픽스하고 끝이 아니라, 향후 신규 카테고리/논문 추가나 chunker 정책 변경 시 동일한 방식으로 안전하게 재처리할 수 있는 운영 파이프라인을 구축한다.

### 1.2 배경 (해결할 문제)

| 문제 | 증거 |
|---|---|
| 청크 평균 토큰 56 (목표 300~512의 11%) | `embeddings_3k_batch1` 평균 56.3, `3k_20260522_060614` 평균 55.4 |
| `score = similarity × 0.5` 일률 표시 | `rag.py:115-141`. evidence_weight=0.5 단일값 |
| `publication_types` 0% 추출 | 3개 적재 대상 파일 모두 200/200 빈 리스트 |
| JATS `.//sec` 중첩 추출 버그 | `crawler.py:976`, `europepmc.py:58` — 부모+자식 sec 모두 별개 PaperSection 추출 |
| chunker small-section pack 부재 | ✅ PR #174 (2026-05-28 머지)로 해결 — 보호망 확보 |
| ChromaDB HNSW partial-write 위험 | 2026-05-27 crash loop 재발 가능 |

### 1.3 범위 (in-scope)

| # | 항목 |
|---|---|
| S1 | JATS `.//sec` 파서 픽스 (`crawler.py`, `europepmc.py`) — chunker packing이 보호망이지만 근본 원인 정정 |
| S2 | 자동화 ingestion 파이프라인 (`full_reingest.py`) — fetch → chunk → embed → validate → upsert, resumable, manifest 멱등성 |
| S3 | local_pdf 경로 통합 — 동일 파이프라인이 JATS + PDF 모두 처리 |
| S4 | ChromaDB 적재 안정성 — graceful shutdown, alias-swap 패턴, `/admin/rag/pmids` 페이지네이션 |
| S5 | **publication_types 추출 파이프라인 디버그 + 픽스 + 회귀 테스트** — `efetch_pubmed_batch`/`crawler.py` PubMed 보강이 5/22·5/26 export 모두 0% 추출률. NCBI XML 파싱 누락 또는 키 매핑 오류로 추정. 픽스 없이는 C2/C3 임계 달성 불가 |
| S6 | 골드셋 A/B 평가 게이트 — recall@10 합격 임계 검증 후 prod 적용 |
| S7 | 운영 절차 — Phase 1 (데모) + Phase 2 (전체 재처리), 시기·순서·롤백 절차 명문화 |

### 1.4 범위 외 (out-of-scope, follow-up)

- `_safe_doc_id` PMID fallback 강화 (재크롤 후 dead path)
- D1 (threshold 정책) / D2 (`DEFAULT_EVIDENCE_WEIGHT`) 변경 — 평가 결과 보고 별도 결정
- ChromaDB → pgvector 마이그레이션 등 인프라 변경
- 신규 데이터 소스 추가 (Semantic Scholar 등)

### 1.5 성공 기준

| ID | 조건 | 측정 |
|---|---|---|
| C1 | 모든 청크가 `(paper_doi OR paper_pmid)`를 100% 가짐 — 둘 다 없는 레코드는 ingestion 단계에서 drop. PMID-only fallback chunk_id 비율 < 1% (DOI 부재 paper만 허용) | ChromaDB `collection.get(include=["metadatas"])` 전수 집계 (admin export endpoint 또는 ECS exec script). sampling은 보조용 |
| C2 | 모든 청크에 `publication_types` 비어있지 않은 비율 ≥ 90% | jsonl 통계 + ChromaDB sampling |
| C3 | `evidence_weight` 분포 다양화 — distinct 값 ≥ 5종, 0.5 비율 < 50% | 분포 히스토그램 |
| C4 | 청크 평균 토큰 300~450 범위 (PR #174 본문 예측 "55→~400" 부합) | `mlops/eval` 통계 |
| C5 | 골드셋 recall@10이 baseline 대비 회귀 없음 (가능하면 향상). **baseline 정의**: 컬렉션=`papers` (alias swap 직전 prod snapshot), 골드셋=`mlops/eval/goldset.jsonl` 현재 커밋 SHA (Phase 2 시작 시점 develop HEAD에 고정), 평가 스크립트=`mlops/eval/run_eval.py` 동일 커밋. 합격 임계: recall@10 회귀 폭 ≤ 2pp (절댓값) | A/B 평가 리포트, baseline·refeed_v2 두 리포트 PR에 첨부 |
| C6 | 파이프라인이 resumable — 중간 중단 후 재실행 시 멱등 동작 | 단위 테스트 + 운영 검증 |
| C7 | prod 적용 시 다운타임 ≤ 5분 (alias swap 사용 시). **다운타임 정의**: T0=admin endpoint `collection-swap` 호출 시각, T1=새 alias에 대한 첫 200 응답 시각 (`/api/v1/admin/rag/pmids` 헬스체크) | CloudWatch ALB 로그 + admin endpoint 로그 타임스탬프. swap 운영 일지에 T0/T1 기록 |
| C8 | pre-upsert validation 게이트 합격 — §3.3.1의 10개 항목 모두 임계 충족 | `validate_embeddings.py` |
| C9 | validation 리포트가 PR review/머지 evidence로 첨부됨 | Phase 2 alias swap 직전 commit |

### 1.6 핵심 제약

- 학기말 데모 임박 → **Phase 1 (local_pdf 즉시 처리)이 일정 최우선**
- 5/20 batch 1.13M 청크 재크롤 비용 — NCBI/EuropePMC rate limit 감안 수일~1주
- ECS 단일 task 운영 (CLAUDE.md §16) — ChromaDB 동시 쓰기 금지
- Alembic 단독 DB 관리 (Supabase UI 직접 수정 금지)
- 5/22·5/26 export에서 `publication_types` 0/200, `evidence_weight` {0.5} 단일값 — 단순 재크롤만으로는 차등화 복원 불가. **S5 픽스가 prerequisite**
- **AWS ALB idle timeout 300초** (메모리 #12461, 5/27 이슈로 30초 → 300초 상향 완료) — admin endpoint를 거치는 모든 적재 호출은 300초 내 응답 보장 필요. `load_embeddings.py --batch-size 200`이 ALB 300초 한도 내 안전 + 502/503/504 retry로 부분 timeout 흡수. batch_size 상향 시 ALB 한도와 ChromaDB upsert 시간 측정 필수

---

## §2 아키텍처 / 컴포넌트

### 2.1 전체 흐름

```
┌──────────────────────────────────────────────────────────────────┐
│ 신규: mlops/scripts/full_reingest.py (orchestrator)              │
└──┬───────────────────────────────────────────────────────────────┘
   │
   ├─► [Stage 1: 메타 수집]
   │     crawler.crawl_papers (JATS 파서 픽스 후)         ─┐
   │     └─► PubMed efetch (publication_types 추출 픽스)  │── PaperFull
   │     └─► OpenAlex / EuropePMC fallback (DOI primary)  │   리스트
   │     └─► local_pdf: parse_pdf + efetch 보강           ─┘
   │
   ├─► [Stage 1.5: Manifest sanity 검증 (paper-level)]
   │     publication_types fill rate ≥ 90%, (paper_doi OR paper_pmid) = 100%
   │     └─► 미달 시 abort → S5 디버그 재방문
   │
   ├─► [Stage 2: 청킹]
   │     chunker.chunk_papers (PR #174 머저 + JATS 파서 픽스 적용)
   │     └─► 평균 ~400 토큰, paper.meta 7개 필드 보존
   │
   ├─► [Stage 3: 임베딩]
   │     embedder.embed_chunks_with_spec (bge-large-en-v1.5)
   │     └─► shard 단위 디스크 기록 (OOM 방지, 기존 패턴)
   │
   ├─► [Stage 3.5: Pre-Upsert Validation 게이트 (chunk-level)]
   │     validate_embeddings.py — jsonl 10개 항목 임계 검증 (§3.3.1)
   │     └─► 미달 시 abort, ChromaDB 진입 금지
   │
   ├─► [Stage 4: 적재]
   │     ChromaDB 신규 collection `papers_v2`에 upsert
   │     └─► graceful shutdown hook (HNSW partial-write 방지)
   │
   └─► [Stage 5: 평가 게이트 + alias swap]
         골드셋 recall@10 A/B (papers vs papers_v2)
         └─► 합격 시 운영자 명령으로 alias swap (다운타임 ≤ 5분)
         └─► 불합격 시 papers_v2 폐기
```

### 2.2 컴포넌트별 책임

| 컴포넌트 | 위치 | 책임 | 변경 유형 |
|---|---|---|---|
| `crawler.py` `_parse_pmc_sections` | `mlops/pipeline/crawler.py:968` | JATS `<sec>` 추출 — `./sec` 직계 + descendant text 통합 | **수정** (S1) |
| `europepmc.py` `parse_sections` | `mlops/pipeline/europepmc.py:50` | EuropePMC JATS — 동일 로직 | **수정** (S1) |
| `pmc.py` 코드 중복 정리 | `mlops/pipeline/pmc.py` | crawler/europepmc 중복 제거, `parse_sections` 재사용 | **수정** (S1, C2) |
| `ncbi.py` efetch publication_types | `mlops/pipeline/ncbi.py` (**확인 필요** — PR-α 착수 시 실제 efetch 모듈 경로 grep으로 확정. `crawler.py`에 inline 구현됐을 가능성도 있음) | PubMed XML에서 `PublicationType` 추출 | **수정/디버그** (S5) |
| `ingest_local_pdfs.py` efetch 보강 | `mlops/scripts/ingest_local_pdfs.py:133-148` | PubMed publication_types 보강 검증 | **수정/회귀** (S5) |
| `chunker.py` `chunk_paper` | `mlops/pipeline/chunker.py` | 머저 + 분할 + 메타 보존 | ✅ PR #174 머지 완료 |
| `chunker.py` `_split_text_by_tokens` tail 가드 | (PR #174) | `is_last` 가드로 mini-chunk 폭증 차단 | ✅ 머지 완료 |
| `chunker.py` `_absorb_into_previous` | (PR #174) | 분할 잔여 <150 토큰을 직전 청크에 흡수 | ✅ 머지 완료 |
| `chunker.py` `_merge_section_names` | (PR #174) | 머저된 섹션명 ' / ' join + 80자 truncate | ✅ 머지 완료 |
| `chunker.py` `_make_chunk` 헬퍼 | (PR #174) | 분할/머저 두 경로 모두 `paper.meta` 7개 필드 보존 | ✅ 머지 완료 |
| `evidence.py` `calculate_evidence_weight` | `mlops/pipeline/evidence.py` | publication_types → weight | ✅ 기존 코드 OK |
| `full_reingest.py` (orchestrator) | `mlops/scripts/full_reingest.py` (신규) | 5단계 통합, resumable, manifest 멱등성 | **신규** (S2) |
| `validate_embeddings.py` | `mlops/scripts/validate_embeddings.py` (신규) | jsonl 통계 산출, 임계 검증, fail-fast abort | **신규** (S2) |
| `mlops/eval/validation_thresholds.py` | (신규) | 임계값 모듈 (테스트에서 import, 운영 중 튜닝 용이) | **신규** |
| `upserter.py` + `admin.py` ingest | `mlops/pipeline/upserter.py` + `server/app/api/v1/admin.py` | ChromaDB alias-swap 패턴 지원 | **수정** (S4) |
| `admin.py` `/admin/rag/pmids` | `server/app/api/v1/admin.py` | 페이지네이션 추가 (B2 500 픽스) | **수정** (S4) |
| `rag.py` collection lookup | `server/app/services/rag.py` | 모듈 글로벌 캐시 → 동적 lookup (alias swap 지원) | **수정** (S4) |
| `eval/run_eval.py` | `mlops/eval/run_eval.py` (기존) | recall@10 A/B 평가 게이트 | ✅ 기존 활용 |

### 2.3 데이터 흐름 — Resumable + Idempotent

**Manifest 기반 멱등성** (`mlops/data/manifest.json` 기존 패턴 확장):
- **key 우선순위**: `paper_doi` → `paper_pmid` → **drop** (둘 다 없는 레코드는 ingestion 단계에서 제외). SHA/hash fallback 도입하지 않음 (식별자 충돌 위험 회피)
- value: `{key_type: "doi"|"pmid", paper_doi, paper_pmid, pmcid, openalex_id, fulltext_source, publication_types, evidence_weight, tried_sources, chunked_at, embedded_at, upserted_at, batch_tag}`
- `key_type` 필드로 어떤 식별자가 manifest key로 쓰였는지 추적 (재실행 시 key 정합성 확인)
- local_pdf entry는 manifest 단계 진입 전에 PubMed efetch 또는 OpenAlex로 DOI/PMID를 반드시 보강. 보강 실패 시 해당 PDF는 ingestion skip (skipped log에 기록)
- 각 단계 완료 시점에 manifest를 atomic write로 갱신
- 재실행 시 manifest를 보고 이미 완료된 stage skip

**중단/재개 보장**:
- Stage 1: crawler가 round-robin dedup 시 manifest의 `existing_dois`/`fully_tried` 패턴 (기존 코드 재사용)
- Stage 2~3: `<batch_tag>` 별 jsonl + sidecar `.meta.json` (PR #139 패턴 재사용)
- Stage 4: ChromaDB upsert는 이미 idempotent (chunk_id 충돌 시 덮어쓰기). batch별 `upserted_at` 마킹

**Alias-Swap 적재 패턴** (다운타임 ≤ 5분 보장):
- 현재 컬렉션: `papers` (prod)
- 신규 적재: `papers_v2` (또는 `papers_<batch_tag>`)
- **공식 swap 인터페이스**: `POST /api/v1/admin/rag/collection-swap` (admin endpoint). 헤더 `X-Admin-Token: $ADMIN_API_TOKEN`. body `{"to": "papers_v2"}`. 응답에 `swapped_at` 타임스탬프 포함 (C7 다운타임 측정 증적)
- 호출 주체: jingyu (codeowner). 외부 도구(`gh api`, `curl`)는 모두 위 admin endpoint를 호출하는 wrapper. 직접 ChromaDB collection 이름 변경 금지
- rag.py가 ChromaDB collection 핸들을 매 요청마다 lookup하도록 (현재 모듈 글로벌 캐시 → 수정 필요, PR-δ에서 처리)
- 롤백: 동일 endpoint로 `{"to": "papers"}` 호출 → 즉시 복구

### 2.4 인터페이스

`full_reingest.py` CLI:
```bash
python -m mlops.scripts.full_reingest \
  --mode {phase1_local_pdf | phase2_full} \
  --batch-tag refeed_v2 \
  --collection-suffix _v2 \
  --max-per-category 500 \
  --skip-stages {crawl|chunk|embed|upsert}  # 디버그용
  --eval-gate  # recall@10 합격 임계 검증
```

`validate_embeddings.py` CLI:
```bash
# pre-upsert validation 단독 호출
python -m mlops.scripts.validate_embeddings \
  --input "mlops/data/emb_bge-large/refeed_v2_*.jsonl.gz" \
  --thresholds default \
  --report mlops/eval/reports/refeed_v2_validation.md \
  --fail-fast

# full_reingest orchestrator에 자동 포함됨 (Stage 4 진입 전 자동 호출)
```

환경변수: 기존 `NCBI_HTTP_*`, `OPENALEX_*`, `CHROMA_*`, `ADMIN_API_TOKEN` 재사용.

### 2.5 핵심 아키텍처 결정

| 결정 | 선택 | 이유 |
|---|---|---|
| 새 컬렉션 vs 와이프 | **alias-swap 신규 컬렉션** | 다운타임 최소화, 롤백 가능 |
| 자동화 트리거 | **수동 1회성 (이번 사이클)** + 후속 cron 검토 | 검증·평가가 충분히 안정되기 전까지 자동화 위험 |
| local_pdf 통합 | **별도 entry point + 같은 chunker/embedder** | PDF 파싱은 별도 코드 (`parse_pdf`), 그 외 단계 공유 |
| efetch publication_types 픽스 | **PR 별도로 분리** | 회귀 + fixture 테스트 필요, 다른 변경과 섞으면 review 어려움 |
| ChromaDB `papers_v2` 전환 시점 | **평가 게이트 합격 후 운영자 명령으로 swap** | 자동 swap은 평가 회귀 위험 |
| 흡수 후 청크가 ~660 토큰까지 가능 (bge-large 512 max_seq_length 초과) | **수용 + 운영 모니터링** | PR #174의 trade-off — mini-chunk 폭증보다 우월. 재임베딩 후 토큰 분포 p99/p999 확인하고 5% 이상이 truncation되면 후속 PR로 직전 청크 임계 강화 |
| JATS 파서 픽스 (S1) 우선순위 | **chunker packing(PR #174) 머지로 보호망 확보됨 → 우선순위 ↓, 그러나 근본 원인 정리 + 컴포지션 정확성을 위해 별도 PR 유지** | 보호망은 청크 사이즈를 정상화하지만 "Methods 부모 + Subjects 자식"이 별개 PaperSection으로 들어가는 본질 문제는 그대로 |

---

## §3 작업 단계 / PR 분할 / 일정 / 롤백

### 3.1 Phase 1 — 데모용 local_pdf 즉시 적재

| 단계 | 작업 | 비고 |
|---|---|---|
| P1-1 | GPU 서버 `develop` pull (PR #174 코드 받기) | Phase 1은 기존 jsonl 그대로 적재라 chunker 변경은 효과 없음 |
| **P1-1.5** | **prod ChromaDB 백업** — ECS task에서 `python -c "import chromadb; c=chromadb.PersistentClient('/chroma-data'); col=c.get_collection('papers'); ids, embs, metas, docs = col.get(include=['embeddings','metadatas','documents']).values(); ..." `로 jsonl export 후 GPU 서버 또는 S3로 백업. 추가로 가능하면 EFS snapshot 생성 (AWS 콘솔). 백업 위치를 P1-2 와이프 명령 직전에 기록 | 5~10분. **와이프 전 필수** |
| P1-2 | prod ChromaDB 와이프 (EFS `/chroma-data` + ECS force-new-deployment) | 기존 38,800 청크 폐기. 메모리 `project_prod_rag_full_reload_20260528` 절차. **P1-1.5 백업 확인 후 진행** |
| P1-3 | `load_embeddings.py --input mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz --mode api --batch-size 200` | 5~10분 |
| P1-4 | 검증 — `/admin/rag/pmids` chunks 카운트 + chat 응답 1~2건 수동 확인 | B2 500 가능성 — 우회 endpoint 또는 ECS exec |

**Phase 1 제약 (수용)**:
- 청크는 옛 청킹 결과(평균 199 토큰), 새 chunker 미적용
- `publication_types=[]` / `evidence_weight=0.5` 단일값 → score = sim × 0.5 일률
- 그래도 데모 chat은 정상 동작 (threshold 0.70 통과 + LLM 응답 생성)

### 3.2 Phase 2 — 전체 자동화 + 재처리

5개 PR을 병행/순차 조합으로 진행:

| PR | 범위 | 브랜치 | 의존성 |
|---|---|---|---|
| **PR-α** (S5) | `efetch_pubmed_batch` publication_types 추출 디버그+픽스 + NCBI XML 파싱 회귀 테스트 | `fix/jingyu/pubmed-publication-types` | 독립 |
| **PR-β** (S1) | JATS 파서 `.//sec` → `./sec` + descendant 통합 (crawler.py + europepmc.py). `pmc.py` 코드 중복 정리 | `fix/jingyu/jats-nested-sec` (이미 생성, develop 위에 빈 상태) | 독립 |
| **PR-γ** (S2+S3) | `full_reingest.py` orchestrator + `validate_embeddings.py` + manifest 멱등성 + resumable + local_pdf 통합 | `feat/jingyu/full-reingest-pipeline` | α/β 머지 전 review 가능, 실행은 둘 다 머지 후 |
| **PR-δ** (S4-1) | ChromaDB alias-swap 패턴 (`papers_v2` 적재 → swap → 롤백) + rag.py collection lookup 동적화 | `feat/jingyu/chroma-alias-swap` | γ와 병행 |
| **PR-ε** (S4-2, B2) | `/admin/rag/pmids` 페이지네이션 + graceful shutdown hook. **결합 사유**: 둘 다 admin endpoint/ChromaDB 라이프사이클 안정성 한 묶음 + 동일한 통합 테스트 fixture(대용량 메타·SIGTERM 시뮬레이션) 공유 → 검증 비용 절감. 분리 시 회귀 가능성. 결합 PR 본문에 두 변경의 통합 테스트 evidence 첨부 의무 | `fix/jingyu/admin-pmids-pagination` | 독립 |

**병행/순차 그래프**:
```
        ┌─ PR-α (efetch 픽스) ──┐
develop ┼─ PR-β (JATS 파서) ───┼─► full_reingest 실행 가능
        ├─ PR-γ (orchestrator) ┤
        ├─ PR-δ (alias swap) ──┘
        └─ PR-ε (admin 안정성) ── 독립 머지
```

### 3.3 실행 단계 (PR 머지 후) — Pre-Upsert Validation 게이트 포함

| 단계 | 작업 | ETA |
|---|---|---|
| E1 | GPU 서버 `develop` pull (PR α/β/γ/δ 머지 완료 후) | 1분 |
| E2 | `full_reingest --mode phase2_full --batch-tag refeed_v2 --collection-suffix _v2` 실행 | (아래 분해) |
| E2-1 | Stage 1 fetch: local_pdf 158편 efetch (publication_types 보강 검증) | 5분 |
| E2-2 | Stage 1 fetch: 5/22 chunks 캐시 reconstruct (PaperFull 복원 후 PMID로 efetch 보강) | 30분 |
| E2-3 | Stage 1 fetch: 5/20 카테고리 전면 재크롤 (NCBI/EuropePMC rate limit) | **수일~1주** (critical path) |
| **E2-3.5** | **Manifest sanity 검증 (paper-level)** — crawl 직후 manifest에서 publication_types 비어있지 않은 paper 비율 ≥ 90%, `(paper_doi OR paper_pmid) = 100%` (둘 다 없는 paper는 자동 drop된 후라 100% 보장돼야 함). 미달 시 abort → S5 디버그 재방문 (전체 fetch 재실행보다 먼저 차단). 임베딩 비용 절감용 early gate. | 1분 |
| E2-4 | Stage 2 chunk + Stage 3 embed (shard 단위 streaming) | 4~8시간 (~2.1M 청크 → 새 chunker로 ~400k 청크 감소 예상) |
| **E2-4.5** | **Pre-Upsert Validation 게이트 (chunk-level)** — `validate_embeddings.py`로 임베딩 jsonl 10개 항목 임계 검증 (§3.3.1). paper→chunk 전파 + 임베딩 차원 검증까지 포함. E2-3.5는 paper 메타 기준, E2-4.5는 청크/임베딩 산출물 기준. 미달 시 abort, ChromaDB 진입 금지. | 5분 |
| E2-5 | Stage 4 upsert to `papers_v2` collection | 6~12시간 |
| E2-6 | Stage 5 평가 게이트 — `run_eval`로 recall@10 A/B (`papers` vs `papers_v2`) | 30분 |
| E3 | 합격 시 `POST /api/v1/admin/rag/collection-swap` body `{"to": "papers_v2"}` 호출 (`X-Admin-Token`). 응답의 `swapped_at` 기록 = C7 다운타임 T0 | 1분 (다운타임 ≤ 5분) |
| **E3.5** | **Post-swap 검증** — (a) `/api/v1/admin/rag/pmids?limit=10` 200 응답 + chunks count > 0 확인 (= C7 T1), (b) 골드셋 쿼리 3건 직접 호출해서 응답 정합·지연 측정, (c) `rag.search_chunks("hypertrophy")` 등 표본 쿼리로 evidence_weight 분포 다양화 확인, (d) ALB 5xx 비율 ≤ 1% (10분 윈도우, CloudWatch). 검증 실패 시 즉시 §3.4 alias 원복 | 10분 |
| E4 | 1주 후 옛 `papers` 컬렉션 정리 (E3.5 안정 + 운영 모니터링 정상 확인 후) | 별도 |

**총 ETA**: **1~2주** (5/20 재크롤이 가장 큰 비용)

### 3.3.1 Pre-Upsert Validation 임계표

| 검증 항목 | 임계 |
|---|---|
| **스키마**: 키 12개 모두 존재 (`chunk_index`, `paper_pmid`, `paper_title`, `section_name`, `token_count`, `search_categories`, `paper_doi`, `publication_types`, `evidence_weight`, `fulltext_source`, `published_year`, `embedding`) | 100% |
| **식별자 fill rate** — `(paper_doi OR paper_pmid)` 채워진 청크 | 100% (만족 못하면 ingestion 단계에서 이미 drop됐어야 함 — 게이트 미달은 manifest 누수 버그 신호) |
| **paper_doi 단독 fill rate** (정보용, blocker 아님) | 권장 ≥ 99% (local_pdf 일부 예외 허용). PMID-only 청크 비율 1% 초과 시 알림 |
| **publication_types fill rate** | ≥ 90% |
| **evidence_weight 분포 다양화** | distinct 값 ≥ 5종, 0.5 비율 < 50% |
| **청크 평균 토큰** | 300 ≤ avg ≤ 450 (목표 ~400) |
| **청크 토큰 p99** | ≤ 660 (PR #174 흡수 trade-off 한계) |
| **청크 토큰 > 512 비율** (bge-large truncation 대상) | ≤ 5% |
| **청크/논문 비율** | 20 ≤ avg ≤ 60 (현재 263 → 정상화 확인) |
| **PDF 경로 회귀** | `fulltext_source='local_pdf'` 평균 토큰 150~250 (옛 199 유지) |
| **임베딩 차원** | 정확히 1024 |

**리포트 예시 출력**:
```
=== validate_embeddings.py mlops/data/emb_bge-large/refeed_v2_*.jsonl.gz ===
schema:                   ✅ 12/12 keys present, 0 missing
identifier coverage:      ✅ (paper_doi OR paper_pmid) = 100% (drop된 paper 12편 skipped log에 기록)
paper_doi fill rate:      ✅ 99.8% (5/2,341 missing — local_pdf만, PMID로 보강됨)
publication_types:        ❌ 67% filled (threshold 90%) — FAIL
evidence_weight distinct: ✅ 7 values: {0.30, 0.40, 0.50, 0.60, 0.75, 0.90, 1.00}
                          ⚠️ 0.5 ratio = 33% (acceptable)
avg token count:          ✅ 397.2 (range 300~450)
p99 token count:          ✅ 612 (≤ 660)
> 512 ratio:              ⚠️ 4.1% (≤ 5%, near threshold)
chunks per paper:         ✅ avg 28.4 (range 20~60)
PDF subset avg:           ✅ 198.6 (PDF 회귀 없음)
embedding dim:            ✅ 1024

VERDICT: ❌ FAIL (publication_types 67% < 90% threshold)
Action: efetch 추출 로직 디버그 후 Stage 1부터 재실행
```

### 3.4 롤백 절차

| 시나리오 | 조치 | 손실 |
|---|---|---|
| Phase 1 적재 후 chat 응답 회귀 | (1) P1-1.5 백업 jsonl로 즉시 재적재 (구 prod 상태 복원), (2) 그래도 실패 시 빈 상태 유지 + 핫픽스 | 데모 임시 중단, 복원에 5~10분 |
| Phase 2 PR-α/β 머지 후 회귀 발견 | `git revert <merge-commit>` + 골드셋 재검증 | 머지 시간 손실 |
| Phase 2 Stage 1 manifest 검증 실패 (E2-3.5) | abort → S5 디버그 재방문 | crawl 시간 손실 (수일) |
| Phase 2 Pre-Upsert Validation 실패 (E2-4.5) | abort → 원인 분석 후 해당 Stage부터 재실행 | embed 시간 손실 |
| Phase 2 `papers_v2` 적재 실패 (중단/exception) | manifest 보고 resumable 재실행 | 부분 stage 손실 |
| Phase 2 alias swap 후 회귀 발견 | `POST /api/v1/admin/rag/collection-swap` body `{"to": "papers"}` 즉시 원복 | swap 시간만 |
| Phase 2 recall@10 회귀 (게이트 불합격) | `papers_v2` 폐기 후 원인 분석 → 재실행 | 임베딩 시간 손실 (재크롤은 manifest로 보존) |
| ChromaDB HNSW partial-write 재발 | `papers_v2` 와이프 + Stage 4부터 재실행 | upsert 시간 |

### 3.5 운영 명령 시퀀스 (Phase 1)

```bash
# 1. GPU 서버에 develop 최신
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && git fetch && git checkout develop && git pull'

# 2a. (필수) 와이프 전 백업 — ECS exec로 컬렉션 jsonl export, GPU 서버 또는 S3에 보관
aws ecs execute-command --cluster scifit-sync --task <task-id> --interactive \
  --command 'python -c "import chromadb, json, gzip; c=chromadb.PersistentClient(\"/chroma-data\"); col=c.get_collection(\"papers\"); d=col.get(include=[\"embeddings\",\"metadatas\",\"documents\"]); ..." > /chroma-data/backup_$(date +%Y%m%d_%H%M%S).jsonl.gz'
# 결과 파일을 GPU 서버 또는 S3로 복사 후 다음 단계 진행. 가능하면 추가로 EFS snapshot.

# 2b. prod ChromaDB 와이프 (AWS 콘솔 또는 ECS exec)
#    EFS /chroma-data wipe + ECS force-new-deployment
#    (이전 메모리 project_prod_rag_full_reload_20260528.md의 패턴)

# 3. 와이프 검증
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" https://scifit-sync.com/api/v1/admin/rag/pmids
# 기대: chunks=0

# 4. local_pdf 적재
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.load_embeddings \
    --input mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz \
    --mode api --batch-size 200 --skip-errors 2>&1 | \
  tee /mnt/data/scifit-sync/phase1_local_pdf.log'

# 5. 검증
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" https://scifit-sync.com/api/v1/admin/rag/pmids
# 기대: chunks=15361

# 6. chat smoke test (앱 또는 admin endpoint)
```

### 3.6 핵심 위험과 대응

| 위험 | 대응 |
|---|---|
| 5/20 재크롤 1주 초과 | NCBI/EuropePMC를 병렬 호출하지 말 것 (rate limit ban 위험). 백그라운드 두고 다른 작업 병행 |
| `papers_v2` 적재 중 EFS provisioned throughput 부족 | Phase 2 시작 전 한 번 활성화 검토 |
| 평가 게이트 회귀 (recall@10 하락) | **분기 의사결정 트리**: ① C2(publication_types) < 90% → PR-α 디버그 재방문 (efetch 추출 문제) ② C2 ≥ 90% AND C4(평균 토큰) 범위 외 → chunker 분포 이슈 점검 (PR #174 흡수 trade-off 또는 JATS 파서 잔여 문제) ③ C2/C4 모두 정상 AND recall 회귀 → alias swap 문제(rag.py collection lookup 캐시 버그) 또는 평가 스크립트 정합. 각 분기마다 별도 핫픽스 PR로 격리 |
| 적재 중간 ChromaDB HNSW partial-write 재발 | PR-ε의 graceful shutdown + alias-swap 패턴이 1차 방어. 발생 시 `papers_v2` 폐기 + Stage 4 재실행으로 격리 (`papers`는 무관) |
| efetch publication_types 픽스(S5)가 어려운 경우 | **정상 경로**: Pre-Upsert 게이트 합격(§3.3.1, C2 90%) → `papers_v2` 적재 → alias swap. **Incident override 경로**: C2 70%까지 일시 완화 가능, 단 **별도 컬렉션 `papers_v2_override`에만 적재** + **alias swap 금지** (prod alias는 `papers` 유지). override 승인 주체: jingyu (codeowner) + Slack/Telegram 1명 이상 팀 동의. override 적용 시 S5 픽스 PR 생성 의무 (override는 임시 운영 상태로만 허용, 1주 이내 정상 경로로 회귀) |
| 재크롤 비용/시간 부족으로 사후 메타 패치가 필요한 경우 | **운영 도구**: `mlops/scripts/patch_emb_publication_types.py` — 기존 임베딩 jsonl의 `publication_types`/`evidence_weight`만 PMID→NCBI efetch로 in-place 갱신, 임베딩 벡터 재계산 없음. 임베딩 비용 (시간/GPU) 절감용 incident 도구. **단, 청크 사이즈(평균 56 토큰) 문제는 해소되지 않음** — chunker packing 효과 보려면 결국 재청킹 필요. 사후 패치는 evidence_weight 차등화만 임시 복원하는 단기 대안 |

---

## §4 의존성 및 후속 작업

### 4.1 의존성

**코드 의존성**:
- PR #174 (chunker packing) — ✅ 2026-05-28 머지 완료 (`a3eede2`)
- develop OTP 회원가입 머지 — ✅ 0d5fde2까지 반영

**인프라 의존성**:
- AWS 환경: EFS `/chroma-data`, ECS Fargate, Route 53, ACM (CLAUDE.md §2)
- GPU 서버: `<교내 GPU 서버>` — fetch/chunk/embed 실행 환경

**Phase 2 시작 전 prerequisite 체크리스트**:
- [ ] GPU 서버 SSH 접근 (alias `gpu`, key-based auth) — `ssh gpu` 통신 확인
- [ ] AWS CLI `ecs execute-command` 권한 (Phase 1 백업 + 와이프) — IAM `AmazonECSExecAccess` + ECS exec 활성화된 task
- [ ] `ADMIN_API_TOKEN` 시크릿 (Secrets Manager 또는 .env, X-Admin-Token 헤더용)
- [ ] `gh` CLI 인증 (`gh auth status` OK) — PR 생성/review용
- [ ] EFS snapshot 권한 (`elasticfilesystem:CreateSnapshot`) — 가능하면 백업 강화용
- [ ] CloudWatch 로그 그룹 접근 (`/ecs/scifit-sync`) — C7 다운타임 증적
- [ ] PubMed efetch 무인증 호출 quota (E-utilities, IP 기반 rate limit) — 5/20 재크롤 1주에 영향
- [ ] OpenAlex API key (있으면 rate limit 완화) — 환경변수 `OPENALEX_API_KEY`

**시크릿/환경변수 준비 상태**:
- `ADMIN_API_TOKEN`, `DATABASE_URL`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `KAKAO_REST_API_KEY` — ECS Task Definition `secrets` 참조 (CLAUDE.md §2)
- GPU 서버 `.env`: `API_BASE_URL=https://scifit-sync.com`, `ADMIN_API_TOKEN`, `NCBI_HTTP_*`, `CHROMA_*`, `EMBEDDING_DIM=1024`

### 4.2 후속 작업 (out-of-scope이지만 추적 필요)

- D1: rag.py threshold 정책 (raw similarity vs weighted score)
- D2: `DEFAULT_EVIDENCE_WEIGHT` 보존/변경 결정
- 신규 데이터 소스 (Semantic Scholar 등) 추가
- ChromaDB → pgvector 마이그레이션 검토
- 자동화 cron 설정 (수동 1회성 검증 후)

---

## §5 참고

- 메모리: [[project_chunker_section_size_diagnosis]], [[project_jats_nested_sec_bug]], [[project_evidence_weight_data_gap]], [[project_prod_rag_full_reload_20260528]]
- PR #174 머지 커밋: a3eede2
- 5/22 발견 메모리 #11735: "ChromaDB Metadata Lacks evidence_weight Field" — 후속 처리 누락 상태에서 본 spec으로 통합 처리
