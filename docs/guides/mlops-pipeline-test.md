# MLOps 파이프라인 로컬/클라우드 테스트 가이드

`mlops/` 파이프라인(크롤링 → 청킹 → 임베딩 → JSON Lines export → ChromaDB 적재 → RAG 검색)을 다른 환경에서 재현하기 위한 절차. 본 가이드는 브랜치 `feature/jingyu/mlops-paper-ingest` (commit `b917369`, `4b83f22`, `a14d0ab`) 기준으로 실측 검증된 흐름을 정리한 것이다.

> 본 가이드의 모든 명령은 로컬(WSL Ubuntu 24.04, Python 3.12.3, CPU)에서 max-papers 3으로 E2E 검증 완료. 클라우드 환경(Colab/EC2/GCE/Kaggle)에서도 동일 흐름이 동작한다.

## 검증된 시스템 보장 사항

| 보장 | 검증 방식 |
|---|---|
| 29개 카테고리 round-robin 분배 (FIFO cap 회피) | `pytest mlops/tests/test_crawler.py::TestRoundRobinDedup` 8건 |
| transient NCBI 에러 재시도 (ChunkedEncoding/5xx/429, 기본 5회 backoff cap 10s) | `pytest .../TestRequestWithRateLimit` 9건, 실측 PMC 성공률 0/3→2/3 |
| HTTP 200 + 깨진 JSON/XML body 재시도 (fulltext 함수 layer, 기본 3회) | `pytest .../TestResolvePmcId` 5건, `TestFetchPmcSections` 3건, 실측 50편 dry-run에서 fulltext 회수율 92% (46/50) |
| 카테고리 메타 합집합 (다중 매칭 시) | 실측 PMID 1편이 6개 카테고리 동시 매칭 |
| JSON Lines round-trip (gzip 포함) | `Chunk.model_dump()` ↔ `Chunk(**data)` 라운드트립 단위 테스트 |
| BGE 임베딩 1024 dim 보존 | export → load → query 전 구간 일관 |

## 사전 요구사항

- Python 3.11+ (검증: 3.12.3)
- 디스크 ~5GB 여유 (torch ~1.5GB + BGE 모델 ~2GB + 캐시)
- 메모리 4GB+ (BGE 임베딩 동작용)
- NCBI API key (선택, 권장: rate limit 3 → 10 req/s)
- Git, pip, venv 사용 가능
- 인터넷 접근 (NCBI eutils, HuggingFace)

## 1단계: 코드 가져오기

```bash
git clone https://github.com/SciFit-Sync/scifit-sync.git
cd scifit-sync
git checkout feature/jingyu/mlops-paper-ingest
git log --oneline -3   # b917369, 4b83f22, a14d0ab 세 commit 확인
```

## 2단계: 의존성 설치

### 표준 환경 (Linux/macOS/EC2)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r mlops/requirements.txt
```

설치 패키지(`mlops/requirements.txt`):
- 크롤링: `requests`, `beautifulsoup4`, `lxml>=6.1.0`, `biopython`
- RAG: `chromadb`, `sentence-transformers` (→ torch 자동 동반)
- LLM: `google-genai`, `openai`
- 청킹: `tiktoken`
- 검증: `pydantic`, `pytest`, `pytest-cov`

총 다운로드 ~3.5GB, 시간 5-10분 (네트워크 따라).

### 분리 설치 옵션 (가벼운 것 먼저 → dry-run → 무거운 것)

`torch + sentence-transformers`(~3GB)가 가장 무거우므로 분리하면 빠른 사전 검증 가능:

```bash
# 1차: 가벼운 의존성만 (dry-run + chromadb까지 가능)
pip install tiktoken chromadb beautifulsoup4 lxml biopython tqdm requests pydantic python-dotenv pytest pytest-cov pytest-asyncio

# (여기서 4단계 dry-run + 단위 테스트 가능)

# 2차: 무거운 임베딩 의존성
pip install sentence-transformers   # torch 자동 동반
```

## 3단계: 환경변수

```bash
# NCBI API key (강력 권장)
export NCBI_API_KEY=<발급키>   # https://www.ncbi.nlm.nih.gov/account/settings/

# 로컬 ChromaDB 경로 (load_embeddings.py --mode local 사용 시)
export CHROMA_PERSIST_PATH=./mlops/data/chroma-data
export CHROMA_COLLECTION_NAME=paper_chunks   # 기본값

# 본 실행 사이즈 튜닝
export MAX_PAPERS_PER_RUN=300       # 전체 cap
export MAX_PAPERS_PER_CATEGORY=20   # 카테고리당 검색 상한

# (서버 admin 적재 시에만) 운영 ChromaDB 적재용
# export API_BASE_URL=https://api.scifit-sync.example.com
# export ADMIN_API_TOKEN=<서버와 동일한 값>
```

API key 미설정 시 rate limit 3 req/s (29 카테고리 esearch ≈ 1-2분), 설정 시 10 req/s (≈ 20초).

## 4단계: 단위 테스트 실행 (선택, 빠른 검증)

```bash
pytest mlops/tests/test_crawler.py -v
# 기대: 36 passed
#  - parse(PubMed article 2 + PMC sections 2 + get_text 3)
#  - search 2
#  - round-robin 8
#  - HTTP retry 9 (transient 에러 5회 + backoff cap + 4xx 비재시도 + 5xx 재시도 등)
#  - fulltext 함수 layer retry 12
#    (_resolve_pmc_id 5건: JSON 깨짐 재시도 / PMC 미존재 즉시 None / 한도 초과)
#    (_fetch_pmc_sections 3건: XML 깨짐 재시도 / 한도 초과)
#    (fetch_pmc_fulltext end-to-end 2건)
```

## 5단계: dry-run (크롤링 + 청킹만, 임베딩 없이)

NCBI/PMC 호출과 round-robin/카테고리 메타가 환경에서 정상 동작하는지 확인:

```bash
python mlops/scripts/export_embeddings.py --max-papers 3 --dry-run
```

기대 로그 마지막:
```
INFO  [mlops.pipeline.crawler] round-robin 결과: 신규 PMID 3건 (카테고리 다중 매칭 분포: 평균 X.X카테고리/논문)
INFO  [mlops.pipeline.crawler] 크롤링 완료: 3건 (전문 포함 N건)
INFO  [mlops.pipeline.chunker] 전체 청킹 완료: 논문 3편 → 청크 N개
INFO  [__main__] [DRY RUN] 임베딩/파일 출력 생략
```

소요 시간: NCBI key 없으면 ~1-2분, 있으면 ~20초.

## 6단계: 본 실행 — JSON Lines export

크롤링 → 청킹 → BGE 임베딩 → 파일 출력:

```bash
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz
```

manifest.json은 기본적으로 갱신되지 **않는다**. export 결과 파일을 ChromaDB에
실제로 적재 완료한 뒤, 별도로 `--update-manifest`를 명시해 호출해야 manifest가
업데이트된다 (또는 적재 검증 후 수동으로 manifest를 갱신). 이렇게 분리해두면
적재 도중 실패해도 manifest가 깨끗하게 남아 동일 PMID로 재시도할 수 있다.

| 옵션 | 효과 |
|---|---|
| `--max-papers N` | 전체 PMID 수집 상한 |
| `--output PATH` | 출력 경로 (`.jsonl.gz` 확장자 시 gzip 자동) |
| `--gzip` | 명시적 gzip (확장자 무관) |
| `--dry-run` | 임베딩/파일 생략 (크롤링+청킹만) |
| `--min-date YYYY/MM/DD` | PubMed 출판일 하한 |
| `--max-date YYYY/MM/DD` | PubMed 출판일 상한 |
| `--update-manifest` | export 완료 후 즉시 manifest.json 갱신 (**기본 OFF — 적재 검증 후 수동 갱신 권장**) |

기대 출력 (마지막 줄):
```
INFO  [__main__] Export 완료: N청크 → mlops/data/embeddings.jsonl.gz (X.XX MB)
INFO  [__main__] === Export 완료: M편 → N청크 ===
```

소요 시간 (CPU 환경):
- BGE 모델 첫 다운로드: ~3-5분 (이후 캐시됨)
- 100편 임베딩: ~10-15분
- 총 100편 첫 실행 ~20분, 재실행 ~15분

GPU 환경(T4/A10/V100): 임베딩 시간 ~1-2분으로 단축.

출력 파일 사이즈 (실측 기반):
- 1편 ≈ 25KB (gzip 후 ~8KB)
- 100편 ≈ ~12-50MB (PMC 성공률 따라), gzip 후 ~4-17MB

## 7단계: 출력 파일 가져오기 (클라우드 → 로컬)

```bash
# AWS EC2
scp -i key.pem ubuntu@<ip>:~/scifit-sync/mlops/data/embeddings.jsonl.gz .

# Google Colab (노트북 셀)
from google.colab import files
files.download("mlops/data/embeddings.jsonl.gz")

# S3 경유
aws s3 cp mlops/data/embeddings.jsonl.gz s3://my-bucket/
aws s3 cp s3://my-bucket/embeddings.jsonl.gz ./local-dest/
```

내용 미리보기 (gzip 파일도 가능):
```bash
zcat embeddings.jsonl.gz | wc -l                       # 청크 수
zcat embeddings.jsonl.gz | head -1 | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print('PMID:', d['paper_pmid'], '| dim:', len(d['embedding']))
print('cats:', d['search_categories'])
"
```

## 8단계: 로컬 ChromaDB 적재 (개발/검증용)

```bash
export CHROMA_PERSIST_PATH=./mlops/data/chroma-data
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local
```

기대 출력:
```
INFO  [mlops.pipeline.upserter] ChromaDB upsert: N/N
INFO  [__main__] === 적재 완료: N청크 (mode=local) ===
```

이 단계에서 `./mlops/data/chroma-data/` 디렉토리가 처음 생성된다 (sqlite + HNSW 인덱스 바이너리).

오류 처리 정책: 기본은 **fail-fast** — 단일 라인 파싱 실패(JSON 깨짐, 임베딩
차원 불일치 등)에서 즉시 raise하여 적재를 중단한다. 수천 청크 중 소수 라인만
오염되어도 나머지를 살리고 싶으면 `--skip-errors` 플래그를 명시한다:

```bash
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local --skip-errors
```

skip된 라인은 WARNING 로그로 남고, 종료 시 총 skip 라인 수가 요약된다.

## 9단계: 운영 ChromaDB 적재 (AWS admin endpoint 경유)

```bash
export API_BASE_URL=https://api.scifit-sync.example.com
export ADMIN_API_TOKEN=<서버와 동일한 값>
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode api
```

서버측 `server/app/api/v1/admin.py:55`의 `POST /api/v1/admin/rag/ingest`로 batch upsert. X-Admin-Token 인증. 운영 시에도 `--skip-errors`로 부분 적재 허용 가능.

적재 검증 완료 후 manifest를 갱신하려면:

```bash
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz \
    --update-manifest
```

또는 별도 스크립트로 적재된 PMID를 추출해 `mlops/data/manifest.json`에 머지해도 된다.

## 10단계: RAG 검색 시뮬레이션 (로컬 ChromaDB 한정)

```bash
CHROMA_PERSIST_PATH=./mlops/data/chroma-data python3 - <<'PY'
import sys, os
sys.path.insert(0, ".")
import chromadb
from mlops.pipeline.embedder import embed_texts

c = chromadb.PersistentClient(os.environ["CHROMA_PERSIST_PATH"])
col = c.get_collection("paper_chunks")
print(f"총 청크: {col.count()}")

for q in [
    "How many sets per week for muscle hypertrophy?",
    "Optimal rest interval between resistance training sets",
    "Resistance training for older women",
]:
    print(f"\n=== {q} ===")
    [vec] = embed_texts([q], batch_size=1)
    result = col.query(query_embeddings=[vec], n_results=3)
    for i in range(len(result["ids"][0])):
        meta = result["metadatas"][0][i]
        sim = 1 - result["distances"][0][i]
        print(f"  [{i+1}] sim={sim:.3f} | PMID={meta['paper_pmid']} | cats={meta['search_categories']}")
        print(f"      {result['documents'][0][i][:160]}...")
PY
```

## 결과 검증 체크리스트

- [ ] `pytest mlops/tests/test_crawler.py -v` → 24 passed
- [ ] dry-run 출력에 `round-robin 결과: 신규 PMID N건 (카테고리 다중 매칭 분포: 평균 ...)` 라인 존재
- [ ] `mlops/data/embeddings.jsonl.gz` 파일 생성, sample 청크에 `search_categories` 필드 포함
- [ ] 적재 후 `col.count()` == export 청크 수
- [ ] RAG 검색 결과 metadata에 `search_categories` CSV string 포함
- [ ] 검색 sim 값이 0.5+ 범위 (resistance training 도메인 쿼리 기준)

## 알려진 한계 (본 브랜치 기준)

| 한계 | 영향 | 후속 대응 |
|---|---|---|
| ~~PMC 전문 fetch 일부 실패 (JSONDecodeError 케이스)~~ | ~~abstract fallback으로 자동 처리, RAG 동작 무영향~~ | **본 PR에서 해결** — fulltext 함수 layer retry로 회수율 92% (50편 dry-run 실측). 끝까지 실패한 1편만 abstract fallback |
| BGE prefix 정책 부정확 | 검색 품질 ~10% 손실 가능성 (document/query 같은 prefix 사용) | embedder.py + rag.py 동시 PR |
| ~~`--update-manifest` 기본 True~~ | ~~export 직후 적재 실패 시 PMID 영구 누락 위험~~ | **PR #63 리뷰 반영으로 해결** — `--update-manifest`가 기본 OFF로 변경됨. export 단독으로는 manifest 변경 없음 |
| `MAX_PAPERS_PER_RUN=300`이 `29 × 20 = 580` 후보보다 작음 | 큰 영향 없음 (round-robin이 균등 분배 보장) | 필요 시 환경변수로 상향 |
| PMC retry 최악 케이스 대기시간 | 단일 PMID에서 HTTP layer 재시도(5회 × 10s cap) × 함수 layer 재시도(3회) ≈ **150s/PMID** 까지 대기 가능 | 야간 cron 권장. 회수율 vs 시간 트레이드오프는 `--http-retries`/`--fulltext-attempts`로 조정 |

## 트러블슈팅

### WSL Ubuntu 24.04: `externally-managed-environment` (PEP 668)

```
error: externally-managed-environment
× This environment is externally managed
```

원인: Ubuntu 24.04부터 시스템 Python 보호. 해결:
```bash
# A) python3-venv 설치 후 venv 사용 (권장)
sudo apt install -y python3.12-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r mlops/requirements.txt

# B) user-level 설치로 우회
pip install --user --break-system-packages -r mlops/requirements.txt
```

### Docker 미설치 환경

서버를 띄우지 않고도 본 파이프라인은 동작한다 — `--mode local`로 로컬 ChromaDB 사용. server 측 검증은 운영 환경에서.

### NCBI 응답 transient 에러 / fulltext 회수율 튜닝

크롤러는 fulltext 회수율을 최대화하기 위해 **2단 retry**를 적용한다:

1. **HTTP layer** (`_request_with_rate_limit`): `ChunkedEncodingError` / `Timeout` / `ConnectionError` / `HTTP 5xx` / `HTTP 429`를 **기본 5회** 지수 백오프(최대 10s cap)로 재시도. `HTTP 4xx`는 영구 에러로 즉시 raise.
2. **함수 layer** (`_resolve_pmc_id`, `_fetch_pmc_sections`): HTTP 200인데 body가 깨진 케이스(`JSONDecodeError`, `ET.ParseError`)를 **기본 3회** 재시도. NCBI가 동일 위치에서 corrupt response를 반복 반환하는 케이스가 실측되어 별도 layer로 처리.

두 단을 모두 소진하면 `crawl_papers`가 **abstract fallback**으로 처리 — 청크 손실 없음. 50편 dry-run 실측 결과: PMC 회수율 **92%** (46/50, 3편은 PMC 미등재 정상 케이스, 1편만 retry 한도 초과).

#### CLI / 환경변수로 retry 강도 조정

시간 더 들어도 회수율을 더 끌어올리고 싶을 때:

```bash
# CLI (initial_ingest.py 한정)
python mlops/scripts/initial_ingest.py --dry-run --max-papers 50 \
    --http-retries 8 --fulltext-attempts 5

# 환경변수 (모든 진입점에서 동작)
NCBI_HTTP_MAX_RETRIES=8 \
NCBI_HTTP_MAX_BACKOFF=20.0 \
NCBI_HTTP_TIMEOUT=120 \
PMC_FULLTEXT_MAX_ATTEMPTS=5 \
python mlops/scripts/initial_ingest.py --dry-run --max-papers 50
```

| 변수 (env) | 기본값 | 의미 |
|---|---|---|
| `NCBI_HTTP_MAX_RETRIES` | 5 | HTTP layer transient 에러 재시도 횟수 |
| `NCBI_HTTP_MAX_BACKOFF` | 10.0 | HTTP 지수 백오프 초당 상한 |
| `NCBI_HTTP_TIMEOUT` | 60 | HTTP read timeout 초 |
| `PMC_FULLTEXT_MAX_ATTEMPTS` | 3 | parse 실패 시 함수 layer 재시도 횟수 |
| `PMC_FULLTEXT_RETRY_BACKOFF_BASE` | 2.0 | 함수 layer backoff 시작 초 |
| `PMC_FULLTEXT_RETRY_BACKOFF_MAX` | 10.0 | 함수 layer backoff 상한 초 |

> 회수율 vs 실행시간 trade-off — 50편 기준 기본값 ≈ 18분. 최악 케이스(모든 paper에서 모든 retry 소진)는 한 편당 ~2-3분 추가될 수 있으니, 야간 cron으로 돌리는 게 안전.

### HuggingFace 다운로드 느림

```bash
# 옵션: HF_TOKEN 설정으로 rate limit 완화
export HF_TOKEN=<your_token>

# 옵션: 다운로드 캐시 위치 변경 (디스크 부족 시)
export HF_HOME=/path/to/cache
```

### BGE 모델 메모리 초과

BGE-large-en-v1.5는 ~1.3GB RAM 사용. 인스턴스 RAM < 2GB 환경에서는 OOM 가능 — 더 작은 환경 권장 또는 GPU 사용.

## 참고

- 코드 리뷰 절차 및 발견 이슈: 본 commit history (`b917369 → 4b83f22 → a14d0ab`)의 commit body 참조
- ChromaDB 폴더 구조 vs JSON Lines 의미 차이: `docs/guides/deployment.md` 참조
- 서버 admin endpoint 동작: `server/app/api/v1/admin.py:55` (`POST /api/v1/admin/rag/ingest`)
- 운영 ECS 제약 (Task count=1, EFS `/chroma-data`): `CLAUDE.md` §15
