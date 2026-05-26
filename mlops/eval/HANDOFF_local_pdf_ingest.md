# 핸드오프: 로컬 PDF ingest + 골드셋 A/B 평가 + 전체 upsert

> 최종 업데이트: 2026-05-27 00:15 KST
> 브랜치: `feat/jingyu/local-pdf-ingest`
> GPU 서버: `ssh gpu` (cscloud.gpu3.hufs.ac.kr:30007, venv: `.venv-gpu`)

---

## 1. 완료된 작업

### 1.1 manifest.json 작성 (184개 논문)
- **3단계 자동 검증**: draft manifest (43편) → CrossRef API 검증 → pdf_topic_report DOI 병합
- 사용자 수동 확인 6편 DOI 추가
- 최종: **184 unique DOI** (CrossRef 검증 완료)
- 파일: `mlops/data/local_pdfs/manifest.json`

### 1.2 임베딩 생성 (bge-large)
- **15,361 chunks** → 1024차원 bge-large 벡터
- GPU 서버 산출물: `mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz` (139MB)
- chunks: `mlops/data/chunks/local_pdf_ingest.jsonl.gz` (3.5MB)

### 1.3 프로덕션 upsert (local_pdf_ingest)
- `load_embeddings.py --mode api` → **184 DOIs upsert 완료**
- `load_embeddings.py` 버그 수정: `paper_doi` 등 5개 필드 누락 → `9f38bff`

### 1.4 골드셋 최신화
- `goldset.jsonl` → `expected_dois` 필드 추가 (PMID→DOI 변환)
- 코퍼스 미커버 14개 질문 제거: **85 → 71 questions**, `corpus_coverage=1.0`

### 1.5 run_eval.py PMID∪DOI 매칭 확장
- `evaluate_query`: PMID 또는 DOI 중 하나라도 매칭이면 hit
- `_recall_at_k_union`, `_mrr_union` 헬퍼 추가
- 기존 PMID-only 테스트 호환 (`expected_dois` 기본값 빈 튜플)
- 459 tests pass

### 1.6 커밋 이력
| 커밋 | 내용 |
|------|------|
| `fcc6f9e` | manifest.json 184개 논문 |
| `9f38bff` | load_embeddings payload 버그 수정 |
| `1be47c0` | 핸드오프 문서 + upsert 결과 |
| `881fee2` | 골드셋 DOI 매칭 확장 + run_eval union recall |
| `c60ccd5` | 골드셋 미커버 질문 제거 (85→71) |

---

## 2. 실행 중 (GPU 서버 nohup)

### 스크립트: `run_ab_eval_and_upsert.sh`
### 로그: `/mnt/data/scifit-sync/ab_eval_and_upsert.log`

```
Phase 1: Re-embedding (3k_060614 + local_pdf → bge-base, pubmedbert)
Phase 2: Merge (noise + goldset per model)
Phase 3: A/B Eval (3모델 × 골드셋 71 questions)
Phase 4: Full upsert (legacy + 3k batches → production)
```

### Phase 1 — 재임베딩
| 단계 | chunks | 모델 | 예상 시간 |
|------|--------|------|-----------|
| 1a. 3k_060614 | 476,547 | bge-base | ~8분 |
| 1b. 3k_060614 | 476,547 | pubmedbert-msmarco | ~8분 |
| 1c. local_pdf | 15,361 | bge-base | ~2분 |
| 1d. local_pdf | 15,361 | pubmedbert-msmarco | ~2분 |

### Phase 2 — 합치기
모델별 `ab_eval_merged.jsonl.gz` = `3k_060614` (노이즈 1,812 DOIs) + `local_pdf` (골드셋 184 DOIs)

### Phase 3 — A/B 평가
| 모델 | 임베딩 차원 | 리포트 |
|------|------------|--------|
| bge-large | 1024 | `mlops/eval/reports/ab_bge-large.md` |
| bge-base | 768 | `mlops/eval/reports/ab_bge-base.md` |
| pubmedbert-msmarco | 768 | `mlops/eval/reports/ab_pubmedbert-msmarco.md` |

메트릭: recall@5, recall@10, MRR (전체 + 카테고리별)

### Phase 4 — 전체 프로덕션 upsert (bge-large)
| 파일 | chunks | DOIs |
|------|--------|------|
| embeddings_3k_batch1-11 | 1,130,165 | 4,305 |
| emb_bge-large/3k_20260522_060614 | 476,547 | 1,812 |
| emb_bge-large/3k_20260522_152209 | 476,932 | 1,704 |
| **합계** | **2,083,644** | **~7,821** |

기존 local_pdf 184 DOIs 포함 → 최종 프로덕션: **~7,910 unique DOIs**

---

## 3. 확인 필요 사항 (내일)

### 3.1 A/B 평가 결과 확인
```bash
ssh gpu
cat /mnt/data/scifit-sync/scifit-sync/mlops/eval/reports/ab_bge-large.md
cat /mnt/data/scifit-sync/scifit-sync/mlops/eval/reports/ab_bge-base.md
cat /mnt/data/scifit-sync/scifit-sync/mlops/eval/reports/ab_pubmedbert-msmarco.md
```

### 3.2 upsert 완료 확인
```bash
ssh gpu 'cd /mnt/data/scifit-sync/scifit-sync && .venv-gpu/bin/python3 -c "
from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL
import requests
r = requests.get(API_BASE_URL + \"/api/v1/admin/rag/dois\", headers={\"X-Admin-Token\": ADMIN_API_TOKEN}, timeout=10)
print(r.json()[\"data\"][\"count\"], \"DOIs in production\")
"'
```
기대값: ~7,910

### 3.3 에러 발생 시
```bash
# 로그 전체 확인
ssh gpu "cat /mnt/data/scifit-sync/ab_eval_and_upsert.log"

# 특정 phase에서 실패했으면 해당 부분만 재실행
ssh gpu "tail -50 /mnt/data/scifit-sync/ab_eval_and_upsert.log | grep -i error"
```

---

## 4. 임베딩 데이터 파일 맵

### 프로덕션용 (bge-large)
| 파일 | 용도 |
|------|------|
| `embeddings_3k_batch1-11.jsonl.gz` | 레거시 코퍼스 (4,305 DOIs) |
| `emb_bge-large/3k_20260522_060614.jsonl.gz` | curated batch A (1,812 DOIs) |
| `emb_bge-large/3k_20260522_152209.jsonl.gz` | curated batch B (1,704 DOIs) |
| `emb_bge-large/local_pdf_ingest.jsonl.gz` | 골드셋 보강 (184 DOIs) |

### A/B 평가용
| 파일 | 용도 |
|------|------|
| `emb_*/ab_eval_merged.jsonl.gz` | 노이즈(1,812) + 골드셋(184) 합본 |

### 아카이브 대상
| 파일 | 이유 |
|------|------|
| `emb_*/3k_curated_merged.*` | merged 대신 개별 파일 사용 |
| `emb_*/curated_20260523_*` | 내용 품질 이슈로 제외 |
| `chunks/3k_20260523_204636.*` | 구버전 intermediate |
| `chunks/prod_smoke_*` | 테스트용 |

---

## 5. 알려진 제약

- `load_embeddings.py`는 manifest 업데이트를 하지 않음 — ChromaDB에는 들어가지만 `curated_provenance.json` 미반영
- legacy batch의 `search_categories`가 구버전 (덜 세분화). 나중 파일이 같은 DOI를 덮어쓰면 새 카테고리로 교체됨
- 전체 upsert 시 2.1M chunks × HTTP POST → 수십 분~수 시간 소요
- OOM 방지: 항상 `--batch-size 200 --skip-errors` 사용
