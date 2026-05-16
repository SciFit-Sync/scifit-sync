# SciFit-Sync MLOps 파이프라인 클라우드 실행 가이드

> 환경 셋업부터 본 실행, RAG 검증까지 따라할 수 있는 빠른시작 가이드.
> **검증 환경**: GPU 클러스터 (Ubuntu 22.04, Python 3.10/3.11 공존, NVIDIA CUDA 12.0 드라이버)
> **기준 코드**: `develop` 브랜치, PR #63 머지 완료 (commit `4abf227`)
>
> 상세 검증 절차 및 알려진 한계는 [`mlops-pipeline-test.md`](./mlops-pipeline-test.md) 참고.

---

## 사전 준비

- 클라우드 인스턴스 (Linux, RAM 4GB+, 디스크 5GB+)
- root 또는 sudo 권한
- 인터넷 접근 (NCBI eutils, HuggingFace, PyPI)
- **선택 / 강력 권장**: NCBI API key — https://www.ncbi.nlm.nih.gov/account/settings/ (rate limit 3→10 req/s)

---

## STEP 1. 코드 가져오기 (develop 브랜치)

PR #63이 develop에 머지 완료됨 (`4abf227`).

```bash
# 처음이면 clone
git clone https://github.com/SciFit-Sync/scifit-sync.git
cd scifit-sync

# 이미 있으면 pull만
cd ~/capstone/scifit-sync   # 본인 경로
git fetch origin
git checkout develop
git pull origin develop
```

**검증**:
```bash
git log --oneline -1
# 출력: 4abf227 Merge pull request #63 from SciFit-Sync/feature/jingyu/mlops-paper-ingest
```

---

## STEP 2. Python 환경 진단

```bash
python3 --version
ls /usr/bin/python3*
nvidia-smi   # GPU 인스턴스만, CUDA Version 메모
```

**의사 결정**:
- Python 3.11이 있으면 → 3.11로 venv (가이드 권장)
- 3.10밖에 없으면 → `apt install -y python3.11 python3.11-venv`로 추가 설치 권장

---

## STEP 3. venv 생성 & 활성화

```bash
apt install -y python3.11-venv   # 없을 때만
cd ~/capstone/scifit-sync
python3.11 -m venv .venv
source .venv/bin/activate

# 검증
python --version          # Python 3.11.x
which python              # .../scifit-sync/.venv/bin/python
```

> 앞으로 모든 명령은 `.venv` 활성화 상태에서. 세션 끊기면 `source .venv/bin/activate` 먼저.

---

## STEP 4. 의존성 설치

```bash
pip install --upgrade pip wheel
pip install -r mlops/requirements.txt
```

⏱️ ~5-10분 (총 ~3.5GB).

---

## STEP 5. GPU 매칭 (CUDA 인식 확인)

```bash
python -c "import torch; print('cuda:', torch.cuda.is_available(), '| device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

### 케이스 A — `cuda: True`
GPU 정상. STEP 6으로 진행.

### 케이스 B — `cuda: False` + "driver too old"
PyTorch가 컴파일된 CUDA가 시스템 드라이버보다 새 것. 드라이버에 맞는 빌드로 재설치:

```bash
pip uninstall -y torch torchvision torchaudio

# nvidia-smi의 CUDA Version 보고 한 줄만 골라서 실행:
pip install torch --index-url https://download.pytorch.org/whl/cu121   # CUDA 12.0~12.3
# pip install torch --index-url https://download.pytorch.org/whl/cu124 # CUDA 12.4~12.6
# pip install torch --index-url https://download.pytorch.org/whl/cu118 # CUDA 11.8

# 재검증
python -c "import torch; print('cuda:', torch.cuda.is_available(), '| device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

**기대 출력**: `cuda: True | device: NVIDIA <GPU 이름>`

`sentence-transformers`는 torch만 갈아끼우면 그대로 동작 (재설치 불요).

### 케이스 C — GPU 없는 인스턴스
CPU만으로도 동작 (100편 ~10-15분). 그대로 STEP 6 진행.

---

## STEP 6. 환경변수 — 전체 상세

`mlops/pipeline/config.py`가 읽는 환경변수. 모두 **있으면 사용, 없으면 기본값**.

### 6-1. 외부 API

| 변수 | 기본값 | 설명 |
|---|---|---|
| `NCBI_API_KEY` | `""` | NCBI E-utilities API key. 있으면 rate limit **3 → 10 req/s** (코드 내부 `NCBI_RATE_LIMIT`: 1.0s → 0.34s). 29 카테고리 esearch 1-2분 → 20초. |
| `API_BASE_URL` | `""` | **`--mode api`** 적재 시 필수. 운영 서버 URL (예: `https://api.scifit-sync.example.com`). `--mode local`에선 무관 |
| `ADMIN_API_TOKEN` | `""` | **`--mode api`** 적재 시 필수. 서버 `X-Admin-Token` 헤더 값. 서버 환경변수와 정확히 동일해야 인증 통과 |

### 6-2. ChromaDB

| 변수 | 기본값 | 설명 |
|---|---|---|
| `CHROMA_PERSIST_PATH` | `/chroma-data` | **로컬 적재 시 필수 변경**. 기본값은 ECS/EFS 마운트 가정이라 로컬에선 `$PWD/mlops/data/chroma-data` 같은 쓰기 가능 경로로 |
| `CHROMA_COLLECTION_NAME` | `paper_chunks` | 컬렉션명. 운영과 동일하게 유지. BGE prefix 마이그레이션 시 `paper_chunks_v2`로 바뀐 적 있음 — 운영 서버 설정과 동기화 필수 |

### 6-3. 임베딩

| 변수 | 기본값 | 설명 |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | HuggingFace 모델 ID. 1024차원 고정. 모델 변경 시 차원도 같이 — ChromaDB 호환성 깨질 수 있으니 주의 |

### 6-4. 청킹

| 변수 | 기본값 | 설명 |
|---|---|---|
| `CHUNK_MIN_TOKENS` | `300` | 청크 최소 토큰. 이보다 작은 단편은 인접 청크와 병합 |
| `CHUNK_MAX_TOKENS` | `512` | 청크 최대 토큰. BGE 입력 한계 |
| `CHUNK_OVERLAP_TOKENS` | `50` | 인접 청크 간 오버랩, 문맥 단절 방지 |

### 6-5. 파이프라인 사이즈 캡

| 변수 | 기본값 | 설명 |
|---|---|---|
| `MAX_PAPERS_PER_RUN` | `300` | 1회 실행에서 처리할 PMID 최대 수. `export_embeddings.py --max-papers` 미지정 시 이 값 사용 |
| `MAX_PAPERS_PER_CATEGORY` | `20` | 29개 카테고리 각각의 esearch retmax. `29 × 20 = 580`이 round-robin 입력. `MAX_PAPERS_PER_RUN`이 580보다 작으면 round-robin이 균등 분배 |

### 6-6. PMC fulltext 수집 retry 튜닝

NCBI eutils가 일시 장애를 자주 일으키는 환경(WSL, 일부 클라우드 망)에서 fulltext 회수율을 끌어올리려면 retry 강도를 키운다. **시간이 더 걸려도 회수율을 우선**할 때만 손대도 충분.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `NCBI_HTTP_MAX_RETRIES` | `5` | HTTP transient 에러(ChunkedEncoding/Timeout/5xx/429) 재시도 횟수 |
| `NCBI_HTTP_MAX_BACKOFF` | `10.0` | HTTP 지수 백오프 초당 상한 (이걸 키우면 NCBI 장애 시 더 오래 기다림) |
| `NCBI_HTTP_TIMEOUT` | `60` | HTTP read timeout 초 |
| `PMC_FULLTEXT_MAX_ATTEMPTS` | `3` | HTTP 200인데 body 깨진(`JSONDecodeError`/`ParseError`) 케이스의 함수 layer 재시도 횟수 |
| `PMC_FULLTEXT_RETRY_BACKOFF_BASE` | `2.0` | 함수 layer backoff 시작 초 |
| `PMC_FULLTEXT_RETRY_BACKOFF_MAX` | `10.0` | 함수 layer backoff 상한 초 |

**실측 회수율** (50편 dry-run, 기본값 기준): 전문 포함 **46/50 = 92%**, abstract fallback 1편, PMC 미등재 정상 3편. 실행 시간 18분.

retry 강하게 (예: 10편 ↑):
```bash
NCBI_HTTP_MAX_RETRIES=8 PMC_FULLTEXT_MAX_ATTEMPTS=5 \
python mlops/scripts/initial_ingest.py --dry-run --max-papers 50
```

initial_ingest.py는 CLI 인자도 지원 (`--http-retries`, `--fulltext-attempts`):
```bash
python mlops/scripts/initial_ingest.py --dry-run --max-papers 50 \
    --http-retries 8 --fulltext-attempts 5
```

> `export_embeddings.py` 등 다른 진입점은 env 변수만 지원.

### 6-7. (선택) HuggingFace

| 변수 | 기본값 | 설명 |
|---|---|---|
| `HF_HOME` | `~/.cache/huggingface` | BGE 모델(~2GB) 캐시 경로. 디스크 부족 시 큰 볼륨으로 |
| `HF_TOKEN` | (없음) | HuggingFace 토큰. rate limit 자주 걸리면 발급 |

### 권장 세팅 (로컬/클라우드 개발)

```bash
export NCBI_API_KEY=<발급키>
export CHROMA_PERSIST_PATH=$PWD/mlops/data/chroma-data
export CHROMA_COLLECTION_NAME=paper_chunks
export MAX_PAPERS_PER_RUN=300
export MAX_PAPERS_PER_CATEGORY=20
```

세션 끊겨도 유지하려면 `~/.bashrc` 또는 `mlops/.env` 파일에 저장 (`python-dotenv`가 자동 로드).

---

## STEP 7. 단위 테스트 (선택, 5분 이내)

```bash
pytest mlops/tests/test_crawler.py mlops/tests/test_load_embeddings.py -v
# 기대: 36 + 11 = 47 passed
# (test_crawler 36 = parse 7 + search 2 + round-robin 8 + HTTP retry 9 + fulltext layer retry 10)
```

⚠️ 실패하면 환경 설정 문제. 출력 확보 후 트러블슈팅.

---

## STEP 8. dry-run (NCBI 통신 + round-robin 검증)

```bash
python mlops/scripts/export_embeddings.py --max-papers 3 --dry-run
```

**기대 로그 마지막 4줄**:
```
INFO [mlops.pipeline.crawler] round-robin 결과: 신규 PMID 3건 (카테고리 다중 매칭 분포: 평균 X.X카테고리/논문)
INFO [mlops.pipeline.crawler] 크롤링 완료: 3건 (전문 포함 N건)
INFO [mlops.pipeline.chunker] 전체 청킹 완료: 논문 3편 → 청크 N개
INFO [__main__] [DRY RUN] 임베딩/파일 출력 생략
```

소요: NCBI key 있으면 ~20초, 없으면 ~1-2분.

---

## STEP 9. `export_embeddings.py` — 옵션 상세

```bash
python mlops/scripts/export_embeddings.py [옵션...]
```

| 옵션 | 타입 / 기본 | 설명 |
|---|---|---|
| `--max-papers N` | int / `MAX_PAPERS_PER_RUN` (300) | **전체 PMID 수집 상한**. round-robin으로 29 카테고리에서 균등 분배 |
| `--output PATH` | Path / `mlops/data/embeddings.jsonl` | 출력 파일 경로. **확장자 `.jsonl.gz`면 gzip 자동 적용** |
| `--gzip` | flag / False | 확장자 무관하게 gzip 강제 |
| `--dry-run` | flag / False | **크롤링 + 청킹만 수행**, 임베딩/파일 출력 생략 |
| `--min-date YYYY/MM/DD` | str / None | PubMed 출판일 하한 |
| `--max-date YYYY/MM/DD` | str / None | PubMed 출판일 상한 |
| `--update-manifest` | flag / **False** ⚠️ | **export 완료 후 즉시 `mlops/data/manifest.json` 갱신**. PR #63에서 기본 OFF로 변경됨. 적재 검증 후 별도 호출 권장 (이유: 적재 도중 실패 시 PMID가 manifest에 박혀 영구 누락되는 사고 방지) |

### 사용 예시

```bash
# 기본 본 실행 (gzip 자동)
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz

# 날짜 필터 (2023년 이후만)
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --min-date 2023/01/01 \
    --output mlops/data/recent.jsonl.gz

# 작은 샘플 (10편)
python mlops/scripts/export_embeddings.py \
    --max-papers 10 \
    --output mlops/data/sample.jsonl.gz

# dry-run (환경 검증)
python mlops/scripts/export_embeddings.py --max-papers 3 --dry-run

# 적재 검증 후 manifest 갱신 (재실행)
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz \
    --update-manifest
```

### manifest 동작

- `mlops/data/manifest.json`은 **처리 완료된 PMID 집합** 저장
- 다음 실행 시 manifest에 있는 PMID는 **자동 스킵** → 중복 처리 방지
- `--update-manifest` 미지정 시 manifest 변경 없음 → 동일 PMID 재크롤 가능 (개발/테스트 용도로 유용)

### 장시간 작업 백그라운드 실행

```bash
nohup python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz \
    > /tmp/export.log 2>&1 &
tail -f /tmp/export.log   # Ctrl+C로 빠져나와도 백그라운드 계속
```

⏱️ **소요 시간**:
- GPU (CUDA OK): ~3-5분 (BGE 첫 다운로드 ~3분 포함, 재실행 ~1-2분)
- CPU: ~15-20분

---

## STEP 10. 출력 파일 검증

```bash
zcat mlops/data/embeddings.jsonl.gz | wc -l   # 청크 수
zcat mlops/data/embeddings.jsonl.gz | head -1 | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
print('PMID:', d['paper_pmid'])
print('Dim:', len(d['embedding']))   # 1024여야 함
print('Cats:', d['search_categories'])
"
```

**검증 포인트**:
- 청크 수 > 0
- 임베딩 차원 = 1024
- `search_categories`에 카테고리 CSV 포함

---

## STEP 11. `load_embeddings.py` — 옵션 상세

```bash
python mlops/scripts/load_embeddings.py [옵션...]
```

| 옵션 | 타입 / 기본 | 설명 |
|---|---|---|
| `--input PATH` | Path / **필수** | `export_embeddings.py` 출력 파일. `.jsonl` 또는 `.jsonl.gz` 자동 감지 |
| `--mode {local,api}` | choice / `local` | **`local`**: `chromadb.PersistentClient`로 직접 적재 (`CHROMA_PERSIST_PATH` 사용). **`api`**: 서버 `POST /api/v1/admin/rag/ingest` 호출 (`API_BASE_URL` + `ADMIN_API_TOKEN` 필요) |
| `--batch-size N` | int / `100` | upsert 배치 크기. 메모리 타이트하면 줄이고, 네트워크 좋으면 늘림 (ChromaDB는 1000까지 안정적) |
| `--skip-errors` | flag / **False** | **PR #63 신규**. 기본은 fail-fast — 단일 라인 파싱 실패 시 즉시 raise. `--skip-errors` 지정 시 깨진 라인을 WARNING으로 로그하고 건너뜀. 종료 시 총 skip 라인 수 요약 |

### 사용 예시

```bash
# 로컬 개발/검증 (기본)
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local

# 부분 적재 허용 (대용량에서 일부 라인 깨졌을 때)
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local \
    --skip-errors

# 운영 ChromaDB 적재 (서버 admin endpoint)
export API_BASE_URL=https://api.scifit-sync.example.com
export ADMIN_API_TOKEN=<서버와_동일_값>
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode api

# 메모리 작은 인스턴스 (배치 크기 줄임)
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local \
    --batch-size 50
```

### `--mode local` vs `--mode api` 선택 기준

| 상황 | 권장 모드 | 비고 |
|---|---|---|
| 로컬 개발/검증 | `local` | `CHROMA_PERSIST_PATH` 디렉토리에 sqlite 생성 |
| GitHub Actions에서 운영 ChromaDB 적재 | `api` | 서버 admin endpoint 경유, EFS 직접 접근 불요 |
| 임시 클라우드에서 운영 적재 | `api` | 인스턴스가 EFS 접근 불가하면 필수 |
| 같은 인스턴스에 서버+적재 둘 다 | `local` | EFS 마운트 경로(`/chroma-data`) 그대로 사용 |

### `--skip-errors` 사용 가이드

- **기본(fail-fast) 권장**: 신선한 export 직후 1차 적재 — 오류 즉시 발견해서 export부터 다시
- **`--skip-errors` 권장**: 수천 청크 중 소수만 손상된 케이스. 대부분 살리고 나머지 별도 분석

---

## STEP 12. RAG 검색 검증

```bash
CHROMA_PERSIST_PATH=$PWD/mlops/data/chroma-data python3 - <<'PY'
import os, sys
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

**검증 포인트**:
- `총 청크` 값이 STEP 10 청크 수와 일치
- sim 값이 0.5~0.9 범위 (resistance training 도메인 쿼리 기준)
- 결과 metadata에 `search_categories` CSV 표시

---

## STEP 13. (선택) manifest 갱신

여기까지 모두 검증 끝났으면, 다음 실행에서 동일 PMID 중복 처리 방지를 위해 manifest 갱신:

```bash
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz \
    --update-manifest
```

> ⚠️ 이 단계는 **적재가 성공한 후에만**. 적재 전에 manifest를 갱신해두면, 적재 실패 시 PMID가 영구 누락됨.

---

## STEP 14. (선택, 운영 환경) 운영 ChromaDB 적재

```bash
export API_BASE_URL=https://api.scifit-sync.example.com
export ADMIN_API_TOKEN=<서버와_동일_값>

python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode api
```

`POST /api/v1/admin/rag/ingest` 호출. `--skip-errors` 동일 적용 가능.

---

## STEP 15. 대용량 적재 워크플로우 (1000편+ / 분할 + nohup 백그라운드)

500편 이상 한 번에 처리하면 시간이 길어서 SSH 끊김/메모리 압박/실패 리스크가 커진다. **500편씩 분할 + 각 배치 후 manifest 갱신 + nohup 백그라운드** 패턴이 검증된 안전 흐름.

### 15-1. 핵심 제약 — `MAX_PAPERS_PER_CATEGORY`

```
29 카테고리 × MAX_PAPERS_PER_CATEGORY = 후보 풀 크기
```

기본값 20 → 후보 풀 580. `--max-papers 2000`을 줘봐야 580에서 멈춤. **2000편 수집하려면 카테고리당 70 이상 필요** (29 × 70 = 2030).

```bash
export MAX_PAPERS_PER_CATEGORY=70
```

### 15-2. NCBI 키 외부 환경 파일 (보안 + 재사용)

스크립트 안에 키 박지 말고 별도 파일로 분리. **노출 사고 방지**.

```bash
vi ~/.scifit_env
```

vi에서 `i` → 아래 입력 → `Esc` → `:wq`:
```bash
export NCBI_API_KEY="발급받은_NCBI_키"
export MAX_PAPERS_PER_CATEGORY=70
```

권한 제한:
```bash
chmod 600 ~/.scifit_env
```

### 15-3. 분할 적재 스크립트 작성 (vi 권장 — heredoc은 따옴표 깨짐 잦음)

```bash
vi ~/run_2k.sh
```

vi에서 `i` 누르고 아래 내용 붙여넣기 → `Esc` → `:wq`:

```bash
#!/bin/bash
set -e
cd ~/capstone/scifit-sync
source .venv/bin/activate
source ~/.scifit_env

export CHROMA_PERSIST_PATH="$PWD/data/chroma-data"
export CHROMA_COLLECTION_NAME=paper_chunks

mkdir -p data

for i in 1 2 3 4; do
    OUT="data/embeddings_batch${i}.jsonl.gz"
    echo "=== 배치 $i 시작 $(date) ==="

    python mlops/scripts/export_embeddings.py \
        --max-papers 500 \
        --output "$OUT" || { echo "[배치 $i] export 실패, 중단"; exit 1; }

    python mlops/scripts/load_embeddings.py \
        --input "$OUT" --mode local --skip-errors || { echo "[배치 $i] 적재 실패, 중단"; exit 1; }

    python mlops/scripts/export_embeddings.py \
        --max-papers 500 \
        --output "$OUT" \
        --update-manifest || { echo "[배치 $i] manifest 갱신 실패, 중단"; exit 1; }

    echo "=== 배치 $i 완료 $(date) ==="
done
echo "=== 전체 완료 $(date) ==="
```

권한 + 문법 검증:
```bash
chmod +x ~/run_2k.sh
bash -n ~/run_2k.sh && echo "syntax OK"
```

**`syntax OK`** 안 뜨면 파일이 깨진 거. `cat ~/run_2k.sh`로 확인 후 다시 `vi`로 수정.

### 15-4. nohup 백그라운드 실행

```bash
nohup ~/run_2k.sh > /tmp/run_2k.log 2>&1 &
pgrep -f "run_2k.sh" > /tmp/run_2k.pid
echo "PID: $(cat /tmp/run_2k.pid)"
```

> ⚠️ `echo "PID: $!" | tee /tmp/run_2k.pid` 패턴은 PID 파일에 `PID: 12345` 형태 텍스트가 박혀서 이후 `ps -p $(cat ...)` 가 파싱 실패한다. **`pgrep -f "run_2k.sh" > /tmp/run_2k.pid`로 숫자만 저장**해야 안전.

### 15-5. 모니터링

```bash
# 살아있는지 (숫자만 있는 PID 파일 기준)
ps -p $(cat /tmp/run_2k.pid) && echo "ALIVE" || echo "DEAD"

# 또는 직접 검색 (PID 파일 신뢰 안 해도 됨)
pgrep -af "run_2k.sh"

# 실시간 로그
tail -f /tmp/run_2k.log

# 마일스톤만 빠르게
grep -E "배치.*시작|배치.*완료|메타데이터 수집:|크롤링 완료|청킹 완료|Export 완료|적재 완료|실패|전체 완료" /tmp/run_2k.log

# 출력 파일 변화
ls -lah ~/capstone/scifit-sync/data/embeddings_batch*.jsonl.gz 2>/dev/null
```

### 15-6. SSH 끊김 / 재접속 시나리오

`nohup`이므로 SSH 끊어도 백그라운드 작업 계속. 재접속 후:

```bash
# 살아있는지 확인
pgrep -af "run_2k.sh"

# 로그 어디까지 진행됐는지
tail -50 /tmp/run_2k.log

# 출력 파일 어디까지 만들어졌는지
ls -lah ~/capstone/scifit-sync/data/embeddings_batch*.jsonl.gz
```

**프로세스가 죽었으면** 마지막 완료된 배치를 확인 후 그 다음부터 재실행:
```bash
# 예: 배치 2까지 완료, 배치 3에서 죽은 경우
# manifest엔 배치 1, 2의 PMID가 박혀있으므로
# 그냥 ~/run_2k.sh 재실행하면 manifest 덕에 같은 PMID는 스킵됨
nohup ~/run_2k.sh > /tmp/run_2k.log 2>&1 &
pgrep -f "run_2k.sh" > /tmp/run_2k.pid
```

⚠️ 단, 인스턴스 자체가 셧다운돼서 `~/capstone/...`이 ephemeral volume이면 코드/데이터 둘 다 소실. `mount | grep capstone`으로 영구 볼륨인지 미리 확인.

### 15-7. 중단

```bash
kill $(cat /tmp/run_2k.pid)
# 안 죽으면 강제
kill -9 $(cat /tmp/run_2k.pid)
```

### 15-8. 완료 후 통계 확인

전체 끝나면 abstract-only 비중과 PMID 다양성 측정:

```bash
zcat data/embeddings_batch*.jsonl.gz | python3 -c "
import json, sys
from collections import Counter

pmid_sections = {}
for line in sys.stdin:
    d = json.loads(line)
    pmid = d['paper_pmid']
    section = d.get('section_name', 'unknown')
    pmid_sections.setdefault(pmid, set()).add(section)

total = len(pmid_sections)
abstract_only = sum(1 for s in pmid_sections.values() if s == {'Abstract'})
print(f'전체 PMID: {total}')
print(f'전문 포함: {total - abstract_only} ({(total-abstract_only)/total*100:.1f}%)')
print(f'abstract만: {abstract_only} ({abstract_only/total*100:.1f}%)')
"
```

성공률 < 50%면 시간대 바꿔 재실행하거나 NCBI 안정성 강화 PR 검토 (`mlops-pipeline-test.md` "알려진 한계" 참고).

### 15-9. 시간 예상 (GPU 인스턴스, cu121 매칭 후)

| 단계 | 배치당 (500편) | 4배치 합계 |
|---|---|---|
| esearch + 메타데이터 (NCBI key 있음) | ~3분 | ~12분 |
| PMC 전문 fetch | ~10-15분 | ~40-60분 |
| 청킹 (CPU) | ~30초 | ~2분 |
| BGE 임베딩 (GPU) | ~5-7분 | ~25분 |
| ChromaDB 적재 + manifest 갱신 (재 fetch 포함) | ~10-15분 | ~50분 |
| **배치 합계** | **~30-40분** | **~2-2.5시간** |

CPU 인스턴스는 임베딩 단계만 ~4배 더 걸려 총 3-4시간 예상.

---

# 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `Unable to locate package python3.X-venv` | apt 캐시 누락 또는 버전 오타 | `apt update` 후 정확한 버전(`python3.11-venv`) |
| `externally-managed-environment` (PEP 668) | 시스템 Python 보호 (Ubuntu 24.04+) | venv 사용 (STEP 3) |
| `cuda: False` + "driver too old" | PyTorch CUDA 빌드 > 시스템 드라이버 | `nvidia-smi` 확인 → 맞는 `cuXXX` 빌드로 재설치 (STEP 5 케이스 B) |
| NCBI 4xx/5xx 산발 | transient 네트워크 | HTTP layer가 **5회** 자동 재시도(backoff 10s cap). 그래도 실패하면 abstract fallback (RAG 동작 무영향). 더 강하게 → `--http-retries 8` 또는 `NCBI_HTTP_MAX_RETRIES=8` |
| HuggingFace 다운로드 느림 | rate limit | `export HF_TOKEN=<token>` 추가 |
| BGE OOM | RAM < 2GB | 더 큰 인스턴스 또는 GPU |
| `col.count() == 0` | 적재 실패 | `--skip-errors` 없이 다시 실행 → 정확한 에러 라인 확인 |
| `PMC elink JSON 파싱 실패 (시도 N/3)` 로그 | NCBI가 HTTP 200으로 응답했지만 body가 깨진 케이스 | 함수 layer가 **3회** 자동 재시도 (50편 dry-run 기준 92%가 1-2회 재시도 내 복구). 끝까지 실패하면 abstract fallback. 더 강하게 → `--fulltext-attempts 5` 또는 `PMC_FULLTEXT_MAX_ATTEMPTS=5` |
| `NCBI 요청 재시도 N/5 (... 백오프): Response ended prematurely` 반복 | NCBI 측 throttling 또는 chunked response 끊김 | 자동 재시도(5회) 후에도 실패하면 abstract fallback 작동 — 그대로 진행. 빈도 높으면 시간대 바꿔 재실행 (한국 낮 = 미국 새벽 = NCBI 한산) |
| `전문 수집 최종 실패 — abstract fallback` 로그 | HTTP/함수 layer retry를 모두 소진한 PMID | 정상 동작 (abstract만 청킹). 끝부분 `전문 수집 최종 실패(abstract fallback) 누적: N건` 라인으로 batch 단위 카운트 확인 |
| `bash: line N: python: command not found` (nohup 안에서) | nohup이 새 셸이라 venv 미상속 + wd 다름 | 스크립트 안에 `cd ~/capstone/scifit-sync && source .venv/bin/activate` 명시 (STEP 15-3) |
| `bash: -c: line N: unexpected EOF while looking for matching` | heredoc/quote 깨짐 (특히 한글이나 키 직접 박을 때) | heredoc 대신 vi로 파일 직접 편집 (STEP 15-3) |
| `ps -p ...: process ID list syntax error` + 항상 `DEAD` 출력 | PID 파일에 `PID: 12345` 텍스트가 박혀 ps가 파싱 실패 | `pgrep -f "run_2k.sh" > /tmp/run_2k.pid` 로 **숫자만** 저장 (STEP 15-4) |
| NCBI API key가 채팅/로그에 노출됨 | 스크립트에 직접 박았다가 공유 | 즉시 [NCBI 계정](https://www.ncbi.nlm.nih.gov/account/settings/)에서 재발급 + 폐기. 이후 `~/.scifit_env` 외부 파일 패턴 사용 (STEP 15-2) |

---

# 한 번에 복붙 — 풀 흐름

```bash
# === 1회 셋업 ===
cd ~/capstone/scifit-sync
git checkout develop && git pull origin develop
apt install -y python3.11 python3.11-venv
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r mlops/requirements.txt

# (GPU 인스턴스만) 드라이버에 맞는 torch
pip uninstall -y torch torchvision torchaudio
pip install torch --index-url https://download.pytorch.org/whl/cu121

# === 매 세션 ===
source .venv/bin/activate

# 필수 환경변수
export CHROMA_PERSIST_PATH=$PWD/mlops/data/chroma-data   # 로컬 ChromaDB 경로
export CHROMA_COLLECTION_NAME=paper_chunks               # 컬렉션명 (운영과 동기화)

# 권장 환경변수
export NCBI_API_KEY=<발급키>                              # rate limit 3→10 req/s
export MAX_PAPERS_PER_RUN=300                            # 1회 실행 PMID 상한
export MAX_PAPERS_PER_CATEGORY=20                        # 카테고리당 후보 상한

# === 검증 → 실행 ===
pytest mlops/tests/test_crawler.py mlops/tests/test_load_embeddings.py -v

# dry-run (NCBI 통신 확인)
python mlops/scripts/export_embeddings.py --max-papers 3 --dry-run

# 본 실행 (--update-manifest 기본 OFF, 적재 검증 후 별도 호출)
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz

# 로컬 적재 (fail-fast 기본, 부분 적재 허용은 --skip-errors)
python mlops/scripts/load_embeddings.py \
    --input mlops/data/embeddings.jsonl.gz \
    --mode local

# RAG 검색 검증 (STEP 12 스크립트 사용)

# 모두 검증되면 manifest 갱신
python mlops/scripts/export_embeddings.py \
    --max-papers 100 \
    --output mlops/data/embeddings.jsonl.gz \
    --update-manifest
```

**1000편 이상 대용량은 분할 + nohup 패턴 사용 →** [STEP 15](#step-15-대용량-적재-워크플로우-1000편-분할--nohup-백그라운드)

---

## 참고

- **상세 검증 절차 / 알려진 한계**: [`mlops-pipeline-test.md`](./mlops-pipeline-test.md)
- **배포 / CI 흐름**: [`deployment.md`](./deployment.md)
- **서버 admin endpoint**: `server/app/api/v1/admin.py:55` (`POST /api/v1/admin/rag/ingest`)
- **운영 ECS 제약** (Task count=1, EFS `/chroma-data`): `CLAUDE.md` §15
