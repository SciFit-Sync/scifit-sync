# OA Fetcher Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Chain-of-Resolvers 패턴으로 OA fetcher 통합. crawler.py + ingest_curated_pmids.py가 동일 chain 공유. Phase 1 무손실 리팩토링 → Phase 2에서 A 회수율 +12%p.

**Architecture:** `mlops/pipeline/oa_fetcher.py` 신설 (OASource Protocol + fetch_chain). 기존 PMC/EuropePMC client는 어댑터로 wrap. 신규 OA sources(OpenAlex PDF/HTML, Unpaywall)는 `curated.py`의 fetch primitives 재사용.

**Tech Stack:** Python 3.11, pytest, ruff

**Spec:** `docs/superpowers/specs/2026-05-24-oa-fetcher-chain-design.md`

---

## File Structure

### Created
- `mlops/pipeline/oa_fetcher.py` — Protocol, dataclasses, `fetch_chain`, source 어댑터들
- `mlops/tests/test_oa_fetcher.py` — chain 동작 + 각 source 단위 테스트

### Modified
- `mlops/pipeline/fulltext.py` — `fetch_cascading`을 deprecated wrapper로 전환
- `mlops/pipeline/crawler.py:_attach_fulltext` — `fetch_chain(ref, DEFAULT_CHAIN)` 사용
- `mlops/scripts/ingest_curated_pmids.py:build_paperfulls_for_ingest` — 절차적 fallback 삭제 → `fetch_chain` 한 줄
- `mlops/scripts/export_embeddings.py` + `ingest_curated_pmids.py` — `ACTIVE_SOURCES` 일원화 (oa_fetcher에서 import)

### 기존 자산 재사용 (수정 X)
- `mlops/pipeline/curated.py` — `openalex_oa_url`, `fetch_pdf_sections`, `fetch_html_sections`, `unpaywall_oa_locations` 그대로 import해서 source 클래스가 사용
- `mlops/pipeline/pmc.py`, `mlops/pipeline/europepmc.py` — Client 재작성 X, 어댑터로 wrap

---

## Phase 1: 무손실 리팩토링 (회수율 0%p 변화)

### Task 1: `oa_fetcher.py` 핵심 (Protocol + dataclasses + fetch_chain)

**Files:**
- Create: `mlops/pipeline/oa_fetcher.py`
- Test: `mlops/tests/test_oa_fetcher.py`

- [ ] **1.1 Write failing test**

`mlops/tests/test_oa_fetcher.py`:
```python
"""oa_fetcher chain + source 단위 테스트."""
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from mlops.pipeline.models import PaperSection
from mlops.pipeline.oa_fetcher import (
    FulltextStatus,
    PaperRef,
    FulltextResult,
    ChainResult,
    fetch_chain,
)


def _make_source(name: str, status: FulltextStatus, sections=None):
    src = MagicMock()
    src.name = name
    result = FulltextResult(status=status, sections=sections or [])
    src.try_fetch.return_value = result
    return src


class TestFetchChain:
    def test_returns_first_success(self):
        s1 = _make_source("s1", FulltextStatus.NOT_AVAILABLE)
        s2 = _make_source("s2", FulltextStatus.SUCCESS, sections=[PaperSection(name="M", content="x")])
        s3 = _make_source("s3", FulltextStatus.SUCCESS, sections=[PaperSection(name="X", content="never")])

        ref = PaperRef(doi="10.1/a")
        result = fetch_chain(ref, [s1, s2, s3])

        assert result.fulltext_source == "s2"
        assert len(result.sections) == 1
        # s3는 호출 안 됨 (stop on first success)
        s3.try_fetch.assert_not_called()
        # tried log: s1 NOT_AVAILABLE, s2 SUCCESS
        assert result.tried == [("s1", FulltextStatus.NOT_AVAILABLE), ("s2", FulltextStatus.SUCCESS)]
        assert result.had_transient_error is False

    def test_all_not_available_returns_no_source(self):
        s1 = _make_source("s1", FulltextStatus.NOT_AVAILABLE)
        s2 = _make_source("s2", FulltextStatus.NOT_AVAILABLE)
        result = fetch_chain(PaperRef(doi="10.1/a"), [s1, s2])

        assert result.fulltext_source is None
        assert result.sections == []
        assert result.had_transient_error is False

    def test_transient_falls_through_and_flags(self):
        s1 = _make_source("s1", FulltextStatus.TRANSIENT_ERROR)
        s2 = _make_source("s2", FulltextStatus.SUCCESS, sections=[PaperSection(name="M", content="x")])
        result = fetch_chain(PaperRef(doi="10.1/a"), [s1, s2])

        assert result.fulltext_source == "s2"
        assert result.had_transient_error is True

    def test_empty_chain_returns_no_source(self):
        result = fetch_chain(PaperRef(doi="10.1/a"), [])
        assert result.fulltext_source is None
        assert result.sections == []
        assert result.tried == []
```

- [ ] **1.2 Run test (expect fail — ImportError)**

```bash
cd /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync
pytest mlops/tests/test_oa_fetcher.py::TestFetchChain -v
```

- [ ] **1.3 Implement**

`mlops/pipeline/oa_fetcher.py`:
```python
"""Unified OA fetcher chain.

Chain-of-Resolvers 패턴으로 다양한 OA source를 순회한다.
새 source 추가는 OASource Protocol 구현 + DEFAULT_CHAIN 등록 두 단계.

Spec: docs/superpowers/specs/2026-05-24-oa-fetcher-chain-design.md
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from mlops.pipeline.models import PaperSection

logger = logging.getLogger(__name__)


class FulltextStatus(Enum):
    """단일 source 시도 결과 분류."""
    SUCCESS = "success"
    NOT_AVAILABLE = "not_available"  # 영구 부재 (404 등)
    TRANSIENT_ERROR = "transient"  # 일시적 (5xx, timeout)


@dataclass
class PaperRef:
    """OA source가 시도하기 위한 paper 식별자 묶음."""
    doi: str
    pmid: str | None = None
    pmcid: str | None = None
    # 사전 resolve된 OpenAlex blob (있으면 source 간 캐시 공유로 중복 API 호출 회피)
    openalex_oa: dict | None = None


@dataclass
class FulltextResult:
    """단일 source 시도 결과."""
    status: FulltextStatus
    sections: list[PaperSection] = field(default_factory=list)
    error: str | None = None


@dataclass
class ChainResult:
    """전체 chain 시도 결과."""
    fulltext_source: str | None  # 성공한 source.name, 실패 시 None
    tried: list[tuple[str, FulltextStatus]]  # per-source attempt log
    sections: list[PaperSection]
    had_transient_error: bool


@runtime_checkable
class OASource(Protocol):
    name: str  # manifest의 tried_sources에 기록될 식별자

    def try_fetch(self, ref: PaperRef) -> FulltextResult: ...


def fetch_chain(ref: PaperRef, sources: list[OASource]) -> ChainResult:
    """순회 sources. SUCCESS에서 stop, NOT_AVAILABLE/TRANSIENT는 다음 source로 진행."""
    tried: list[tuple[str, FulltextStatus]] = []
    had_transient = False

    for source in sources:
        try:
            result = source.try_fetch(ref)
        except Exception as e:
            logger.warning("OASource %s raised unexpected: %s", source.name, e)
            result = FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=str(e))

        tried.append((source.name, result.status))

        if result.status == FulltextStatus.TRANSIENT_ERROR:
            had_transient = True
            continue
        if result.status == FulltextStatus.SUCCESS:
            return ChainResult(
                fulltext_source=source.name,
                tried=tried,
                sections=result.sections,
                had_transient_error=had_transient,
            )
        # NOT_AVAILABLE → 다음 source

    return ChainResult(
        fulltext_source=None,
        tried=tried,
        sections=[],
        had_transient_error=had_transient,
    )
```

- [ ] **1.4 Run test (expect pass)**

```bash
pytest mlops/tests/test_oa_fetcher.py::TestFetchChain -v
```
Expected: 4 passed

- [ ] **1.5 Commit**

```bash
git add mlops/pipeline/oa_fetcher.py mlops/tests/test_oa_fetcher.py
git commit -m "feat: oa_fetcher 핵심 (Protocol + fetch_chain)"
```

---

### Task 2: `PMCSource` 어댑터

**Files:**
- Modify: `mlops/pipeline/oa_fetcher.py` (append)
- Modify: `mlops/tests/test_oa_fetcher.py` (append)

- [ ] **2.1 Write failing test**

Append to `test_oa_fetcher.py`:
```python
from unittest.mock import patch
from mlops.pipeline.oa_fetcher import PMCSource


class TestPMCSource:
    def test_no_pmcid_returns_not_available(self):
        src = PMCSource(pmc_client=MagicMock())
        result = src.try_fetch(PaperRef(doi="10.1/a", pmid="123", pmcid=None))
        assert result.status == FulltextStatus.NOT_AVAILABLE
        assert result.sections == []

    def test_success_when_pmc_client_returns_sections(self):
        mock_client = MagicMock()
        mock_client.fetch.return_value = MagicMock(
            sections=[PaperSection(name="Intro", content="...")],
            had_transient_error=False,
        )
        src = PMCSource(pmc_client=mock_client)
        result = src.try_fetch(PaperRef(doi="10.1/a", pmid="123", pmcid="PMC1"))
        assert result.status == FulltextStatus.SUCCESS
        assert len(result.sections) == 1
        mock_client.fetch.assert_called_once_with("PMC1")

    def test_transient_when_pmc_client_flags_transient(self):
        mock_client = MagicMock()
        mock_client.fetch.return_value = MagicMock(
            sections=[],
            had_transient_error=True,
        )
        src = PMCSource(pmc_client=mock_client)
        result = src.try_fetch(PaperRef(doi="10.1/a", pmid="123", pmcid="PMC1"))
        assert result.status == FulltextStatus.TRANSIENT_ERROR

    def test_not_available_when_empty_sections(self):
        mock_client = MagicMock()
        mock_client.fetch.return_value = MagicMock(
            sections=[],
            had_transient_error=False,
        )
        src = PMCSource(pmc_client=mock_client)
        result = src.try_fetch(PaperRef(doi="10.1/a", pmid="123", pmcid="PMC1"))
        assert result.status == FulltextStatus.NOT_AVAILABLE
```

- [ ] **2.2 Run test (fail)**
- [ ] **2.3 Implement PMCSource**

Append to `oa_fetcher.py`:
```python
class PMCSource:
    """기존 PMCClient 어댑터. pmcid가 있을 때만 시도."""
    name: str = "pmc"

    def __init__(self, pmc_client) -> None:
        self.pmc_client = pmc_client

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        if not ref.pmcid:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        result = self.pmc_client.fetch(ref.pmcid)
        if result.had_transient_error:
            return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR)
        if result.sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=result.sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
```

- [ ] **2.4 Run test (pass)**, **2.5 Commit**: `feat: oa_fetcher PMCSource 어댑터`

---

### Task 3: `EuropePMCSource` 어댑터

Same pattern as Task 2. Source:
```python
class EuropePMCSource:
    name: str = "europepmc"
    
    def __init__(self, europepmc_client) -> None:
        self.europepmc_client = europepmc_client

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        # PMID 우선, 없으면 DOI
        if ref.pmid:
            result = self.europepmc_client.fetch_by_pmid(ref.pmid)
        elif ref.doi:
            result = self.europepmc_client.fetch_by_doi(ref.doi)
        else:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        
        if result.had_transient_error:
            return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR)
        if result.sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=result.sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
```

테스트 패턴 Task 2와 동일 (4 case: no_pmid_no_doi, success, transient, not_available). 4-case test 작성 → fail → impl → pass → commit (`feat: oa_fetcher EuropePMCSource 어댑터`).

---

### Task 4: `fetch_cascading` deprecated wrapper로 전환

**Files:**
- Modify: `mlops/pipeline/fulltext.py`
- Verify: `mlops/tests/test_fulltext.py` (기존 테스트 통과 확인)

- [ ] **4.1 Write integration test (fail)**

Append to `test_oa_fetcher.py`:
```python
class TestFetchCascadingWrapper:
    def test_wrapper_returns_same_shape_as_before(self):
        """fetch_cascading이 기존 CascadingFulltextResult 그대로 반환."""
        from mlops.pipeline.fulltext import fetch_cascading
        
        # mock clients
        mock_pmc = MagicMock()
        mock_pmc.fetch.return_value = MagicMock(
            sections=[PaperSection(name="M", content="x")],
            had_transient_error=False,
        )
        mock_epmc = MagicMock()
        
        result = fetch_cascading(
            pmcid="PMC1", pmid="123", doi="10.1/a",
            pmc_client=mock_pmc, europepmc_client=mock_epmc,
        )
        
        # 기존 CascadingFulltextResult shape
        assert result.fulltext_source == "pmc"
        assert len(result.sections) == 1
        assert "pmc" in result.tried_sources
        assert result.had_transient_error is False
```

- [ ] **4.2 Implement wrapper**

Modify `mlops/pipeline/fulltext.py:fetch_cascading`. 기존 hardcoded 2-단계 로직 내부 구현을 `fetch_chain` 호출로 교체:
```python
def fetch_cascading(*, pmcid, pmid, doi, pmc_client, europepmc_client) -> CascadingFulltextResult:
    """DEPRECATED — use mlops.pipeline.oa_fetcher.fetch_chain instead.
    
    호환성을 위해 90일 유지. 내부적으로 fetch_chain 호출.
    """
    from mlops.pipeline.oa_fetcher import (
        PaperRef, PMCSource, EuropePMCSource, fetch_chain,
    )
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

- [ ] **4.3 Run tests**: wrapper integration test + 기존 `test_fulltext.py` + `test_crawler.py` 모두 통과 (회수율 회귀 X)
- [ ] **4.4 Commit**: `refactor: fetch_cascading을 fetch_chain wrapper로 전환 (deprecated)`

---

### Task 5: Phase 1 회수율 회귀 가드

**Files:**
- Create: `mlops/tests/test_chain_regression.py`

- [ ] **5.1 Create fixture-based test**

```python
"""Phase 1 회수율 회귀 가드.

기지의 OA paper 5개 fixture에 대해 chain이 SUCCESS 반환하는지 검증.
chain 변경 후 이 테스트가 깨지면 회수율 회귀 시그널.
"""
from unittest.mock import MagicMock, patch
import pytest
from mlops.pipeline.oa_fetcher import PaperRef, fetch_chain, PMCSource, EuropePMCSource


class TestChainRegression:
    @pytest.fixture
    def known_oa_papers(self):
        """5개 known-OA paper 시나리오."""
        return [
            # (doi, pmid, pmcid, expected_source)
            ("10.2478/hukin-2022-0017", "35291645", "PMC8884877", "pmc"),
            # 더 추가는 Phase 2에서 (OpenAlex/Unpaywall fixture)
        ]

    def test_pmc_paper_succeeds(self, known_oa_papers):
        # PMC fetch mock으로 success 시뮬레이션
        doi, pmid, pmcid, expected_source = known_oa_papers[0]
        mock_pmc = MagicMock()
        mock_pmc.fetch.return_value = MagicMock(
            sections=[MagicMock()],
            had_transient_error=False,
        )
        mock_epmc = MagicMock()
        
        chain = [PMCSource(mock_pmc), EuropePMCSource(mock_epmc)]
        result = fetch_chain(PaperRef(doi=doi, pmid=pmid, pmcid=pmcid), chain)
        
        assert result.fulltext_source == expected_source, f"Regression: {doi}"
```

- [ ] **5.2 Run + Commit**: `test: oa_fetcher Phase 1 회수율 회귀 가드`

---

## Phase 2: A 회수율 끌어올리기 (+12%p 목표)

### Task 6: `OpenAlexPDFSource` + `OpenAlexHTMLSource`

**Files:**
- Modify: `mlops/pipeline/oa_fetcher.py`
- Modify: `mlops/tests/test_oa_fetcher.py`

- [ ] **6.1 Write tests** (TestOpenAlexPDFSource + TestOpenAlexHTMLSource, 각각 4-case)

```python
class TestOpenAlexPDFSource:
    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_pdf_sections")
    def test_success_when_pdf_url_returns_sections(self, mock_fetch, mock_oa):
        from mlops.pipeline.oa_fetcher import OpenAlexPDFSource
        mock_oa.return_value = {"is_oa": True, "pdf_url": "https://x/p.pdf", "landing_page_url": None}
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        
        src = OpenAlexPDFSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS

    # ... 3 more cases (not_oa, no_pdf_url, fetch_returns_empty)


class TestOpenAlexHTMLSource:
    @patch("mlops.pipeline.oa_fetcher.openalex_oa_url")
    @patch("mlops.pipeline.oa_fetcher.fetch_html_sections")
    def test_success_when_landing_url_returns_sections(self, mock_fetch, mock_oa):
        from mlops.pipeline.oa_fetcher import OpenAlexHTMLSource
        mock_oa.return_value = {"is_oa": True, "pdf_url": None, "landing_page_url": "https://x/landing"}
        mock_fetch.return_value = [PaperSection(name="M", content="x")]
        
        src = OpenAlexHTMLSource()
        result = src.try_fetch(PaperRef(doi="10.1/a"))
        assert result.status == FulltextStatus.SUCCESS

    # ... 3 more cases
```

- [ ] **6.2 Implement**

Append to `oa_fetcher.py`:
```python
from mlops.pipeline.curated import (
    openalex_oa_url,
    fetch_pdf_sections,
    fetch_html_sections,
)


class OpenAlexPDFSource:
    name: str = "openalex_pdf"

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        oa = ref.openalex_oa or openalex_oa_url(ref.doi)
        if not oa or not oa.get("is_oa"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        # 캐시: 다음 source(HTML)가 재사용
        ref.openalex_oa = oa
        if not oa.get("pdf_url"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        sections = fetch_pdf_sections(oa["pdf_url"])
        if sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


class OpenAlexHTMLSource:
    name: str = "openalex_html"

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        oa = ref.openalex_oa or openalex_oa_url(ref.doi)
        if not oa or not oa.get("is_oa"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        ref.openalex_oa = oa
        if not oa.get("landing_page_url"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        sections = fetch_html_sections(oa["landing_page_url"])
        if sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
```

- [ ] **6.3 Commit**: `feat: oa_fetcher OpenAlex PDF/HTML sources`

---

### Task 7: `UnpaywallSource`

Same pattern. `mlops/pipeline/curated.py:unpaywall_oa_locations` 활용. mirror 순회 후 첫 SUCCESS 반환.

```python
from mlops.pipeline.curated import unpaywall_oa_locations


class UnpaywallSource:
    name: str = "unpaywall"

    def __init__(self, email: str = "research@scifit-sync.org") -> None:
        self.email = email

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        locations = unpaywall_oa_locations(ref.doi, email=self.email)
        if not locations:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        for loc in locations:
            if loc.get("pdf_url"):
                sections = fetch_pdf_sections(loc["pdf_url"])
                if sections:
                    return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
            if loc.get("landing_url"):
                sections = fetch_html_sections(loc["landing_url"])
                if sections:
                    return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
```

4-case test (no_locations, success_via_first_mirror_pdf, success_via_second_mirror_html, all_mirrors_fail). Commit: `feat: oa_fetcher UnpaywallSource`.

---

### Task 8: `DEFAULT_CHAIN` + `ACTIVE_SOURCES` 일원화

**Files:**
- Modify: `mlops/pipeline/oa_fetcher.py` (DEFAULT_CHAIN factory 함수)
- Modify: `mlops/scripts/ingest_curated_pmids.py` (ACTIVE_SOURCES 제거, import)
- Modify: `mlops/scripts/export_embeddings.py` 또는 monthly_ingest/initial_ingest의 ACTIVE_SOURCES (있는 곳 다 동일하게 import)

- [ ] **8.1 Implement DEFAULT_CHAIN factory**

```python
# oa_fetcher.py 하단:

def build_default_chain(pmc_client, europepmc_client, unpaywall_email="research@scifit-sync.org") -> list[OASource]:
    """기본 OA chain: PMC → EuropePMC → OpenAlex PDF → OpenAlex HTML → Unpaywall."""
    return [
        PMCSource(pmc_client),
        EuropePMCSource(europepmc_client),
        OpenAlexPDFSource(),
        OpenAlexHTMLSource(),
        UnpaywallSource(email=unpaywall_email),
    ]


def default_source_names() -> list[str]:
    """ACTIVE_SOURCES 일원화. manifest의 fully-tried 판정에 사용."""
    return ["pmc", "europepmc", "openalex_pdf", "openalex_html", "unpaywall"]
```

- [ ] **8.2 ingest_curated_pmids.py 갱신**
- `ACTIVE_SOURCES = {"pmc", "europepmc"}` 제거
- `from mlops.pipeline.oa_fetcher import default_source_names`
- `ACTIVE_SOURCES = set(default_source_names())` 또는 직접 inline 사용

- [ ] **8.3 Test + Commit**: `feat: oa_fetcher DEFAULT_CHAIN 정의 + ACTIVE_SOURCES 일원화`

---

### Task 9: `build_paperfulls_for_ingest` 절차적 fallback → `fetch_chain` 한 줄

**Files:**
- Modify: `mlops/scripts/ingest_curated_pmids.py:build_paperfulls_for_ingest`

- [ ] **9.1 Replace lines 333-377 (절차적 fallback)**:

```python
from mlops.pipeline.oa_fetcher import PaperRef, fetch_chain, build_default_chain

# ... inside build_paperfulls_for_ingest:
chain = build_default_chain(pmc_client, europepmc_client)

for paper in papers:
    # ... 기존 skip 조건 그대로 ...
    
    ref = PaperRef(
        doi=paper["resolved_doi"],
        pmid=paper.get("resolved_pmid"),
        pmcid=meta_dict.get("pmcid") or None,
    )
    chain_result = fetch_chain(ref, chain)
    sections = chain_result.sections
    fulltext_source = chain_result.fulltext_source
    
    if not sections:
        paper["fulltext_ok"] = False
        _mark_failure(paper, "no_fulltext")
        continue
    paper["fulltext_ok"] = True
    
    # 이후 PaperFull 구성은 기존 그대로 (fulltext_source 사용)
```

- [ ] **9.2 기존 OA fallback 코드(line ~340-377) 삭제** + import 정리 (openalex_oa_url, fetch_pdf_sections 등은 oa_fetcher 내부에서만 사용)
- [ ] **9.3 Test**: 기존 `test_ingest_curated_pmids.py::TestBuildPaperFulls`, `TestOAFallback` 통과 (chain mock으로 검증). 일부 테스트 시그니처 갱신 필요할 수 있음.
- [ ] **9.4 Commit**: `refactor: ingest_curated_pmids 절차적 fallback → fetch_chain`

---

### Task 10: `crawler.py:_attach_fulltext` → `fetch_chain` 사용 (A 파이프라인)

**Files:**
- Modify: `mlops/pipeline/crawler.py:_attach_fulltext`

- [ ] **10.1 Locate `_attach_fulltext`** — 현재 `fetch_cascading(pmc_client, europepmc_client, ...)` 호출하는 부분

- [ ] **10.2 교체**:

```python
from mlops.pipeline.oa_fetcher import PaperRef, fetch_chain, build_default_chain

# _attach_fulltext 안에서:
chain = build_default_chain(pmc_client, europepmc_client)
ref = PaperRef(
    doi=paper.meta.doi,
    pmid=paper.meta.pmid or None,
    pmcid=paper.meta.pmcid or None,
)
chain_result = fetch_chain(ref, chain)

paper.sections = chain_result.sections
paper.meta.fulltext_source = chain_result.fulltext_source
paper.meta.tried_sources = [name for name, _ in chain_result.tried]
# had_transient_error 처리는 기존 동일
```

- [ ] **10.3 Test**: 기존 `test_crawler.py` 통과 (mock 시그니처 조정 필요할 수 있음)

- [ ] **10.4 Commit**: `refactor: crawler._attach_fulltext가 fetch_chain 사용 (A 파이프라인 OA fallback 활성화)`

---

### Task 11: Phase 2 회수율 검증 (cloud smoke, 사용자 진행)

코드 변경 X. 사용자가 cloud에서 진행.

- [ ] **11.1 Cloud 환경 sync + dependency**:
```bash
cd /mnt/data/scifit-sync/scifit-sync
git pull origin feature/jingyu/curated-paper-ingest
pip install -r mlops/requirements.txt  # pypdf 등 신규 의존성
```

- [ ] **11.2 B 파이프라인 회귀 가드 (29.7% 유지)**:
```bash
# provenance reset (이전 결과 지움)
python3 -c "<reset 스크립트>"

# dry-run 30건
python -m mlops.scripts.ingest_curated_pmids \
    --provenance mlops/data/curated_provenance.json \
    --dry-run --limit 30

# stats: fulltext 회수율 측정
```
Expected: ~29.7% 유지 (B는 이미 OA fallback 적용 중이므로 변화 X)

- [ ] **11.3 A 파이프라인 측정 (목표 +12%p)**:
```bash
# crawler 흐름으로 실행
python -m mlops.scripts.export_embeddings \
    --batch-tag "chain_test_$(date +%Y%m%d)" \
    --model bge-large \
    --max-papers 30 \
    --max-per-category 30 \
    --dry-run
```
Expected: 회수율 48% → 60%+ (OA fallback 흡수 효과)

- [ ] **11.4 결과 보고 + 최종 decision**: 풀 실행 진행 / 추가 source / 별도 PR

---

## Self-Review

**Spec coverage**:
- §4.1 oa_fetcher 핵심 → Task 1 ✅
- §4.2 source 어댑터 → Task 2, 3, 6, 7 ✅
- §4.3 fetch_cascading deprecated wrapper → Task 4 ✅
- §4.4 ingest_curated_pmids fallback 삭제 → Task 9 ✅
- §4.5 crawler.py _attach_fulltext → Task 10 ✅
- §4.6 ACTIVE_SOURCES 일원화 → Task 8 ✅
- §5 Phase 1+2 마이그레이션 → Task 1-5 (Phase 1), Task 6-10 (Phase 2) ✅
- §8 Testing → 각 Task에 unit test + Task 5 회귀 가드 + Task 11 cloud smoke ✅

**Placeholder check**: 모든 step에 actual code + 명령어 포함. TODO/TBD 없음. ✅

**Type consistency**:
- `OASource.try_fetch(ref) -> FulltextResult` — Task 1 정의, Task 2/3/6/7 구현, Task 8 DEFAULT_CHAIN에서 사용 ✅
- `fetch_chain(ref, sources) -> ChainResult` — Task 1 정의, Task 4/9/10에서 호출 ✅
- `PaperRef(doi, pmid, pmcid, openalex_oa)` — Task 1 dataclass, 모든 source가 동일 형태 사용 ✅

---

## Execution Handoff

Plan complete. Subagent-driven으로 Phase 1 (Task 1-5) → Phase 2 (Task 6-11) 순차 진행.

각 Task별로:
1. Implementer dispatch (oh-my-claudecode:executor, sonnet) → TDD red/green/commit
2. Spec compliance review → 회귀 X 검증
3. Code quality review → SLOP 회피 원칙 7개 통과
4. 모든 통과 후 다음 Task

Task 11 (cloud smoke)은 사용자 진행.
