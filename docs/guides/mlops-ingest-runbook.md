# MLOps 클라우드 Ingest 운영 Runbook (65 카테고리 기준)

> **대상**: 클라우드 인스턴스에서 `develop` pull → env 설정 → 본 ingest → 메타 동기화 → RAG 검증까지 **한 번에** 돌리고 싶을 때.
> **소요 시간**: 사전 점검 5분 + 본 ingest 1.5–6시간 (GPU/CPU) + 메타 동기화 3–5분.
> **자세한 옵션·트러블슈팅**: `mlops-cloud-quickstart.md`, `mlops-query-categories.md` 참조.

---

## 0. 사전 조건 (1회만)

| 항목 | 발급/확인 |
|---|---|
| **NCBI API 키** | https://account.ncbi.nlm.nih.gov → Settings → API Key Management (무료, 10분) |
| **운영 백엔드 ADMIN_API_TOKEN** | DevOps 또는 ECS task definition의 `.env` 값 확인 |
| **운영 백엔드 API_BASE_URL** | 예: `https://api.scifit-sync.example.com` |
| **클라우드 인스턴스 SSH 접근** | ingest를 실행할 별도 EC2/GCE 인스턴스 |

---

## STEP 1. 코드 최신화

```bash
cd ~/scifit-sync
git fetch origin
git checkout develop
git pull origin develop
```

> PR #70이 develop에 머지되어 있는지 확인. 머지 전이면 `git checkout feature/jingyu/mlops-query-expansion`.

---

## STEP 2. 환경 변수 설정

`~/.scifit_env`에 한 번 작성해두면 매 실행마다 `source`만 하면 됩니다.

```bash
vi ~/.scifit_env
```

```bash
# === NCBI ===
# rate limit 1s → 0.34s, PMC 전문 회수율 +20%p
export NCBI_API_KEY="발급받은_NCBI_키"

# === 운영 백엔드 (적재 API 호출용) ===
export API_BASE_URL="https://api.scifit-sync.example.com"
export ADMIN_API_TOKEN="발급받은_admin_토큰"

# === ingest 파라미터 (CLI로 override 가능, 기본값 그대로면 생략) ===
export MAX_PAPERS_PER_RUN=2000          # 한 번에 신규 PMID 상한
export MAX_PAPERS_PER_CATEGORY=50       # 65 × 50 = 후보 풀 3,250

# === ChromaDB / 임베딩 (RAG 서비스도 같은 값을 봐야 함) ===
export CHROMA_PERSIST_PATH=/chroma-data
export CHROMA_COLLECTION_NAME=paper_chunks
export EMBEDDING_MODEL="BAAI/bge-large-en-v1.5"
```

권한 + 적용:

```bash
chmod 600 ~/.scifit_env
source ~/.scifit_env
```

확인:

```bash
echo "NCBI_API_KEY: ${NCBI_API_KEY:0:4}..."
echo "API_BASE_URL: $API_BASE_URL"
echo "ADMIN: ${ADMIN_API_TOKEN:0:4}..."
```

---

## STEP 3. 운영 ChromaDB 상태 점검 (선택)

```bash
curl -s "$API_BASE_URL/api/v1/admin/rag/pmids" \
    -H "X-Admin-Token: $ADMIN_API_TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
print(f'기존 적재: PMID {d[\"count\"]}편 / 청크 {d[\"total_chunks\"]}개')"
```

→ 0이면 첫 적재, 109k 같은 큰 수면 기존 적재 위에 증분 추가됨.

---

## STEP 4. 본 ingest 실행 (백그라운드)

65 카테고리에서 2,000편 신규 수집:

```bash
nohup python3 -m mlops.scripts.initial_ingest \
    --max-papers 2000 \
    --max-per-category 50 \
    > /tmp/ingest.log 2>&1 &

pgrep -f "initial_ingest" > /tmp/ingest.pid
echo "PID: $(cat /tmp/ingest.pid)"
```

소요 시간:

| 인스턴스 | 임베딩 단계 | 총 |
|---|---|---|
| GPU (CUDA 12.x) | ~25분 | **1.5–2시간** |
| CPU | ~100분 | **4–6시간** |

모니터링:

```bash
# 핵심 로그만
tail -f /tmp/ingest.log | grep -E "검색 결과|크롤링 완료|청킹 완료|적재 완료|실패"

# 전체 로그
tail -f /tmp/ingest.log
```

생존 확인:

```bash
ps -p $(cat /tmp/ingest.pid) && echo "ALIVE" || echo "DEAD"
```

SSH 끊겨도 안전 — manifest 기반 자동 dedup이라 재실행하면 같은 PMID는 skip됨.

---

## STEP 5. 메타 동기화 (옛 카테고리 메타가 있을 때만 1회)

운영 ChromaDB에 옛 (29 / 100 카테고리 시절) 메타가 남아있다면 65 기준으로 재매핑:

```bash
# 미리 보기 (API 호출 없음)
python3 -m mlops.scripts.refresh_search_categories --dry-run

# 본 실행 (~3-5분)
python3 -m mlops.scripts.refresh_search_categories
```

> 이 단계는 카테고리 변경 후 RAG가 새 카테고리 가중치로 검색하려면 **필수**.
> 한 번만 돌리면 끝. 다음 carb monthly ingest는 자동으로 새 메타로 적재됨.

---

## STEP 6. RAG 검증

### 6-A. 빠른 검증 — ChromaDB 직접 query

```bash
python3 <<'PY'
import chromadb
import os

client = chromadb.PersistentClient(path=os.environ.get("CHROMA_PERSIST_PATH", "/chroma-data"))
col = client.get_collection(os.environ.get("CHROMA_COLLECTION_NAME", "paper_chunks"))

print(f"총 청크: {col.count():,}")

# 한국어 → 영어 변환 없이 영어로 직접 검색
res = col.query(
    query_texts=["bench press hypertrophy optimal volume sets"],
    n_results=3,
)
for i, (doc, meta) in enumerate(zip(res["documents"][0], res["metadatas"][0]), 1):
    print(f"\n--- {i} ---")
    print(f"PMID: {meta['paper_pmid']} | 카테고리: {meta['search_categories']}")
    print(doc[:250])
PY
```

기대: `chest_training`, `hypertrophy_strength`, `volume`, `intensity` 같은 새 카테고리가 결과 메타에 보여야 함.

### 6-B. End-to-end — 챗봇 API 검증

```bash
# JWT 토큰은 실제 사용자 로그인으로 발급 (또는 테스트용 토큰)
curl -X POST "$API_BASE_URL/api/v1/chat/messages" \
    -H "Authorization: Bearer <테스트_JWT>" \
    -H "Content-Type: application/json" \
    -d '{"message": "벤치프레스 근비대를 위한 적정 세트와 반복은?", "session_id": "test-runbook"}'
```

응답 SSE 스트림에 논문 출처 카드가 포함되면 정상.

---

## STEP 7. 마무리 점검

```bash
# 적재 통계
grep -E "크롤링 완료|적재 완료|총" /tmp/ingest.log | tail

# manifest
python3 -c "import json; print('manifest 총 PMID:', json.load(open('mlops/data/manifest.json'))['count'])"

# 운영 DB 상태
curl -s "$API_BASE_URL/api/v1/admin/rag/pmids" -H "X-Admin-Token: $ADMIN_API_TOKEN" | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
print(f'운영 ChromaDB: PMID {d[\"count\"]}편 / 청크 {d[\"total_chunks\"]}개')"
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| PMC 회수율 < 50% (로그 "전문 포함 X건") | NCBI_API_KEY 누락 / InvalidChunkLength 다발 | `.scifit_env`에 키 추가 + `--http-retries 8 --fulltext-attempts 5` |
| 카테고리당 검색이 20건만 (cap 부족) | `MAX_PAPERS_PER_CATEGORY` 기본값(20) | `--max-per-category 50` CLI 명시 |
| ingest 도중 SSH 끊김 | 네트워크 | 그냥 다시 `bash` — manifest 자동 dedup |
| 메타 동기화 후에도 RAG가 옛 카테고리만 사용 | 백엔드 서비스 캐시 | `docker compose restart server` 또는 ECS task 재시작 |
| `403 Admin 인증이 필요합니다` | `ADMIN_API_TOKEN` 불일치 | 운영 백엔드 env와 동일 값 확인 |
| ChromaDB 권한 에러 | `/chroma-data` mount 누락 (로컬 테스트) | `CHROMA_PERSIST_PATH=./chroma-data` 로컬 경로로 |

---

## 운영 사이클 정리

| 시점 | 액션 |
|---|---|
| **카테고리 변경 시 (drop/add/어휘 수정)** | `refresh_search_categories.py` 1회 |
| **매월 자동** | GitHub Actions `monthly-ingest.yml` (`monthly_ingest.py`로 신규 35일치 PMID 추가) |
| **수동 대량 적재** | 본 Runbook의 STEP 1–6 |
| **새 카테고리 추가 후 운영 반영** | crawler.py 수정 → PR → develop 머지 → 본 Runbook STEP 5만 실행 (신규 PMID는 다음 monthly로 들어옴) |
