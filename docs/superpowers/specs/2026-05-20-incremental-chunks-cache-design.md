# Incremental Chunks Cache 설계 (2026-05-20)

## 1. 배경과 목적

`mlops/scripts/export_embeddings.py`의 `--reuse-chunks` 옵션은 현재 **binary** 동작을 한다.

- 캐시 파일이 있으면 → 통째로 로드 (개수 검증 없음)
- 캐시 파일이 없으면 → 통째로 재크롤링 (수 시간 + OpenAlex daily quota 소모)

2026-05-20 GPU 서버에서 3000편 ingest(500 × 11배치)를 돌린 결과, 4번째 배치까지는 OpenAlex 정상, 5번째 배치에서 `429 Too Many Requests` 발생 후 9번째 배치까지 OpenAlex 0건 응답이 누적됐다. 원인은 OpenAlex polite pool의 **하루 search 1000 calls** 한도 초과로 추정되며, 한도는 `midnight UTC` 기준 리셋된다.

이 설계의 목적은 다음을 달성하는 것이다.

1. **부족분만 채워서 OpenAlex search 호출 최소화** — 이미 캐시에 있는 paper는 다시 search하지 않는다.
2. **임베딩 A/B 테스트 워크로드 단순화** — 첫 run에서 충분한 chunks 캐시를 만들면 이후 모델 비교는 OpenAlex/PubMed 호출 0회로 가능.
3. **부분 실패 허용** — quota 차단으로 부족분을 다 못 채워도 캐시까지로 임베딩을 진행해 산출물이 0이 되는 일을 막는다.

`monthly_ingest.py`는 chunks를 디스크에 저장하지 않으며 manifest 단위 DOI dedup이 이미 동작하므로 본 설계의 변경 대상에서 제외한다.

## 2. 핵심 결정 사항 (브레인스토밍 + Codex 리뷰 합의)

1. **부족분 정의는 chunks에 들어간 paper 수 기준**. 크롤링한 paper 중 본문 미확보로 chunks 생성에 실패한 paper는 부족분 계산에서 제외한다 — usable chunks가 사용자 인자(`--max-papers`)에 부합해야 한다.
2. **manifest의 `existing_dois` 의미를 그대로 보존**. 기존 흐름은 `fulltext_source != None` 또는 `tried_sources ⊇ ACTIVE_SOURCES`만 제외한다. 본 설계는 여기에 **캐시 chunks의 paper_doi**만 추가하고, retry candidates는 차단하지 않는다.
3. **schema/포맷 검증은 사이드카로**. `mlops/data/chunks/<batch-tag>.meta.json`을 도입해 `version` + `created_at` + `paper_count` 등을 기록하고, chunks 파일 자체 포맷(line-delimited gzip JSON)은 그대로 둔다.
4. **chunks 파일 갱신은 atomic rewrite**. 기존 chunks 로드 → 부족분 크롤링 + 청킹 → merge → `tmp + os.replace` 패턴. 동시 실행은 README 경고로 처리하고 file lock은 별도 PR로 미룬다 (YAGNI).
5. **에러 분류 명확화**. `JSONDecodeError`/`pydantic.ValidationError`/사이드카 version mismatch는 캐시 무효 처리하고 warn + 전체 재크롤링으로 fallback. `OSError`/`gzip.BadGzipFile`은 raise해서 디스크 문제를 운영자가 즉시 인지하도록 한다.
6. **카테고리 균형은 `max_per_category` 인자 위임**. fill 경로에서도 호출자가 넘긴 `max_per_category`를 `crawl_papers()`에 그대로 전달. 캐시의 `search_categories` 분포 분석 등의 가중치 로직은 YAGNI로 보류.

## 3. 아키텍처

### 변경 위치

| 파일 | 변경 |
|---|---|
| `mlops/scripts/export_embeddings.py` | Stage 1 chunks 결정 분기 확장 (incremental fill 추가) + 사이드카 read/write helper |
| `mlops/pipeline/manifest.py` | 변경 없음 |
| `mlops/pipeline/crawler.py` | 변경 없음 (`existing_dois` 인자는 이미 지원) |
| `mlops/pipeline/models.py` | 변경 없음 (`Chunk.paper_doi` 기존 필드 활용) |
| `mlops/tests/test_export_embeddings.py` | 신규 생성 — 본 설계 동작 검증 |

### 데이터 흐름

```
export_embeddings.py main()
└── stage 1: chunks 결정
    ├── chunks_path 존재?
    │   ├── No → crawl_full(args.max_papers)  # 기존 동작
    │   └── Yes
    │       ├── meta = _load_meta_sidecar(chunks_path)
    │       │   ├── version mismatch → warn + fallback_full_crawl
    │       │   └── 정상 또는 사이드카 없음(legacy) → continue
    │       ├── try _load_chunks(chunks_path)
    │       │   ├── JSONDecodeError/ValidationError → warn + fallback_full_crawl
    │       │   ├── OSError/BadGzipFile → raise
    │       │   └── 정상 → chunks 보유
    │       ├── cached_paper_count = _count_unique_papers(chunks)
    │       ├── shortage = max(0, args.max_papers - cached_paper_count)
    │       └── shortage > 0 분기
    │           ├── manifest = Manifest.load(MANIFEST_PATH)
    │           ├── manifest_skip = {기존 흐름과 동일}
    │           ├── cached_dois = {c.paper_doi for c in chunks if c.paper_doi}
    │           ├── existing_dois = manifest_skip | cached_dois
    │           ├── new_papers = crawl_papers(max_total=shortage,
    │           │                              max_per_category=args.max_per_category,
    │           │                              existing_dois=existing_dois)
    │           ├── indexed = [p for p in new_papers if p.sections]
    │           ├── new_chunks = chunk_papers(indexed)
    │           ├── merged = _merge_chunks(chunks, new_chunks)
    │           ├── _save_chunks_atomic(chunks_path, merged)
    │           ├── _write_meta_sidecar(chunks_path, merged)
    │           └── warn if (cached_paper_count + len(indexed)) < args.max_papers
└── stage 2: 임베딩 (현재 코드 그대로)
```

`fallback_full_crawl`은 chunks 파일과 사이드카를 무효화(이름에 `.invalid.<timestamp>` 접미사로 옆에 이동)한 뒤 기존 통째 크롤링 경로로 진입한다. 원본을 즉시 삭제하지 않는 이유는 사용자가 진단할 수 있는 흔적을 남기기 위함이다.

### 신규 helper (export_embeddings.py 내부)

```python
CHUNKS_META_VERSION = 1

def _meta_path(chunks_path: Path) -> Path:
    """`<tag>.jsonl.gz` → `<tag>.jsonl.gz.meta.json`. Path.with_suffix는 마지막 suffix를
    교체하므로 사이드카 이름 충돌을 피하기 위해 name에 직접 append한다."""
    return chunks_path.parent / (chunks_path.name + ".meta.json")

def _load_meta_sidecar(chunks_path: Path) -> dict | None: ...
def _write_meta_sidecar(chunks_path: Path, chunks: list[Chunk]) -> None: ...
def _count_unique_papers(chunks: list[Chunk]) -> int:
    keys = {(c.paper_doi or c.paper_pmid) for c in chunks if (c.paper_doi or c.paper_pmid)}
    return len(keys)
def _chunks_doi_set(chunks: list[Chunk]) -> set[str]:
    return {c.paper_doi for c in chunks if c.paper_doi}  # 빈 string 제외
def _merge_chunks(old: list[Chunk], new: list[Chunk]) -> list[Chunk]:
    """paper_doi 또는 paper_pmid 기준 dedup. old 우선."""
    ...
def _save_chunks_atomic(path: Path, chunks: list[Chunk]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    # gzip write to tmp, then os.replace(tmp, path)
    ...
```

### 사이드카 스키마

`mlops/data/chunks/<batch-tag>.jsonl.gz.meta.json`:

```json
{
  "version": 1,
  "chunks_path": "run_3k.jsonl.gz",
  "paper_count": 1500,
  "chunk_count": 8400,
  "created_at": "2026-05-20T22:30:00Z",
  "updated_at": "2026-05-21T09:30:00Z",
  "max_papers_requested": 3000
}
```

`version`이 `CHUNKS_META_VERSION`과 다르면 schema 변경으로 간주.
사이드카가 없는 경우는 legacy 캐시로 보고 _load_chunks 시도 → 성공하면 사용, 실패하면 fallback.

## 4. 에러 처리

| 상황 | 동작 |
|---|---|
| chunks 파일 존재 안 함 | 기존 통째 크롤링 (정상 경로) |
| chunks 파일 + 사이드카 정상 | shortage 계산 후 fill |
| 사이드카 없음(legacy) | _load_chunks 시도. 성공 시 사용, 실패 시 fallback_full_crawl |
| 사이드카 version mismatch | warn + fallback_full_crawl |
| `JSONDecodeError`/`ValidationError` | warn + fallback_full_crawl |
| `OSError`/`gzip.BadGzipFile` | raise (silent fallback 금지) |
| crawl 부족분 < shortage | warn `OpenAlex/PubMed로 N편만 회수, 요청 M편 미충족` + 캐시까지로 진행 |
| crawl 0건 + 캐시 비었음 | 현재 동작 유지 `신규 논문 없음. 종료.` |

## 5. 테스트 전략

`mlops/tests/test_export_embeddings.py` 신규 작성. crawl/chunk를 monkeypatch로 가짜화하여 stage 1 분기 동작을 검증한다.

| 테스트 | 검증 |
|---|---|
| `test_no_cache_falls_back_to_full_crawl` | chunks 파일 없으면 통째 크롤링 경로 진입 |
| `test_reuse_chunks_sufficient` | 캐시 paper 수 ≥ max_papers → crawl 0회 호출 |
| `test_reuse_chunks_partial_fill` | shortage만큼만 crawl_papers(max_total=shortage) 호출 |
| `test_reuse_chunks_existing_dois_merged` | crawl 인자 existing_dois에 manifest_skip + cached_dois 합집합 (retry candidates는 포함 안 됨) |
| `test_chunks_doi_set_excludes_empty_string` | paper_doi=="" 인 Chunk는 existing_dois에서 제외 |
| `test_fill_passes_max_per_category` | fill 경로의 crawl_papers 호출이 `args.max_per_category`를 그대로 전달 |
| `test_reuse_chunks_partial_fill_below_shortage` | crawl 신규 < shortage → warn 로그 + 캐시까지로 진행 (return 0 아님) |
| `test_meta_sidecar_version_mismatch_invalidates_cache` | version != CHUNKS_META_VERSION → fallback_full_crawl |
| `test_meta_sidecar_missing_treated_as_legacy` | 사이드카 없고 _load_chunks 성공 → 정상 사용 |
| `test_paper_count_based_on_chunks_papers_only` | indexed_papers (sections 있는) 기준으로 카운트 |
| `test_chunks_atomic_save` | `_save_chunks_atomic` 중간에 예외 발생 시 원본 파일 보존 |
| `test_gzip_corruption_raises` | `gzip.BadGzipFile` 시 raise (silent fallback 안 함) |

기존 `mlops/tests/test_openalex.py` 등 다른 모듈 테스트에는 영향 없음. monthly_ingest 흐름은 변경 없으므로 회귀 테스트는 기존 mlops/tests 전체 실행으로 충분.

## 6. 범위 (확정)

**포함**

- `mlops/scripts/export_embeddings.py` stage 1 분기 보강
- `<batch-tag>.jsonl.gz.meta.json` 사이드카 도입
- 신규 helper 함수 (위 §3 목록)
- 신규 테스트 12종 (위 §5 목록)

**제외 (YAGNI 또는 별도 PR)**

- `monthly_ingest.py` 변경 — chunks 디스크 저장 자체를 안 함
- chunks 파일 포맷 변경 — 사이드카로 우회
- 동시 실행 file lock — atomic rewrite로 partial write만 방어. 다중 프로세스 보호는 별도 PR
- 캐시의 `search_categories` 분포 가중치 — `max_per_category` 인자에 위임
- OpenAlex search 응답 캐시 — chunks 캐시가 사실상 같은 효과 (사용자 워크로드: A/B 임베딩 비교)
- legacy 캐시 자동 사이드카 생성 — 첫 fill 시점에 자연 생성됨

## 7. 마이그레이션

- 기존 사용자가 보유한 `mlops/data/chunks/<tag>.jsonl.gz`는 사이드카 없음. 본 PR 머지 후 첫 `--reuse-chunks` 실행 시 _load_chunks 성공하면 그대로 사용되고, fill 또는 정상 완료 시 사이드카가 자동 생성된다.
- 사이드카 파일 자체는 `.gitignore`에 포함 — chunks 파일과 동일 정책. CI/CD 영향 없음.

## 8. 운영 노트

- 같은 `--batch-tag`로 동시에 export_embeddings를 두 번 띄우지 말 것. atomic write가 partial write를 방어하지만 lost update는 막지 못한다.
- OpenAlex daily quota는 midnight UTC (한국시간 09:00)에 리셋. 부족분 fill을 새 quota로 돌리려면 그 시각 이후에 재실행.
- `<tag>.jsonl.gz.invalid.<timestamp>` 파일이 생겼다면 schema mismatch 또는 corruption fallback이 발생한 흔적. 진단 후 삭제.
