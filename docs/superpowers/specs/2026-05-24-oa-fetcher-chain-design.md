# Unified OA Fetcher Chain — Design

작성일: 2026-05-24
대상 브랜치: `feature/jingyu/curated-paper-ingest` (Phase 1+2 추가)
참조 architect 권고: 본 spec §6
선행 spec: `docs/superpowers/specs/2026-05-23-curated-paper-ingest-design.md`

## 1. Background

기존 두 파이프라인의 fulltext 회수 흐름:

| 파이프라인 | 진입점 | Cascade | 회수율 |
|---|---|---|---|
| A. Search-driven crawler | `mlops/scripts/export_embeddings.py` → `crawler._attach_fulltext` | PMC → EuropePMC (2단계, hardcoded) | ~48% |
| B. Curated paper ingest | `mlops/scripts/ingest_curated_pmids.py:build_paperfulls_for_ingest` | PMC → EuropePMC → OpenAlex(PDF/HTML) → Unpaywall(mirrors) (4단계, 절차적 if-사슬) | ~29.7% |

**문제**:
- B의 OA fallback이 A의 흐름에 흡수되지 않아 A가 자체 회수율 끌어올릴 수 없음
- `fetch_cascading(pmc_client, europepmc_client, ...)`이 2-client 시그니처로 hardcoded — 새 source 추가가 시그니처 변경 강제
- B는 `if not sections: try X` 절차적 fallback이 30줄 누적 — SLOP 위험
- 새 source 추가 (CrossRef, Semantic Scholar 등) 시 두 파이프라인 동시 수정 필요

**근본 원인**: 코드 중복이 아니라 **확장성 부재**. cascade를 N-source generic하게 추상화해야 함.

## 2. Goal

**Chain-of-Resolvers 패턴으로 OA fetcher를 통합**하여 (a) A의 회수율을 B 수준으로 끌어올리고, (b) 새 OA source 추가가 한 파일 변경으로 끝나도록 한다.

**Non-goals**:
- Manifest schema v3 (attempt history) — 학기 일정 압박으로 Phase 3로 보류, 본 spec에서 다루지 않음
- Playwright/Selenium 기반 봇 차단 우회 — 의존성/CI 비용 학기 범위 밖
- HUFS 도서관 proxy 활용 — 학내 IP 정책 미확보, 별도 D-issue
- `curl_cffi` TLS fingerprint 위장 — Phase 2 완료 후 측정 결과 봐서 별도 PR로 검토
- 새 OA source 5개+ 일괄 추가 — Semantic Scholar/CrossRef/CORE는 Phase 2에서 제외, 향후 ROI 측정 후 도입

## 3. Approach

신규 모듈 `mlops/pipeline/oa_fetcher.py`에 chain-of-resolvers 패턴 구현. 기존 PMC/EuropePMC client는 어댑터로 wrapping (재작성 없음). 두 파이프라인이 동일 chain instance 공유.

```
[A: crawler.py]                        [B: ingest_curated_pmids.py]
       │                                      │
       │ _attach_fulltext(paper)              │ build_paperfulls_for_ingest(papers)
       ▼                                      ▼
       └──────────► fetch_chain(ref, sources=DEFAULT_CHAIN) ◄──────────┘
                           │
                           ▼
              ┌────────────┴────────────┐
              │  Chain (순서대로 시도):    │
              │  1. PMCSource           │  ← 기존 PMCClient 어댑터
              │  2. EuropePMCSource     │  ← 기존 EuropePMCClient 어댑터
              │  3. OpenAlexPDFSource   │  ← curated.py의 fetch_pdf_sections 활용
              │  4. OpenAlexHTMLSource  │  ← curated.py의 fetch_html_sections 활용
              │  5. UnpaywallSource     │  ← curated.py의 unpaywall_oa_locations 활용
              │  (Phase 3+: bioRxiv,    │
              │   Semantic Scholar 등)  │
              └─────────────────────────┘
```

## 4. Components

### 4.1 `mlops/pipeline/oa_fetcher.py` (신규, ~250 LoC)

**핵심 인터페이스**:

```python
from typing import Protocol
from dataclasses import dataclass
from enum import Enum

class FulltextStatus(Enum):
    """기존 europepmc.py의 enum 재사용 (옮겨와서 공용으로)."""
    SUCCESS = "success"
    NOT_AVAILABLE = "not_available"   # 영구 부재 (404 등)
    TRANSIENT_ERROR = "transient"     # 일시적 (5xx, timeout)


@dataclass
class PaperRef:
    """OA source가 시도하기 위한 paper 식별자 묶음."""
    doi: str
    pmid: str | None = None
    pmcid: str | None = None
    # 사전 resolve된 OpenAlex blob (있으면 중복 API 호출 회피)
    openalex_oa: dict | None = None


@dataclass
class FulltextResult:
    """단일 source 시도 결과."""
    status: FulltextStatus
    sections: list[PaperSection]
    error: str | None = None


@dataclass
class ChainResult:
    """전체 chain 시도 결과."""
    fulltext_source: str | None      # 성공한 source.name, 실패 시 None
    tried: list[tuple[str, FulltextStatus]]  # per-source 시도 log
    sections: list[PaperSection]
    had_transient_error: bool


class OASource(Protocol):
    name: str  # manifest의 tried_sources에 기록될 식별자

    def try_fetch(self, ref: PaperRef) -> FulltextResult: ...


def fetch_chain(ref: PaperRef, sources: list[OASource]) -> ChainResult:
    """순회 source. SUCCESS에서 stop, NOT_AVAILABLE은 다음 source로,
    TRANSIENT_ERROR는 had_transient_error 플래그만 set하고 다음 source로 진행.
    """
```

**기본 chain (`DEFAULT_CHAIN`)**:
```python
DEFAULT_CHAIN: list[OASource] = [
    PMCSource(pmc_client),
    EuropePMCSource(europepmc_client),
    OpenAlexPDFSource(),
    OpenAlexHTMLSource(),
    UnpaywallSource(email="research@scifit-sync.org"),
]
```

### 4.2 Source 어댑터들 (신규)

각 source 클래스는 `oa_fetcher.py` 또는 `oa_fetcher/sources/` 하위로 분리:

#### `PMCSource` (기존 PMCClient wrapping)
- `name = "pmc"`
- `try_fetch(ref)`:
  - ref.pmcid 없으면 `NOT_AVAILABLE` 즉시
  - `pmc_client.fetch(pmcid)` 호출 → 결과 매핑

#### `EuropePMCSource` (기존 EuropePMCClient wrapping)
- `name = "europepmc"`
- ref.pmid 우선 사용, 없으면 ref.doi
- `europepmc_client.fetch_by_pmid(pmid)` 또는 `fetch_by_doi(doi)`

#### `OpenAlexPDFSource` (신규)
- `name = "openalex_pdf"`
- ref.openalex_oa가 None이면 `openalex_oa_url(ref.doi)` 호출해서 채움
- `oa["is_oa"]`이고 `oa["pdf_url"]`이 있으면 `fetch_pdf_sections(pdf_url)` → SUCCESS / NOT_AVAILABLE
- HTTP 5xx/timeout → TRANSIENT_ERROR

#### `OpenAlexHTMLSource` (신규)
- `name = "openalex_html"`
- ref.openalex_oa의 `landing_page_url` 사용 (PDFSource가 채워두면 재사용)
- `fetch_html_sections(landing_page_url)` → 결과 매핑

#### `UnpaywallSource` (신규)
- `name = "unpaywall"`
- `unpaywall_oa_locations(ref.doi)` → mirror list 순회
- 각 mirror의 `pdf_url` → `fetch_pdf_sections` 시도, 실패 시 `landing_url` → `fetch_html_sections` 시도
- 첫 SUCCESS 반환, 모두 실패면 NOT_AVAILABLE

### 4.3 기존 `mlops/pipeline/fulltext.py` 수정

`fetch_cascading`을 **deprecated wrapper**로 보존 (호환성):
```python
def fetch_cascading(*, pmcid, pmid, doi, pmc_client, europepmc_client) -> CascadingFulltextResult:
    """DEPRECATED — use mlops.pipeline.oa_fetcher.fetch_chain instead.
    
    기존 호출자(crawler.py 등)와 테스트 호환을 위해 90일 유지.
    """
    ref = PaperRef(doi=doi, pmid=pmid, pmcid=pmcid)
    chain = [PMCSource(pmc_client), EuropePMCSource(europepmc_client)]
    chain_result = fetch_chain(ref, chain)
    return CascadingFulltextResult(
        fulltext_source=chain_result.fulltext_source,
        tried_sources=[name for name, _ in chain_result.tried],
        sections=chain_result.sections,
        had_transient_error=chain_result.had_transient_error,
    )
```

### 4.4 `mlops/scripts/ingest_curated_pmids.py` 수정 (B 파이프라인)

`build_paperfulls_for_ingest` 내 30줄 절차적 fallback **삭제** → 한 줄로:
```python
from mlops.pipeline.oa_fetcher import fetch_chain, PaperRef, DEFAULT_CHAIN

# 기존 line 333-377 전체를 다음으로 대체:
ref = PaperRef(
    doi=paper["resolved_doi"],
    pmid=paper.get("resolved_pmid"),
    pmcid=meta_dict.get("pmcid") or None,
)
chain_result = fetch_chain(ref, DEFAULT_CHAIN)
sections = chain_result.sections
fulltext_source = chain_result.fulltext_source

if not sections:
    paper["fulltext_ok"] = False
    _mark_failure(paper, "no_fulltext")
    continue
paper["fulltext_ok"] = True
```

### 4.5 `mlops/pipeline/crawler.py` 수정 (A 파이프라인)

`_attach_fulltext` 함수가 현재 `fetch_cascading` 호출. 이를 `fetch_chain(ref, DEFAULT_CHAIN)`로 직접 교체. deprecated wrapper 안 거치도록.

### 4.6 `ACTIVE_SOURCES` 상수 일원화

기존: `mlops/scripts/ingest_curated_pmids.py:ACTIVE_SOURCES = {"pmc", "europepmc"}`, `mlops/scripts/export_embeddings.py`에 동일 정의.

신규: `mlops/pipeline/oa_fetcher.py`에서 `DEFAULT_CHAIN_SOURCE_NAMES = [s.name for s in DEFAULT_CHAIN]` 동적 계산. 두 스크립트가 이걸 import.

→ chain에 source 추가하면 manifest의 fully-tried 판정도 자동 갱신.

## 5. Migration plan (Phase 1 → Phase 2)

### Phase 1: 무손실 리팩토링 (회수율 변화 0)

| 단계 | 작업 | 검증 |
|---|---|---|
| 1.1 | `oa_fetcher.py` 신설 (Protocol + dataclasses + `fetch_chain` 함수) | unit test (mock source 3개로 chain 동작) |
| 1.2 | `PMCSource` 어댑터 작성 (기존 PMCClient wrap) | unit test (PMC client mock) |
| 1.3 | `EuropePMCSource` 어댑터 작성 | unit test |
| 1.4 | `fetch_cascading`을 deprecated wrapper로 전환 (내부적으로 `fetch_chain` 호출) | 기존 `test_fulltext.py`, `test_crawler.py` 등 통과 |
| 1.5 | 통합 테스트: A 파이프라인 (crawler) 회수율 회귀 가드 | known-OA paper 5개 fixture로 SUCCESS 검증 |

Phase 1 끝나면 회수율 0%p 변화이지만 architecture는 새 source 추가 준비 완료.

### Phase 2: A 회수율 끌어올리기 (목표 +12~15%p)

| 단계 | 작업 | 검증 |
|---|---|---|
| 2.1 | `OpenAlexPDFSource` 작성 (기존 `openalex_oa_url` + `fetch_pdf_sections` 활용) | unit test |
| 2.2 | `OpenAlexHTMLSource` 작성 | unit test |
| 2.3 | `UnpaywallSource` 작성 (기존 `unpaywall_oa_locations` + mirror 순회) | unit test |
| 2.4 | `DEFAULT_CHAIN`에 3개 source 추가 | chain 통합 test |
| 2.5 | B 파이프라인의 절차적 fallback (line 333-377) 삭제 → `fetch_chain` 한 줄 | B 테스트 통과 + 회수율 회귀 X (29.7% 유지) |
| 2.6 | A 파이프라인 (`crawler._attach_fulltext`)을 `fetch_chain` 사용으로 전환 | A의 known-OA 회수율 측정 |
| 2.7 | `ACTIVE_SOURCES` 일원화 | manifest tried_sources 일관성 |
| 2.8 | Cloud smoke test: 30 paper로 회수율 측정. A는 48% → 60%+ 목표, B는 29.7% 유지 | dry-run 결과 분석 |

Phase 2 끝나면:
- A의 회수율: 48% → 60%+ (목표 +12%p)
- B의 회수율: 29.7% (변화 X — 이미 OA fallback 적용 중)
- 새 source 추가가 한 파일 변경으로 가능한 architecture

## 6. Decision Log (Architect 권고 반영)

| Architect 권고 | 반영 |
|---|---|
| Chain-of-Resolvers 패턴 + `OASource` Protocol | ✅ §4.1 |
| 기존 PMC/EuropePMC client는 어댑터로 wrapping | ✅ §4.2 PMCSource/EuropePMCSource |
| `fetch_cascading`은 deprecated wrapper로 90일 유지 | ✅ §4.3 |
| OpenAlex PDF/HTML + Unpaywall이 1~2순위 (이미 있는 자산 이식) | ✅ Phase 2 |
| bioRxiv/medRxiv는 Phase 3+ | ✅ Non-goals + 후속 |
| Semantic Scholar/CrossRef/CORE는 ROI 측정 후 | ✅ Non-goals |
| `curl_cffi`는 Phase 2 완료 후 PoC | ✅ Non-goals + 후속 |
| Playwright/Selenium 거부 | ✅ Non-goals |
| Manifest v3는 Phase 3로 보류 | ✅ Non-goals |
| SLOP 회피 7원칙 | ✅ §8 Testing + §10 Code Review Gates |

## 7. Error Handling

`FulltextStatus` enum이 source별 attempt 결과를 분류:

| Status | 의미 | 다음 source 시도? |
|---|---|---|
| `SUCCESS` | sections 확보 | 중단 |
| `NOT_AVAILABLE` | 영구 부재 (404, OA 아님 등) | 진행 |
| `TRANSIENT_ERROR` | 일시적 (5xx, timeout) | 진행, `had_transient_error=True` 기록 |

기존 §7.1 invariant (`failure_reason ⟺ indexed=false`)는 그대로 유지:
- chain의 모든 source가 SUCCESS 아니면 caller가 `_mark_failure(paper, "no_fulltext")`
- `had_transient_error=True`인 경우 재시작 시 retry 가능 (manifest의 `tried_sources` 정책 그대로)

## 8. Testing

### 8.1 Unit tests
- `test_oa_fetcher.py`: chain 동작 검증 (mock source 3개 — SUCCESS / NOT_AVAILABLE 진행 / TRANSIENT 진행)
- `test_pmc_source.py`: PMCClient mock으로 status mapping
- `test_europepmc_source.py`: 동일 패턴
- `test_openalex_pdf_source.py`, `test_openalex_html_source.py`, `test_unpaywall_source.py`: 각각 SUCCESS / NOT_AVAILABLE / TRANSIENT 4-case
- 기존 `test_fulltext.py`: deprecated wrapper 호환성 검증

### 8.2 Integration test
- `test_oa_fetcher_integration.py`: DEFAULT_CHAIN 실제 instance에 mocked source 5개 → 다양한 시나리오 (모두 NOT_AVAILABLE, 첫 SUCCESS, 중간 TRANSIENT 후 SUCCESS 등)

### 8.3 회수율 회귀 가드
- `test_chain_regression.py`: known-OA paper 5개 fixture (PMC OA, EuropePMC OA, OpenAlex PDF, Unpaywall mirror, 모두 실패)
- 각 paper에 대해 chain 결과의 `fulltext_source`와 sections.length 검증
- chain 수정 시 이 5개 fixture가 깨지면 CI fail

### 8.4 Cloud smoke verification (Phase 2 후)
- A 파이프라인: `python -m mlops.scripts.export_embeddings --max-papers 30 --dry-run` 또는 비슷한 manual run
- B 파이프라인: 기존 dry-run 동일
- 회수율 측정 + per-source success count

## 9. SLOP 회피 7원칙 (Code review gates)

1. **새 source = 1 PR = 1 파일 추가** (`oa_fetcher/sources/<name>_source.py`). chain 등록 외 다른 파일 수정 0건.
2. **fallback if-사슬 금지** — chain에 등록. PR에 `if not sections: try X` 패턴 발견 시 reject.
3. **fetch primitive와 source 분리** — `fetch_pdf_sections`/`fetch_html_sections`는 source 안에서 import.
4. **manifest `tried_sources` ↔ `source.name` 동일성** — string literal 박지 않고 source 객체에서 가져옴.
5. **새 source 테스트 mandatory 4-case** — SUCCESS / NOT_AVAILABLE / TRANSIENT / timeout. 미동반 PR reject.
6. **회수율 회귀 가드 (§8.3)** — chain 변경 후 5개 fixture 검증.
7. **`fetch_chain(ref, sources)` 시그니처 동결** — source 추가가 시그니처 변경 유발 시 design smell.

## 10. Open Questions / Future Work

- **Phase 3 (manifest v3)**: `tried_sources: list[str]` → `attempts: list[{source, status, tried_at}]`. observability 향상. 별도 D-issue.
- **`curl_cffi` PoC**: Phase 2 cloud smoke 결과에서 Wiley 등 차단 paper 비율이 여전히 높으면 `curl_cffi` 1일 PoC. 별도 PR.
- **추가 OA source**: bioRxiv/medRxiv → Semantic Scholar → CrossRef → CORE 순. 각각 ROI 측정 후 도입. Phase 2 완료 후 1주 측정 기반 결정.
- **HUFS 도서관 proxy**: 학내 IP로 closed access 접근 가능한지 정책 확인. 학기 후 D-issue.
- **rate limit / polite pool**: OpenAlex, Unpaywall 모두 폴라이트 풀 정책 있음. `email=` 파라미터로 식별. ratelimit 진입 가능성 모니터링 필요.
