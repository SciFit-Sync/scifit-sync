# Curated Paper Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 큐레이션된 `논문.txt`의 PMID/DOI를 기존 RAG 파이프라인에 명시 입력으로 적재하고, 결과로 `goldset.jsonl`을 자동 생성해 baseline 평가 가능 상태로 만든다.

**Architecture:** 3 신규 스크립트 + 1 신규 helper module. 기존 `mlops/pipeline/{fulltext, chunker, embedder, upserter, manifest, evidence, openalex}` 컴포넌트는 그대로 import해 재사용. crawler의 search-driven discovery만 우회. 서버 코드 변경 없음.

**Tech Stack:** Python 3.11, pytest (mock), requests, 기존 mlops pipeline.

**Spec:** `docs/superpowers/specs/2026-05-23-curated-paper-ingest-design.md` (Codex 5회 리뷰 통과 v5)

---

## File Structure

### Created
- `mlops/pipeline/curated.py` — 공용 helper (normalize_doi, NCBI ID Converter, OpenAlex DOI lookup, title sanity check)
- `mlops/scripts/parse_curated_papers.py` — 로컬 파서 (논문.txt → provenance JSON + issues)
- `mlops/scripts/ingest_curated_pmids.py` — cloud GPU ingest 엔트리포인트
- `mlops/scripts/build_goldset.py` — 로컬, provenance → goldset.jsonl + summary 리포트
- `mlops/tests/test_curated_helpers.py` — Task 1 테스트
- `mlops/tests/test_parse_curated_papers.py` — Task 2 테스트
- `mlops/tests/test_ingest_curated_pmids.py` — Task 3, 4 테스트
- `mlops/tests/test_build_goldset.py` — Task 5 테스트

### Modified
없음 (기존 모듈은 import만)

### Inputs (이미 존재)
- `/mnt/c/Users/User/Desktop/coding/Main_Project/capstone/논문.txt` (사용자 큐레이션)
- `mlops/eval/goldset_seed.jsonl` (102 query seed)

### Outputs (생성될 산출물, gitignore 또는 별도 처리)
- `mlops/data/curated_provenance.json` (parse + ingest 단계에서 갱신)
- `mlops/data/curated_issues.json` (parse-time issues)
- `mlops/data/.ingest.lock` (flock 파일)
- `mlops/eval/goldset.jsonl` (build_goldset 출력)
- `mlops/eval/reports/goldset_summary.md` (build_goldset 출력)

---

## Task 1: 공용 helper module `mlops/pipeline/curated.py`

**Files:**
- Create: `mlops/pipeline/curated.py`
- Test: `mlops/tests/test_curated_helpers.py`

### 1.1 `normalize_doi()` — TDD

- [ ] **Step 1.1.1: Write failing tests**

`mlops/tests/test_curated_helpers.py`:
```python
"""curated helper 단위 테스트."""
import pytest
from mlops.pipeline.curated import normalize_doi


class TestNormalizeDoi:
    def test_lowercases_doi(self):
        assert normalize_doi("10.1080/02640414.2016.1210197") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("10.1519/JSC.0000000000002776") == "10.1519/jsc.0000000000002776"

    def test_strips_url_prefix(self):
        assert normalize_doi("https://doi.org/10.1080/02640414.2016.1210197") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("http://dx.doi.org/10.1080/02640414") == "10.1080/02640414"

    def test_strips_whitespace_and_punctuation(self):
        assert normalize_doi("  10.1080/02640414.2016.1210197.  ") == "10.1080/02640414.2016.1210197"
        assert normalize_doi("10.1080/02640414;") == "10.1080/02640414"

    def test_returns_empty_for_invalid(self):
        assert normalize_doi("") == ""
        assert normalize_doi("not-a-doi") == ""
        assert normalize_doi(None) == ""

    def test_idempotent(self):
        first = normalize_doi("HTTPS://DOI.ORG/10.1080/JSC.001;")
        second = normalize_doi(first)
        assert first == second
```

- [ ] **Step 1.1.2: Run test (expect fail)**

```bash
cd /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync
pytest mlops/tests/test_curated_helpers.py::TestNormalizeDoi -v
```
Expected: ImportError (`mlops.pipeline.curated` doesn't exist yet)

- [ ] **Step 1.1.3: Implement `normalize_doi()`**

`mlops/pipeline/curated.py`:
```python
"""큐레이션 paper 적재용 공용 helper.

normalize_doi, NCBI ID Converter, OpenAlex DOI lookup, title sanity check.
"""

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_VALIDATE_RE = re.compile(r"^10\.\d{4,9}/")


def normalize_doi(raw: Optional[str]) -> str:
    """DOI 정규화 — idempotent.

    규칙: strip whitespace → URL prefix 제거 → lowercase → 말미 구두점(.,;) 제거.
    유효하지 않으면 빈 문자열 반환 (10.{prefix}/ 패턴 미충족).
    """
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    s = _DOI_URL_PREFIX_RE.sub("", s)
    s = s.lower()
    s = s.rstrip(".,;")
    if not _DOI_VALIDATE_RE.match(s):
        return ""
    return s
```

- [ ] **Step 1.1.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestNormalizeDoi -v
```
Expected: 5 passed

- [ ] **Step 1.1.5: Commit**

```bash
git add mlops/pipeline/curated.py mlops/tests/test_curated_helpers.py
git commit -m "feat: curated 공용 helper normalize_doi 추가"
```

### 1.2 NCBI ID Converter — TDD with mock

- [ ] **Step 1.2.1: Write failing tests**

Append to `mlops/tests/test_curated_helpers.py`:
```python
from unittest.mock import MagicMock, patch
from mlops.pipeline.curated import ncbi_pmid_to_doi


class TestNcbiPmidToDoi:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_doi_when_present(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345", "doi": "10.1080/test"}]}
        mock_get.return_value = mock_resp

        result = ncbi_pmid_to_doi("12345")
        assert result == "10.1080/test"

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_when_doi_missing(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345"}]}
        mock_get.return_value = mock_resp

        assert ncbi_pmid_to_doi("12345") == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_empty_on_http_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("503")
        assert ncbi_pmid_to_doi("12345") == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_normalizes_returned_doi(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"records": [{"pmid": "12345", "doi": "10.1080/TEST.001;"}]}
        mock_get.return_value = mock_resp

        assert ncbi_pmid_to_doi("12345") == "10.1080/test.001"
```

(import `requests` at top of test file if not already)

- [ ] **Step 1.2.2: Run test (expect fail — ImportError)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestNcbiPmidToDoi -v
```

- [ ] **Step 1.2.3: Implement**

Append to `mlops/pipeline/curated.py`:
```python
NCBI_ID_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def ncbi_pmid_to_doi(pmid: str, timeout: int = 30) -> str:
    """NCBI ID Converter로 PMID → DOI 변환.

    실패 시 빈 문자열 반환. 정규화된 DOI를 돌려준다.
    """
    if not pmid:
        return ""
    try:
        resp = requests.get(
            NCBI_ID_CONVERTER_URL,
            params={"ids": pmid, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("NCBI ID Converter failed for PMID=%s: %s", pmid, e)
        return ""

    records = data.get("records", [])
    if not records:
        return ""
    raw_doi = records[0].get("doi", "")
    return normalize_doi(raw_doi)
```

- [ ] **Step 1.2.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestNcbiPmidToDoi -v
```
Expected: 4 passed

- [ ] **Step 1.2.5: Commit**

```bash
git add mlops/pipeline/curated.py mlops/tests/test_curated_helpers.py
git commit -m "feat: curated NCBI ID Converter wrapper 추가"
```

### 1.3 OpenAlex DOI lookup — TDD with mock

- [ ] **Step 1.3.1: Write failing tests**

Append to `mlops/tests/test_curated_helpers.py`:
```python
from mlops.pipeline.curated import openalex_doi_lookup


class TestOpenalexDoiLookup:
    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_metadata_with_pmid(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1080/test",
            "title": "Sample Paper",
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/12345"},
            "publication_year": 2023,
            "type": "journal-article",
        }
        mock_get.return_value = mock_resp

        result = openalex_doi_lookup("10.1080/test")
        assert result is not None
        assert result["pmid"] == "12345"
        assert result["title"] == "Sample Paper"
        assert result["doi"] == "10.1080/test"
        assert result["publication_year"] == 2023

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_metadata_without_pmid(self, mock_get):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"doi": "https://doi.org/10.1080/x", "title": "X", "ids": {}}
        mock_get.return_value = mock_resp

        result = openalex_doi_lookup("10.1080/x")
        assert result is not None
        assert result["pmid"] == ""

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_404(self, mock_get):
        mock_resp = MagicMock(status_code=404)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = mock_resp

        assert openalex_doi_lookup("10.1080/notfound") is None

    @patch("mlops.pipeline.curated.requests.get")
    def test_returns_none_on_request_exception(self, mock_get):
        mock_get.side_effect = requests.RequestException("timeout")
        assert openalex_doi_lookup("10.1080/x") is None
```

- [ ] **Step 1.3.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestOpenalexDoiLookup -v
```

- [ ] **Step 1.3.3: Implement**

Append to `mlops/pipeline/curated.py`:
```python
OPENALEX_DOI_LOOKUP_URL = "https://api.openalex.org/works/doi:"
_PMID_URL_RE = re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def openalex_doi_lookup(doi: str, timeout: int = 30) -> Optional[dict]:
    """OpenAlex DOI lookup. 정상 응답이면 metadata dict 반환, 404/empty/error면 None.

    반환 dict 구조:
      {
        "doi": str (normalized),
        "pmid": str (없으면 ""),
        "title": str,
        "publication_year": int | None,
        "type": str (OpenAlex work type),
      }
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    url = f"{OPENALEX_DOI_LOOKUP_URL}{normalized}"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("OpenAlex DOI lookup failed for %s: %s", normalized, e)
        return None

    if not data:
        return None

    # PMID 추출
    pmid_url = data.get("ids", {}).get("pmid", "")
    pmid_match = _PMID_URL_RE.search(pmid_url) if pmid_url else None
    pmid = pmid_match.group(1) if pmid_match else ""

    return {
        "doi": normalize_doi(data.get("doi", "")),
        "pmid": pmid,
        "title": data.get("title", "") or "",
        "publication_year": data.get("publication_year"),
        "type": data.get("type", "") or "",
    }
```

- [ ] **Step 1.3.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestOpenalexDoiLookup -v
```
Expected: 4 passed

- [ ] **Step 1.3.5: Commit**

```bash
git add mlops/pipeline/curated.py mlops/tests/test_curated_helpers.py
git commit -m "feat: curated OpenAlex DOI lookup helper 추가"
```

### 1.4 Title keyword overlap (Step 4 sanity check) — TDD

- [ ] **Step 1.4.1: Write failing tests**

Append to `mlops/tests/test_curated_helpers.py`:
```python
from mlops.pipeline.curated import title_keyword_overlap


class TestTitleKeywordOverlap:
    def test_high_overlap(self):
        title = "Effects of weekly training volume on muscle hypertrophy"
        context = "weekly set volume per muscle group hypertrophy"
        ratio = title_keyword_overlap(title, context)
        assert ratio >= 0.5  # significant overlap

    def test_low_overlap(self):
        title = "Hammer Strength Cybernetics for Robotic Cardiology"
        context = "weekly set volume per muscle group hypertrophy"
        ratio = title_keyword_overlap(title, context)
        assert ratio < 0.2

    def test_empty_inputs(self):
        assert title_keyword_overlap("", "anything") == 0.0
        assert title_keyword_overlap("anything", "") == 0.0

    def test_stopwords_ignored(self):
        title = "The Effect of A Variable on The Outcome"
        context = "Outcome"
        ratio = title_keyword_overlap(title, context)
        assert ratio > 0.0  # "outcome" matches, stopwords excluded
```

- [ ] **Step 1.4.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestTitleKeywordOverlap -v
```

- [ ] **Step 1.4.3: Implement**

Append to `mlops/pipeline/curated.py`:
```python
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "on", "in", "at", "to", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "with", "by", "from", "as", "this", "that", "these", "those", "vs",
})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def title_keyword_overlap(title: str, context: str) -> float:
    """title과 context의 키워드 jaccard-style overlap ratio.

    title의 tokens가 context tokens 안에 얼마나 들어있는지로 계산.
    range [0.0, 1.0]. typo auto-fixed DOI의 title sanity check에 사용.
    """
    if not title or not context:
        return 0.0
    title_tokens = _tokenize(title)
    context_tokens = _tokenize(context)
    if not title_tokens:
        return 0.0
    matched = title_tokens & context_tokens
    return len(matched) / len(title_tokens)
```

- [ ] **Step 1.4.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_curated_helpers.py::TestTitleKeywordOverlap -v
```
Expected: 4 passed

- [ ] **Step 1.4.5: Commit**

```bash
git add mlops/pipeline/curated.py mlops/tests/test_curated_helpers.py
git commit -m "feat: curated title keyword overlap helper 추가"
```

---

## Task 2: `mlops/scripts/parse_curated_papers.py`

**Files:**
- Create: `mlops/scripts/parse_curated_papers.py`
- Test: `mlops/tests/test_parse_curated_papers.py`

Spec §4.1 참조.

### 2.1 PMID/DOI 추출 + Q 파싱 — TDD

- [ ] **Step 2.1.1: Write failing tests**

`mlops/tests/test_parse_curated_papers.py`:
```python
"""parse_curated_papers 단위 테스트."""
import json
from pathlib import Path

import pytest

from mlops.scripts.parse_curated_papers import (
    extract_ids_from_lines,
    parse_papers_txt,
    detect_issues,
)


SAMPLE_TXT = """Hypertrophy
Q001: What is the optimal weekly set volume?
1. DOI: 10.1080/02640414.2016.1210197
2. PMID: 35291645 PMCID: PMC8884877 DOI: 10.2478/hukin-2022-0017
3. PMID 20512950

Q004 삭제

Q027: Concurrent gains
1. DOI: 10.1007/s40279-026-02401-y
2. DOI: 10.1519/JSC.0000000000004304
"""


class TestExtractIdsFromLines:
    def test_extracts_pmid_with_label(self):
        lines = ["PMID: 35291645 DOI: 10.2478/hukin-2022-0017"]
        pmids, pmcids, dois = extract_ids_from_lines(lines)
        assert "35291645" in pmids
        assert "10.2478/hukin-2022-0017" in dois

    def test_extracts_pmid_without_colon(self):
        lines = ["3. PMID 20512950"]
        pmids, _, _ = extract_ids_from_lines(lines)
        assert "20512950" in pmids

    def test_extracts_pmcid(self):
        lines = ["PMCID: PMC8884877"]
        _, pmcids, _ = extract_ids_from_lines(lines)
        assert "PMC8884877" in pmcids

    def test_dedup_within_lines(self):
        lines = ["DOI: 10.1080/test", "DOI: 10.1080/test"]
        _, _, dois = extract_ids_from_lines(lines)
        assert dois.count("10.1080/test") == 1
```

- [ ] **Step 2.1.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_parse_curated_papers.py::TestExtractIdsFromLines -v
```

- [ ] **Step 2.1.3: Implement extraction + parsing**

`mlops/scripts/parse_curated_papers.py`:
```python
"""논문.txt → curated_provenance.json + curated_issues.json 파서.

Spec §4.1 참조. 로컬에서 실행. 네트워크 호출 없음.

사용법:
    python -m mlops.scripts.parse_curated_papers \\
        --input /path/to/논문.txt \\
        --provenance mlops/data/curated_provenance.json \\
        --issues mlops/data/curated_issues.json
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.curated import normalize_doi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PMID_RE = re.compile(r"PMID:?\s*(\d{5,9})", re.IGNORECASE)
PMCID_RE = re.compile(r"PMCID:?\s*(PMC\d+)", re.IGNORECASE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.IGNORECASE)
TYPO_DOI_RE = re.compile(r"(?<![\d\.])0\.(\d{4,9}/[^\s,;]+)")
Q_HEADER_RE = re.compile(r"^Q(\d{3})\b")

PLACEHOLDER_TOKENS = ("XXXX",)
FUTURE_DOI_PREFIXES = (
    "10.1007/s40279-026",
    "10.1038/s41430-026",
    "10.1038/s41598-026",
    "10.1186/s40798-026",
)

# Q-id → LABELING_PLAN.md 카테고리 매핑 (Q001~Q121 범위)
# 미정의 Q는 'unknown' → ingest 단계에서 경고만, 적재 진행은 함
DEFAULT_CATEGORY = "unknown"


def extract_ids_from_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """라인 리스트에서 unique PMID, PMCID, DOI 추출 (등장 순서 유지, dedup)."""
    pmids: list[str] = []
    pmcids: list[str] = []
    dois: list[str] = []
    seen_p, seen_c, seen_d = set(), set(), set()
    for line in lines:
        for m in PMID_RE.finditer(line):
            val = m.group(1)
            if val not in seen_p:
                pmids.append(val)
                seen_p.add(val)
        for m in PMCID_RE.finditer(line):
            val = m.group(1).upper()
            if val not in seen_c:
                pmcids.append(val)
                seen_c.add(val)
        for m in DOI_RE.finditer(line):
            val = normalize_doi(m.group(1))
            if val and val not in seen_d:
                dois.append(val)
                seen_d.add(val)
    return pmids, pmcids, dois


def parse_papers_txt(path: Path) -> tuple[dict[str, list[str]], set[str]]:
    """논문.txt → {qid: [lines]} 매핑 + 삭제된 qid set.

    Q 헤더는 ``Q\\d{3}`` 시작 라인. '삭제' 마크 포함 시 deleted_qids에 추가.
    """
    qid_lines: dict[str, list[str]] = {}
    deleted: set[str] = set()
    current_qid: Optional[str] = None

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            m = Q_HEADER_RE.match(line)
            if m:
                current_qid = f"Q{m.group(1)}"
                qid_lines[current_qid] = [line]
                if "삭제" in line:
                    deleted.add(current_qid)
            elif current_qid:
                qid_lines[current_qid].append(line)
                if "질문 삭제" in line.strip():
                    deleted.add(current_qid)
    return qid_lines, deleted
```

- [ ] **Step 2.1.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_parse_curated_papers.py::TestExtractIdsFromLines -v
```
Expected: 4 passed

- [ ] **Step 2.1.5: Commit**

```bash
git add mlops/scripts/parse_curated_papers.py mlops/tests/test_parse_curated_papers.py
git commit -m "feat: curated parser PMID/DOI 추출 기본 로직"
```

### 2.2 Issue detection — TDD

- [ ] **Step 2.2.1: Write failing tests**

Append to `mlops/tests/test_parse_curated_papers.py`:
```python
class TestDetectIssues:
    def test_detects_placeholder_doi(self):
        issues = detect_issues(["10.1001/jamanetworkopen.2024.XXXX"], [], "Q039")
        assert len(issues["placeholder_doi"]) == 1
        assert issues["placeholder_doi"][0]["value"] == "10.1001/jamanetworkopen.2024.xxxx"

    def test_detects_future_prefix_doi(self):
        issues = detect_issues(["10.1007/s40279-026-02401-y"], [], "Q027")
        assert len(issues["future_prefix_doi"]) == 1

    def test_detects_typo_doi(self):
        # 0.1123/... → 10.1123/...
        raw_lines = ["3. 0.1123/ijsnem.2013-0054"]
        issues = detect_issues([], raw_lines, "Q037")
        assert len(issues["typo_doi_autofixed"]) == 1
        autofixed = issues["typo_doi_autofixed"][0]
        assert autofixed["original"] == "0.1123/ijsnem.2013-0054"
        assert autofixed["fixed"] == "10.1123/ijsnem.2013-0054"

    def test_no_false_positives(self):
        issues = detect_issues(["10.1080/02640414.2016.1210197"], [], "Q001")
        assert issues["placeholder_doi"] == []
        assert issues["future_prefix_doi"] == []
        assert issues["typo_doi_autofixed"] == []
```

- [ ] **Step 2.2.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_parse_curated_papers.py::TestDetectIssues -v
```

- [ ] **Step 2.2.3: Implement**

Append to `mlops/scripts/parse_curated_papers.py`:
```python
def detect_issues(dois: list[str], raw_lines: list[str], qid: str) -> dict:
    """DOI / raw 라인에서 placeholder, 미래 prefix, typo 검출.

    반환: {"placeholder_doi": [...], "future_prefix_doi": [...], "typo_doi_autofixed": [...]}
    각 entry는 {"qid": str, "value": str} 또는 typo의 경우 {"qid", "original", "fixed"}.
    """
    issues = {"placeholder_doi": [], "future_prefix_doi": [], "typo_doi_autofixed": []}

    for doi in dois:
        if any(tok.lower() in doi for tok in PLACEHOLDER_TOKENS):
            issues["placeholder_doi"].append({"qid": qid, "value": doi})
        if any(doi.startswith(p) for p in FUTURE_DOI_PREFIXES):
            issues["future_prefix_doi"].append({"qid": qid, "value": doi})

    # typo: 라인 내 0.{prefix}/ 패턴 → 10.{prefix}/로 보정
    for line in raw_lines:
        for m in TYPO_DOI_RE.finditer(line):
            original = "0." + m.group(1)
            fixed = "10." + m.group(1)
            issues["typo_doi_autofixed"].append({"qid": qid, "original": original, "fixed": fixed})

    return issues
```

- [ ] **Step 2.2.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_parse_curated_papers.py::TestDetectIssues -v
```
Expected: 4 passed

- [ ] **Step 2.2.5: Commit**

```bash
git add mlops/scripts/parse_curated_papers.py mlops/tests/test_parse_curated_papers.py
git commit -m "feat: curated parser issue 검출(placeholder/future/typo)"
```

### 2.3 Provenance JSON 생성 + CLI — TDD with fixture

- [ ] **Step 2.3.1: Create fixture + integration test**

Create fixture: `mlops/tests/fixtures/sample_curated.txt`
```
Hypertrophy
Q001: What is the optimal weekly set volume?
1. DOI: 10.1080/02640414.2016.1210197
2. PMID: 35291645 PMCID: PMC8884877 DOI: 10.2478/hukin-2022-0017
3. PMID 20512950

Q004 삭제

Q027: Concurrent gains
1. DOI: 10.1007/s40279-026-02401-y
2. DOI: 10.1519/JSC.0000000000004304

Q037: Protein intake
1. 0.1123/ijsnem.2013-0054
2. DOI: 10.1186/1550-2783-11-20
```

Append to `mlops/tests/test_parse_curated_papers.py`:
```python
from mlops.scripts.parse_curated_papers import build_provenance, run


FIXTURE = Path(__file__).parent / "fixtures" / "sample_curated.txt"


class TestBuildProvenance:
    def test_provenance_structure(self, tmp_path):
        prov_path = tmp_path / "prov.json"
        issues_path = tmp_path / "iss.json"
        run(FIXTURE, prov_path, issues_path)

        prov = json.loads(prov_path.read_text())
        # Q001 present
        assert "Q001" in prov
        assert prov["Q001"]["category"] == "unknown"  # 매핑 없으면 unknown
        # 3 papers in Q001
        assert len(prov["Q001"]["papers"]) == 3
        # 각 paper는 resolved_* / indexed / fulltext_ok null로 시작
        for p in prov["Q001"]["papers"]:
            assert p["indexed"] is None
            assert p["fulltext_ok"] is None
            assert p["failure_reason"] is None

    def test_deleted_q_skipped(self, tmp_path):
        prov_path = tmp_path / "prov.json"
        issues_path = tmp_path / "iss.json"
        run(FIXTURE, prov_path, issues_path)
        prov = json.loads(prov_path.read_text())
        assert "Q004" not in prov

    def test_issues_recorded(self, tmp_path):
        prov_path = tmp_path / "prov.json"
        issues_path = tmp_path / "iss.json"
        run(FIXTURE, prov_path, issues_path)
        issues = json.loads(issues_path.read_text())
        assert len(issues["future_prefix_doi"]) >= 1
        assert any("s40279-026" in entry["value"] for entry in issues["future_prefix_doi"])
        assert len(issues["typo_doi_autofixed"]) >= 1
        assert any("0.1123" in entry["original"] for entry in issues["typo_doi_autofixed"])

    def test_deleted_queries_in_issues(self, tmp_path):
        prov_path = tmp_path / "prov.json"
        issues_path = tmp_path / "iss.json"
        run(FIXTURE, prov_path, issues_path)
        issues = json.loads(issues_path.read_text())
        assert "Q004" in issues["deleted_queries"]
```

- [ ] **Step 2.3.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_parse_curated_papers.py::TestBuildProvenance -v
```

- [ ] **Step 2.3.3: Implement `build_provenance` + `run` + `main()`**

Append to `mlops/scripts/parse_curated_papers.py`:
```python
def build_provenance(
    qid_lines: dict[str, list[str]],
    deleted: set[str],
    issues_acc: dict,
) -> dict:
    """qid_lines + issues → provenance 구조 생성.

    - 삭제 Q는 스킵
    - 각 Q의 paper entry는 raw_id / resolved_* / indexed=None / failure_reason=None 형태로 초기화
    - 동일 paper(PMID 또는 normalized DOI 기준)는 multi-Q에 등재되어도 raw_id만 다르게 보존
    """
    provenance: dict = {}
    for qid, lines in qid_lines.items():
        if qid in deleted:
            continue
        pmids, pmcids, dois = extract_ids_from_lines(lines)

        # issue 검출 + acc 누적
        local_issues = detect_issues(dois, lines, qid)
        for k, v in local_issues.items():
            issues_acc.setdefault(k, []).extend(v)

        # placeholder/future는 paper에서 제거, typo는 autofixed_doi로 변환
        placeholder_set = {e["value"] for e in local_issues["placeholder_doi"]}
        future_set = {e["value"] for e in local_issues["future_prefix_doi"]}
        typo_map = {e["original"]: e["fixed"] for e in local_issues["typo_doi_autofixed"]}

        dois_clean = [
            normalize_doi(typo_map.get(d, d))
            for d in dois
            if d not in placeholder_set and d not in future_set
        ]
        dois_clean = [d for d in dois_clean if d]  # normalize 실패 제거

        papers = []
        # PMID-bearing entries
        for pmid in pmids:
            papers.append({
                "raw_id": f"PMID:{pmid}",
                "raw_pmid": pmid,
                "raw_doi": None,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "already_in_corpus": None,
                "fulltext_ok": None,
                "failure_reason": None,
                "is_typo_autofixed": False,
                "search_categories": [DEFAULT_CATEGORY],
            })
        # DOI-only entries (PMID 없는 paper)
        for doi in dois_clean:
            is_typo = doi in typo_map.values()
            papers.append({
                "raw_id": f"DOI:{doi}",
                "raw_pmid": None,
                "raw_doi": doi,
                "resolved_pmid": None,
                "resolved_doi": None,
                "resolved_title": None,
                "indexed": None,
                "already_in_corpus": None,
                "fulltext_ok": None,
                "failure_reason": None,
                "is_typo_autofixed": is_typo,
                "search_categories": [DEFAULT_CATEGORY],
            })

        provenance[qid] = {
            "category": DEFAULT_CATEGORY,
            "papers": papers,
        }

    # deleted queries를 issues에 별도 기록
    issues_acc.setdefault("deleted_queries", []).extend(sorted(deleted))
    return provenance


def _atomic_write_json(path: Path, data) -> None:
    """tmp + os.replace 패턴."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def run(input_path: Path, provenance_path: Path, issues_path: Path) -> None:
    qid_lines, deleted = parse_papers_txt(input_path)
    issues: dict = {
        "placeholder_doi": [],
        "future_prefix_doi": [],
        "typo_doi_autofixed": [],
        "deleted_queries": [],
    }
    provenance = build_provenance(qid_lines, deleted, issues)
    _atomic_write_json(provenance_path, provenance)
    _atomic_write_json(issues_path, issues)
    logger.info(
        "parsed: %d Qs (skipped %d deleted), placeholder=%d future=%d typo=%d",
        len(provenance),
        len(deleted),
        len(issues["placeholder_doi"]),
        len(issues["future_prefix_doi"]),
        len(issues["typo_doi_autofixed"]),
    )


def main():
    parser = argparse.ArgumentParser(description="논문.txt → curated provenance + issues 파서")
    parser.add_argument("--input", required=True, type=Path, help="논문.txt 경로")
    parser.add_argument("--provenance", required=True, type=Path, help="curated_provenance.json 출력 경로")
    parser.add_argument("--issues", required=True, type=Path, help="curated_issues.json 출력 경로")
    args = parser.parse_args()
    run(args.input, args.provenance, args.issues)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2.3.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_parse_curated_papers.py -v
```
Expected: all pass

- [ ] **Step 2.3.5: Smoke run on real 논문.txt**

```bash
python -m mlops.scripts.parse_curated_papers \
    --input "/mnt/c/Users/User/Desktop/coding/Main_Project/capstone/논문.txt" \
    --provenance mlops/data/curated_provenance.json \
    --issues mlops/data/curated_issues.json
```
Expected stdout (log lines): "parsed: ~110 Qs (skipped ~8 deleted), placeholder>=4 future>=3 typo>=1"

Manually inspect `mlops/data/curated_provenance.json` and `curated_issues.json` for sanity.

- [ ] **Step 2.3.6: Commit**

```bash
git add mlops/scripts/parse_curated_papers.py mlops/tests/test_parse_curated_papers.py mlops/tests/fixtures/sample_curated.txt mlops/data/curated_provenance.json mlops/data/curated_issues.json
git commit -m "feat: curated parser provenance/issues 생성 + CLI"
```

---

## Task 3: `mlops/scripts/ingest_curated_pmids.py` — Core resolution

**Files:**
- Create: `mlops/scripts/ingest_curated_pmids.py`
- Test: `mlops/tests/test_ingest_curated_pmids.py`

Spec §4.2 참조.

### 3.1 Argument parsing + lock 획득 — TDD

- [ ] **Step 3.1.1: Write failing tests**

`mlops/tests/test_ingest_curated_pmids.py`:
```python
"""ingest_curated_pmids 단위 테스트."""
import fcntl
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestLockAcquisition:
    def test_acquires_lock_when_free(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock
        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path) as lock_fd:
            assert lock_fd is not None
        # 락 해제 후 파일 존재 OK (lock 파일은 reuse)
        assert lock_path.exists()

    def test_lock_fails_when_held(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock
        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path):
            # 이미 잡힌 락은 두 번째 호출에서 BlockingIOError
            with pytest.raises(BlockingIOError):
                with acquire_lock(lock_path):
                    pass
```

- [ ] **Step 3.1.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestLockAcquisition -v
```

- [ ] **Step 3.1.3: Implement skeleton + lock**

`mlops/scripts/ingest_curated_pmids.py`:
```python
"""큐레이션 paper 명시 입력 ingest.

Spec §4.2 단일 상태머신 참조.

사용법 (cloud GPU 서버에서):
    python -m mlops.scripts.ingest_curated_pmids \\
        --provenance mlops/data/curated_provenance.json \\
        [--dry-run] [--limit N]
"""

import argparse
import contextlib
import fcntl
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.curated import (
    normalize_doi,
    ncbi_pmid_to_doi,
    openalex_doi_lookup,
    title_keyword_overlap,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

LOCK_FILENAME = ".ingest.lock"
TITLE_OVERLAP_THRESHOLD = 0.2


@contextlib.contextmanager
def acquire_lock(lock_path: Path):
    """flock 기반 advisory lock. 실패 시 BlockingIOError."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
```

- [ ] **Step 3.1.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestLockAcquisition -v
```
Expected: 2 passed

- [ ] **Step 3.1.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids lock 기반 동시성 보호"
```

### 3.2 PubMed efetch wrapper (batch) — TDD

- [ ] **Step 3.2.1: Write failing tests**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
SAMPLE_EFETCH_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>35291645</PMID>
      <Article>
        <ArticleTitle>Test Paper Title One</ArticleTitle>
        <Abstract><AbstractText>Sample abstract one.</AbstractText></Abstract>
        <PublicationTypeList>
          <PublicationType>Meta-Analysis</PublicationType>
        </PublicationTypeList>
        <Journal><JournalIssue><PubDate><Year>2022</Year></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="doi">10.2478/hukin-2022-0017</ArticleId>
        <ArticleId IdType="pmc">PMC8884877</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


class TestEfetchBatch:
    @patch("mlops.scripts.ingest_curated_pmids.requests.get")
    def test_parses_efetch_batch_response(self, mock_get):
        from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch
        mock_resp = MagicMock(status_code=200, text=SAMPLE_EFETCH_XML)
        mock_get.return_value = mock_resp

        result = efetch_pubmed_batch(["35291645"])
        assert "35291645" in result
        meta = result["35291645"]
        assert meta["doi"] == "10.2478/hukin-2022-0017"
        assert meta["pmcid"] == "PMC8884877"
        assert meta["title"] == "Test Paper Title One"
        assert meta["publication_year"] == 2022
        assert "Meta-Analysis" in meta["publication_types"]

    @patch("mlops.scripts.ingest_curated_pmids.requests.get")
    def test_returns_empty_dict_on_error(self, mock_get):
        from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch
        import requests as _r
        mock_get.side_effect = _r.RequestException("timeout")

        result = efetch_pubmed_batch(["35291645"])
        assert result == {}
```

- [ ] **Step 3.2.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestEfetchBatch -v
```

- [ ] **Step 3.2.3: Implement efetch wrapper**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
import xml.etree.ElementTree as ET

import requests

from mlops.pipeline.config import NCBI_API_KEY, NCBI_BASE_URL

EFETCH_BATCH_SIZE = 200


def efetch_pubmed_batch(pmids: list[str], timeout: int = 60) -> dict[str, dict]:
    """PubMed efetch로 PMID batch metadata 수집.

    Returns: {pmid: {doi, pmcid, title, abstract, publication_types, publication_year}}.
    응답에 없는 PMID는 dict에서 빠진다 (호출자가 누락 처리).
    """
    if not pmids:
        return {}
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        resp = requests.get(f"{NCBI_BASE_URL}/efetch.fcgi", params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("efetch batch failed (%d PMIDs): %s", len(pmids), e)
        return {}

    result: dict[str, dict] = {}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        logger.warning("efetch XML parse failed: %s", e)
        return {}

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()

        title_el = article.find(".//Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abstract_el = article.find(".//Abstract/AbstractText")
        abstract = "".join(abstract_el.itertext()).strip() if abstract_el is not None else ""

        pub_types = [
            (pt.text or "").strip()
            for pt in article.findall(".//PublicationTypeList/PublicationType")
            if pt.text
        ]

        year_el = article.find(".//Article/Journal/JournalIssue/PubDate/Year")
        try:
            year = int(year_el.text) if year_el is not None and year_el.text else None
        except (ValueError, TypeError):
            year = None

        doi = ""
        pmcid = ""
        for aid in article.findall(".//ArticleIdList/ArticleId"):
            id_type = aid.attrib.get("IdType", "").lower()
            if id_type == "doi" and aid.text:
                doi = normalize_doi(aid.text)
            elif id_type == "pmc" and aid.text:
                pmcid = aid.text.strip().upper()

        result[pmid] = {
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "abstract": abstract,
            "publication_types": pub_types,
            "publication_year": year,
        }
    return result
```

- [ ] **Step 3.2.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestEfetchBatch -v
```
Expected: 2 passed

- [ ] **Step 3.2.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids efetch batch metadata 수집"
```

### 3.3 Identifier resolution 단일 상태머신 — TDD

- [ ] **Step 3.3.1: Write failing tests**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
class TestResolveIdentifier:
    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_pmid_with_doi_from_efetch(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers

        mock_efetch.return_value = {
            "12345": {
                "doi": "10.1080/test",
                "pmcid": "PMC1",
                "title": "T",
                "abstract": "A",
                "publication_types": ["RCT"],
                "publication_year": 2020,
            }
        }
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["hypertrophy"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="hypertrophy volume")

        p = resolved[0]
        assert p["resolved_pmid"] == "12345"
        assert p["resolved_doi"] == "10.1080/test"
        assert p["resolved_title"] == "T"
        assert p["failure_reason"] is None
        assert p["metadata"]["publication_types"] == ["RCT"]

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    @patch("mlops.scripts.ingest_curated_pmids.ncbi_pmid_to_doi")
    def test_branch_a_efetch_no_doi_converter_succeeds(self, mock_conv, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_efetch.return_value = {
            "12345": {"doi": "", "pmcid": "", "title": "T", "abstract": "",
                      "publication_types": [], "publication_year": 2020}
        }
        mock_conv.return_value = "10.1080/converted"
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_doi"] == "10.1080/converted"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    @patch("mlops.scripts.ingest_curated_pmids.ncbi_pmid_to_doi")
    def test_branch_a_both_fail(self, mock_conv, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_efetch.return_value = {"12345": {"doi": "", "pmcid": "", "title": "T", "abstract": "",
                                              "publication_types": [], "publication_year": 2020}}
        mock_conv.return_value = ""
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "doi_resolution_failed"
        assert resolved[0]["indexed"] is False

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_branch_a_efetch_not_found(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        # PMID 12345 was requested but not in efetch response
        mock_efetch.return_value = {}
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        # Patch single re-fetch to also miss
        with patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch", return_value={}):
            resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "efetch_not_found"

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_doi_only_success(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_lookup.return_value = {
            "doi": "10.1080/test",
            "pmid": "99999",
            "title": "OA Title",
            "publication_year": 2021,
            "type": "journal-article",
        }
        papers = [{"raw_id": "DOI:10.1080/test", "raw_pmid": None, "raw_doi": "10.1080/test",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["resolved_pmid"] == "99999"
        assert resolved[0]["resolved_doi"] == "10.1080/test"
        assert resolved[0]["failure_reason"] is None

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_doi_only_no_pmid(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_lookup.return_value = {"doi": "10.1080/x", "pmid": "", "title": "T",
                                     "publication_year": None, "type": ""}
        papers = [{"raw_id": "DOI:10.1080/x", "raw_pmid": None, "raw_doi": "10.1080/x",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "no_pmid_from_openalex"

    @patch("mlops.scripts.ingest_curated_pmids.openalex_doi_lookup")
    def test_branch_b_openalex_not_found(self, mock_lookup):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_lookup.return_value = None
        papers = [{"raw_id": "DOI:10.1080/x", "raw_pmid": None, "raw_doi": "10.1080/x",
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": False, "fulltext_ok": None,
                   "search_categories": ["x"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="x")
        assert resolved[0]["failure_reason"] == "openalex_not_found"

    @patch("mlops.scripts.ingest_curated_pmids.efetch_pubmed_batch")
    def test_title_mismatch_skip(self, mock_efetch):
        from mlops.scripts.ingest_curated_pmids import resolve_papers
        mock_efetch.return_value = {
            "12345": {"doi": "10.1080/test", "pmcid": "", "title": "Robotic Cardiology Cybernetics",
                      "abstract": "", "publication_types": [], "publication_year": 2020}
        }
        papers = [{"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
                   "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
                   "indexed": None, "failure_reason": None, "already_in_corpus": None,
                   "is_typo_autofixed": True, "fulltext_ok": None,  # ← typo flag
                   "search_categories": ["hypertrophy"]}]
        resolved = resolve_papers(papers, qid="Q001", query_context="hypertrophy weekly set volume")
        assert resolved[0]["failure_reason"] == "title_mismatch"
```

- [ ] **Step 3.3.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestResolveIdentifier -v
```

- [ ] **Step 3.3.3: Implement `resolve_papers()`**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
def _mark_failure(paper: dict, reason: str) -> None:
    """invariant: failure_reason과 indexed=false 동시 기록 (§7.1)."""
    paper["failure_reason"] = reason
    paper["indexed"] = False


def resolve_papers(
    papers: list[dict],
    qid: str,
    query_context: str,
) -> list[dict]:
    """단일 상태머신: PMID 분기 + DOI-only 분기 + title sanity check.

    in-place로 paper["resolved_*"] / paper["failure_reason"] / paper["metadata"] 채움.
    metadata에는 publication_types, publication_year, pmcid, title, abstract 저장.
    """
    # 분기 A: PMID-bearing → efetch batch
    branch_a = [p for p in papers if p["raw_pmid"]]
    branch_b = [p for p in papers if p["raw_doi"] and not p["raw_pmid"]]

    if branch_a:
        pmids = [p["raw_pmid"] for p in branch_a]
        efetch_result = efetch_pubmed_batch(pmids)

        # 누락 PMID는 single re-fetch
        missing = [pmid for pmid in pmids if pmid not in efetch_result]
        if missing:
            logger.info("efetch missing %d PMIDs, single-fetch retry", len(missing))
            for pmid in missing:
                single = efetch_pubmed_batch([pmid])
                if pmid in single:
                    efetch_result[pmid] = single[pmid]

        for paper in branch_a:
            pmid = paper["raw_pmid"]
            if pmid not in efetch_result:
                _mark_failure(paper, "efetch_not_found")
                continue
            meta = efetch_result[pmid]
            paper["metadata"] = meta
            paper["resolved_pmid"] = pmid
            paper["resolved_title"] = meta["title"]
            doi = meta["doi"]
            if not doi:
                # converter fallback
                doi = ncbi_pmid_to_doi(pmid)
            if not doi:
                _mark_failure(paper, "doi_resolution_failed")
                continue
            paper["resolved_doi"] = doi

    # 분기 B: DOI-only → OpenAlex
    for paper in branch_b:
        doi = normalize_doi(paper["raw_doi"])
        lookup = openalex_doi_lookup(doi)
        if lookup is None:
            _mark_failure(paper, "openalex_not_found")
            continue
        if not lookup["pmid"]:
            _mark_failure(paper, "no_pmid_from_openalex")
            continue
        paper["resolved_pmid"] = lookup["pmid"]
        paper["resolved_doi"] = lookup["doi"] or doi
        paper["resolved_title"] = lookup["title"]
        paper["metadata"] = {
            "doi": lookup["doi"] or doi,
            "pmcid": "",
            "title": lookup["title"],
            "abstract": "",
            "publication_types": [],
            "publication_year": lookup["publication_year"],
        }

    # title sanity check for typo-autofixed papers
    for paper in papers:
        if not paper.get("is_typo_autofixed"):
            continue
        if paper.get("failure_reason"):
            continue  # already failed
        title = paper.get("resolved_title") or ""
        overlap = title_keyword_overlap(title, query_context)
        if overlap < TITLE_OVERLAP_THRESHOLD:
            _mark_failure(paper, "title_mismatch")

    return papers
```

- [ ] **Step 3.3.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestResolveIdentifier -v
```
Expected: 8 passed

- [ ] **Step 3.3.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids 단일 상태머신 identifier 해석"
```

### 3.4 already_in_corpus 처리 + atomic write — TDD

- [ ] **Step 3.4.1: Write failing tests**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
class TestAlreadyInCorpus:
    def test_marks_already_in_corpus_after_resolution(self):
        from mlops.scripts.ingest_curated_pmids import mark_already_in_corpus

        existing_dois = {"10.1080/test"}
        papers = [
            {"resolved_doi": "10.1080/test", "resolved_pmid": "12345",
             "indexed": None, "already_in_corpus": None, "failure_reason": None},
            {"resolved_doi": "10.1080/new", "resolved_pmid": "99999",
             "indexed": None, "already_in_corpus": None, "failure_reason": None},
        ]
        mark_already_in_corpus(papers, existing_dois)

        assert papers[0]["already_in_corpus"] is True
        assert papers[0]["indexed"] is True
        assert papers[1]["already_in_corpus"] is False
        assert papers[1]["indexed"] is None  # not yet processed

    def test_does_not_touch_failed_papers(self):
        from mlops.scripts.ingest_curated_pmids import mark_already_in_corpus
        existing_dois = {"10.1080/anything"}
        papers = [{"resolved_doi": "10.1080/anything", "resolved_pmid": "1",
                   "indexed": False, "already_in_corpus": None,
                   "failure_reason": "doi_resolution_failed"}]
        mark_already_in_corpus(papers, existing_dois)
        # 이미 실패한 paper는 변경하지 않음
        assert papers[0]["already_in_corpus"] is None


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import atomic_write_json
        path = tmp_path / "out.json"
        atomic_write_json(path, {"k": "v"})
        assert path.exists()
        assert json.loads(path.read_text()) == {"k": "v"}

    def test_atomic_write_replaces_existing(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import atomic_write_json
        path = tmp_path / "out.json"
        path.write_text('{"old": true}')
        atomic_write_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
        # tmp 파일은 남지 않아야 함
        assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 3.4.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestAlreadyInCorpus mlops/tests/test_ingest_curated_pmids.py::TestAtomicWrite -v
```

- [ ] **Step 3.4.3: Implement**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
def mark_already_in_corpus(papers: list[dict], existing_dois: set[str]) -> None:
    """Step 5: identifier 해석 후 already_in_corpus 판정.

    이미 실패한 paper(failure_reason 채워진 것)는 건드리지 않음.
    """
    for paper in papers:
        if paper.get("failure_reason"):
            continue
        doi = paper.get("resolved_doi")
        if not doi:
            paper["already_in_corpus"] = False
            continue
        if doi in existing_dois:
            paper["already_in_corpus"] = True
            paper["indexed"] = True
        else:
            paper["already_in_corpus"] = False


def atomic_write_json(path: Path, data) -> None:
    """tmp + os.replace 패턴 (POSIX atomic)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
```

- [ ] **Step 3.4.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py -v
```
Expected: all pass

- [ ] **Step 3.4.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids already_in_corpus 판정 + atomic write"
```

---

## Task 4: `ingest_curated_pmids.py` — Downstream integration

### 4.1 Existing DOIs loading — TDD

- [ ] **Step 4.1.1: Write failing tests**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
class TestLoadExistingDois:
    def test_combines_manifest_and_server(self):
        from mlops.scripts.ingest_curated_pmids import load_existing_dois

        manifest = MagicMock()
        manifest.papers = {
            "10.1/A": MagicMock(fulltext_source="pmc", tried_sources=["pmc"]),
            "10.1/B": MagicMock(fulltext_source=None, tried_sources=["pmc", "europepmc"]),
        }
        with patch("mlops.scripts.ingest_curated_pmids._fetch_server_dois") as mock_srv:
            mock_srv.return_value = {"10.1/C", "10.1/D"}
            result = load_existing_dois(manifest)
            assert "10.1/a" in result  # normalized
            assert "10.1/b" in result
            assert "10.1/c" in result
            assert "10.1/d" in result
```

- [ ] **Step 4.1.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestLoadExistingDois -v
```

- [ ] **Step 4.1.3: Implement**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL

ACTIVE_SOURCES = {"pmc", "europepmc"}


def _fetch_server_dois() -> set[str]:
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.warning("API_BASE_URL/ADMIN_API_TOKEN missing - server dedup 생략")
        return set()
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/dois"
    try:
        resp = requests.get(url, headers={"X-Admin-Token": ADMIN_API_TOKEN}, timeout=30)
        resp.raise_for_status()
        return set(resp.json()["data"]["dois"])
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("server DOI fetch failed: %s", e)
        return set()


def load_existing_dois(manifest) -> set[str]:
    """manifest 'indexed 또는 모든 active sources 시도' DOI + server DB DOI union.

    모든 DOI는 normalize_doi() 적용 후 set에 넣음.
    """
    manifest_dois = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            manifest_dois.add(normalize_doi(doi))
    server_dois = {normalize_doi(d) for d in _fetch_server_dois()}
    return manifest_dois | server_dois
```

- [ ] **Step 4.1.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestLoadExistingDois -v
```

- [ ] **Step 4.1.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids existing DOIs union loader"
```

### 4.2 PaperFull 구성 + fulltext + evidence — TDD

- [ ] **Step 4.2.1: Write failing tests**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
class TestBuildPaperFulls:
    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_builds_paperfull_with_fulltext(self, mock_fetch):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest
        from mlops.pipeline.models import PaperSection

        mock_fetch.return_value = ([PaperSection(name="Methods", text="...")], "pmc")
        papers = [{
            "resolved_pmid": "12345",
            "resolved_doi": "10.1080/test",
            "resolved_title": "T",
            "metadata": {"abstract": "abs", "pmcid": "PMC1", "publication_types": ["RCT"],
                          "publication_year": 2020},
            "search_categories": ["hypertrophy"],
            "indexed": None, "already_in_corpus": False, "fulltext_ok": None,
            "failure_reason": None,
        }]
        result = build_paperfulls_for_ingest(papers)

        assert len(result) == 1
        paperfull = result[0]
        assert paperfull.meta.pmid == "12345"
        assert paperfull.meta.doi == "10.1080/test"
        assert paperfull.meta.publication_types == ["RCT"]
        assert paperfull.meta.search_categories == ["hypertrophy"]
        assert papers[0]["fulltext_ok"] is True

    @patch("mlops.scripts.ingest_curated_pmids.fetch_cascading")
    def test_marks_no_fulltext_when_fetch_returns_empty(self, mock_fetch):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest
        mock_fetch.return_value = ([], None)  # no sections
        papers = [{
            "resolved_pmid": "12345", "resolved_doi": "10.1080/test", "resolved_title": "T",
            "metadata": {"abstract": "", "pmcid": "", "publication_types": [],
                          "publication_year": 2020},
            "search_categories": ["x"],
            "indexed": None, "already_in_corpus": False, "fulltext_ok": None,
            "failure_reason": None,
        }]
        result = build_paperfulls_for_ingest(papers)
        # paper는 result에서 빠짐 (sections=[])
        assert len(result) == 0
        # invariant: failure_reason과 indexed=False 동시 기록
        assert papers[0]["fulltext_ok"] is False
        assert papers[0]["failure_reason"] == "no_fulltext"
        assert papers[0]["indexed"] is False

    def test_skips_failed_and_already_in_corpus_papers(self):
        from mlops.scripts.ingest_curated_pmids import build_paperfulls_for_ingest
        papers = [
            {"resolved_pmid": "1", "indexed": True, "already_in_corpus": True,
             "failure_reason": None, "fulltext_ok": None},
            {"resolved_pmid": "2", "indexed": False, "already_in_corpus": False,
             "failure_reason": "doi_resolution_failed", "fulltext_ok": None},
        ]
        result = build_paperfulls_for_ingest(papers)
        assert result == []
```

- [ ] **Step 4.2.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestBuildPaperFulls -v
```

- [ ] **Step 4.2.3: Implement**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
from mlops.pipeline.evidence import calculate_evidence_weight
from mlops.pipeline.fulltext import fetch_cascading
from mlops.pipeline.models import PaperFull, PaperMeta


def build_paperfulls_for_ingest(papers: list[dict]) -> list[PaperFull]:
    """resolved paper들에 대해 fulltext fetch + PaperFull 구성.

    이미 적재됐거나(already_in_corpus=True) 실패한(failure_reason) paper는 스킵.
    fulltext 실패 시 §7.1 invariant 적용 (failure_reason="no_fulltext", indexed=False).
    """
    result: list[PaperFull] = []
    for paper in papers:
        if paper.get("failure_reason") or paper.get("already_in_corpus"):
            continue
        if not paper.get("resolved_doi") or not paper.get("resolved_pmid"):
            continue  # defensive: should be already marked failed

        meta_dict = paper.get("metadata", {})
        pmcid = meta_dict.get("pmcid", "")

        # fulltext cascade
        sections, fulltext_source = fetch_cascading(
            doi=paper["resolved_doi"],
            pmcid=pmcid if pmcid else None,
        )
        if not sections:
            paper["fulltext_ok"] = False
            _mark_failure(paper, "no_fulltext")
            continue
        paper["fulltext_ok"] = True

        evidence = calculate_evidence_weight(meta_dict.get("publication_types", []))

        paperfull = PaperFull(
            meta=PaperMeta(
                doi=paper["resolved_doi"],
                pmid=paper["resolved_pmid"],
                pmcid=pmcid,
                openalex_id="",
                title=paper["resolved_title"] or "",
                abstract=meta_dict.get("abstract", ""),
                publication_types=meta_dict.get("publication_types", []),
                publication_year=meta_dict.get("publication_year"),
                search_categories=paper["search_categories"],
                evidence_weight=evidence,
                fulltext_source=fulltext_source,
            ),
            sections=sections,
        )
        result.append(paperfull)

    return result
```

- [ ] **Step 4.2.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestBuildPaperFulls -v
```

- [ ] **Step 4.2.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids PaperFull 구성 + fulltext 통합"
```

### 4.3 Main flow integration (downstream + provenance batch update) — TDD

- [ ] **Step 4.3.1: Write integration test (mocking heavy)**

Append to `mlops/tests/test_ingest_curated_pmids.py`:
```python
class TestMainFlow:
    @patch("mlops.scripts.ingest_curated_pmids.api_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.embed_chunks")
    @patch("mlops.scripts.ingest_curated_pmids.chunk_papers")
    @patch("mlops.scripts.ingest_curated_pmids.build_paperfulls_for_ingest")
    @patch("mlops.scripts.ingest_curated_pmids.resolve_papers")
    @patch("mlops.scripts.ingest_curated_pmids.load_existing_dois")
    @patch("mlops.scripts.ingest_curated_pmids.Manifest")
    def test_main_end_to_end_happy_path(
        self, mock_manifest_cls, mock_existing, mock_resolve, mock_build,
        mock_chunk, mock_embed, mock_api, tmp_path
    ):
        from mlops.scripts.ingest_curated_pmids import run

        # Setup provenance fixture
        prov = {"Q001": {"category": "hypertrophy", "papers": [
            {"raw_id": "PMID:12345", "raw_pmid": "12345", "raw_doi": None,
             "resolved_pmid": None, "resolved_doi": None, "resolved_title": None,
             "indexed": None, "already_in_corpus": None, "fulltext_ok": None,
             "failure_reason": None, "is_typo_autofixed": False,
             "search_categories": ["hypertrophy"]}
        ]}}
        prov_path = tmp_path / "prov.json"
        prov_path.write_text(json.dumps(prov))

        mock_manifest_cls.load.return_value = MagicMock(papers={})
        mock_existing.return_value = set()

        # resolve_papers: PMID 12345 successfully resolved
        def resolve_side(papers, qid, query_context):
            for p in papers:
                p["resolved_pmid"] = "12345"
                p["resolved_doi"] = "10.1080/test"
                p["resolved_title"] = "T"
                p["metadata"] = {"abstract": "", "pmcid": "", "publication_types": [],
                                  "publication_year": 2020}
            return papers
        mock_resolve.side_effect = resolve_side

        from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection
        mock_build.return_value = [PaperFull(
            meta=PaperMeta(doi="10.1080/test", pmid="12345", pmcid="", openalex_id="",
                           title="T", abstract="", publication_types=[],
                           publication_year=2020, search_categories=["hypertrophy"],
                           evidence_weight=0.5, fulltext_source="pmc"),
            sections=[PaperSection(name="M", text="...")]
        )]
        mock_chunk.return_value = ["fake_chunk"]
        mock_embed.return_value = [("fake_chunk", [0.0] * 1024)]
        mock_api.return_value = 1  # 1 upserted

        run(prov_path, dry_run=False, limit=None, lock_path=tmp_path / ".lock")

        # provenance updated to indexed=True for the resolved paper
        updated = json.loads(prov_path.read_text())
        paper = updated["Q001"]["papers"][0]
        assert paper["resolved_pmid"] == "12345"
        assert paper["indexed"] is True
        # api_ingest was called with 1 chunk
        mock_api.assert_called_once()

    def test_dry_run_skips_api_ingest(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import run
        prov = {"Q001": {"category": "x", "papers": []}}
        prov_path = tmp_path / "prov.json"
        prov_path.write_text(json.dumps(prov))

        # dry-run: no API calls
        with patch("mlops.scripts.ingest_curated_pmids.Manifest") as mock_m, \
             patch("mlops.scripts.ingest_curated_pmids.load_existing_dois", return_value=set()), \
             patch("mlops.scripts.ingest_curated_pmids.api_ingest") as mock_api:
            mock_m.load.return_value = MagicMock(papers={})
            run(prov_path, dry_run=True, limit=None, lock_path=tmp_path / ".lock")
            mock_api.assert_not_called()
```

- [ ] **Step 4.3.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py::TestMainFlow -v
```

- [ ] **Step 4.3.3: Implement `run()` + `main()`**

Append to `mlops/scripts/ingest_curated_pmids.py`:
```python
from mlops.pipeline.chunker import chunk_papers
from mlops.pipeline.embedder import embed_chunks
from mlops.pipeline.manifest import Manifest
from mlops.pipeline.config import MANIFEST_PATH


def _build_api_payload(chunk_vectors: list[tuple]) -> dict:
    """initial_ingest.py와 동일한 schema."""
    return {
        "chunks": [
            {
                "paper_doi": chunk.paper_doi,
                "paper_pmid": chunk.paper_pmid or "",
                "paper_title": chunk.paper_title,
                "section_name": chunk.section_name,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "token_count": chunk.token_count,
                "embedding": vec,
                "search_categories": chunk.search_categories,
                "publication_types": chunk.publication_types,
                "evidence_weight": chunk.evidence_weight,
                "fulltext_source": chunk.fulltext_source or "",
                "published_year": chunk.published_year or 0,
            }
            for chunk, vec in chunk_vectors
        ]
    }


def api_ingest(chunk_vectors: list[tuple]) -> int:
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.error("API_BASE_URL / ADMIN_API_TOKEN 미설정")
        sys.exit(1)
    payload = _build_api_payload(chunk_vectors)
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"
    resp = requests.post(url, json=payload, headers={"X-Admin-Token": ADMIN_API_TOKEN}, timeout=300)
    resp.raise_for_status()
    return resp.json()["data"]["upserted"]


def _is_paper_processed(paper: dict) -> bool:
    """resumability: indexed=True 또는 failure_reason 채워진 paper는 처리됨."""
    return paper.get("indexed") is True or bool(paper.get("failure_reason"))


def run(
    provenance_path: Path,
    dry_run: bool = False,
    limit: Optional[int] = None,
    lock_path: Optional[Path] = None,
) -> None:
    lock_path = lock_path or (provenance_path.parent / LOCK_FILENAME)

    try:
        with acquire_lock(lock_path):
            _run_locked(provenance_path, dry_run=dry_run, limit=limit)
    except BlockingIOError:
        logger.error("Lock %s already held (run_3k.sh 또는 다른 ingest 진행 중?). 수동 재시도.", lock_path)
        sys.exit(1)


def _run_locked(provenance_path: Path, dry_run: bool, limit: Optional[int]) -> None:
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    logger.info("provenance loaded: %d Qs", len(provenance))

    manifest = Manifest.load(MANIFEST_PATH)
    existing_dois = load_existing_dois(manifest)
    logger.info("existing_dois loaded: %d (manifest + server union, normalized)", len(existing_dois))

    total_resolved = 0
    total_indexed = 0
    total_skipped = 0

    for qid, q_data in provenance.items():
        # 미처리 paper만 처리 (resumability)
        unprocessed = [p for p in q_data["papers"] if not _is_paper_processed(p)]
        if limit is not None and total_resolved >= limit:
            break
        if not unprocessed:
            continue

        if limit is not None:
            unprocessed = unprocessed[: max(0, limit - total_resolved)]

        category = q_data.get("category", "unknown")
        # Q의 query string은 seed에서 가져와야 하지만 본 스크립트는 seed 미참조.
        # 대신 category + qid를 sanity check 컨텍스트로 사용 (typo paper는 소수라 충분).
        query_context = f"{category} {qid}"

        # Step 3 + Step 4 (identifier + title sanity)
        resolve_papers(unprocessed, qid=qid, query_context=query_context)
        # Step 5 (already_in_corpus)
        mark_already_in_corpus(unprocessed, existing_dois)
        # batch atomic write (resolved/failed 상태)
        atomic_write_json(provenance_path, provenance)

        # Step 6-9 (fulltext + chunk + embed + ingest)
        paperfulls = build_paperfulls_for_ingest(unprocessed)
        if not paperfulls:
            total_skipped += len(unprocessed)
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        chunks = chunk_papers(paperfulls)
        if not chunks:
            for p in unprocessed:
                if p["fulltext_ok"] and not p.get("failure_reason"):
                    _mark_failure(p, "no_fulltext")  # safety net
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        if dry_run:
            logger.info("[DRY RUN] qid=%s would ingest %d chunks", qid, len(chunks))
            total_resolved += len(unprocessed)
            continue

        try:
            chunk_vectors = embed_chunks(chunks)
        except Exception as e:
            logger.error("embed_chunks failed for qid=%s: %s", qid, e)
            for p in unprocessed:
                if p.get("fulltext_ok") and not p.get("failure_reason"):
                    _mark_failure(p, "embed_failed")
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        try:
            upserted = api_ingest(chunk_vectors)
            logger.info("qid=%s ingested %d chunks (%d upserted)", qid, len(chunks), upserted)
            # 성공한 paper들에 indexed=True
            for p in unprocessed:
                if p.get("fulltext_ok") and not p.get("failure_reason"):
                    p["indexed"] = True
                    total_indexed += 1
            # manifest 갱신
            for paperfull in paperfulls:
                manifest.record_attempt(
                    doi=paperfull.meta.doi,
                    pmid=paperfull.meta.pmid or None,
                    pmcid=paperfull.meta.pmcid,
                    openalex_id=paperfull.meta.openalex_id,
                    fulltext_source=paperfull.meta.fulltext_source,
                    tried_sources=list(ACTIVE_SOURCES),
                )
        except Exception as e:
            logger.error("api_ingest failed for qid=%s: %s", qid, e)
            for p in unprocessed:
                if p.get("fulltext_ok") and not p.get("failure_reason"):
                    _mark_failure(p, "api_ingest_failed")

        atomic_write_json(provenance_path, provenance)
        total_resolved += len(unprocessed)

    manifest.save(MANIFEST_PATH)
    logger.info("=== curated ingest done: resolved=%d indexed=%d skipped=%d ===",
                total_resolved, total_indexed, total_skipped)


def main():
    parser = argparse.ArgumentParser(description="큐레이션 PMID/DOI 명시 입력 ingest")
    parser.add_argument("--provenance", required=True, type=Path,
                        help="curated_provenance.json 경로 (in-place 갱신)")
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve + fulltext + chunk까지만, embed/api_ingest 생략")
    parser.add_argument("--limit", type=int, default=None,
                        help="처리할 paper 상한 (smoke test용)")
    args = parser.parse_args()
    run(args.provenance, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.3.4: Run all tests (expect pass)**

```bash
pytest mlops/tests/test_ingest_curated_pmids.py -v
```

- [ ] **Step 4.3.5: Commit**

```bash
git add mlops/scripts/ingest_curated_pmids.py mlops/tests/test_ingest_curated_pmids.py
git commit -m "feat: ingest_curated_pmids main flow + resumability"
```

---

## Task 5: `mlops/scripts/build_goldset.py`

**Files:**
- Create: `mlops/scripts/build_goldset.py`
- Test: `mlops/tests/test_build_goldset.py`

Spec §4.3 참조.

### 5.1 Provenance 분류 + goldset 생성 — TDD

- [ ] **Step 5.1.1: Write failing tests**

`mlops/tests/test_build_goldset.py`:
```python
"""build_goldset 단위 테스트."""
import json
from pathlib import Path

import pytest

from mlops.scripts.build_goldset import (
    classify_paper,
    build_goldset_entry,
    run,
)


class TestClassifyPaper:
    def test_matchable(self):
        paper = {"indexed": True, "resolved_pmid": "12345",
                 "failure_reason": None}
        assert classify_paper(paper) == "matchable"

    def test_indexed_but_no_pmid(self):
        # DOI-only paper that lost PMID resolution → can't match
        paper = {"indexed": True, "resolved_pmid": "",
                 "failure_reason": None}
        assert classify_paper(paper) == "failed"

    def test_failed(self):
        paper = {"indexed": False, "resolved_pmid": "12345",
                 "failure_reason": "no_fulltext"}
        assert classify_paper(paper) == "failed"

    def test_no_pmid(self):
        paper = {"indexed": False, "resolved_pmid": "",
                 "failure_reason": "no_pmid_from_openalex"}
        assert classify_paper(paper) == "no_pmid"


class TestBuildGoldsetEntry:
    def test_emits_matchable_set(self):
        seed = {"id": "Q001", "query": "test", "query_ko": "테스트",
                "category": "hypertrophy", "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"], "expected_pmids": [], "notes": ""}
        q_prov = {"category": "hypertrophy", "papers": [
            {"raw_id": "PMID:1", "resolved_pmid": "1", "indexed": True,
             "failure_reason": None, "resolved_doi": "10.1/a"},
            {"raw_id": "PMID:2", "resolved_pmid": "2", "indexed": False,
             "failure_reason": "no_fulltext", "resolved_doi": "10.1/b"},
            {"raw_id": "DOI:10.1/c", "resolved_pmid": "", "indexed": False,
             "failure_reason": "no_pmid_from_openalex", "resolved_doi": "10.1/c"},
        ]}
        entry = build_goldset_entry(seed, q_prov)
        assert entry["expected_pmids"] == ["1"]
        assert entry["curated_pmids_all"] == ["1", "2"]  # PMID 없는 c는 제외
        assert len(entry["papers_failed"]) == 2  # b (no_fulltext), c (no_pmid_from_openalex)
        assert entry["corpus_coverage"] == 0.5

    def test_returns_none_for_empty_matchable(self):
        """Method B: empty expected_pmids는 goldset entry 생성 안 함."""
        seed = {"id": "Q002", "query": "x", "expected_pmids": []}
        q_prov = {"category": "x", "papers": [
            {"raw_id": "PMID:1", "resolved_pmid": "1", "indexed": False,
             "failure_reason": "no_fulltext", "resolved_doi": "10.1/a"},
        ]}
        entry = build_goldset_entry(seed, q_prov)
        assert entry is None
```

- [ ] **Step 5.1.2: Run test (expect fail)**

```bash
pytest mlops/tests/test_build_goldset.py -v
```

- [ ] **Step 5.1.3: Implement**

`mlops/scripts/build_goldset.py`:
```python
"""curated_provenance.json + goldset_seed.jsonl → goldset.jsonl + summary 리포트.

Spec §4.3 참조. 로컬 실행, 네트워크 없음.

사용법:
    python -m mlops.scripts.build_goldset \\
        --seed mlops/eval/goldset_seed.jsonl \\
        --provenance mlops/data/curated_provenance.json \\
        --goldset mlops/eval/goldset.jsonl \\
        --summary mlops/eval/reports/goldset_summary.md
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def classify_paper(paper: dict) -> str:
    """spec §4.3 책임 #2 분류.

    Returns: 'matchable' | 'failed' | 'no_pmid'
    """
    pmid = paper.get("resolved_pmid") or ""
    if paper.get("indexed") and pmid:
        return "matchable"
    if pmid:
        return "failed"  # indexed=False but has PMID → curated_pmids_all 포함
    return "no_pmid"  # PMID 없음 → curated_pmids_all에서 제외


def build_goldset_entry(seed: dict, q_prov: dict) -> Optional[dict]:
    """spec §4.3 책임 #2, #3.

    Returns None when matchable set is empty (Method B: empty Q는 goldset 제외).
    """
    expected_pmids: list[str] = []
    curated_pmids_all: list[str] = []
    papers_failed: list[dict] = []

    for paper in q_prov["papers"]:
        klass = classify_paper(paper)
        pmid = paper.get("resolved_pmid") or ""
        if klass == "matchable":
            expected_pmids.append(pmid)
            curated_pmids_all.append(pmid)
        elif klass == "failed":
            curated_pmids_all.append(pmid)
            papers_failed.append({
                "raw_id": paper.get("raw_id", ""),
                "resolved_pmid": pmid,
                "failure_reason": paper.get("failure_reason") or "unknown",
            })
        else:  # no_pmid
            papers_failed.append({
                "raw_id": paper.get("raw_id", ""),
                "resolved_pmid": "",
                "failure_reason": paper.get("failure_reason") or "unknown",
            })

    if not expected_pmids:
        return None  # Method B 일관 적용

    total_curated = len(curated_pmids_all)
    coverage = len(expected_pmids) / total_curated if total_curated else 0.0

    return {
        **seed,
        "expected_pmids": expected_pmids,
        "curated_pmids_all": curated_pmids_all,
        "papers_failed": papers_failed,
        "corpus_coverage": round(coverage, 4),
    }


def run(seed_path: Path, provenance_path: Path, goldset_path: Path, summary_path: Path) -> None:
    seeds: list[dict] = []
    with open(seed_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))

    provenance: dict = json.loads(provenance_path.read_text(encoding="utf-8"))

    eligible_entries: list[dict] = []
    corpus_gap: list[str] = []
    unlabeled: list[str] = []
    total_expected = 0
    total_curated = 0

    for seed in seeds:
        qid = seed["id"]
        if qid not in provenance:
            unlabeled.append(qid)
            continue
        entry = build_goldset_entry(seed, provenance[qid])
        # seed-wide totals
        q_prov = provenance[qid]
        for p in q_prov["papers"]:
            klass = classify_paper(p)
            if klass == "matchable":
                total_expected += 1
                total_curated += 1
            elif klass == "failed":
                total_curated += 1

        if entry is None:
            # matchable 없음 → goldset에서 제외
            curated_any = any(classify_paper(p) != "no_pmid" for p in q_prov["papers"])
            if curated_any:
                corpus_gap.append(qid)
            else:
                unlabeled.append(qid)
            continue
        eligible_entries.append(entry)

    # goldset.jsonl write
    goldset_path.parent.mkdir(parents=True, exist_ok=True)
    with open(goldset_path, "w", encoding="utf-8") as f:
        for entry in eligible_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # summary report
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    total_coverage = total_expected / total_curated if total_curated else 0.0
    lines = [
        "# Curated Goldset Summary",
        f"- seed total: {len(seeds)} queries",
        f"- metrics_eligible_queries: {len(eligible_entries)}",
        f"- corpus_gap_queries: {len(corpus_gap)}",
        f"- unlabeled_queries: {len(unlabeled)}",
        f"- total matchable PMIDs: {total_expected}",
        f"- total curated PMIDs (with resolved_pmid): {total_curated}",
        f"- **total corpus coverage: {total_coverage:.2%}**",
        "",
        "## corpus_gap_queries (큐레이션은 됐지만 corpus 매칭 가능 paper 없음)",
        *([f"- {q}" for q in corpus_gap] or ["(none)"]),
        "",
        "## unlabeled_queries (논문.txt 추가 큐레이션 필요)",
        *([f"- {q}" for q in unlabeled] or ["(none)"]),
    ]
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("goldset.jsonl: %d entries, summary written", len(eligible_entries))


def main():
    parser = argparse.ArgumentParser(description="curated provenance + seed → goldset.jsonl")
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--goldset", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    run(args.seed, args.provenance, args.goldset, args.summary)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.1.4: Run test (expect pass)**

```bash
pytest mlops/tests/test_build_goldset.py -v
```

- [ ] **Step 5.1.5: Commit**

```bash
git add mlops/scripts/build_goldset.py mlops/tests/test_build_goldset.py
git commit -m "feat: build_goldset matchable set + summary 리포트"
```

### 5.2 End-to-end goldset 생성 — 통합 테스트

- [ ] **Step 5.2.1: Run integration test**

```bash
pytest mlops/tests/test_build_goldset.py -v
```
Expected: all pass

- [ ] **Step 5.2.2: Verify all tests still pass**

```bash
pytest mlops/tests/test_curated_helpers.py mlops/tests/test_parse_curated_papers.py mlops/tests/test_ingest_curated_pmids.py mlops/tests/test_build_goldset.py -v
```
Expected: all pass

- [ ] **Step 5.2.3: Lint check**

```bash
ruff check mlops/scripts/parse_curated_papers.py mlops/scripts/ingest_curated_pmids.py mlops/scripts/build_goldset.py mlops/pipeline/curated.py
```
Expected: no errors. Fix any reported issues then re-run.

- [ ] **Step 5.2.4: Commit linting fixes (if any)**

```bash
git add -A
git commit -m "chore: curated 스크립트 ruff 정리"
```

---

## Task 6: Cloud smoke test + 풀 실행

이 task는 cloud GPU 서버 접근이 필요하므로 사용자가 진행 또는 안내. 코드 변경 없음.

### 6.1 Cloud 배포

- [ ] **Step 6.1.1: 로컬 → cloud 동기화**

cloud 서버에서:
```bash
cd /mnt/data/scifit-sync/scifit-sync
git fetch origin
git checkout feature/jingyu/curated-ingest  # 이 brainstorm 결과 브랜치
git pull
```

또는 scp로 신규 파일만:
```bash
scp mlops/pipeline/curated.py mlops/scripts/parse_curated_papers.py mlops/scripts/ingest_curated_pmids.py mlops/scripts/build_goldset.py root@gpu-host:/mnt/data/scifit-sync/scifit-sync/<paths>
scp mlops/data/curated_provenance.json root@gpu-host:/mnt/data/scifit-sync/scifit-sync/mlops/data/
```

### 6.2 Smoke test (10 PMID)

- [ ] **Step 6.2.1: cloud에서 dry-run 10건**

```bash
cd /mnt/data/scifit-sync/scifit-sync
source venv/bin/activate  # 메모리 obs 11756의 venv 경로
python -m mlops.scripts.ingest_curated_pmids \
    --provenance mlops/data/curated_provenance.json \
    --dry-run --limit 10
```
Expected: 변환 성공률, fulltext 성공률, chunk 개수 stdout 로그. provenance 파일에 indexed=null 그대로 (dry-run).

- [ ] **Step 6.2.2: cloud에서 실제 10건 ingest**

```bash
python -m mlops.scripts.ingest_curated_pmids \
    --provenance mlops/data/curated_provenance.json \
    --limit 10
```
Expected: 10개 paper 적재 시도. provenance에 indexed=true 또는 failure_reason 채워짐. ChromaDB 청크 수 증가.

### 6.3 풀 실행 + goldset 생성

- [ ] **Step 6.3.1: cloud에서 풀 실행 (limit 제거)**

```bash
nohup python -m mlops.scripts.ingest_curated_pmids \
    --provenance mlops/data/curated_provenance.json \
    > ingest_curated_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo $! > run_curated.pid
```

진행 모니터링:
```bash
tail -f ingest_curated_*.log
```

- [ ] **Step 6.3.2: 완료 후 provenance를 로컬로 가져옴**

```bash
scp root@gpu-host:/mnt/data/scifit-sync/scifit-sync/mlops/data/curated_provenance.json mlops/data/
```

- [ ] **Step 6.3.3: 로컬에서 goldset.jsonl 생성**

```bash
python -m mlops.scripts.build_goldset \
    --seed mlops/eval/goldset_seed.jsonl \
    --provenance mlops/data/curated_provenance.json \
    --goldset mlops/eval/goldset.jsonl \
    --summary mlops/eval/reports/goldset_summary.md
```

- [ ] **Step 6.3.4: baseline 평가 실행**

```bash
python -m mlops.eval.run_eval \
    --goldset mlops/eval/goldset.jsonl \
    --output mlops/eval/reports/baseline_$(date +%Y-%m-%d).md
```

- [ ] **Step 6.3.5: 결과물 커밋**

```bash
git add mlops/data/curated_provenance.json mlops/eval/goldset.jsonl mlops/eval/reports/goldset_summary.md mlops/eval/reports/baseline_*.md
git commit -m "feat: curated goldset baseline 평가 결과 추가"
```

---

## Self-Review

**Spec coverage check** (spec §4-§8 vs plan tasks):

| Spec section | Plan task |
|---|---|
| §4.1 parse_curated_papers (정규식, issue 검출, provenance JSON) | Task 2 |
| §4.2 Step 1 existing_dois loading | Task 4.1 |
| §4.2 Step 2 input 펼침 | Task 4.3 `run()` |
| §4.2 Step 3 identifier 해석 단일 상태머신 | Task 3.3 |
| §4.2 Step 4 title sanity check | Task 3.3 (resolve_papers 내부) |
| §4.2 Step 5 already_in_corpus | Task 3.4 |
| §4.2 Step 6 fulltext cascade | Task 4.2 |
| §4.2 Step 7 evidence | Task 4.2 |
| §4.2 Step 8 search_categories | Task 4.2 (PaperMeta 생성 시 주입) |
| §4.2 Step 9 PaperFull 반환 + downstream | Task 4.2 + 4.3 |
| §4.2 동시성 보호 flock | Task 3.1 |
| §4.2 atomic provenance write | Task 3.4 |
| §4.3 build_goldset (matchable set, curated_pmids_all, summary) | Task 5 |
| §7.1 failure_reason enum (8개) | Task 3.3 + 4.2 (_mark_failure 사용) |
| §7.1 invariant (failure_reason ⟺ indexed=false) | Task 3.3 `_mark_failure` helper로 강제 |
| §7.4 transient → permanent enum | Task 4.2 (no_fulltext), Task 4.3 (embed_failed, api_ingest_failed) |
| §7.5 resumability | Task 4.3 `_is_paper_processed()` |
| §8.1 parse 테스트 | Task 2 (3개 TestClass) |
| §8.2 ingest mocking 테스트 | Task 3 + 4 (TestResolveIdentifier, TestAlreadyInCorpus, TestBuildPaperFulls, TestMainFlow) |
| §8.3 build_goldset 테스트 | Task 5 (TestClassifyPaper, TestBuildGoldsetEntry) |
| §8.4 smoke test | Task 6.2 |
| §8.5 end-to-end | Task 6.3 |

**Placeholder check**: No "TODO", "TBD", "implement later" in steps. Each code-step has actual code or actual command. ✓

**Type/method consistency**:
- `normalize_doi()` Task 1.1, used in Tasks 2.3, 3.3, 4.1 ✓
- `efetch_pubmed_batch(pmids: list[str]) -> dict[str, dict]` Task 3.2, called in Task 3.3 ✓
- `resolve_papers(papers, qid, query_context)` Task 3.3, called in Task 4.3 ✓
- `mark_already_in_corpus(papers, existing_dois)` Task 3.4, called in Task 4.3 ✓
- `build_paperfulls_for_ingest(papers)` Task 4.2, called in Task 4.3 ✓
- `_mark_failure(paper, reason)` Task 3.3, used throughout Tasks 4.2/4.3 ✓
- provenance paper schema: `raw_id, raw_pmid, raw_doi, resolved_pmid, resolved_doi, resolved_title, indexed, already_in_corpus, fulltext_ok, failure_reason, is_typo_autofixed, search_categories, metadata` — consistent across Tasks 2.3, 3.3, 4.2, 5.1 ✓

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-curated-paper-ingest.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
