# Curated Paper Ingest Pipeline for Goldset Evaluation

작성일: 2026-05-23
대상 브랜치: 후속 `feat/jingyu/curated-ingest` (예정)
참조: `mlops/eval/LABELING_PLAN.md`, `feat/jingyu/goldset-labeling`

## 1. Background

`mlops/eval/goldset_seed.jsonl` (102 query)의 `expected_pmids`는 전부 빈 배열 상태. 원래 `LABELING_PLAN.md`는 pool-based labeling (RAG top-20 후보 중 binary 판정, ~17시간 수작업)을 제안했음. 사용자는 별도로 `논문.txt`에 query별 PMID/DOI를 직접 큐레이션했고, 이 expert curation으로 pool-based 수작업을 우회하고자 함.

다만 현재 RAG corpus (~785 paper, 5600 chunk 추정)에 이 큐레이션 paper들이 얼마나 적재돼 있는지 불명. 사용자 직관은 "코사인 유사도가 낮다"이고, 적재 안 된 paper가 다수일 가능성이 큼.

## 2. Goal

**`논문.txt`의 큐레이션 paper를 기존 RAG 파이프라인에 명시 입력으로 적재하고, 적재 결과를 기반으로 `goldset.jsonl`을 자동 생성한다.** 이후 `run_eval.py`로 baseline recall@5/10·MRR 측정.

**Non-goals**:
- 카테고리 필터 기반 검색 (`goldset_q*` 태그로 필터링) — 시도하지 않음. retrieval은 일반 semantic search.
- 기존 indexed paper의 메타 갱신 (categories MERGE) — 본 PR에서 다루지 않음.
- 서버 코드 변경 — `/admin/rag/ingest`, `search_chunks` 시그니처 등 그대로 사용.
- **`run_eval.py` 수정 — 변경 없음.** `build_goldset.py`가 `expected_pmids`에 채워 넣는 값을 **matchable set** (`indexed=true AND resolved_pmid non-empty`)으로 한정함으로써 `run_eval.py` 자체 코드 변경 없이 평가 의미를 닫는다. 큐레이션 원본 PMID는 별도 필드 `curated_pmids_all`에 보존하여 corpus coverage 측정에 사용.
- 새 평가 방법론 도입 — 기존 `(query, top_k) → retrieved chunks → expected_pmids 매칭` 그대로.

## 3. Approach

3개 스크립트로 구성. 기존 파이프라인의 search-driven discovery만 우회하고 downstream(fulltext / chunker / embedder / upserter / manifest)은 그대로 재사용.

```
[로컬]                            [GPU 서버 cloud]                      [로컬]

parse_curated_papers.py    →    ingest_curated_pmids.py    →    build_goldset.py
       │                                │                              │
       ▼                                ▼                              ▼
curated_provenance.json    (efetch → fulltext → chunk →           goldset.jsonl
curated_issues.json         embed → API ingest, flock)            (expected_pmids
       │                                │                          + in_corpus 분리)
       │                                ▼                              │
       │                       manifest + provenance update            ▼
       │                                                          run_eval.py
       └────────────────────────────────┐                          baseline 리포트
                                        │
                            provenance에 indexed/fulltext_ok 기록
```

## 4. Components

### 4.1 `mlops/scripts/parse_curated_papers.py` (로컬, ~120 LoC)

**입력**: `/mnt/c/Users/User/Desktop/coding/Main_Project/capstone/논문.txt`

**책임**:
- 정규식으로 Q번호별 PMID/PMCID/DOI 추출
- 명시 삭제 항목 (`Q004 삭제`, `질문 삭제`) 스킵
- 이슈 자동 검출:
  - placeholder DOI (말미 `*.XXXX`)
  - 미래 prefix DOI (`10.1xxx/...-026-...`, `10.1xxx/...-2026-...`)
  - typo DOI (`0.1xxx/...` → `10.1xxx/...` 자동 보정 후보 + title mismatch 검증용 메타 저장)
  - 동일 paper가 여러 Q-id에 매핑 (정상, 다대다 보존)
- DOI normalization은 `normalize_doi()` 공용 helper로 (strip, lower, `https://doi.org/` 제거, 말미 구두점 제거)

**출력 1**: `mlops/data/curated_provenance.json` (Critical #1 대응 — manifest로 갈음 불가)
```json
{
  "Q001": {
    "category": "hypertrophy",
    "papers": [
      {
        "raw_id": "PMID:35291645",
        "resolved_pmid": "35291645",
        "resolved_doi": null,
        "resolved_title": null,
        "indexed": null,
        "already_in_corpus": null,
        "fulltext_ok": null,
        "failure_reason": null,
        "search_categories": ["hypertrophy"]
      },
      {
        "raw_id": "DOI:10.1080/02640414.2016.1210197",
        "resolved_pmid": null,
        "resolved_doi": "10.1080/02640414.2016.1210197",
        ...
      }
    ]
  }
}
```
`resolved_*` / `indexed` / `fulltext_ok` 필드는 parse 단계에서는 null, ingest 단계에서 채움.

**출력 2**: `mlops/data/curated_issues.json`
```json
{
  "placeholder_doi": [{"qid": "Q039", "value": "10.1001/jamanetworkopen.2024.XXXX"}, ...],
  "future_prefix_doi": [{"qid": "Q027", "value": "10.1007/s40279-026-02401-y"}, ...],
  "typo_doi_autofixed": [{"qid": "Q037", "original": "0.1123/ijsnem.2013-0054", "fixed": "10.1123/ijsnem.2013-0054"}, ...],
  "duplicate_in_query": [{"qid": "Q017", "doi": "10.1007/s00421-011-2249-9", "count": 2}, ...],
  "deleted_queries": ["Q004", "Q006", "Q011", "Q024", "Q060", "Q062", "Q064", "Q066"]
}
```

### 4.2 `mlops/scripts/ingest_curated_pmids.py` (cloud GPU, ~200 LoC)

**입력**: `curated_provenance.json` (parse 산출물)

**책임**: `initial_ingest.py:main()`의 흐름을 그대로 따르되, `crawl_papers()` 호출만 `fetch_papers_from_ids()`로 교체. 모든 downstream(chunker/embedder/api_ingest/manifest)은 그대로 재사용.

**`fetch_papers_from_ids()` 내부 흐름** (단일 상태머신, Codex 2차 리뷰 반영):

**Step 1 — existing_dois 로딩**
`existing_dois = manifest_dois ∪ server_dois`. 모든 DOI는 `normalize_doi()` 적용 후 set에 들어감.

**Step 2 — Input 펼침**
parse 출력의 모든 paper를 `(raw_pmid, raw_doi, qid, category)` tuple로 펼침. 동일 paper가 여러 Q에 있으면 같은 raw_id 묶음으로 처리 (다대다 보존).

**Step 3 — Identifier 해석 (단일 상태머신)**

```
                ┌─── PMID 있음 ───┐
                │                  │
                ▼                  │
        PubMed efetch (batch 200) ◄┘
                │
                ├── DOI 추출 성공 ──► resolved_pmid + resolved_doi 채움 → Step 4
                │
                └── DOI 추출 실패 ──► NCBI ID Converter (PMID → DOI)
                                          │
                                          ├── 성공 ──► resolved_pmid + resolved_doi 채움 → Step 4
                                          │
                                          └── 실패 ──► failure_reason="doi_resolution_failed", skip


                ┌─── DOI만 있음 (PMID 없음) ───┐
                │                                │
                ▼                                │
   OpenAlex DOI lookup ◄────────────────────────┘
   (`GET https://api.openalex.org/works/doi:{normalized_doi}`)
                │
                ├── 200 OK + PMID 있음 ──► resolved_pmid + resolved_doi 채움 → Step 4
                │
                ├── 200 OK + PMID 없음 ──► failure_reason="no_pmid_from_openalex", skip
                │                          (PMID 없으면 evaluator 매칭 불가, matchable_in_eval 정의상 무의미)
                │
                └── 404 / empty ───────► failure_reason="openalex_not_found", skip
```

PubMed efetch 시 일부 PMID가 응답에 누락된 경우: 누락된 PMID만 모아 single-fetch (id=PMID 1개씩)로 재시도 1회. 그래도 누락이면 `failure_reason="efetch_not_found"` 기록 + skip.

NCBI ID Converter API: `https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids=<pmid>&format=json`. 응답의 `records[0].doi` 확인.

**Step 4 — Title sanity check** (Low #10 반영)
parse 단계에서 `typo_doi_autofixed`로 마킹된 paper에 한해 simple keyword overlap 검증:
- `resolved_title.lower()` vs query 컨텍스트의 핵심 키워드 (LABELING_PLAN category, Q의 query string에서 추출한 stop-word 제거 토큰들)
- overlap ratio < 0.2 → `failure_reason="title_mismatch"` 기록 + skip

**Step 5 — `already_in_corpus` 처리**
Step 3에서 채워진 `resolved_doi`가 `existing_dois`에 있으면:
- `already_in_corpus = true`, `indexed = true` 기록
- `resolved_pmid`는 이미 Step 3에서 채워졌으므로 backfill 자동 완료 (High #1 해소)
- 청킹/임베딩/api_ingest 스킵, 다음 paper로

**Step 6 — Fulltext cascade**
`fulltext.fetch_cascading()` PMC → EuropePMC (변경 없음).
- 성공 → `fulltext_ok=true`, sections 확보
- 실패 → `fulltext_ok=false`, sections=[]로 진행 → chunker가 0 chunk 처리 → `indexed=false`로 자동 귀결

**Step 7 — Evidence weight**
`evidence.calculate_evidence_weight()` 호출 (Medium #9 — publication_types 의존만, search-context 의존 없음).

**Step 8 — search_categories 주입**
`paper.search_categories = [<labeling_plan_category>]` (LABELING_PLAN 카테고리 1개. Q-id 태그 없음).

**Step 9 — PaperFull 반환**
downstream(chunker / embedder / api_ingest / manifest)은 기존 그대로. api_ingest 성공 시 provenance에 `indexed=true` 기록.

**동시성 보호** (Medium #8): 스크립트 시작 시 `mlops/data/.ingest.lock`에 `flock` 획득. `run_3k.sh`와 본 스크립트는 같은 락 사용해 serialize. 락 획득 실패 시 명확한 에러 메시지 출력하고 즉시 종료 (재시도 안 함, 사용자가 상황 판단 후 수동 재시도).

**Provenance 갱신 (atomic write)**: provenance 파일 갱신은 항상 다음 패턴 사용 — 장애 시 partial write로 인한 손상 방지:
```python
tmp_path = path.with_suffix('.json.tmp')
with open(tmp_path, 'w', encoding='utf-8') as f:
    json.dump(provenance, f, indent=2, ensure_ascii=False)
os.replace(tmp_path, path)  # atomic on POSIX
```
갱신 시점:
- Step 3 identifier 해석 직후: `resolved_pmid`, `resolved_doi`, `resolved_title` 채움
- Step 5 `already_in_corpus` 판정 직후: `indexed=true`, `already_in_corpus=true`
- Step 6 fulltext 결과 직후: `fulltext_ok`
- api_ingest 응답 직후 (성공한 paper만): `indexed=true`
- 모든 실패 경로: `failure_reason` 채움

검토 단위: 매 paper 단위가 아니라 batch 단위 (예: efetch 200건 처리 후 1회, fulltext 50건 처리 후 1회 등) — atomic write 비용 최소화.

### 4.3 `mlops/scripts/build_goldset.py` (로컬, ~100 LoC)

**입력**: `mlops/eval/goldset_seed.jsonl` + `mlops/data/curated_provenance.json` (ingest 후 indexed 필드 채워진 상태)

**핵심 설계 (Codex 2차 Critical #1 — 방법 B 채택)**: `run_eval.py` 코드는 일절 변경하지 않는다. 대신 `build_goldset.py`가 `expected_pmids`에 채우는 값을 **matchable set**으로 한정함으로써 평가의 의미를 닫는다. 큐레이션 원본 PMID는 별도 필드 `curated_pmids_all`에 보존.

**용어 정의** (단일 정의, 자기 모순 없음):
- `matchable_in_eval` (= goldset.jsonl의 `expected_pmids` 필드): `paper.indexed=true` **AND** `paper.resolved_pmid != ""`인 paper의 PMID. evaluator가 retrieved chunks의 `paper_pmid`와 비교 가능한 set.
- `curated_pmids_all`: 큐레이션된 paper 중 **resolved_pmid가 비어있지 않은 것**의 PMID set. 적재 실패 paper도 resolved_pmid가 있으면 포함. PMID 없는 DOI-only paper(`no_pmid_from_openalex`, `openalex_not_found`)는 coverage 계산에 무의미하므로 **포함하지 않음**. 평가에는 사용 안 함, coverage 측정 전용.
- `papers_failed`: `indexed=false`인 모든 paper의 entry (raw_id, resolved_pmid, failure_reason 포함). `failure_reason`은 §7 taxonomy 중 하나.

**책임**:
1. seed의 각 Q에 대해 provenance에서 해당 Q의 papers 조회
2. 각 paper를 분류:
   - `indexed=true AND resolved_pmid != ""` → `expected_pmids`에 추가, `curated_pmids_all`에도 추가
   - `indexed=false AND resolved_pmid != ""` → `papers_failed`에 추가, `curated_pmids_all`에 추가
   - `resolved_pmid = ""` (PMID 못 얻음) → `papers_failed`에 추가 (resolved_pmid 빈 값), `curated_pmids_all`에는 추가 안 함
3. `corpus_coverage = len(expected_pmids) / max(1, len(curated_pmids_all))`
4. **분모 제외 정책 (Method B 일관 적용)**: `run_eval.py`는 빈 `expected_pmids`를 recall=0.0으로 평균에 포함시키므로, **`expected_pmids=[]`인 Q는 goldset.jsonl에 entry를 쓰지 않는다.** 그러면 run_eval은 그 Q를 평가 자체에서 못 보고, 평균 분모에서 자동 제외됨. 코드 변경 없음.
5. **제외된 Q의 추적**: §4.3 출력 2의 summary 리포트에 별도 카운트로 보존:
   - `metrics_eligible_queries`: goldset.jsonl에 포함된 Q 개수 (`expected_pmids != []`)
   - `corpus_gap_queries`: 제외된 Q 중 `curated_pmids_all != []`인 것 (큐레이션은 됐는데 corpus에 매칭 가능한 게 없는 query — RAG 평가에 못 들어가지만 corpus 보강 우선순위)
   - `unlabeled_queries`: 제외된 Q 중 `curated_pmids_all=[]`인 것 (논문.txt에 항목 없거나 전부 placeholder/typo로 제거된 경우)

**출력 1**: `mlops/eval/goldset.jsonl`
```json
{
  "id": "Q001",
  "query": "What is the optimal weekly set volume per muscle group for hypertrophy?",
  "query_ko": "...",
  "category": "hypertrophy",
  "fitness_goals": ["hypertrophy"],
  "used_in": ["routine_generation"],
  "expected_pmids": ["35291645", "27433992"],
  "curated_pmids_all": ["35291645", "27433992", "30063555", "20512950"],
  "papers_failed": [
    {"raw_id": "DOI:10.1519/JSC.0000000000002776", "resolved_pmid": "30063555", "failure_reason": "no_fulltext"},
    {"raw_id": "PMID:20512950", "resolved_pmid": "20512950", "failure_reason": "no_fulltext"}
  ],
  "corpus_coverage": 0.50,
  "notes": "..."
}
```

`run_eval.py`는 기존 코드 그대로 `expected_pmids` 필드만 읽음. `curated_pmids_all`/`papers_failed`/`corpus_coverage`는 무시되지만 schema 호환성 깨지지 않음 (Pydantic extra fields는 ignore가 기본).

**출력 2**: `mlops/eval/reports/goldset_summary.md` (build_goldset이 함께 생성)
- query별 corpus coverage 표
- `corpus_gap_queries` 목록 (RAG 평가에서 0점 받을 query — corpus 보강 우선순위)
- `unlabeled_queries` 목록 (논문.txt 추가 큐레이션 필요)
- 전체 통계: matchable PMID 총수, eligible query 비율 등

## 5. Data flow (end-to-end)

```
1. 로컬: parse_curated_papers.py
   논문.txt → curated_provenance.json (resolved 필드 미채움) + curated_issues.json

2. scp curated_provenance.json → cloud:/mnt/data/scifit-sync/scifit-sync/mlops/data/

3. cloud GPU: ingest_curated_pmids.py (flock 락)
   - existing_dois 로딩
   - efetch batch 200 → metadata 수집
   - fulltext cascade → chunk → embed → API ingest
   - provenance in-place 업데이트 (indexed/fulltext_ok 등)
   - manifest 갱신

4. scp cloud:.../curated_provenance.json → 로컬 mlops/data/

5. 로컬: build_goldset.py
   goldset_seed.jsonl + curated_provenance.json → goldset.jsonl

6. 로컬: python -m mlops.eval.run_eval --goldset mlops/eval/goldset.jsonl
   baseline 리포트 출력
```

## 6. Decision Log

### 6.1 Codex 1차 리뷰 반영 결과

| Codex 1차 지적 | 등급 | 본 spec 반영 |
|---|---|---|
| #1 build_goldset manifest 기반 불가 | Critical | ✅ provenance artifact로 승격, manifest 사용 안 함 |
| #2 dedup skip이 카테고리 MERGE 막음 | High | ❌ 해당 없음 — 카테고리 필터 전략 폐기 |
| #3 retriever filters 인자 필요 | High | ❌ 해당 없음 — 카테고리 필터 전략 폐기 |
| #4 DOI 미해결 hard skip | High | ✅ `failure_reason` 기록 + chunking/ingest 전 stage에서 skip |
| #5 DOI normalization | High | ✅ `normalize_doi()` 공용 helper, 전 단계 적용 |
| #6 efetch-first | Medium | ✅ efetch 200 batch가 1차, converter는 fallback |
| #7 in_corpus 분리 리포트 | Medium | ✅ `expected_pmids` vs `curated_pmids_all` 분리 (6.2 #1 참조) |
| #8 flock with run_3k.sh | Medium | ✅ `.ingest.lock` 공용 flock + graceful exit |
| #9 post-condition 충족 | Medium | ✅ `PaperFull` 스키마 모두 충족 + DOI-only matchability 닫음 (6.2 #3 참조) |
| #10 title mismatch | Low | ✅ typo auto-fix시 keyword overlap 검증 |

**대전제 변경**: "카테고리 필터로 평가"라는 가정을 사용자 의견에 따라 폐기. 평가는 일반 semantic search retrieval + expected_pmids 매칭. 결과적으로 Codex의 High 2개가 무력화되고 서버 코드 변경이 0개로 감소.

### 6.2 Codex 2차 리뷰 반영 결과

| Codex 2차 지적 | 등급 | 본 spec 반영 |
|---|---|---|
| #1 평가 계약 미체결 (run_eval.py 변경 vs 그대로 사용 모순) | Critical | ✅ **방법 B 채택**: build_goldset이 `expected_pmids`를 matchable set으로 한정, `curated_pmids_all`은 별도 필드. `run_eval.py` 코드 일절 변경 없음. §2 Non-goals + §4.3 명시. |
| #2 `already_in_corpus` PMID backfill 누락 | High | ✅ **identifier 해석을 dedup보다 먼저 수행**. Step 3에서 resolved_pmid 채운 뒤 Step 5에서 already_in_corpus 판정. §4.2 단일 상태머신. |
| #3 efetch-first / converter / skip 충돌 | High | ✅ **단일 상태머신으로 재작성**. 분기 A (PMID 있음): efetch → converter fallback → skip. 분기 B (DOI만): OpenAlex DOI lookup → skip. failure_reason taxonomy 통일 (§7 참조). |
| #4 `expected_pmids_in_corpus` 정의 실수 | High | ✅ **`matchable_in_eval = indexed=true AND resolved_pmid != ""`로 재정의**. PMID 없는 DOI-only paper는 적재되더라도 expected_pmids에 들어가지 않음 (evaluator 매칭 불가). §4.3에 용어 정의 명시. |
| #5 OpenAlex fallback 막연 | Medium | ✅ **DOI lookup endpoint 명시**: `GET https://api.openalex.org/works/doi:{normalized_doi}`. 404/empty/no_pmid 분기 + failure_reason 정의. §4.2 Step 3 분기 B. |
| #6 §7 에러 표 미닫힘 + atomic write | Medium | ✅ `efetch_not_found`, `embed_failed`, `api_ingest_failed`, `openalex_not_found`, `no_pmid_from_openalex` 추가. provenance `tmp + os.replace` 패턴 명시 (§4.2 Provenance 갱신). |
| #7 §8 테스트 갭 | Medium | ✅ already_in_corpus PMID backfill, DOI-only unmatchable, expected_pmids=[] 분류, efetch partial batch, OpenAlex 404 테스트 추가 (§8). |

### 6.3 Codex 3차 리뷰 반영 결과

| Codex 3차 지적 | 등급 | 본 spec 반영 |
|---|---|---|
| #1 `expected_pmids=[]` 분모 제외 미닫힘 | High | ✅ **build_goldset이 empty Q는 goldset.jsonl entry에서 아예 제외**. run_eval은 자동으로 평균 분모에서 빠짐. 제외된 Q는 summary 리포트에서 `corpus_gap_queries` / `unlabeled_queries`로 분리 추적. §4.3 책임 4번 + 5번 항목. |
| #2 `no_fulltext` 계약 미닫힘 | High | ✅ §7.1 enum에 `no_fulltext` 추가. fulltext 실패 paper도 `failure_reason="no_fulltext"` + `fulltext_ok=false`로 일관 기록. resumability 규칙 (§7.5)이 모든 failure_reason에 적용됨. |
| #3 `curated_pmids_all` 자기모순 | Medium | ✅ **resolved_pmid 있는 paper만 포함**으로 단일 정의 (PMID 없으면 coverage 계산에 무의미). §4.3 용어 정의 명시. |
| #4 §7 enum 엄밀성 + §8.5 폐기 용어 | Medium | ✅ §7을 4개 sub-section으로 재구성: 7.1 enum (papers_failed용 8개 값), 7.2 parse-time issues, 7.3 정상 흐름, 7.4 process-level, 7.5 resumability. §8.5에서 `expected_pmids_in_corpus` 옛 용어 제거. |

### 6.4 Codex 4차 리뷰 반영 결과

| Codex 4차 지적 | 본 spec 반영 |
|---|---|
| `failure_reason != null ⟺ indexed=false` 불변 조건 미명시 | ✅ §7.1에 invariant 명시. provenance 무결성 위반 조건도 정의. |
| transient → permanent enum 귀결 계약 미명시 | ✅ §7.4 상단에 명시 + 표에 각 transient의 최종 귀결 enum 1:1 매핑. |
| corpus coverage 집계 대상 모호 | ✅ §8.5에 산식 형식으로 명시. 분모/분자 정의 + emitted goldset이 아니라 seed 전체 기준임을 강조. |

## 7. Error Handling

### 7.1 `failure_reason` enum — provenance-tracked failures (§4.2 상태머신과 1:1)

papers_failed entry의 `failure_reason` 필드는 다음 8개 값 중 하나만 가질 수 있다.

**불변 조건 (invariant)**:
- `failure_reason != null` ⟺ `indexed = false` (양방향 동치)
- `failure_reason = null` ⟺ `indexed ∈ {true, null}` (정상 흐름 또는 미처리)
- 모든 실패 경로 (§4.2 Step 3 분기 A/B의 skip, Step 4 title_mismatch, Step 6 no_fulltext, embedder 실패, api_ingest 실패)는 provenance에 **`failure_reason` 와 `indexed=false`를 함께 기록한다.** 둘 중 하나만 기록되는 상태는 invalid (provenance 무결성 위반).
- 재시작 시 skip 조건은 `indexed=true OR failure_reason != null` 양쪽 모두로 판정 (둘 다 같은 결과지만 방어적으로 OR).

| failure_reason | 발생 시점 | 처리 |
|---|---|---|
| `doi_resolution_failed` | §4.2 Step 3 분기 A | efetch + converter 모두 실패. PMID 입력에서 DOI를 못 얻음. skip. |
| `efetch_not_found` | §4.2 Step 3 분기 A | efetch batch 응답에 해당 PMID 누락 + single re-fetch 1회도 실패. skip. |
| `openalex_not_found` | §4.2 Step 3 분기 B | OpenAlex DOI lookup 404 또는 empty 응답. skip. |
| `no_pmid_from_openalex` | §4.2 Step 3 분기 B | OpenAlex 200 OK인데 PMID 필드 없음 (evaluator 매칭 불가). skip. |
| `title_mismatch` | §4.2 Step 4 | typo auto-fixed paper의 keyword overlap < 0.2. skip. |
| `no_fulltext` | §4.2 Step 6 | PMC + EuropePMC 모두 fulltext 없음. sections=[] → chunker가 0 chunk → 자동 skip. 동시에 `fulltext_ok=false`로 기록. |
| `embed_failed` | embedder | GPU OOM 등 batch 실패 → 단일 batch retry 1회 → 그래도 실패 시 skip. |
| `api_ingest_failed` | api_ingest | 서버 5xx 응답 → 기존 NCBI_HTTP_MAX_RETRIES (5회) 패턴 → 최종 실패 시 skip. |

### 7.2 parse-time issues — `curated_issues.json`에 기록 (provenance 진입 전)

논문.txt 원본에서 즉시 제거되거나 보정되는 경우. provenance entry로 등재되지 않음.

| 케이스 | 처리 | issues.json 기록 |
|---|---|---|
| placeholder DOI (`*.XXXX`) | 즉시 제거 | `placeholder_doi[]` |
| 미래 prefix DOI (`10.1xxx/...-026-...`) | 즉시 제거 | `future_prefix_doi[]` |
| typo DOI (`0.1xxx/...`) | auto-fix 후 provenance 등재 (§4.2 Step 4에서 sanity check) | `typo_doi_autofixed[]` (raw_id, autofixed_doi) |
| 중복 PMID/DOI (Q내) | dedup, count 기록 | `duplicate_in_query[]` |
| 명시 삭제 마크 (`Q004 삭제`) | Q 자체 스킵 | `deleted_queries[]` |

### 7.3 정상 흐름 (failure_reason 없음)

| 케이스 | 처리 | provenance 기록 |
|---|---|---|
| 동일 paper, 다중 Q | 같은 raw_id를 multiple Q에 등재 (다대다 보존) | provenance의 각 Q.papers[]에 entry |
| 이미 적재된 DOI | §4.2 Step 5 skip | `already_in_corpus=true, indexed=true`, `resolved_pmid`는 Step 3에서 채움 |
| 정상 적재 | §4.2 Step 9 완료 | `indexed=true, fulltext_ok=true, already_in_corpus=false` |

### 7.4 process-level 장애 (failure_reason과 별개)

**Transient → Permanent 귀결 계약**: HTTP 5xx / 타임아웃 / 일시적 네트워크 단절은 모두 **transient**로 분류하여 `NCBI_HTTP_MAX_RETRIES` (5회) backoff retry 실시. **retry 소진 후에도 실패하면 해당 단계의 영구 failure_reason enum으로 귀결**하여 `papers_failed`에 등재. 즉, transient는 절대 in-flight 상태로 provenance에 머무르지 않으며, 항상 §7.1의 enum 값 하나로 닫힌다. 이 계약으로 §7.5 재시작 규칙이 transient 실패를 무한 재시도하는 위험을 차단한다.

| 케이스 | 분류 | 처리 | 최종 귀결 |
|---|---|---|---|
| NCBI efetch transient (5xx/timeout) | transient | NCBI_HTTP_MAX_RETRIES backoff | 성공 시 정상 흐름, 실패 시 `efetch_not_found` (영구) |
| NCBI ID Converter transient | transient | NCBI_HTTP_MAX_RETRIES backoff | 성공 시 정상 흐름, 실패 시 `doi_resolution_failed` (영구) |
| OpenAlex transient (5xx/timeout) | transient | NCBI_HTTP_MAX_RETRIES backoff | 성공 시 정상 흐름, 실패 시 `openalex_not_found` (영구) |
| EuropePMC transient | transient | NCBI_HTTP_MAX_RETRIES backoff | 성공 시 정상 흐름, 실패 시 `no_fulltext` (영구) |
| GPU OOM 또는 embedder 일시 장애 | transient | 단일 batch retry 1회 | 성공 시 정상 흐름, 실패 시 `embed_failed` (영구) |
| api_ingest 5xx | transient | NCBI_HTTP_MAX_RETRIES backoff | 성공 시 정상 흐름, 실패 시 `api_ingest_failed` (영구) |
| Lock 획득 실패 (run_3k.sh 동시 실행 중) | **process-level**, paper와 무관 | stderr 에러 + PID 안내, exit code 1 | (provenance 기록 없음, 수동 재시도) |
| 스크립트 중단 (SIGINT/SIGTERM/OOM) | **process-level**, paper와 무관 | atomic write로 직전 batch 시점까지 보존 | 재시작 시 §7.5 적용 (미처리 paper만 재처리) |

### 7.5 Resumability

스크립트 재시작 시 provenance를 읽어 다음 paper만 처리:
- `indexed=true` 또는 `failure_reason` 필드가 채워진 paper → 스킵
- 둘 다 null인 paper → 미처리 → 처리 큐에 포함

**Provenance 파일 무결성**: 모든 갱신은 `tmp + os.replace` atomic 패턴 (§4.2 Provenance 갱신 참조). 중단돼도 마지막 batch 갱신 시점까지의 상태는 손상 없이 보존됨.

## 8. Testing

### 8.1 `parse_curated_papers.py` (unit)
- placeholder/future-prefix/typo 검출 정확성
- 동일 paper의 multi-Q 매핑 보존
- `normalize_doi()` 멱등성 (대문자, URL prefix, 말미 구두점)
- 삭제 마크 항목 (`Q004 삭제`) 스킵 검증

### 8.2 `ingest_curated_pmids.py` (mocking)
- 이미 indexed된 DOI 입력 시 청킹 skip + `already_in_corpus=true`
- **already_in_corpus skip 경로에서도 PMID backfill 확인** (Step 3에서 resolved_pmid 채워진 뒤 Step 5에서 skip — DOI-only input이 이미 corpus에 있어도 expected_pmids에 들어갈 수 있도록 보장) — Codex 2차 High #2
- efetch batch 응답 mock으로 metadata 추출 검증
- **efetch partial batch 처리**: 200건 요청에 195건만 응답 → 누락 5건 single re-fetch 후 실패 시 `efetch_not_found` — Codex 2차 #7
- DOI 미해결 PMID는 chunker까지 안 내려가는지 hard skip 경로 검증
- **DOI-only paper의 PMID 매칭 불가 경로**: OpenAlex가 200 응답하지만 PMID 없는 경우 → `no_pmid_from_openalex` 기록 + skip (expected_pmids에 들어가지 않음) — Codex 2차 High #3
- **OpenAlex DOI lookup 404 처리**: → `openalex_not_found` 기록 + skip — Codex 2차 Medium #4
- title mismatch failure path 검증
- `search_categories`에 LABELING_PLAN 카테고리만 들어가는지 (Q-id 태그 없음)
- flock 경합 시 graceful exit (exit code 1, stderr 메시지)
- **Provenance atomic write**: 중간에 process kill 시 provenance JSON 파일이 손상되지 않는지 (tmp_path 잔존만 허용) — Codex 2차 Medium #5

### 8.3 `build_goldset.py` (unit)
- provenance + seed → goldset.jsonl 변환
- **`expected_pmids` = matchable set 검증**: indexed=true AND resolved_pmid != "" 인 paper만 포함되는지 — Codex 2차 Critical #1
- **`curated_pmids_all` 보존 검증**: 적재 실패 paper의 resolved_pmid도 포함 (resolved_pmid가 채워진 경우에 한해)
- **`expected_pmids=[]` query 분류 검증**:
  - `curated_pmids_all != []` AND `expected_pmids = []` → `corpus_gap_queries` 카운트에 포함
  - `curated_pmids_all = []` → `unlabeled_queries` 카운트에 포함
  - `metrics_eligible_queries` 카운트 정확성
- 적재 실패 paper의 `papers_failed` 기록 (raw_id, resolved_pmid, failure_reason)
- `corpus_coverage` 계산 정확성
- 동일 paper가 multiple Q에 등재될 때 각 Q의 expected_pmids에 모두 등장하는지

### 8.4 Smoke test (cloud, 통합)
- `--limit 10` 옵션으로 첫 10 paper만 처리
- 변환 성공률 / fulltext 성공률 / chunk 개수 / api_ingest 응답 확인
- 통과 후 풀 실행

### 8.5 End-to-end (수동)
- 풀 실행 후 `run_eval.py` 돌려 baseline 리포트 (run_eval은 emitted goldset.jsonl만 평가)
- **전체 corpus coverage 집계 대상은 seed 전체 기준** (emitted goldset이 아님). build_goldset의 summary 리포트에서:
  ```
  total_corpus_coverage = Σ_{Q ∈ seed} len(expected_pmids_Q) / Σ_{Q ∈ seed} len(curated_pmids_all_Q)
  ```
  - 분모: seed의 **모든 Q**에서 `resolved_pmid` 얻은 paper 수 (`expected_pmids=[]`라서 emitted goldset에서 빠진 Q도 분모에 포함)
  - 분자: `indexed=true AND resolved_pmid != ""`인 paper 수
  - 이 산식이 "큐레이션 paper 중 RAG에서 매칭 가능한 비율"을 의미함. emitted goldset만 분모로 쓰면 corpus_gap_queries가 누락되어 coverage가 과대평가됨.
- `metrics_eligible_queries` (=emitted goldset Q 개수) / `corpus_gap_queries` / `unlabeled_queries` 카운트 sanity check: 합이 seed의 총 query 개수와 일치
- recall@5/10/MRR가 query 카테고리별로 분포 확인 (run_eval 출력 — emitted goldset 한정)

## 9. Open Questions / Future Work

- **OpenAlex/EuropePMC fulltext recovery rate**: 현재 추정 ~48% (PMC OA 한정). 큐레이션 paper의 closed access 비율이 높으면 in_corpus coverage가 낮을 수 있음. 추후 fulltext 소스 확장 검토.
- **Categories MERGE**: 본 PR 범위 밖. 이후 D-issue로 등록하여 기존 indexed paper에 큐레이션 컨텍스트 메타 추가 가능성 평가.
- **Retriever filter 인자**: 본 PR 범위 밖. 카테고리 필터 평가 전략을 다시 채택하면 후속 D-issue.
- **Q-id 태그 부활 여부**: 현재 미사용이지만, 향후 query별 retrieval 분석에 유용할 수 있음. `extra_metadata` 같은 별도 필드로 ChromaDB metadata에 둘지 검토.
- **Pool-based labeling 잔존 가치**: expert curation에서 누락된 borderline relevant paper 발굴용. 별도 D-issue.
