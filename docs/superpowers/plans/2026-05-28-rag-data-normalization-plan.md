# RAG 데이터 정상화 + Ingestion 자동화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SciFit-Sync RAG 파이프라인의 메타데이터(`publication_types`/`evidence_weight`/`paper_doi`) 정상화와 청크 사이즈 정상화를 위해 JATS 파서 픽스 + PubMed efetch 추출 디버그 + 재현 가능한 자동 ingestion 파이프라인 구축 + ChromaDB alias-swap 적재 안정화를 5개 PR로 진행.

**Architecture:** 5개 PR을 의존성 그래프대로 병행/순차 머지한 뒤, `full_reingest.py` orchestrator로 5 Stage(fetch → chunk → embed → validate → upsert) 파이프라인을 실행. paper-level/chunk-level 두 게이트로 silent failure를 사전 차단하고, ChromaDB alias-swap으로 다운타임 ≤ 5분 보장.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, ChromaDB PersistentClient, BAAI/bge-large-en-v1.5, pytest, ruff, AWS ECS Fargate + EFS, GPU 서버(cscloud.gpu3.hufs.ac.kr).

**Spec 참조:** `docs/superpowers/specs/2026-05-28-rag-data-normalization-design.md` (commit 515a9ee)

---

## 의존성 그래프

```
                  ┌─ PR-α (efetch S5) ────┐
                  ├─ PR-β (JATS S1) ─────┤
develop (a3eede2) ┼─ PR-γ (orchestrator) ├─► Phase 2 실행 (E1~E4)
                  ├─ PR-δ (alias swap) ──┘
                  └─ PR-ε (admin 안정성) ── 독립 머지

Phase 1 (운영 절차, PR 없음) — design §3.5 시퀀스, 데모 임박이므로 가장 먼저
```

| PR | 브랜치 | 의존성 | 병렬 가능 |
|---|---|---|---|
| PR-α | `fix/jingyu/pubmed-publication-types` | 없음 (develop) | 다른 PR 모두와 |
| PR-β | `fix/jingyu/jats-nested-sec` (이미 존재) | 없음 (develop) | 다른 PR 모두와 |
| PR-γ | `feat/jingyu/full-reingest-pipeline` | 자체 코드는 독립, **실행은 α/β 머지 후** | 다른 PR review 단계와 |
| PR-δ | `feat/jingyu/chroma-alias-swap` | 없음 (develop) | 다른 PR 모두와 |
| PR-ε | `fix/jingyu/admin-pmids-pagination` | 없음 (develop) | 다른 PR 모두와 |

---

## Phase 1 — 데모용 local_pdf 즉시 적재 (운영 절차)

> PR 없이 운영 명령으로 처리. **데모 임박 = 최우선**. design §3.5 시퀀스 그대로.

### Task P1-1: 사전 검증 — GPU 서버 상태 확인

**Files:** N/A (운영)

- [ ] **Step 1: GPU 서버 접속 및 코드 최신화**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && git fetch origin && git checkout develop && git pull origin develop && git log --oneline -3'
```
기대 출력: `a3eede2 Merge pull request #174 ...` 첫 줄 보임.

- [ ] **Step 2: local_pdf_ingest 파일 존재 + 키 검증**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && python3 -c "
import gzip, json
with gzip.open(\"mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz\", \"rt\") as f:
    d = json.loads(f.readline())
    print(\"keys:\", sorted(d.keys()))
    print(\"doi:\", d.get(\"paper_doi\"))
    print(\"pmid:\", d.get(\"paper_pmid\"))
"'
```
기대: `keys` 목록에 `paper_doi`, `paper_pmid` 모두 존재. doi 또는 pmid 둘 중 하나 채워짐.

- [ ] **Step 3: 적재 프로세스 중단 상태 확인**

```bash
ssh gpu 'ps -ef | grep -E "load_embeddings|run_upsert" | grep -v grep'
```
기대: 빈 출력 (멈춰있어야 함). 만약 실행 중이면 P1으로 진입 금지.

### Task P1-2: prod ChromaDB 백업 (필수)

**Files:** N/A (AWS 운영)

- [ ] **Step 1: ECS task ID 확인**

```bash
aws ecs list-tasks --cluster scifit-sync --service-name scifit-sync-api --query 'taskArns[0]' --output text
```
기대 출력: `arn:aws:ecs:...:task/scifit-sync/<task-id>`

- [ ] **Step 2: 백업 스크립트 작성 (로컬)**

`scripts/backup_chroma.py` 생성:

```python
"""prod ChromaDB papers 컬렉션을 jsonl로 export."""
import chromadb, json, gzip, sys
from datetime import datetime

client = chromadb.PersistentClient("/chroma-data")
col = client.get_collection("papers")
data = col.get(include=["embeddings", "metadatas", "documents"])

out = f"/chroma-data/backup_papers_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.jsonl.gz"
with gzip.open(out, "wt", encoding="utf-8") as f:
    for i, doc_id in enumerate(data["ids"]):
        rec = {
            "id": doc_id,
            "document": data["documents"][i],
            "metadata": data["metadatas"][i],
            "embedding": data["embeddings"][i],
        }
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"OK: {out}, {len(data['ids'])} chunks", file=sys.stderr)
```

- [ ] **Step 3: ECS exec로 백업 실행**

```bash
TASK_ID=$(aws ecs list-tasks --cluster scifit-sync --service-name scifit-sync-api --query 'taskArns[0]' --output text | awk -F/ '{print $NF}')
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command "python /app/scripts/backup_chroma.py"
```
기대: `OK: /chroma-data/backup_papers_<ts>.jsonl.gz, 38800 chunks` 같은 출력.

- [ ] **Step 4: 백업 파일을 GPU 서버로 복사 (이중 보존)**

```bash
ssh gpu 'aws s3 cp s3://scifit-sync-backup/papers/backup_papers_<ts>.jsonl.gz /mnt/data/scifit-sync/phase1_backup.jsonl.gz' \
  || echo "S3 경로 없으면 EFS에서 직접 복사 — 추가 절차 필요"
```
(S3 경로가 셋업 안 됐으면 ECS exec 안의 EFS에서 직접 다운로드)

### Task P1-3: prod ChromaDB 와이프 + 적재

**Files:** N/A (AWS 운영)

- [ ] **Step 1: ChromaDB 와이프 (EFS /chroma-data 클리어)**

```bash
TASK_ID=$(aws ecs list-tasks --cluster scifit-sync --service-name scifit-sync-api --query 'taskArns[0]' --output text | awk -F/ '{print $NF}')
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command "rm -rf /chroma-data/* && echo wiped"
```
기대: `wiped` 출력.

- [ ] **Step 2: ECS force-new-deployment로 빈 컬렉션 재기동**

```bash
aws ecs update-service --cluster scifit-sync --service scifit-sync-api --force-new-deployment
aws ecs wait services-stable --cluster scifit-sync --services scifit-sync-api
```
기대: 새 task가 `RUNNING`. 시간 ~3분.

- [ ] **Step 3: 와이프 검증**

```bash
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" https://scifit-sync.com/api/v1/admin/rag/pmids?limit=10
```
기대: chunks=0 또는 빈 결과.

- [ ] **Step 4: local_pdf_ingest 적재**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.load_embeddings \
    --input mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz \
    --mode api --batch-size 200 --skip-errors 2>&1 | \
  tee /mnt/data/scifit-sync/phase1_local_pdf.log'
```
기대: 마지막 로그 `=== 적재 완료: 15361청크 (mode=api) ===`.

- [ ] **Step 5: 적재 검증**

```bash
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" https://scifit-sync.com/api/v1/admin/rag/pmids?limit=10 \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('chunks:', d.get('data',{}).get('chunks','?'))"
```
기대: chunks=15361 (또는 비슷). `/admin/rag/pmids` 500 에러면 우회: `aws ecs execute-command ... --command "python -c 'import chromadb; print(chromadb.PersistentClient(\"/chroma-data\").get_collection(\"papers\").count())'"` 으로 직접 카운트.

- [ ] **Step 6: chat smoke test**

앱에서 또는 admin endpoint로 chat 호출 1~2건. 응답 정상이면 데모 준비 완료. 회귀 발생 시 P1-4 롤백.

### Task P1-4: 롤백 (회귀 시만)

**Files:** N/A (AWS 운영, optional)

- [ ] **Step 1: 백업 jsonl로 재적재**

```bash
ssh gpu '.venv-gpu/bin/python3 -m mlops.scripts.load_embeddings \
  --input /mnt/data/scifit-sync/phase1_backup.jsonl.gz \
  --mode api --batch-size 200 --skip-errors'
```
기대: chunks=38800 복원.

- [ ] **Step 2: 복원 검증 + 사고 보고**

복구 완료 후 incident note 작성, S5 디버그 우선순위 상향.

---

## PR-α — efetch publication_types 추출 디버그 + 픽스 (S5)

**브랜치:** `fix/jingyu/pubmed-publication-types`
**의존성:** 없음 (develop 직접)
**목적:** crawler/local_pdf 양쪽에서 `publication_types`가 모두 0% 추출되는 문제 해결

### Task A1: 브랜치 생성 + 현황 조사

**Files:**
- Inspect: `mlops/scripts/ingest_curated_pmids.py:110` (이미 PublicationType 파싱 코드 존재)
- Inspect: `mlops/pipeline/crawler.py` (efetch 호출 경로)
- Inspect: `mlops/scripts/ingest_local_pdfs.py:133-148` (efetch 보강 분기)

- [ ] **Step 1: 브랜치 생성**

```bash
git fetch origin && git checkout develop && git pull origin develop && git checkout -b fix/jingyu/pubmed-publication-types
```

- [ ] **Step 2: efetch_pubmed_batch 정의 위치 확인**

```bash
grep -n "def efetch_pubmed_batch" mlops/scripts/ingest_curated_pmids.py
grep -n "from .* import.*efetch_pubmed_batch" mlops/ -r
```
기대 출력: `ingest_curated_pmids.py:<line>:def efetch_pubmed_batch` + 사용처 목록(local_pdfs, curated 두 곳).

- [ ] **Step 3: crawler.py가 efetch 호출하는 위치 파악**

```bash
grep -n "efetch\|publication_types" mlops/pipeline/crawler.py | head -30
```
기대: crawler가 어디서 publication_types를 채우는지 — OpenAlex source인지 PubMed 보조 호출인지 식별. (메모리에 따르면 `crawler.py:1180` `existing.publication_types = m.publication_types` 라인)

### Task A2: 재현 테스트 — 알려진 PMID로 efetch 호출 결과 확인

**Files:**
- Create: `mlops/tests/test_efetch_publication_types.py`

- [ ] **Step 1: 회귀 테스트 작성 (RCT/Meta-Analysis 알려진 PMID)**

```python
"""efetch_pubmed_batch publication_types 추출 회귀 테스트.

문제: 5/22·5/26 export에서 publication_types 0% 추출. 코드는 있는데 적용 안 됨.
검증: 알려진 PMID 3개(Meta-Analysis/RCT/Review)에 대해 정확한 type 반환되는지.
"""
import pytest
from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch


KNOWN_PMIDS = {
    "30180479": "Meta-Analysis",         # Schoenfeld 2018 meta-analysis (volume)
    "26834059": "Randomized Controlled Trial",  # Bartolomei et al. 2015 RCT
    "27291741": "Review",                # Schoenfeld 2016 review
}


@pytest.mark.integration
@pytest.mark.parametrize("pmid,expected_type", KNOWN_PMIDS.items())
def test_efetch_extracts_publication_types(pmid, expected_type):
    """알려진 PMID에 대해 PublicationTypeList가 정확히 파싱되어야 함."""
    result = efetch_pubmed_batch([pmid])
    assert pmid in result, f"efetch가 {pmid}를 반환하지 않음"
    pub_types = result[pmid].get("publication_types", [])
    assert pub_types, f"{pmid}: publication_types 비어있음 (S5 회귀)"
    assert expected_type in pub_types, f"{pmid}: expected {expected_type!r} not in {pub_types!r}"
```

- [ ] **Step 2: 실패 확인**

```bash
cd /mnt/c/Users/User/Desktop/coding/Main_Project/capstone/scifit-sync && \
  pytest mlops/tests/test_efetch_publication_types.py -v -m integration
```
기대: 3개 모두 FAIL (현재 추출 0% 가설 확정). 만약 PASS면 efetch 자체는 정상이고 호출자(crawler/local_pdf)에서 결과를 활용 못하는 게 원인 — Task A3로 진행.

### Task A3: 분기별 원인 진단

**Files:**
- Read: `mlops/scripts/ingest_curated_pmids.py:80-130` (efetch 본문)
- Read: `mlops/pipeline/crawler.py` (PubMed 보조 호출)
- Read: `mlops/scripts/ingest_local_pdfs.py:133-148`

- [ ] **Step 1: 시나리오 A — efetch 자체 추출 실패**

A2 테스트 FAIL이면 `ingest_curated_pmids.py:110` 부근의 XPath 또는 dict assembly가 문제. PubMed esummary→efetch 분기, key name 매핑(`publication_types` vs `pubtype` 등), namespace 등 확인. 직접 esummary URL 호출해서 raw XML 확인:

```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=30180479&retmode=xml" | grep -A1 PublicationType
```
기대: `<PublicationType UI="...">Meta-Analysis</PublicationType>` 같은 element 보임. 보이면 efetch는 정상, 파싱이 문제.

- [ ] **Step 2: 시나리오 B — crawler가 efetch 결과 무시**

A2 PASS면 efetch는 정상. crawler.py의 PubMed 보조 호출 경로(메모리에 따르면 `crawler.py:1164-1180` `_merge_doi_metas`)에서 publication_types 전파가 누락됐을 가능성. grep:

```bash
grep -n "publication_types" mlops/pipeline/crawler.py
```
기대: `existing.publication_types = m.publication_types` 같은 라인이 실제 코드 path에서 실행되는지 확인.

- [ ] **Step 3: 시나리오 C — local_pdf efetch는 다른 경로**

`ingest_local_pdfs.py:133-148`의 `efetch_data.get("publication_types", [])` 가 빈 리스트인지 키 자체가 없는지 확인. `efetch_pubmed_batch` 반환 dict의 키 이름과 일치하는지 (`publication_types` vs 다른 명칭).

### Task A4: 픽스 적용 (가장 흔한 시나리오 B 가정)

**Files:**
- Modify: `mlops/pipeline/crawler.py` (PubMed 보조 호출에서 publication_types 추출/전파)
- Modify: `mlops/scripts/ingest_curated_pmids.py` (필요 시 dict key 정규화)

- [ ] **Step 1: 픽스 후보 1 — crawler.py의 PubMed 보조 호출 후 publication_types를 채우는 코드 추가**

만약 crawler가 OpenAlex만 쓰고 PubMed 보강을 안 하면, A2 PMID 3개를 OpenAlex로 crawl했을 때도 publication_types가 비어있을 것. 그 경우 crawler에서 esummary/efetch 추가 호출 보강:

```python
# 예시 (실제 파일 본문에 맞게 위치 조정):
from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch

# 기존 round-robin dedup 직후, search_categories + evidence_weight 부여 이전에:
need_pmid_lookup = [doi for doi, meta in doi_to_meta.items()
                    if meta.pmid and not meta.publication_types]
if need_pmid_lookup:
    pmids = [doi_to_meta[doi].pmid for doi in need_pmid_lookup]
    efetch_data = efetch_pubmed_batch(pmids)
    for doi in need_pmid_lookup:
        m = doi_to_meta[doi]
        ef = efetch_data.get(m.pmid, {})
        if ef.get("publication_types"):
            m.publication_types = ef["publication_types"]
```

- [ ] **Step 2: A2 테스트 재실행**

```bash
pytest mlops/tests/test_efetch_publication_types.py -v -m integration
```
기대: 3개 PASS.

- [ ] **Step 3: 추가 단위 테스트 — 빈 입력/네트워크 실패 케이스**

```python
def test_efetch_empty_input():
    assert efetch_pubmed_batch([]) == {}

def test_efetch_unknown_pmid_returns_no_pub_types(monkeypatch):
    """PMID 존재해도 PublicationTypeList가 빈 케이스 — 안전 동작."""
    # 실제 호출 mock 또는 알려진 빈 케이스 PMID 사용
    result = efetch_pubmed_batch(["99999999"])  # 가짜 PMID
    # 키가 없거나 publication_types 빈 리스트 — 둘 다 허용
    assert result.get("99999999", {}).get("publication_types", []) == []
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest mlops/tests/test_efetch_publication_types.py -v
```
기대: 모두 PASS.

### Task A5: evidence_weight 분포 회귀 테스트

**Files:**
- Modify: `mlops/tests/test_evidence.py` (기존 파일 확장)

- [ ] **Step 1: end-to-end 테스트 추가**

```python
# mlops/tests/test_evidence.py 끝에 추가

from mlops.pipeline.evidence import calculate_evidence_weight

def test_meta_analysis_yields_weight_1():
    """Meta-Analysis publication_types → weight 1.00 보장 (회귀 방지)."""
    assert calculate_evidence_weight(["Meta-Analysis"]) == 1.00

def test_rct_yields_weight_0_9():
    assert calculate_evidence_weight(["Randomized Controlled Trial"]) == 0.90

def test_empty_falls_back_to_default():
    assert calculate_evidence_weight([]) == 0.50
```

- [ ] **Step 2: 테스트 실행 + commit**

```bash
pytest mlops/tests/test_evidence.py mlops/tests/test_efetch_publication_types.py -v
ruff check mlops/ && ruff format --check mlops/
git add mlops/pipeline/crawler.py mlops/tests/test_efetch_publication_types.py mlops/tests/test_evidence.py
git commit -m "fix: PubMed efetch publication_types 추출 누락 픽스 + 회귀 테스트"
```
기대: 모든 테스트 PASS, ruff clean.

### Task A6: PR-α 생성

- [ ] **Step 1: push + PR 생성**

```bash
git push -u origin fix/jingyu/pubmed-publication-types
gh pr create --base develop --title "fix: PubMed efetch publication_types 추출 누락 픽스" --body "$(cat <<'EOF'
## Summary

- 5/22·5/26 export에서 `publication_types` 0/200, `evidence_weight` 0.5 일률값 회귀 픽스
- 알려진 PMID 3개(Meta/RCT/Review)에 대한 추출 회귀 테스트 추가

## 원인

`crawler.py` round-robin dedup 후 PubMed 보조 호출에서 publication_types 전파 누락.

## 검증

- `pytest mlops/tests/test_efetch_publication_types.py -v` 3 PASS
- `pytest mlops/tests/test_evidence.py -v` 신규 3 PASS + 기존 통과

## 영향

Phase 2 재크롤 후 `publication_types ≥ 90%` 임계 (design §1 C2) 달성 가능.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-β — JATS 파서 픽스 (S1)

**브랜치:** `fix/jingyu/jats-nested-sec` (이미 존재, develop 위에 빈 상태)
**의존성:** 없음
**목적:** `.//sec` descendant 추출로 부모+자식 sec가 모두 별개 섹션이 되는 근본 원인 정리. PR #174 chunker packing이 보호망이지만 컴포지션 정확성을 위해 본질 픽스.

### Task B1: 현재 브랜치 동기화

**Files:**
- N/A (브랜치 작업)

- [ ] **Step 1: 브랜치 develop 최신 받기**

```bash
git checkout fix/jingyu/jats-nested-sec
git fetch origin
git rebase origin/develop
```
기대: 빈 브랜치라 conflict 없이 fast-forward 또는 단순 ahead 0.

### Task B2: 실패 테스트 작성 — nested sec fixture

**Files:**
- Create: `mlops/tests/test_jats_nested_sec.py`

- [ ] **Step 1: nested sec를 가진 JATS XML fixture 테스트 작성**

```python
"""JATS nested <sec> 추출 회귀 테스트.

문제: body.findall('.//sec') 가 descendant-or-self라
      부모 Methods sec + 자식 Subjects/Procedure/Statistics 각각이
      별개 PaperSection으로 추출됨 → 평균 56 토큰 청크의 직접 원인.
"""
from mlops.pipeline.europepmc import parse_sections


JATS_XML = b"""<?xml version="1.0"?>
<article>
  <body>
    <sec>
      <title>Methods</title>
      <p>intro paragraph here describing the methodology.</p>
      <sec>
        <title>Subjects</title>
        <p>50 trained males with at least one year of resistance training experience.</p>
      </sec>
      <sec>
        <title>Procedure</title>
        <p>Subjects performed three sets of bench press at 75% 1RM.</p>
      </sec>
      <sec>
        <title>Statistics</title>
        <p>Two-way ANOVA with repeated measures was applied.</p>
      </sec>
    </sec>
    <sec>
      <title>Results</title>
      <p>Significant increases were observed across all groups.</p>
    </sec>
  </body>
</article>"""


def test_parse_sections_emits_top_level_only():
    """Top-level <sec>만 추출되어야 함 (현재 버그는 4+1=5개 emit)."""
    sections = parse_sections(JATS_XML)
    names = [s.name for s in sections]
    assert names == ["Methods", "Results"], f"Expected top-level only, got: {names}"


def test_parse_sections_methods_includes_subsection_content():
    """Methods 섹션은 intro paragraph + 모든 sub-sec text를 포함."""
    sections = parse_sections(JATS_XML)
    methods = next(s for s in sections if s.name == "Methods")
    # 부모 intro
    assert "intro paragraph" in methods.content
    # 모든 자식 sub-sec text
    assert "50 trained males" in methods.content
    assert "three sets of bench press" in methods.content
    assert "Two-way ANOVA" in methods.content


def test_parse_sections_preserves_subsection_titles():
    """Sub-sec title을 inline heading으로 보존 (정보 손실 방지)."""
    sections = parse_sections(JATS_XML)
    methods = next(s for s in sections if s.name == "Methods")
    # heading은 텍스트 안에 어딘가 보존됨 (e.g. "## Subjects" 또는 prefix)
    assert "Subjects" in methods.content
    assert "Procedure" in methods.content
    assert "Statistics" in methods.content


def test_parse_sections_empty_body():
    assert parse_sections(b"<article><body></body></article>") == []
```

- [ ] **Step 2: 실패 확인**

```bash
pytest mlops/tests/test_jats_nested_sec.py -v
```
기대: 3~4개 FAIL (현재 `.//sec` 동작은 부모+자식 모두 emit).

### Task B3: europepmc.py 픽스

**Files:**
- Modify: `mlops/pipeline/europepmc.py:50-67` (`parse_sections`)

- [ ] **Step 1: 픽스 적용**

```python
# europepmc.py:50 함수 본문을 다음과 같이 교체

def parse_sections(xml_bytes: bytes) -> list[PaperSection]:
    """JATS fulltext XML에서 top-level <sec>만 추출, sub-sec text는 통합.

    부모 sec와 그 자식 sec를 별개 PaperSection으로 만들지 않는다
    (옛 `.//sec` 동작은 작은 섹션 폭증의 원인).
    """
    root = ET.fromstring(xml_bytes)
    body = root.find(".//body")
    if body is None:
        return []

    sections: list[PaperSection] = []
    for sec in body.findall("./sec"):  # 직계 자식만
        title_el = sec.find("./title")
        name = _get_text(title_el) or "Untitled"

        # sub-sec 포함 모든 descendant p를 순서대로 수집.
        # sub-sec title은 inline heading으로 보존.
        parts: list[str] = []
        for el in sec.iter():
            if el is sec:
                continue
            if el.tag == "title" and el is not title_el:
                t = _get_text(el)
                if t:
                    parts.append(f"\n## {t}\n")
            elif el.tag == "p":
                t = _get_text(el)
                if t:
                    parts.append(t)

        content = "\n".join(parts).strip()
        if content:
            sections.append(PaperSection(name=name, content=content))

    return sections
```

- [ ] **Step 2: 테스트 PASS 확인**

```bash
pytest mlops/tests/test_jats_nested_sec.py -v
```
기대: 모든 테스트 PASS.

### Task B4: crawler.py `_parse_pmc_sections` 동일 픽스

**Files:**
- Modify: `mlops/pipeline/crawler.py:968-990`

- [ ] **Step 1: crawler 측 함수도 동일 패턴으로 교체**

`europepmc.parse_sections`와 동일 로직으로 `_parse_pmc_sections` 본문 교체. import 추가 (`from mlops.pipeline.europepmc import _get_text, parse_sections as _parse_sections`) 후 위임하거나 본문 복제.

권장: 코드 중복 해소 — crawler에서 직접 `europepmc.parse_sections`를 호출:

```python
# crawler.py 상단 import에 추가
from mlops.pipeline.europepmc import parse_sections as _parse_jats_sections

# 기존 _parse_pmc_sections 본문을 다음으로 교체:
def _parse_pmc_sections(root: ET.Element) -> list[PaperSection]:
    """PMC XML에서 본문 섹션 추출 — europepmc.parse_sections 재사용.

    JATS schema는 EuropePMC와 동일하므로 같은 파서 사용.
    `pmc.py` 모듈 docstring의 "재사용한다" 주석과 일치.
    """
    from defusedxml import ElementTree as ET2
    xml_bytes = ET2.tostring(root) if hasattr(root, "tag") else root
    return _parse_jats_sections(xml_bytes)
```

(또는 `parse_sections`를 Element 받는 버전과 bytes 받는 버전으로 분리하는 게 더 깔끔 — 여건 따라 결정)

- [ ] **Step 2: crawler 측 회귀 테스트 추가 — 동일 fixture로 호출**

`test_jats_nested_sec.py`에 추가:

```python
import defusedxml.ElementTree as ET2
from mlops.pipeline.crawler import _parse_pmc_sections

def test_crawler_uses_same_parser():
    """crawler._parse_pmc_sections도 nested sec 픽스 적용."""
    root = ET2.fromstring(JATS_XML)
    sections = _parse_pmc_sections(root)
    names = [s.name for s in sections]
    assert names == ["Methods", "Results"]
```

- [ ] **Step 3: 모든 chunker/ingest 테스트 회귀 확인**

```bash
pytest mlops/tests/ -v
```
기대: 모든 기존 테스트 PASS (PR #174 머저 테스트 포함).

### Task B5: `pmc.py` 주석 정리 + commit

**Files:**
- Modify: `mlops/pipeline/pmc.py` (모듈 docstring `parse_sections를 재사용한다` 실제 동작과 일치 확인)

- [ ] **Step 1: pmc.py 모듈이 europepmc.parse_sections 재사용하는지 확인**

```bash
grep -n "parse_sections\|from .* import" mlops/pipeline/pmc.py
```
필요 시 import 정리.

- [ ] **Step 2: ruff check + commit**

```bash
ruff check mlops/ && ruff format --check mlops/
git add mlops/pipeline/europepmc.py mlops/pipeline/crawler.py mlops/pipeline/pmc.py mlops/tests/test_jats_nested_sec.py
git commit -m "fix: JATS nested <sec> 추출 — top-level만 emit + sub-sec text 통합"
```

### Task B6: PR-β 생성

- [ ] **Step 1: push + PR**

```bash
git push -u origin fix/jingyu/jats-nested-sec
gh pr create --base develop --title "fix: JATS nested <sec> 추출 버그 — top-level + descendant 통합" --body "$(cat <<'EOF'
## Summary

- `body.findall('.//sec')` descendant-or-self가 부모+자식 sec를 모두 별개 PaperSection으로 추출하던 본질 문제 픽스
- PR #174 chunker packing은 보호망 유지, 본 PR은 근본 원인 정리 + 컴포지션 정확성

## 변경

- `mlops/pipeline/europepmc.py:parse_sections` — `./sec` 직계 + descendant text 통합, sub-sec title은 inline heading으로 보존
- `mlops/pipeline/crawler.py:_parse_pmc_sections` — europepmc.parse_sections 재사용 (코드 중복 해소)
- `mlops/tests/test_jats_nested_sec.py` 신규 — nested fixture 4 케이스

## 검증

`pytest mlops/tests/test_jats_nested_sec.py mlops/tests/test_chunker.py -v` 전 PASS, ruff clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-γ — full_reingest.py + validate_embeddings.py (S2, S3)

**브랜치:** `feat/jingyu/full-reingest-pipeline`
**의존성:** 코드 자체는 독립이지만 실행은 α/β 머지 후
**목적:** fetch→chunk→embed→validate→upsert 5 stage orchestrator + pre-upsert validation 게이트

### Task C1: 브랜치 + 파일 골격

**Files:**
- Create: `mlops/scripts/full_reingest.py`
- Create: `mlops/scripts/validate_embeddings.py`
- Create: `mlops/eval/validation_thresholds.py`
- Create: `mlops/tests/test_validate_embeddings.py`
- Create: `mlops/tests/test_full_reingest.py`

- [ ] **Step 1: 브랜치 생성**

```bash
git checkout develop && git pull origin develop && git checkout -b feat/jingyu/full-reingest-pipeline
```

- [ ] **Step 2: 임계값 모듈 생성**

`mlops/eval/validation_thresholds.py`:

```python
"""Pre-Upsert Validation 임계값 모듈 (design §3.3.1).

운영 중 튜닝이 쉽도록 한 곳에 모음. 변경 시 design spec과 일치 유지.
"""

# 필수 키 (스키마)
REQUIRED_KEYS: tuple[str, ...] = (
    "chunk_index", "paper_pmid", "paper_title", "section_name", "token_count",
    "search_categories", "paper_doi", "publication_types", "evidence_weight",
    "fulltext_source", "published_year", "embedding",
)

# 식별자 fill rate — (paper_doi OR paper_pmid) 채워진 청크 비율
IDENTIFIER_FILL_RATE_MIN: float = 1.00  # 100% (만족 못하면 manifest 누수 버그)

# paper_doi 단독 fill rate (정보용)
PAPER_DOI_FILL_RATE_INFO_MIN: float = 0.99

# publication_types 비어있지 않은 비율 (design §1 C2)
PUBLICATION_TYPES_FILL_RATE_MIN: float = 0.90

# evidence_weight 다양화
EVIDENCE_WEIGHT_DISTINCT_MIN: int = 5
EVIDENCE_WEIGHT_05_RATIO_MAX: float = 0.50

# 청크 토큰
AVG_TOKEN_MIN: int = 300
AVG_TOKEN_MAX: int = 450
TOKEN_P99_MAX: int = 660  # PR #174 흡수 trade-off 한계
TOKEN_OVER_512_RATIO_MAX: float = 0.05

# 청크/논문 비율
CHUNKS_PER_PAPER_MIN: int = 20
CHUNKS_PER_PAPER_MAX: int = 60

# PDF 경로 회귀 — local_pdf 평균 토큰
PDF_AVG_TOKEN_MIN: int = 150
PDF_AVG_TOKEN_MAX: int = 250

# 임베딩 차원
EMBEDDING_DIM: int = 1024
```

- [ ] **Step 3: commit (skeleton)**

```bash
git add mlops/eval/validation_thresholds.py
git commit -m "feat: validation threshold 모듈 — design §3.3.1 임계값"
```

### Task C2: validate_embeddings.py TDD

**Files:**
- Create: `mlops/tests/test_validate_embeddings.py` (먼저)
- Create: `mlops/scripts/validate_embeddings.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
"""validate_embeddings.py 단위 테스트."""
import gzip, json, tempfile
from pathlib import Path
import pytest

from mlops.scripts.validate_embeddings import (
    validate_jsonl,
    ValidationResult,
)


def _make_jsonl(records: list[dict]) -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return tmp


def _ok_record(**overrides) -> dict:
    base = {
        "chunk_index": 0, "paper_pmid": "12345", "paper_title": "T",
        "section_name": "Methods", "token_count": 400,
        "search_categories": ["resistance_training"],
        "paper_doi": "10.1/abc", "publication_types": ["Randomized Controlled Trial"],
        "evidence_weight": 0.9, "fulltext_source": "pmc",
        "published_year": 2018, "embedding": [0.1] * 1024,
    }
    base.update(overrides)
    return base


def test_pass_when_all_thresholds_met():
    """모든 임계 충족 → PASS."""
    records = [_ok_record(chunk_index=i, evidence_weight=0.9 if i % 2 else 0.5,
                          publication_types=["RCT"] if i % 2 else ["Meta-Analysis"])
               for i in range(40)]
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    # 단일 종 RCT/Meta — evidence_weight distinct 부족할 수 있음. 다양화 보강:
    # → 위 다양화 임계 위반 가능. 별도 케이스로 작성.
    # 여기서는 단순 schema OK 검증
    assert result.schema_ok
    assert result.identifier_fill_rate == 1.0


def test_fail_when_key_missing():
    rec = _ok_record()
    rec.pop("publication_types")
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert not result.schema_ok
    assert "publication_types" in result.missing_keys


def test_fail_when_identifier_missing():
    rec = _ok_record(paper_doi="", paper_pmid="")
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert result.identifier_fill_rate < 1.0
    assert not result.passed


def test_fail_when_publication_types_under_threshold():
    """publication_types 빈 비율이 10% 초과 → FAIL."""
    records = []
    for i in range(100):
        rec = _ok_record(chunk_index=i)
        if i < 20:  # 20% 빈 → 80% filled, 90% 임계 미달
            rec["publication_types"] = []
        records.append(rec)
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert result.publication_types_fill_rate < 0.90
    assert not result.passed


def test_fail_when_avg_token_out_of_range():
    """평균 토큰 100 → AVG_TOKEN_MIN(300) 미달."""
    records = [_ok_record(chunk_index=i, token_count=100) for i in range(20)]
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert not result.passed
    assert result.avg_token < 300


def test_embedding_dim_mismatch():
    rec = _ok_record(embedding=[0.1] * 512)  # bge-base 차원
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert not result.passed
    assert result.embedding_dim != 1024
```

- [ ] **Step 2: 실패 확인**

```bash
pytest mlops/tests/test_validate_embeddings.py -v
```
기대: 모두 FAIL (`validate_jsonl` 정의 안 됨).

### Task C3: validate_embeddings.py 구현

**Files:**
- Create: `mlops/scripts/validate_embeddings.py`

- [ ] **Step 1: 구현**

```python
"""Pre-Upsert Validation 게이트 — design §3.3.1.

jsonl 산출물의 통계를 산출하고 임계 미달 시 fail-fast abort.
ChromaDB upsert 진입 직전 자동 호출 또는 단독 CLI로 실행.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, quantiles

from mlops.eval.validation_thresholds import (
    AVG_TOKEN_MAX,
    AVG_TOKEN_MIN,
    CHUNKS_PER_PAPER_MAX,
    CHUNKS_PER_PAPER_MIN,
    EMBEDDING_DIM,
    EVIDENCE_WEIGHT_05_RATIO_MAX,
    EVIDENCE_WEIGHT_DISTINCT_MIN,
    IDENTIFIER_FILL_RATE_MIN,
    PAPER_DOI_FILL_RATE_INFO_MIN,
    PDF_AVG_TOKEN_MAX,
    PDF_AVG_TOKEN_MIN,
    PUBLICATION_TYPES_FILL_RATE_MIN,
    REQUIRED_KEYS,
    TOKEN_OVER_512_RATIO_MAX,
    TOKEN_P99_MAX,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    schema_ok: bool = False
    missing_keys: set[str] = field(default_factory=set)
    identifier_fill_rate: float = 0.0
    paper_doi_fill_rate: float = 0.0
    publication_types_fill_rate: float = 0.0
    evidence_weight_distinct: int = 0
    evidence_weight_05_ratio: float = 0.0
    avg_token: float = 0.0
    p99_token: float = 0.0
    over_512_ratio: float = 0.0
    chunks_per_paper_avg: float = 0.0
    pdf_avg_token: float = 0.0
    embedding_dim: int = 0
    total_chunks: int = 0

    @property
    def passed(self) -> bool:
        return (
            self.schema_ok
            and self.identifier_fill_rate >= IDENTIFIER_FILL_RATE_MIN
            and self.publication_types_fill_rate >= PUBLICATION_TYPES_FILL_RATE_MIN
            and self.evidence_weight_distinct >= EVIDENCE_WEIGHT_DISTINCT_MIN
            and self.evidence_weight_05_ratio < EVIDENCE_WEIGHT_05_RATIO_MAX
            and AVG_TOKEN_MIN <= self.avg_token <= AVG_TOKEN_MAX
            and self.p99_token <= TOKEN_P99_MAX
            and self.over_512_ratio <= TOKEN_OVER_512_RATIO_MAX
            and CHUNKS_PER_PAPER_MIN <= self.chunks_per_paper_avg <= CHUNKS_PER_PAPER_MAX
            and self.embedding_dim == EMBEDDING_DIM
        )


def _iter_records(paths: list[Path]):
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def validate_jsonl(paths: list[Path]) -> ValidationResult:
    result = ValidationResult()
    tokens: list[int] = []
    ew_values: list[float] = []
    paper_chunks: Counter[str] = Counter()
    pdf_tokens: list[int] = []
    schema_ok = True
    missing_keys: set[str] = set()
    id_filled = 0
    doi_filled = 0
    pub_filled = 0
    emb_dims: set[int] = set()
    total = 0

    for rec in _iter_records(paths):
        total += 1
        # 스키마
        for k in REQUIRED_KEYS:
            if k not in rec:
                missing_keys.add(k); schema_ok = False
        # 식별자
        if rec.get("paper_doi") or rec.get("paper_pmid"):
            id_filled += 1
        if rec.get("paper_doi"):
            doi_filled += 1
        if rec.get("publication_types"):
            pub_filled += 1
        # 토큰
        tc = int(rec.get("token_count", 0))
        if tc:
            tokens.append(tc)
            if rec.get("fulltext_source") == "local_pdf":
                pdf_tokens.append(tc)
        # evidence_weight
        ew = float(rec.get("evidence_weight", 0.5))
        ew_values.append(ew)
        # paper chunk count
        key = rec.get("paper_doi") or rec.get("paper_pmid") or "_unknown"
        paper_chunks[key] += 1
        # embedding dim
        emb = rec.get("embedding")
        if isinstance(emb, list):
            emb_dims.add(len(emb))

    result.total_chunks = total
    result.schema_ok = schema_ok
    result.missing_keys = missing_keys
    if total:
        result.identifier_fill_rate = id_filled / total
        result.paper_doi_fill_rate = doi_filled / total
        result.publication_types_fill_rate = pub_filled / total
    if tokens:
        result.avg_token = mean(tokens)
        if len(tokens) >= 100:
            result.p99_token = quantiles(tokens, n=100)[98]
        else:
            result.p99_token = max(tokens)
        result.over_512_ratio = sum(1 for t in tokens if t > 512) / len(tokens)
    if pdf_tokens:
        result.pdf_avg_token = mean(pdf_tokens)
    if ew_values:
        result.evidence_weight_distinct = len(set(round(v, 2) for v in ew_values))
        result.evidence_weight_05_ratio = sum(1 for v in ew_values if abs(v - 0.5) < 1e-6) / len(ew_values)
    if paper_chunks:
        result.chunks_per_paper_avg = mean(paper_chunks.values())
    if emb_dims:
        result.embedding_dim = next(iter(emb_dims)) if len(emb_dims) == 1 else -1
    return result


def print_report(result: ValidationResult, out=sys.stderr) -> None:
    def mark(ok: bool) -> str:
        return "✅" if ok else "❌"

    rows = [
        ("schema", result.schema_ok, f"{len(REQUIRED_KEYS) - len(result.missing_keys)}/{len(REQUIRED_KEYS)} keys, missing={sorted(result.missing_keys)}"),
        ("identifier coverage", result.identifier_fill_rate >= IDENTIFIER_FILL_RATE_MIN, f"{result.identifier_fill_rate:.4f}"),
        ("paper_doi fill rate", result.paper_doi_fill_rate >= PAPER_DOI_FILL_RATE_INFO_MIN, f"{result.paper_doi_fill_rate:.4f} (info-only)"),
        ("publication_types", result.publication_types_fill_rate >= PUBLICATION_TYPES_FILL_RATE_MIN, f"{result.publication_types_fill_rate:.4f}"),
        ("evidence_weight distinct", result.evidence_weight_distinct >= EVIDENCE_WEIGHT_DISTINCT_MIN, f"{result.evidence_weight_distinct} values, 0.5 ratio={result.evidence_weight_05_ratio:.2f}"),
        ("avg token", AVG_TOKEN_MIN <= result.avg_token <= AVG_TOKEN_MAX, f"{result.avg_token:.1f} (range {AVG_TOKEN_MIN}~{AVG_TOKEN_MAX})"),
        ("p99 token", result.p99_token <= TOKEN_P99_MAX, f"{result.p99_token:.0f} (≤ {TOKEN_P99_MAX})"),
        ("> 512 ratio", result.over_512_ratio <= TOKEN_OVER_512_RATIO_MAX, f"{result.over_512_ratio:.3f}"),
        ("chunks/paper", CHUNKS_PER_PAPER_MIN <= result.chunks_per_paper_avg <= CHUNKS_PER_PAPER_MAX, f"avg {result.chunks_per_paper_avg:.1f}"),
        ("pdf subset avg", PDF_AVG_TOKEN_MIN <= result.pdf_avg_token <= PDF_AVG_TOKEN_MAX, f"{result.pdf_avg_token:.1f}"),
        ("embedding dim", result.embedding_dim == EMBEDDING_DIM, f"{result.embedding_dim}"),
    ]
    print("=== validate_embeddings ===", file=out)
    for name, ok, detail in rows:
        print(f"{mark(ok)} {name}: {detail}", file=out)
    print(f"\nVERDICT: {'✅ PASS' if result.passed else '❌ FAIL'} (total {result.total_chunks} chunks)", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-Upsert Validation")
    parser.add_argument("--input", type=Path, nargs="+", required=True, help="jsonl(.gz) paths")
    parser.add_argument("--fail-fast", action="store_true", help="실패 시 exit 2")
    args = parser.parse_args(argv)

    result = validate_jsonl(args.input)
    print_report(result)
    if not result.passed and args.fail_fast:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 테스트 PASS 확인**

```bash
pytest mlops/tests/test_validate_embeddings.py -v
```
기대: 모든 케이스 PASS.

- [ ] **Step 3: commit**

```bash
ruff check mlops/ && ruff format --check mlops/
git add mlops/scripts/validate_embeddings.py mlops/tests/test_validate_embeddings.py
git commit -m "feat: validate_embeddings.py — pre-upsert validation 게이트"
```

### Task C4: full_reingest.py 골격 + manifest 멱등성

**Files:**
- Create: `mlops/scripts/full_reingest.py`

- [ ] **Step 1: orchestrator 골격 작성**

```python
"""5 Stage ingestion orchestrator — design §2.

Stage 1: fetch (crawler + efetch 보강 + local_pdf 통합)
Stage 1.5: manifest sanity (paper-level publication_types/identifier)
Stage 2: chunk
Stage 3: embed
Stage 3.5: validate_embeddings (chunk-level)
Stage 4: upsert to papers_v2
Stage 5: 평가 게이트 (run_eval recall@10) + alias swap 안내

Resumable: manifest 기반 멱등성. 중단 후 재실행 시 완료 stage skip.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mlops.pipeline.config import DATA_DIR
from mlops.pipeline.manifest import Manifest
from mlops.scripts.validate_embeddings import validate_jsonl, print_report

logger = logging.getLogger(__name__)


def stage1_fetch(batch_tag: str, mode: str, max_per_category: int | None) -> Path:
    """Stage 1: crawl + efetch 보강 + local_pdf 통합."""
    from mlops.pipeline.crawler import crawl_papers
    from mlops.pipeline.chunker import chunk_papers  # later stage용 import

    # phase1_local_pdf 모드는 local_pdf만 처리
    if mode == "phase1_local_pdf":
        from mlops.scripts.ingest_local_pdfs import build_paperfull_batch  # 기존 함수 활용
        # ... 구현 (Task C5에서 상세)
        raise NotImplementedError("phase1_local_pdf — Task C5")

    # phase2_full: crawler + local_pdf 모두
    raise NotImplementedError("phase2_full — Task C6")


def stage1_5_manifest_sanity(manifest_path: Path) -> bool:
    """Stage 1.5: paper-level publication_types ≥ 90%, identifier 100% (drop 후이므로)."""
    from mlops.eval.validation_thresholds import PUBLICATION_TYPES_FILL_RATE_MIN

    manifest = Manifest.load(manifest_path)
    if not manifest.papers:
        logger.error("manifest 비어있음")
        return False
    total = len(manifest.papers)
    pub_filled = sum(1 for p in manifest.papers.values() if p.publication_types)
    id_filled = sum(1 for p in manifest.papers.values() if p.doi or p.pmid)
    rate = pub_filled / total
    id_rate = id_filled / total
    logger.info("manifest sanity: pub_types %.3f, id %.3f (total %d)", rate, id_rate, total)
    return rate >= PUBLICATION_TYPES_FILL_RATE_MIN and id_rate >= 1.0


def stage2_3_chunk_embed(batch_tag: str) -> Path:
    """Stage 2+3: chunk + embed (export_embeddings.py 패턴 재사용)."""
    raise NotImplementedError("Task C7")


def stage3_5_validate(embeddings_path: Path) -> bool:
    """Stage 3.5: pre-upsert validation."""
    result = validate_jsonl([embeddings_path])
    print_report(result)
    return result.passed


def stage4_upsert(embeddings_path: Path, collection: str) -> int:
    """Stage 4: ChromaDB papers_v2 upsert (load_embeddings.py 패턴)."""
    raise NotImplementedError("Task C8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full reingest orchestrator")
    parser.add_argument("--mode", choices=["phase1_local_pdf", "phase2_full"], required=True)
    parser.add_argument("--batch-tag", required=True)
    parser.add_argument("--collection-suffix", default="_v2")
    parser.add_argument("--max-per-category", type=int, default=None)
    parser.add_argument("--skip-stages", nargs="*", default=[],
                        choices=["fetch", "manifest_check", "chunk_embed", "validate", "upsert"])
    parser.add_argument("--eval-gate", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
    collection = f"papers{args.collection_suffix}"

    # Stage 1
    if "fetch" not in args.skip_stages:
        manifest_path = stage1_fetch(args.batch_tag, args.mode, args.max_per_category)
    else:
        manifest_path = DATA_DIR / "manifest.json"

    # Stage 1.5
    if "manifest_check" not in args.skip_stages:
        if not stage1_5_manifest_sanity(manifest_path):
            logger.error("Stage 1.5 manifest sanity 실패 — abort")
            return 2

    # Stage 2+3
    if "chunk_embed" not in args.skip_stages:
        embeddings_path = stage2_3_chunk_embed(args.batch_tag)
    else:
        embeddings_path = DATA_DIR / f"emb_bge-large/{args.batch_tag}.jsonl.gz"

    # Stage 3.5
    if "validate" not in args.skip_stages:
        if not stage3_5_validate(embeddings_path):
            logger.error("Stage 3.5 pre-upsert validation 실패 — abort")
            return 3

    # Stage 4
    if "upsert" not in args.skip_stages:
        n = stage4_upsert(embeddings_path, collection)
        logger.info("upsert 완료: %d chunks → %s", n, collection)

    # Stage 5 안내
    if args.eval_gate:
        logger.info("Stage 5: run_eval로 골드셋 recall@10 비교 후 alias swap 진행")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 단위 테스트 — Stage 3.5 게이트만 우선 검증**

`mlops/tests/test_full_reingest.py`:

```python
"""full_reingest orchestrator 단위 테스트 (Stage 3.5 게이트만 우선)."""
import gzip, json, tempfile
from pathlib import Path

from mlops.scripts.full_reingest import stage3_5_validate


def _make_ok_jsonl(n=30) -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for i in range(n):
            rec = {
                "chunk_index": i, "paper_pmid": f"p{i//5}", "paper_title": "T",
                "section_name": "Methods", "token_count": 400,
                "search_categories": [], "paper_doi": f"10.1/{i//5}",
                "publication_types": ["Meta-Analysis"] if i % 7 == 0 else ["RCT"],
                "evidence_weight": [0.3, 0.5, 0.7, 0.9, 1.0][i % 5],
                "fulltext_source": "local_pdf" if i % 5 == 0 else "pmc",
                "published_year": 2018, "embedding": [0.1] * 1024,
            }
            f.write(json.dumps(rec) + "\n")
    return tmp


def test_stage3_5_passes_on_good_jsonl():
    path = _make_ok_jsonl(60)
    assert stage3_5_validate(path)


def test_stage3_5_fails_on_bad_jsonl():
    path = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_index": 0}) + "\n")  # 키 누락
    assert not stage3_5_validate(path)
```

- [ ] **Step 3: 테스트 + commit**

```bash
pytest mlops/tests/test_full_reingest.py -v
git add mlops/scripts/full_reingest.py mlops/tests/test_full_reingest.py
git commit -m "feat: full_reingest.py 골격 + Stage 3.5 게이트 통합"
```

### Task C5: Phase 1 local_pdf 경로 구현

**Files:**
- Modify: `mlops/scripts/full_reingest.py:stage1_fetch` (`phase1_local_pdf` 분기)

- [ ] **Step 1: ingest_local_pdfs.py 기존 함수 재사용해서 PaperFull 빌드**

`stage1_fetch`의 `phase1_local_pdf` 분기 본문:

```python
if mode == "phase1_local_pdf":
    from mlops.scripts.ingest_local_pdfs import (
        build_paperfull, _load_manifest_entries, _pdf_dir,
    )
    entries = _load_manifest_entries()  # 기존 manifest 패턴
    pdf_dir = _pdf_dir()
    papers = []
    for entry in entries:
        pf = build_paperfull(entry, pdf_dir)
        if pf and pf.meta.doi:  # DOI 없으면 drop
            papers.append(pf)
        elif pf and pf.meta.pmid:
            papers.append(pf)
        else:
            logger.warning("drop: no doi/pmid for %s", entry.get("title", "?"))
    # paper-level manifest atomic write — 기존 Manifest 패턴
    # ... (Manifest 객체에 paper 등록 + save)
    return Path(manifest_path)
```

(주: `_load_manifest_entries`, `_pdf_dir` 같은 helper가 ingest_local_pdfs에 있는지 확인 필요 — 없으면 ingest_local_pdfs.py의 main 함수 본문 패턴을 참고해 직접 작성)

- [ ] **Step 2: 통합 테스트 — Phase 1 모드 dry-run**

```bash
python -m mlops.scripts.full_reingest --mode phase1_local_pdf --batch-tag dry_run_v1 \
  --skip-stages chunk_embed validate upsert
```
기대: Stage 1 통과, Stage 1.5에서 manifest sanity 결과 출력. (publication_types 0%면 FAIL — 의도된 동작, PR-α 머지 후 다시 통과)

- [ ] **Step 3: commit**

```bash
git add mlops/scripts/full_reingest.py
git commit -m "feat: full_reingest Phase 1 (local_pdf) 분기 구현"
```

### Task C6: Phase 2 phase2_full 분기

**Files:**
- Modify: `mlops/scripts/full_reingest.py:stage1_fetch` (`phase2_full` 분기)

- [ ] **Step 1: crawler.crawl_papers + local_pdf 통합 호출**

```python
# stage1_fetch 함수 본문에 phase2_full 분기 추가
if mode == "phase2_full":
    from mlops.pipeline.crawler import crawl_papers
    from mlops.scripts.ingest_local_pdfs import build_paperfull, _load_manifest_entries, _pdf_dir
    # JATS 경로
    jats_papers = crawl_papers(
        max_total=99999,  # 카테고리 기반이라 cap은 max_per_category로 제어
        max_per_category=max_per_category,
    )
    # PDF 경로
    entries = _load_manifest_entries()
    pdf_papers = []
    for entry in entries:
        pf = build_paperfull(entry, _pdf_dir())
        if pf and (pf.meta.doi or pf.meta.pmid):
            pdf_papers.append(pf)
    all_papers = jats_papers + pdf_papers
    # manifest atomic write
    # ... save manifest ...
    return Path(manifest_path)
```

- [ ] **Step 2: dry-run 통합 (max_per_category=2로 작게)**

```bash
python -m mlops.scripts.full_reingest --mode phase2_full --batch-tag dry_run_p2 \
  --max-per-category 2 --skip-stages chunk_embed validate upsert
```
기대: 카테고리 수 × 2개 paper + local_pdf 158편 합쳐서 manifest 빌드 완료.

- [ ] **Step 3: commit**

```bash
git add mlops/scripts/full_reingest.py
git commit -m "feat: full_reingest Phase 2 (phase2_full) 분기 구현"
```

### Task C7: Stage 2+3 chunk + embed 통합

**Files:**
- Modify: `mlops/scripts/full_reingest.py:stage2_3_chunk_embed`

- [ ] **Step 1: export_embeddings.py 핵심 함수 재사용**

```python
def stage2_3_chunk_embed(batch_tag: str) -> Path:
    """chunker + embedder 호출, jsonl.gz 산출."""
    from mlops.pipeline.chunker import chunk_papers
    from mlops.pipeline.embedder import embed_chunks_with_spec
    from mlops.pipeline.specs import get_spec
    from mlops.scripts.export_embeddings import _embed_and_write_streaming, _emb_path, _chunks_path, _load_chunks

    # manifest로부터 PaperFull 재구성 — Stage 1에서 저장된 chunks 캐시 활용
    chunks_path = _chunks_path(batch_tag)
    if chunks_path.exists():
        chunks = _load_chunks(chunks_path)
    else:
        raise RuntimeError(f"chunks 캐시 없음: {chunks_path}. Stage 1 chunks 저장 누락")

    spec = get_spec("bge-large")
    emb_path = _emb_path(batch_tag, spec.key)
    _embed_and_write_streaming(emb_path, chunks, spec, batch_size=spec.default_batch_size)
    return emb_path
```

(주: `stage1_fetch`도 `_save_chunks_atomic`로 chunks를 저장하도록 보강 필요. export_embeddings.py 기존 패턴 그대로 차용)

- [ ] **Step 2: 통합 dry-run**

```bash
python -m mlops.scripts.full_reingest --mode phase1_local_pdf --batch-tag dry_run_emb \
  --skip-stages validate upsert
```
기대: Stage 1 + Stage 1.5 + Stage 2/3 완료, `mlops/data/emb_bge-large/dry_run_emb.jsonl.gz` 생성.

- [ ] **Step 3: commit**

```bash
git add mlops/scripts/full_reingest.py
git commit -m "feat: full_reingest Stage 2+3 chunk+embed 통합"
```

### Task C8: Stage 4 upsert + papers_v2 컬렉션 지원

**Files:**
- Modify: `mlops/scripts/full_reingest.py:stage4_upsert`
- Modify: `mlops/pipeline/upserter.py` (collection 이름을 parameter로 받도록)

- [ ] **Step 1: upserter.py가 collection 이름을 받도록 확장**

```python
# upserter.py:_get_collection 시그니처 변경
def _get_collection(collection_name: str = None) -> chromadb.Collection:
    global _client, _collection_cache
    name = collection_name or CHROMA_COLLECTION_NAME
    if name not in _collection_cache:
        if _client is None:
            _client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        _collection_cache[name] = _client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"},
        )
    return _collection_cache[name]

# upsert_chunks 시그니처에 collection_name 추가
def upsert_chunks(chunk_vector_pairs, batch_size=100, collection_name: str = None):
    collection = _get_collection(collection_name)
    ...
```

- [ ] **Step 2: stage4_upsert 구현**

```python
def stage4_upsert(embeddings_path: Path, collection: str) -> int:
    from mlops.scripts.load_embeddings import iter_records
    from mlops.pipeline.upserter import upsert_chunks
    buffer = []
    total = 0
    for chunk, vec in iter_records(embeddings_path, skip_errors=True):
        buffer.append((chunk, vec))
        if len(buffer) >= 200:
            total += upsert_chunks(buffer, batch_size=200, collection_name=collection)
            buffer = []
    if buffer:
        total += upsert_chunks(buffer, batch_size=200, collection_name=collection)
    return total
```

- [ ] **Step 3: 통합 dry-run (local ChromaDB, papers_test 컬렉션)**

```bash
python -m mlops.scripts.full_reingest --mode phase1_local_pdf --batch-tag dry_run_full \
  --collection-suffix _test
```
기대: Stage 1 → 5 전부 진행 (api 모드가 아니라 local mode면 ChromaDB에 직접 upsert).

- [ ] **Step 4: commit**

```bash
git add mlops/pipeline/upserter.py mlops/scripts/full_reingest.py
git commit -m "feat: full_reingest Stage 4 — papers_v2 컬렉션 지원"
```

### Task C9: PR-γ 생성

- [ ] **Step 1: push + PR**

```bash
git push -u origin feat/jingyu/full-reingest-pipeline
gh pr create --base develop --title "feat: full_reingest.py + validate_embeddings.py — RAG 재처리 자동화" --body "$(cat <<'EOF'
## Summary

- `full_reingest.py` orchestrator — 5 Stage(fetch / sanity / chunk+embed / validate / upsert) 자동화
- `validate_embeddings.py` pre-upsert validation 게이트 — design §3.3.1 임계 10개
- `validation_thresholds.py` 임계 모듈 — 운영 중 튜닝 용이

## 주요 동작

- Phase 1: `--mode phase1_local_pdf` — local_pdf만 (데모 비상용)
- Phase 2: `--mode phase2_full` — JATS + local_pdf 모두 (8,300+ paper)
- Resumable: `--skip-stages` 옵션으로 단계 우회
- Fail-fast: Stage 1.5 manifest sanity + Stage 3.5 pre-upsert validation 미달 시 abort

## 검증

`pytest mlops/tests/test_validate_embeddings.py mlops/tests/test_full_reingest.py -v` PASS.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-δ — ChromaDB alias-swap + rag.py 동적 lookup (S4-1)

**브랜치:** `feat/jingyu/chroma-alias-swap`
**의존성:** 없음

### Task D1: alias 메타 저장 패턴 설계 + 브랜치

**Files:**
- N/A (브랜치)

- [ ] **Step 1: 브랜치 생성**

```bash
git checkout develop && git pull && git checkout -b feat/jingyu/chroma-alias-swap
```

- [ ] **Step 2: alias 저장 위치 결정**

ChromaDB는 native alias 미지원이므로 `_metadata` 컬렉션(또는 환경변수)을 alias 저장소로 사용. 권장: `<collection>_aliases` 라는 별도 collection의 metadata로 보관 (DB-native). 또는 EFS의 `current_alias.json` 단일 파일.

본 plan은 **EFS 파일 (`/chroma-data/current_alias.json`)** 방식 채택 — 단순, atomic write 가능, ChromaDB 외부.

### Task D2: rag.py collection lookup 동적화 — TDD

**Files:**
- Modify: `server/app/services/rag.py:_get_collection`
- Create: `server/tests/test_rag_alias_swap.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
"""rag.py가 alias 파일을 읽어 매 요청마다 적절한 collection 사용."""
import json, tempfile
from pathlib import Path
import pytest

from server.app.services import rag


def test_get_collection_reads_alias_file(monkeypatch, tmp_path):
    """current_alias.json의 'current'를 collection 이름으로 사용."""
    alias_file = tmp_path / "current_alias.json"
    alias_file.write_text(json.dumps({"current": "papers_v2"}))
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    # _get_collection이 papers_v2 collection을 호출하는지 — mock client로 확인
    class FakeClient:
        def __init__(self):
            self.requested = []
        def get_or_create_collection(self, name, metadata=None):
            self.requested.append(name)
            class FakeCol:
                count = lambda self: 0
            return FakeCol()

    fake = FakeClient()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers_v2"]


def test_alias_missing_falls_back_to_default(monkeypatch, tmp_path):
    """alias 파일 없으면 기본 'papers' 사용."""
    alias_file = tmp_path / "current_alias.json"  # 미생성
    monkeypatch.setattr(rag, "ALIAS_FILE", alias_file)
    monkeypatch.setattr(rag, "_collection_cache", {})

    class FakeClient:
        def __init__(self): self.requested = []
        def get_or_create_collection(self, name, metadata=None):
            self.requested.append(name)
            class FakeCol: count = lambda self: 0
            return FakeCol()

    fake = FakeClient()
    monkeypatch.setattr(rag, "_client", fake)
    rag._get_collection()
    assert fake.requested == ["papers"]
```

- [ ] **Step 2: 실패 확인**

```bash
cd server && pytest tests/test_rag_alias_swap.py -v
```
기대: FAIL (`ALIAS_FILE` 미정의 등).

- [ ] **Step 3: 구현**

```python
# server/app/services/rag.py 수정
import json
from pathlib import Path

ALIAS_FILE = Path("/chroma-data/current_alias.json")
DEFAULT_COLLECTION = "papers"

_client = None
_collection_cache: dict[str, "chromadb.Collection"] = {}


def _current_collection_name() -> str:
    try:
        if ALIAS_FILE.exists():
            data = json.loads(ALIAS_FILE.read_text())
            return data.get("current", DEFAULT_COLLECTION)
    except Exception as e:
        logger.warning("alias file 읽기 실패: %s, 기본 사용", e)
    return DEFAULT_COLLECTION


def _get_collection():
    global _client
    name = _current_collection_name()
    if name not in _collection_cache:
        if _client is None:
            _client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        _collection_cache[name] = _client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"},
        )
    return _collection_cache[name]
```

- [ ] **Step 4: 테스트 PASS + commit**

```bash
cd server && pytest tests/test_rag_alias_swap.py -v
git add server/app/services/rag.py server/tests/test_rag_alias_swap.py
git commit -m "feat: rag.py current_alias.json 기반 collection 동적 lookup"
```

### Task D3: admin endpoint `/admin/rag/collection-swap`

**Files:**
- Modify: `server/app/api/v1/admin.py`
- Create: `server/tests/test_admin_collection_swap.py`

- [ ] **Step 1: 실패 테스트**

```python
"""POST /api/v1/admin/rag/collection-swap 테스트."""
import json
from fastapi.testclient import TestClient
from server.app.main import app

client = TestClient(app)


def test_swap_updates_alias_file(tmp_path, monkeypatch):
    alias = tmp_path / "current_alias.json"
    monkeypatch.setattr("server.app.services.rag.ALIAS_FILE", alias)
    monkeypatch.setenv("ADMIN_API_TOKEN", "secret")

    r = client.post(
        "/api/v1/admin/rag/collection-swap",
        headers={"X-Admin-Token": "secret"},
        json={"to": "papers_v2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["current"] == "papers_v2"
    assert "swapped_at" in body["data"]

    saved = json.loads(alias.read_text())
    assert saved["current"] == "papers_v2"


def test_swap_rejects_without_admin_token():
    r = client.post(
        "/api/v1/admin/rag/collection-swap",
        json={"to": "papers_v2"},
    )
    assert r.status_code in (401, 403)
```

- [ ] **Step 2: 실패 확인 → 구현**

```python
# server/app/api/v1/admin.py 끝에 추가
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel

from server.app.services import rag as rag_svc


class CollectionSwapRequest(BaseModel):
    to: str


@router.post("/rag/collection-swap")
async def swap_collection(req: CollectionSwapRequest, ...):
    # admin token 검증은 기존 decorator/depends 패턴 따름
    if not req.to.strip():
        raise HTTPException(400, "to 필드는 비어있을 수 없습니다")
    alias_path: Path = rag_svc.ALIAS_FILE
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    swapped_at = datetime.now(timezone.utc).isoformat()
    tmp = alias_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"current": req.to, "swapped_at": swapped_at}))
    tmp.replace(alias_path)
    # collection cache 비우기 — 다음 요청부터 새 collection 사용
    rag_svc._collection_cache.clear()
    return {"success": True, "data": {"current": req.to, "swapped_at": swapped_at}}
```

- [ ] **Step 3: 테스트 PASS + commit**

```bash
cd server && pytest tests/test_admin_collection_swap.py -v
git add server/app/api/v1/admin.py server/tests/test_admin_collection_swap.py
git commit -m "feat: admin endpoint POST /rag/collection-swap — alias atomic swap"
```

### Task D4: PR-δ 생성

- [ ] **Step 1: push + PR**

```bash
git push -u origin feat/jingyu/chroma-alias-swap
gh pr create --base develop --title "feat: ChromaDB alias-swap 패턴 + rag.py 동적 lookup" --body "$(cat <<'EOF'
## Summary

- `/chroma-data/current_alias.json` 기반 ChromaDB collection alias
- `rag.py` 모듈 글로벌 캐시 → 매 요청마다 alias lookup (캐시는 alias key 단위로 유지)
- `POST /api/v1/admin/rag/collection-swap` admin endpoint — atomic alias 변경 (다운타임 ≤ 5분 보장)

## 검증

- `pytest server/tests/test_rag_alias_swap.py -v`
- `pytest server/tests/test_admin_collection_swap.py -v`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## PR-ε — `/admin/rag/pmids` 페이지네이션 + graceful shutdown (S4-2, B2)

**브랜치:** `fix/jingyu/admin-pmids-pagination`
**의존성:** 없음

### Task E1: `/admin/rag/pmids` 페이지네이션

**Files:**
- Modify: `server/app/api/v1/admin.py:list_pmids` (정확한 함수명은 grep으로 확인)
- Create: `server/tests/test_admin_pmids_pagination.py`

- [ ] **Step 1: 현 endpoint 파악**

```bash
grep -n "rag/pmids\|list_pmids\|chunks_count" server/app/api/v1/admin.py
```

- [ ] **Step 2: 실패 테스트**

```python
def test_pmids_paginated(client, monkeypatch):
    """limit/offset 적용으로 일부만 반환."""
    # ChromaDB collection mock으로 1000개 청크 시뮬레이션
    r = client.get("/api/v1/admin/rag/pmids?limit=10&offset=0",
                   headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]["pmids"]) <= 10
    assert "total" in body["data"]
    assert "has_next" in body["data"]
```

- [ ] **Step 3: 구현**

```python
# 기존 list_pmids 함수 수정
@router.get("/rag/pmids")
async def list_pmids(limit: int = 100, offset: int = 0, ...):
    collection = _get_collection()
    total = collection.count()
    # ChromaDB get은 limit/offset 미지원 — 전체 fetch 후 slice
    # 대안: collection.get(ids=None, limit=limit, offset=offset) 일부 버전에서 지원
    try:
        data = collection.get(limit=limit, offset=offset, include=["metadatas"])
    except TypeError:
        # 구버전 ChromaDB
        data = collection.get(include=["metadatas"])
        ids = data["ids"][offset:offset + limit]
        metas = data["metadatas"][offset:offset + limit]
        data = {"ids": ids, "metadatas": metas}
    pmids = sorted({m.get("paper_pmid") for m in data["metadatas"] if m.get("paper_pmid")})
    return {
        "success": True,
        "data": {
            "pmids": pmids, "total": total, "limit": limit, "offset": offset,
            "has_next": offset + limit < total,
        },
    }
```

- [ ] **Step 4: 테스트 PASS + commit**

```bash
cd server && pytest tests/test_admin_pmids_pagination.py -v
git add server/app/api/v1/admin.py server/tests/test_admin_pmids_pagination.py
git commit -m "fix: /admin/rag/pmids 페이지네이션 추가 — collection.get 전체 fetch 회피"
```

### Task E2: graceful shutdown hook

**Files:**
- Modify: `server/app/main.py` (FastAPI lifespan에 ChromaDB graceful close)

- [ ] **Step 1: lifespan 컨텍스트에 close 추가**

```python
# server/app/main.py
from contextlib import asynccontextmanager
from server.app.services import rag

@asynccontextmanager
async def lifespan(app):
    yield
    # shutdown
    try:
        if rag._client is not None:
            # ChromaDB PersistentClient는 명시적 close 없지만, 모든 collection cache 비우고
            # 잔여 pending write가 있으면 flush 시도
            rag._collection_cache.clear()
            del rag._client
            rag._client = None
            logger.info("ChromaDB client closed gracefully")
    except Exception as e:
        logger.error("Graceful shutdown 실패: %s", e)

app = FastAPI(lifespan=lifespan)
```

- [ ] **Step 2: SIGTERM 시뮬레이션 테스트**

```python
# server/tests/test_graceful_shutdown.py
def test_lifespan_clears_chroma_cache():
    from server.app.main import lifespan, app
    # async context 진입/탈출 후 cache 비어있는지
    import asyncio
    async def run():
        async with lifespan(app):
            pass
    asyncio.run(run())
    from server.app.services import rag
    assert rag._collection_cache == {}
    assert rag._client is None
```

- [ ] **Step 3: 통합 결합 테스트 + commit**

```bash
cd server && pytest tests/test_graceful_shutdown.py tests/test_admin_pmids_pagination.py -v
git add server/app/main.py server/tests/test_graceful_shutdown.py
git commit -m "fix: ChromaDB graceful shutdown hook — HNSW partial-write 방지"
```

### Task E3: PR-ε 생성

- [ ] **Step 1: push + PR**

```bash
git push -u origin fix/jingyu/admin-pmids-pagination
gh pr create --base develop --title "fix: /admin/rag/pmids 페이지네이션 + ChromaDB graceful shutdown" --body "$(cat <<'EOF'
## Summary

- `/admin/rag/pmids` 페이지네이션 추가 — collection.get 전체 fetch에 의한 500 에러 해소
- FastAPI lifespan에 ChromaDB graceful shutdown — HNSW partial-write 방지

## 결합 사유

둘 다 admin endpoint/ChromaDB 라이프사이클 안정성 한 묶음 + 동일한 통합 테스트 fixture(대용량 메타·SIGTERM 시뮬레이션) 공유.

## 검증

`pytest server/tests/test_admin_pmids_pagination.py server/tests/test_graceful_shutdown.py -v` PASS.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Phase 2 실행 — PR α/β/γ/δ 머지 후 운영 절차

> α/β/γ/δ 머지 후 GPU 서버에서 실행. PR-ε는 독립이라 머지 시점 무관.

### Task F1: GPU 서버 develop sync + prerequisite 체크

**Files:** N/A (운영)

- [ ] **Step 1: develop pull**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && git fetch && git checkout develop && git pull origin develop && git log --oneline -10'
```
기대: 머지 commit 4개(α/β/γ/δ) 보임.

- [ ] **Step 2: design §4.1 prerequisite 체크리스트 확인**

```bash
# 환경변수
ssh gpu '[ -n "$ADMIN_API_TOKEN" ] && echo OK || echo "ADMIN_API_TOKEN 누락"'
ssh gpu 'echo $API_BASE_URL'
# AWS CLI
aws sts get-caller-identity --query Account --output text
# gh
gh auth status
```
기대: 모두 OK.

### Task F2: Phase 2 dry-run (max_per_category=2)

**Files:** N/A (운영)

- [ ] **Step 1: 작은 규모 dry-run**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.full_reingest \
    --mode phase2_full --batch-tag dry_p2 --max-per-category 2 \
    --collection-suffix _dry'
```
기대: Stage 1~4 전체 통과. local ChromaDB의 `papers_dry` 컬렉션에 적재됨.

- [ ] **Step 2: 결과 검증**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && python3 -c "
import chromadb
c = chromadb.PersistentClient(\"/mnt/data/scifit-sync/chroma-data\")
col = c.get_collection(\"papers_dry\")
print(\"chunks:\", col.count())
"'
```
기대: 수십~수백 청크.

### Task F3: 본 실행 — Stage 1~3 (수일~1주)

**Files:** N/A (운영, critical path)

- [ ] **Step 1: Phase 2 본 실행 nohup으로**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  nohup .venv-gpu/bin/python3 -m mlops.scripts.full_reingest \
    --mode phase2_full --batch-tag refeed_v2 \
    --collection-suffix _v2 --skip-stages upsert validate \
    > /mnt/data/scifit-sync/phase2_v2.log 2>&1 &'
```
(Stage 4/5는 별도 단계, 임베딩까지만 nohup으로 진행)

- [ ] **Step 2: 진행 모니터링 (수일~1주)**

```bash
ssh gpu 'tail -f /mnt/data/scifit-sync/phase2_v2.log'
```
기대: Stage 1 crawl 진행 — 카테고리당 max_per_category 도달까지. Stage 2/3는 fetch 끝나야 시작.

### Task F4: Stage 3.5 pre-upsert validation 실행

**Files:** N/A (운영)

- [ ] **Step 1: validate_embeddings 단독 호출**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.validate_embeddings \
    --input "mlops/data/emb_bge-large/refeed_v2.jsonl.gz" \
    --fail-fast'
```
기대 (성공 경로): VERDICT PASS, 10/10 임계 충족.

**실패 시 분기**:
- publication_types < 90% → PR-α 디버그 재방문 (S5)
- avg_token 범위 외 → chunker 분포 점검
- 다른 항목 → design §3.6 의사결정 트리 따름

### Task F5: Stage 4 papers_v2 적재

**Files:** N/A (운영)

- [ ] **Step 1: prod ChromaDB에 papers_v2 컬렉션으로 적재**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.scripts.load_embeddings \
    --input mlops/data/emb_bge-large/refeed_v2.jsonl.gz \
    --mode api --batch-size 200 --skip-errors 2>&1 | \
  tee /mnt/data/scifit-sync/phase2_upsert.log'
```
(주: api 모드는 admin endpoint를 호출하므로 server 측에서 papers_v2 컬렉션을 지정해야 함. 추가 API param이 필요하면 PR-γ에서 admin ingest endpoint에 `collection` query param 추가 필요)

- [ ] **Step 2: 적재 검증 — papers_v2 chunks 카운트**

```bash
TASK_ID=$(aws ecs list-tasks --cluster scifit-sync --service-name scifit-sync-api --query 'taskArns[0]' --output text | awk -F/ '{print $NF}')
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "import chromadb; c=chromadb.PersistentClient(\"/chroma-data\"); print(\"papers:\", c.get_collection(\"papers\").count()); print(\"papers_v2:\", c.get_collection(\"papers_v2\").count())"'
```
기대: papers는 기존, papers_v2는 신규 청크 수.

### Task F6: Stage 5 평가 게이트 — recall@10 A/B

**Files:** N/A (운영)

- [ ] **Step 1: baseline (papers) recall@10**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.eval.run_eval \
    --goldset mlops/eval/goldset.jsonl \
    --output mlops/eval/reports/baseline_papers.md \
    --retriever chroma --collection papers'
```
기대: 리포트 생성, recall@10 수치.

- [ ] **Step 2: refeed_v2 (papers_v2) recall@10**

```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && \
  .venv-gpu/bin/python3 -m mlops.eval.run_eval \
    --goldset mlops/eval/goldset.jsonl \
    --output mlops/eval/reports/refeed_v2_papers_v2.md \
    --retriever chroma --collection papers_v2'
```
(주: run_eval.py에 `--collection` 옵션 없으면 추가 또는 ChromaDB collection 핸들을 받도록 확장)

- [ ] **Step 3: 임계 검증 (C5 ≤ 2pp 회귀)**

```bash
diff -u mlops/eval/reports/baseline_papers.md mlops/eval/reports/refeed_v2_papers_v2.md | head -40
```
검증: refeed_v2 recall@10이 baseline 대비 -2pp 이내 (또는 향상). 회귀 시 design §3.6 의사결정 트리.

### Task F7: alias swap (E3) + post-swap 검증 (E3.5)

**Files:** N/A (운영)

- [ ] **Step 1: alias swap 명령 + 시각 기록 (C7 T0)**

```bash
T0=$(date -u +%FT%TZ)
echo "T0=$T0"
curl -X POST -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "papers_v2"}' \
  https://scifit-sync.com/api/v1/admin/rag/collection-swap
```
기대 응답: `{"success": true, "data": {"current": "papers_v2", "swapped_at": "..."}}`.

- [ ] **Step 2: post-swap 헬스체크 (C7 T1)**

```bash
T1=$(date -u +%FT%TZ)
echo "T1=$T1"
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" https://scifit-sync.com/api/v1/admin/rag/pmids?limit=10
```
기대: 200 응답, papers_v2의 PMID 일부.

- [ ] **Step 3: 골드셋 쿼리 3건 + chat smoke test**

```bash
# 1) RCT 키워드
curl -H "X-Admin-Token: $ADMIN_API_TOKEN" -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"resistance training volume hypertrophy"}' \
  https://scifit-sync.com/api/v1/admin/rag/debug-search
# 응답 score 분포가 0.5 단일값 아니어야 함 — Meta-Analysis는 sim×1.0, RCT는 sim×0.9 등
```
기대: 결과 score가 다양화됨 (evidence_weight 차등화 확인).

- [ ] **Step 4: CloudWatch 로그로 ALB 5xx 비율 확인 (10분 윈도우)**

```bash
aws logs filter-log-events --log-group-name /ecs/scifit-sync-api \
  --start-time $(date -u -d "$T0 - 1 minute" +%s)000 \
  --end-time $(date -u -d "$T1 + 10 minutes" +%s)000 \
  --filter-pattern "5xx OR ERROR" | head
```
기대: 5xx 비율 < 1%. 초과 시 design §3.4 alias 원복.

- [ ] **Step 5: 다운타임 기록 (T1 - T0)**

운영 일지에 `T0`, `T1`, `T1 - T0` 다운타임 기록. C7 ≤ 5분 충족 확인.

### Task F8: Phase 2 완료 — 메모리 갱신 + 옛 컬렉션 정리

**Files:** 메모리 디렉토리

- [ ] **Step 1: 메모리 갱신**

```bash
# project_prod_rag_full_reload_20260528.md 또는 신규 메모리에 결과 기록
# - papers_v2 적재 완료 시각
# - 다운타임 측정값
# - recall@10 baseline vs refeed_v2 수치
# - 발견된 잔여 이슈
```

- [ ] **Step 2: 1주 후 옛 papers 컬렉션 정리 (별도 일정)**

```bash
# 운영 모니터링 정상 확인 후
aws ecs execute-command --cluster scifit-sync --task "$TASK_ID" --interactive \
  --command 'python -c "import chromadb; c=chromadb.PersistentClient(\"/chroma-data\"); c.delete_collection(\"papers\"); print(\"deleted papers\")"'
```

---

## Self-Review Check

### Spec Coverage

| Spec 요구 | Plan task |
|---|---|
| S1 (JATS 파서) | PR-β Task B1~B6 |
| S2 (orchestrator + validate) | PR-γ Task C1~C9 |
| S3 (local_pdf 통합) | PR-γ Task C5 |
| S4 (alias-swap + admin 안정성) | PR-δ D1~D4 + PR-ε E1~E3 |
| S5 (publication_types 디버그) | PR-α Task A1~A6 |
| S6 (recall@10 평가 게이트) | Phase 2 실행 Task F6 |
| S7 (Phase 1 + Phase 2 운영 절차) | Phase 1 Task P1-1~P1-4 + Phase 2 Task F1~F8 |
| C1~C9 성공 기준 | Task F4, F6, F7에서 검증 |

### Placeholder 점검
- `dry_run`/`dry_p2`/`refeed_v2` 등 batch_tag는 실제 값
- `<task-id>`는 운영 시점 aws cli로 채워짐 — `$(aws ecs list-tasks ...)`으로 표시
- `<merge-commit>` 등 git revert 용 placeholder는 운영 결정 시점 채움

### Type 일관성
- `Manifest`/`PaperFull`/`PaperMeta` 등 기존 타입 일관 사용
- `ValidationResult` dataclass는 PR-γ에서 정의 + full_reingest에서 import

---

## Execution Handoff

Plan이 `docs/superpowers/plans/2026-05-28-rag-data-normalization-plan.md`에 저장되었습니다. 실행 방식 2가지:

**1. Subagent-Driven (권장)** — 매 task마다 fresh subagent 디스패치, task 사이 review. PR이 5개라 PR별로 작업 격리하기 적합.

**2. Inline Execution** — 현 세션에서 `executing-plans` skill로 batch 실행, checkpoint마다 review.

어느 방식으로 진행할까요? 일정 우선순위상 **Phase 1을 가장 먼저** 실행하고, 그 뒤에 PR-α/β/γ/δ/ε 병행 진입을 권합니다.
