# 핸드오프: 로컬 PDF ingest + 골드셋 갭 보강

> 작성일: 2026-05-26
> 작업자: jingyu (이어서 진행)
> 브랜치: `feat/jingyu/local-pdf-ingest`
> 관련 PR: https://github.com/SciFit-Sync/scifit-sync/pull/149

## 1. 진행 상황 요약

### 출발점
- 골드셋 평가에서 OpenAlex/PMC/EuropePMC 체인이 못 가져온 RT 핵심 paper들을 사용자가 직접 PDF로 다운로드해 보강하기로 결정.
- 사용자가 `data/goldset_paper/` 폴더에 PDF 약 330편 (메인 317 + uncertain 13) 배치.

### 본 브랜치에서 완료된 일
1. **`mlops/scripts/ingest_local_pdfs.py` 신규 작성** — 로컬 PDF → chunk/embed/upsert 파이프라인.
   - `parse_pdf`: pypdf로 단일 "Full Text" 섹션 추출 (`curated.fetch_pdf_sections` 패턴 재사용).
   - `enrich_metadata`: manifest 명시값 > PMID efetch > DOI OpenAlex 우선순위 보강.
   - `build_paperfull`: PaperFull 구성 (DOI 또는 PMID 중 하나 필수).
   - dedup 3-레이어:
     - manifest 내 DOI 중복 → skip
     - corpus 기존 DOI (`Manifest.is_indexed` ∪ server `/admin/rag/dois`) → skip
     - `--no-skip-existing` 으로 강제 재임베딩 가능
   - 보안: `_safe_pdf_path`로 path traversal / 절대 경로 / symlink-out 차단.
   - PMID-only in-batch dedup, filename in-batch dedup, manifest dict 타입 검증.

2. **`mlops/tests/test_ingest_local_pdfs.py`** — 14 tests pass.
   - build_paperfull 분기 / manifest override / PMID/DOI 우선순위 / dedup 3-레이어 / path traversal / PMID-only dedup / non-dict entry / duplicate filename / dry-run.

3. **`mlops/scripts/diagnose_doi_recall_gap.py`** — 평가 매칭 키 불일치 진단 도구 (사전 작업).
   - 평가(`run_eval.py`)는 PMID-only 매칭인데 corpus 적재는 DOI-first → mismatch 진단.

### 검증
- `pytest mlops/tests/` — 459/459 pass
- `ruff check` + `ruff format --check mlops/` — clean
- 실제 데이터: 317개 PDF 파싱 100% 성공, 평균 14,667 토큰
- Codex 리뷰 (block → critical 2건 수정 후 OK):
  - ✅ Path traversal 차단
  - ✅ PMID-only in-batch dedup
  - ⏳ corpus PMID set 검사용 server endpoint(`/admin/rag/pmids`) — **별도 PR로 위임**
  - ⏳ `efetch_pubmed_batch` 반환 schema contract test — **별도 PR로 위임**

## 2. 데이터 분석 결과 (이어서 진행할 때 참고)

### PDF 파싱 (317 메인 + 13 uncertain)
- 100% 파싱 성공
- file hash 중복 94편 (메인) → unique 223편
- uncertain 13편은 모두 RT 핵심 (Schoenfeld/Helms/Grgic/Ralston 등)

### 도메인 무관 paper 제외 — 20개 이동 완료
`data/goldset_paper/_discarded/`로 이동 (rm 아닌 mv, 복구 가능).
- 명백 무관 10편 + 약한 관련 6편 + hash sibling 4편 = 20개
- 메인 폴더 남은 PDF: 297개

### DOI 자동 보강 (A+C 알고리즘)
| 메서드 | 결과 |
|---|---|
| A. 파일명 정규식 (sci-hub `@` 패턴) | 4편 |
| C. OpenAlex confident (≥0.5) | 39편 |
| **자동 manifest 등록 가능** | **43편 (31.6%)** |
| C. review 필요 (0.3~0.5) | 38편 |
| 실패 (low_overlap / no_results) | 55편 |

### 산출물 위치 (Windows 접근)
`C:\Users\DOCTOR\Desktop\coding\college_4-1\capstone\data\`
- `dois_to_check.tsv` — 직접 확인할 93편 (review + fail)
- `doi_recovery_manifest_draft.json` — 자동 회수 43편 manifest 초안
- `doi_recovery_full_report.tsv` — 전체 136편 결과 (cand title + OpenAlex match)
- `pdf_topic_report.tsv` — unique 223편 토큰/DOI/kw_density

### 산출물 위치 (프로젝트 안)
- `mlops/eval/candidates.cleaned.jsonl` — 102 question에서 corpus 미보유 PMID 제거. **88 question이 0개로 비어버림** — corpus가 retrieval candidates와 거의 안 겹친다는 신호. **PDF ingest 후 retrieval 재실행이 선행되어야 라벨링 의미 있음** (지금 상태로 라벨링 ❌).
- `mlops/eval/goldset_seed.cleaned.jsonl` — `expected_pmids=[]`라 cleanup 영향 0건. 라벨링 진행 전 상태.

## 3. 다음 단계 (다른 컴퓨터에서 이어서)

### 우선순위 1: manifest.json 작성 (사용자 직접 작업)
1. `data/doi_recovery_manifest_draft.json` 의 43편 entry는 자동 회수 — `search_categories` 채우면 즉시 사용 가능.
2. `data/dois_to_check.tsv` 의 93편은 사용자 검토:
   - **Group A** (review 38편): cand title vs OpenAlex match만 보고 OK/NG 결정. 다수가 명백 동일 paper (algo 단방향 overlap 한계).
   - **Group B** (fail low_overlap 43편): 일부는 실제 동일 paper (예: `jssm-*`, `msse-56-1893`, `williams2021`, `41598_2026_Article_40612` 등). 일부는 잘못된 매칭(`helms2016 (1)`, `cochrane2015`, `harries2015` 등).
   - **Group C** (fail no_results 6편): 수동 PubMed/OpenAlex 검색 필요.
   - **Group D** (uncertain 6편): schoenfeld 시리즈 중복. file hash dedup으로 자동 처리됨.

### 우선순위 2: PDF ingest 실행 (GPU 서버 권장)
```bash
# manifest.json 완성 후 GPU 서버에서
ssh gpu  # cscloud.gpu3.hufs.ac.kr:30007
cd ~/scifit-sync
git pull origin feat/namgw/local-pdf-ingest

# 작업 PDF를 GPU 서버로 전송 (scp or rsync)
# 그 후:
python -m mlops.scripts.ingest_local_pdfs \
    --pdf-dir mlops/data/local_pdfs/ \
    --manifest mlops/data/local_pdfs/manifest.json \
    --dry-run                              # 먼저 dry-run 검증
python -m mlops.scripts.ingest_local_pdfs \
    --pdf-dir mlops/data/local_pdfs/ \
    --manifest mlops/data/local_pdfs/manifest.json
```

### 우선순위 3: candidates 재생성 + 라벨링
PDF ingest 완료 후 corpus 변경됨 → retrieval candidates 다시 만들기:
```bash
# build_candidates 스크립트 또는 build_goldset.py 재실행
# (현재 build_candidates 스크립트는 미작성 — 별도 PR 필요할 수도)
python -m mlops.scripts.build_goldset --seed mlops/eval/goldset_seed.jsonl ...

# 라벨링
python -m mlops.scripts.label_cli \
    --candidates mlops/eval/candidates.jsonl \
    --output mlops/eval/labels.jsonl
```

### 우선순위 4: 평가 매칭 키 확장 (별도 PR)
현재 `mlops/eval/run_eval.py`는 PMID-only 매칭. corpus는 DOI primary라 PMID 빈 paper는 평가에서 영구 누락. **PMID ∪ DOI 매칭으로 확장** 권장.

```python
# run_eval.py:43 GoldSetItem에 expected_dois 추가
# run_eval.py:88 recall_at_k가 PMID 또는 DOI 매칭이면 hit
```

`diagnose_doi_recall_gap.py`로 회복 폭 사전 측정 가능.

### 우선순위 5: 후속 PR (Codex 권고)
1. **server `/admin/rag/pmids` 엔드포인트** — corpus PMID set 조회. 현재는 in-batch PMID dedup만 가능.
2. **`efetch_pubmed_batch` 반환 schema contract test** — `ingest_curated_pmids`와 `ingest_local_pdfs`의 coupling 명시.

## 4. 프로덕션 upsert 완료 (2026-05-26)

### local_pdf_ingest
- **184개 논문** → **15,361 chunks** → bge-large 1024차원
- manifest: `mlops/data/local_pdfs/manifest.json` (CrossRef DOI 검증 완료)
- 임베딩: `mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz` (139MB)
- 프로덕션 upsert: `load_embeddings.py --mode api` → 200 OK, 184 DOIs 확인
- `load_embeddings.py` 버그 수정: `paper_doi` 등 5개 필드 누락 → `9f38bff`에서 수정

### 미upsert 대상 (별도 진행 필요)
| 파일 | chunks | DOIs | 비고 |
|------|--------|------|------|
| embeddings_3k_batch1-11 | 1,130,165 | 4,305 | 레거시 코퍼스 |
| 3k_20260522_060614 | 476,547 | 1,812 | curated batch A |
| 3k_20260522_152209 | 476,932 | 1,704 | curated batch B |
| **합계** | **2,083,644** | **7,821** | 겹침 36 DOIs |

upsert 명령:
```bash
cd /mnt/data/scifit-sync/scifit-sync
.venv-gpu/bin/python3 -m mlops.scripts.load_embeddings \
    --input <FILE> --mode api --batch-size 200 --skip-errors
```

## 5. GPU 서버 라벨링 산출물 확인 필요

WSL에서 `ssh gpu`가 BatchMode에서 실패 (passphrase 또는 키 미등록). 다른 컴퓨터에서 GPU 서버 직접 접속해 라벨링 산출물 위치 확인 부탁:
```bash
ssh gpu 'find ~ -name "labels.jsonl" 2>/dev/null; ls ~/scifit-sync/mlops/eval/'
```
- 있으면 → `mlops/eval/labels.jsonl`로 가져와서 goldset.jsonl과 merge
- 없으면 → 위 우선순위 3대로 라벨링 새로 진행

## 5. 알려진 제약 / 주의사항

- `ingest_local_pdfs.py`의 PMID-only dedup은 **in-batch만**: 사용자 manifest에 같은 PMID 두 번 있는 케이스만 잡음. corpus에 이미 PMID로 적재된 paper와의 중복은 server endpoint 추가 후 가능. 본 PR에서는 위 codex 권고와 함께 별도 작업.
- `_make_doc_id` (upserter.py:38)가 DOI 우선, 없으면 PMID fallback이라 PMID-only re-ingest가 `_make_doc_id`로 같은 id 생성하므로 ChromaDB upsert에서 덮어쓰긴 함 — 즉 데이터 손상은 없음, GPU 시간 낭비만.
- candidates.cleaned.jsonl을 그대로 라벨링하면 14 question만 가능. **PDF ingest → candidates 재생성**이 정상 흐름.
