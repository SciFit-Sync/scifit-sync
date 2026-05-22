# 골드셋 라벨링 작업 계획 (Goldset Labeling Plan)

`mlops/eval/goldset_seed.jsonl` (88개 query 시드) → 라벨링 완료
`mlops/eval/goldset.jsonl` 까지의 작업 단계를 정리한 워킹 플랜.

## 1. 현재 상태

- 시드 파일: `mlops/eval/goldset_seed.jsonl` (88 entries, 완료)
  - 분포: hypertrophy 12 / strength 12 / muscle_specific 10 / endurance 8 /
    weight_loss 8 / frequency_split 8 / recovery 8 / exercise_selection 8 /
    progressive_overload 6 / special_populations 4 / form_technique 4
  - `expected_pmids`: 전부 빈 배열 (라벨링 대기)
- 평가 스크립트: `mlops/eval/run_eval.py` (mocking 테스트 22개 통과, schema 호환)
- corpus: cloud 진행 중 (~5600 청크). `refactor/jingyu/trim-search-categories`
  merge 후 재크롤 + ChromaDB 메타 동기화 권장 (선행 조건)

## 2. 라벨링 워크플로 (pool-based judgment)

학계 IR 평가 표준인 pooling 기법. 사람이 PubMed 전체에서 정답을 찾는 게
아니라, 현재 RAG가 top-N으로 떠올린 후보 중에서만 binary 판정한다.

### 2.1. PMID pool 추출

- 신규 스크립트: `mlops/scripts/extract_pmid_pool.py`
- 입력: cloud manifest.json (fulltext_source != None 만)
- 출력: `mlops/eval/pmid_pool.json` (paper 단위 PMID 목록)

### 2.2. Query → candidate pooling

- 신규 스크립트: `mlops/scripts/pool_candidates.py`
- 입력: `goldset_seed.jsonl` + ChromaDB
- 처리: 각 query를 retriever에 던져 top-20 PMID 후보 수집
  (chunk-level over-fetch → paper-level dedup, `run_eval.py:evaluate_query` 패턴 재사용)
- 출력: `mlops/eval/candidates.jsonl` (qid → top-20 PMIDs + 청크 미리보기)

### 2.3. Human labeling

- 후보 PMID에 대해 binary 판정 (1=relevant / 0=irrelevant)
- 옵션 A: 간단 CLI (`mlops/scripts/label_cli.py`) — PMID + 청크 본문 보여주고 y/n 입력
- 옵션 B: candidates.jsonl → CSV export → 스프레드시트 채움 → 다시 import
- 출력: `mlops/eval/labels.jsonl` (qid + PMID + relevance)

### 2.4. 최종 골드셋 생성

- 신규 스크립트: `mlops/scripts/build_goldset.py`
- 입력: `goldset_seed.jsonl` + `labels.jsonl`
- 처리: seed의 `expected_pmids`에 relevance=1 PMID 머지
- 출력: `mlops/eval/goldset.jsonl` (run_eval.py가 직접 소비 가능)

### 2.5. 평가 실행

```bash
python -m mlops.eval.run_eval \
    --goldset mlops/eval/goldset.jsonl \
    --output mlops/eval/reports/$(date +%Y-%m-%d).md
```

리포트는 전체 지표 + 카테고리별 recall@5/10, MRR 분석.

## 3. 알려진 corpus gap (라벨링 시 주의)

`refactor/jingyu/trim-search-categories` 분석에서 도출된 corpus 누락 영역.
해당 query는 expected_pmids가 0~1건 정도로 낮을 가능성 — recall이 다른
query 대비 현저히 낮으면 corpus gap이지 RAG 알고리즘 문제 아님.

| Query | Gap 원인 |
|---|---|
| Q036 (HIIT vs LISS) | crawler 카테고리에 HIIT/LISS 직접 검색어 없음 |
| Q092 (60+ 노인) | `(humans OR adults)` 필터로 일부 캡처되나 노인 특화 검색어 없음 |
| Q093 (여성·월경 주기) | 여성 호르몬 전용 검색어 없음 (`women_resistance`는 OAM orphan) |
| Q094 (청소년) | `(humans OR adults)` 필터가 adolescent 배제 효과 |

## 4. 작업 체크리스트

- [ ] (선행) `refactor/jingyu/trim-search-categories` merge → cloud 재배포
- [ ] (선행) `python -m mlops.scripts.refresh_search_categories --clear-unmatched` 실행
- [ ] `extract_pmid_pool.py` 작성 + 실행 → `pmid_pool.json`
- [ ] `pool_candidates.py` 작성 + 실행 → `candidates.jsonl`
- [ ] Labeling 도구 결정 (CLI vs 스프레드시트) — 인원·시간 트레이드오프 검토
- [ ] Labeling 수행 (88 × top-20 ≈ 1760건 판정. 1건 30초 가정 시 ~15시간)
- [ ] `build_goldset.py` 작성 + 실행 → `goldset.jsonl`
- [ ] `run_eval.py` 실행 → 베이스라인 리포트 (`mlops/eval/reports/`)
- [ ] 카테고리별 recall 분석 + corpus gap 검증 (§3 표 기준)
- [ ] CI 통합 (recall@10 threshold gating, 선택)
- [ ] 후속 D-issue 등록 (§6)

## 5. 관련 브랜치 / commit

| 브랜치 | commit | 내용 |
|---|---|---|
| `feat/jingyu/rag-eval-script` | `361835b` | 평가 스크립트 골격 + 모킹 테스트 22개 |
| `feat/jingyu/rag-eval-script` | `fd4a59c` | 골드셋 시드 88개 추가 |
| `refactor/jingyu/trim-search-categories` | `02f5c20` | 카테고리 65→50 정리 |
| `feat/jingyu/goldset-labeling` | (this) | 라벨링 본진 + 본 plan 문서 |

## 6. 후속 D-issue 후보

- **D-MX (corpus 보강)**: HIIT/노인/여성/청소년 카테고리 추가 여부 (D-M6 정합성 vs 회수율)
- **D-MX (orphan cleanup)**: `older_adults`/`recommendation_system`/`women_resistance` —
  CATEGORY_OPENALEX_MAPPING에 있는데 SEARCH_QUERY_CATEGORIES엔 없는 죽은 매핑 처리
- **D-MX (번역 평가 분리)**: 현재 골드셋은 retrieval-only 평가. 한→영 번역 단계는
  별도 metric (BLEU/COMET 등) 필요 여부 결정
- **D-MX (RAG filter)**: 카테고리 메타 기반 retrieval 사전 필터 도입 여부
  (예: hypertrophy query는 hypertrophy 태그 청크만 검색)

## 7. 참고 자료

- IR 평가 표준 pooling 기법: TREC pooling protocol
- Retrieval metric: Recall@K, MRR, nDCG (학계 기본 3종)
- 본 프로젝트 평가 구조: `mlops/eval/run_eval.py` docstring
