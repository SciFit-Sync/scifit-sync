# MLOps 논문 검색 쿼리 카테고리 가이드

`mlops/pipeline/crawler.py`의 `SEARCH_QUERY_CATEGORIES`(65개)는 SciFit-Sync RAG가 다양한
사용자 컨텍스트에 답할 수 있도록 PubMed에서 운동 루틴 생성에 직접 관련된 근거 데이터를
수집하기 위한 카테고리별 검색 쿼리 모음이다. 본 가이드는 카테고리를 **추가/수정/검증/적재**할
때의 표준 절차를 정리한다.

> 카테고리는 100개까지 확장됐다가 운동 루틴 생성 핵심 외 35개(영양/임상 인구/특수 보조제 등)를
> 제거하여 65개로 정제됐다. 100개 시절 검증 history는 §5 참조.

---

## 1. SEARCH_QUERY_CATEGORIES 개요

```python
SEARCH_QUERY_CATEGORIES: list[tuple[str, str, str]] = [
    (name, query, filter_level),  # filter_level ∈ {"strict", "semi", "loose"}
    ...
]
```

각 카테고리는 `(이름, PubMed 쿼리, filter_level)` 3-튜플. `crawl_papers()`가 카테고리마다
검색을 돌리고, round-robin dedup으로 카테고리 다양성을 유지하면서 max_total까지 누적한다.
동일 PMID가 여러 카테고리에 매칭되면 `PaperMeta.search_categories`에 합집합으로 누적되어
청크 단계까지 전파된다 (RAG 검색 시 사용자 `fitness_goals` 기반 가중치에 사용).

### filter_level 3-단계

`crawler.py`의 `_filter_for_level()`이 PubMed term에 추가되는 publication-type 필터를 결정한다.

| level | 추가 필터 | 사용처 |
|---|---|---|
| `strict` | RCT / 메타분석 / 시스템 리뷰 + free full text | 메타분석이 풍부한 주류 임상 주제 (볼륨, 강도, 단백질 등) |
| `semi` | RCT / 메타분석 / 시스템 리뷰만 | 좁은 임상 주제 — abstract만으로도 RAG 청크 다양성 확보 (failure_rir, periodization, 부위별 등) |
| `loose` | 없음 (humans/adults만) | RCT가 거의 없는 영역 (메커니즘 이론, 신규 분야, 추천 시스템, 종목 특화 등) |

### 현재 분포 (65개)

| level | 카테고리 수 | 대표 예시 |
|---|---|---|
| strict | 41 | volume, intensity, frequency, chest/legs/arms_training, BFR, plyometric, foam_rolling, VBT, RPE |
| semi | 12 | failure_rir, periodization, tempo_tut, back/shoulders/core_training, stretching_flexibility |
| loose | 12 | personalized_prescription, training_split, exercise_order, advanced_techniques, olympic_lifting |

### 4축 분류 (RAG 사용 관점)

| 축 | 의미 | 사용자 컨텍스트에 따른 트리거 |
|---|---|---|
| A. 근성장 메커니즘·원리 (≈22) | 처방의 "변수" (volume, intensity, tempo, periodization, fiber_type, hormones 등) | `default_goals=hypertrophy/strength` |
| B. 부위 선정 (≈8) | chest/back/legs/shoulders/arms/core_training, compound_isolation, unilateral | 사용자 분할/부위 지정 시 |
| C. 헬스장 루틴 설계 (≈12) | machine_vs_freeweight, training_split, exercise_order, advanced_techniques, warm_up, BFR, plyometric 등 | 기구·분할·기법 추천 시 |
| D. 사용자 컨텍스트 (≈23) | 종목(team/cyclist/swimmer)·회복·평가·행동·체성분·재활 | 프로필 (보유 기구, 종목, 부상, 목표) |

---

## 2. 카테고리 추가 워크플로

신규 카테고리를 추가할 때는 **검증 → 등록 → 테스트 → 커밋** 4단계를 따른다.

### 2.1 후보 발굴 — 운동 루틴 RAG 관련성 우선

기존 65개와 의미 중복 금지. 후보 축 예시:
- 신규 인구: 류마티스, 만성통증, 자가면역 등
- 신규 종목: 골프, 테니스, 스키 등
- 신규 보조제·영양: BCAA 외 EAA 변형, 단백질 타이밍 등
- 신규 modality: vibration training, electrical stimulation 등

### 2.2 PubMed 효용성 검증 — `mlops/scripts/verify_queries.py`

기존 검증 스크립트가 그대로 보존되어 있다. 신규 후보용 임시 스크립트는
`verify_queries.py`를 복사·수정해서 만들고 검증 후 삭제한다 (1회용).

```python
# 예: mlops/scripts/verify_queries_new.py (임시)
from mlops.pipeline.config import NCBI_API_KEY, NCBI_BASE_URL, NCBI_RATE_LIMIT
from mlops.pipeline.crawler import COMMON_PUBLICATION_FILTER, SEMI_STRICT_PUBLICATION_FILTER

NEW = [("category_name", '("주요어1" OR "유의어1") AND ("축2-1" OR "축2-2") AND ("humans" OR "adults")', None)]
# (name, base_query, retry_query_or_None)
```

실행:

```bash
python3 -m mlops.scripts.verify_queries_new
```

스크립트는 각 후보에 대해 `strict → semi → loose` 순으로 시도하여 ≥30건 만족하는
가장 강한 단계를 반환한다. loose에서도 30 미달이면 `retry_query`(어휘 확장 버전)로
1회 재시도 후 그래도 미달이면 폐기한다.

### 2.3 채택/폐기 기준

| 결과 | 처리 |
|---|---|
| 어떤 단계에서든 ≥30건 | 해당 단계로 채택 |
| 어휘 확장 후에도 loose <30건 | 폐기 (단, ≥10건이고 매우 niche한 학술 가치가 있으면 loose 채택 고려 가능) |
| 너무 광범위 (>50,000건) | 어휘 좁히기 (보다 구체적인 MeSH 용어 추가) |

> 30건 임계점 근거: RAG 청크 다양성 확보 하한선. 메타분석 1편당 평균 ~150 청크 생성되므로,
> 30편이면 ~4,500 청크로 카테고리 가중치 검색에 충분.

### 2.4 crawler.py 등록

채택된 카테고리를 `SEARCH_QUERY_CATEGORIES`의 **해당 filter level 섹션 끝**에 추가한다.
섹션은 코드상 주석으로 구분되어 있다 (`# ── strict ──`, `# ── semi ──`, `# ── loose ──`).

```python
(
    "new_category",
    '("키워드1") AND ("키워드2-1" OR "키워드2-2") AND ("humans" OR "adults")',
    "strict",  # or "semi", "loose"
),
```

### 2.5 검증 및 커밋

```bash
ruff check mlops/                      # All checks passed
python3 -m pytest mlops/tests/ -q      # 모두 통과
python3 -c "from mlops.pipeline.crawler import SEARCH_QUERY_CATEGORIES; print(len(SEARCH_QUERY_CATEGORIES))"

git add mlops/pipeline/crawler.py
git commit -m "feat: 논문 검색 쿼리 N개 추가 — <축 설명>"
```

---

## 3. ingest 실행

### 3.1 환경 변수 체크

| 변수 | 필수 여부 | 비고 |
|---|---|---|
| `NCBI_API_KEY` | 권장 | 없으면 rate limit 1s → 0.34s로 ~3배 단축 + 안정성↑ |
| `CHROMA_PERSIST_PATH` | 기본 `/chroma-data` | 로컬은 권한 fallback 자동 동작 (`server/app/services/rag.py`) |
| `CHROMA_COLLECTION_NAME` | 기본 `paper_chunks` | BGE prefix 일관성 위해 `paper_chunks_v2` 권장 |
| `EMBEDDING_MODEL` | 기본 `BAAI/bge-large-en-v1.5` | 변경 시 collection 차원 불일치 주의 |
| `MAX_PAPERS_PER_RUN` | 기본 300 | round-robin dedup 후 신규 PMID 상한 |
| `MAX_PAPERS_PER_CATEGORY` | 기본 20 | 카테고리당 검색 상한 |
| `API_BASE_URL` + `ADMIN_API_TOKEN` | 실제 적재 시 필수 | `initial_ingest.py`가 백엔드 `/api/v1/admin/rag/ingest`로 POST |

### 3.2 dry-run (크롤링·청킹만)

신규 카테고리 추가 후 ingest 영향을 추정할 때 사용. 임베딩·적재 생략으로 ~10–45분 내 완료.

```bash
python3 -m mlops.scripts.initial_ingest --dry-run --max-papers 50
```

체크 포인트:
- 카테고리별 검색 결과가 max(20)에 근접하는가? (효용성 검증과 일치)
- round-robin "평균 N카테고리/논문" — 2.5 이상이면 다양성 양호
- PMC 전문 회수율(`크롤링 완료: X건 (전문 포함 Y건)`) — 50%+ 정상, 80%+ 이상적

### 3.3 본 적재 — 옵션별 절차

#### A. 로컬 전체 적재 (개발/테스트)

```bash
# 1) 백엔드 띄우기
docker compose up -d server

# 2) 환경변수
export API_BASE_URL=http://localhost:8000
export ADMIN_API_TOKEN=<admin token>

# 3) 적재
python3 -m mlops.scripts.initial_ingest --max-papers 300
```

#### B. 임베딩만 export (클라우드 적재용 batch)

```bash
python3 -m mlops.scripts.export_embeddings
# → mlops/data/embeddings_batchN.jsonl.gz 생성
```

#### C. 운영 환경 (GitHub Actions monthly)

`.github/workflows/monthly-ingest.yml`이 매월 1일 실행. 신규 카테고리 추가가 운영에 반영되려면:
1. develop → main PR 머지
2. GitHub Actions secrets 확인: `NCBI_API_KEY`, `API_BASE_URL` (운영), `ADMIN_API_TOKEN`
3. workflow 수동 트리거 또는 다음 월간 사이클 대기

---

## 4. 트러블슈팅

### 4.1 PMC 전문 회수율이 낮을 때 (<50%)

원인:
1. **WSL → NCBI 네트워크 불안정** — `InvalidChunkLength` 에러 다발. retry 로그 확인:
   ```bash
   grep "재시도\|최종 실패" <ingest 로그>
   ```
   해결: NCBI API 키 적용, 또는 retry 횟수 증가:
   ```bash
   python3 -m mlops.scripts.initial_ingest --http-retries 8 --fulltext-attempts 5
   ```

2. **PMC 미존재 논문** — 일부 저널은 PMC 미게재. 정상. `abstract fallback`으로 처리됨.

### 4.2 카테고리 추가 후 검색 결과가 0건

- PubMed 쿼리 문법 오류 확인 (괄호 균형, 따옴표)
- 직접 PubMed 웹에서 동일 쿼리 입력하여 검증:
  https://pubmed.ncbi.nlm.nih.gov/?term=<URL 인코딩된 쿼리>

### 4.3 filter_level 변경 시

이미 등록된 카테고리의 level을 바꿀 때는 기존 적재된 청크의 `search_categories` 메타가
**과거 검색 결과 기반**이라는 점을 인지하자. 차이가 크면 manifest를 비우고 재적재하는
편이 검색 일관성에 좋다 (단, 신규 적재 비용 발생).

### 4.4 65개를 더 늘리는 게 좋을지 판단

권장: **실제 ingest 후 RAG hit rate / 챗봇 미답변 로그**를 먼저 측정. 100개 이상은
NCBI relevance 정렬 한계로 중복 PMID 비율과 폐기율이 빠르게 증가하므로,
사용자 페르소나 갭이나 자주 들어오는 미답변 질문 영역이 드러났을 때만 5–10개씩
타겟형 추가가 효율적.

---

## 5. 참고 — 100개 확장 → 65개 정제 history (재현/검토용)

| 라운드 | 후보 수 | 채택 | 폐기 | 비고 |
|---|---|---|---|---|
| 1 (기존) | 50 | 49 | 1 (mind_muscle_connection) | strict→semi→loose 단계 도입 |
| 2 (+10) | 10 | 10 | 0 | 유산소/HIIT/올림픽/보조제 등 |
| 3 (+41) | 50 | 41 (50 채택 가능 중 9 cut) | 2 (sauna_heat, compression) | 인구·메커니즘·보조제·회복 |

50편 dry-run E2E 결과: 검색 효율 99.9% (1998/2000 hit), 카테고리 다중 매칭 평균 2.9,
청크 7,639개. 검증 스크립트(`verify_queries.py`)는 향후 라운드 재현용으로 보존되어 있다.
