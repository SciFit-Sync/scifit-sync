#!/usr/bin/env bash
# Local 2000 papers (500 x 4 batches) — default 모드 단일 모델 임베딩
# 산출물 경로는 export_embeddings가 batch-tag 기반으로 자동 결정한다:
#   mlops/data/chunks/local_batchN.jsonl.gz
#   mlops/data/emb_bge-large/local_batchN.jsonl.gz
#   mlops/data/emb_bge-large/local_batchN_timing.json

set -uo pipefail

cd "$(dirname "$0")/.."   # repo root

MODEL="${MODEL:-bge-large}"

echo "=== Local 2000 papers (500 x 4 batches, model=$MODEL) 시작: $(date) ==="

for i in 1 2 3 4; do
  echo ""
  echo "=== Batch $i/4 시작: $(date) ==="

  python3 -m mlops.scripts.export_embeddings \
    --model "$MODEL" \
    --batch-tag "local_batch${i}" \
    --max-papers 500 \
    --max-per-category 15 \
    --update-manifest

  rc=$?
  if [ $rc -ne 0 ]; then
    echo "!!! Batch $i 실패 (rc=$rc): $(date)"
    exit 1
  fi

  echo "=== Batch $i 완료: $(date) ==="
done

echo ""
echo "=== 전체 완료: $(date) ==="
echo ""
echo "결과 파일 (emb):"
ls -lh "mlops/data/emb_${MODEL}/local_batch"*.jsonl.gz 2>/dev/null || echo "  (없음)"
echo ""
echo "Timing 사이드카:"
ls -lh "mlops/data/emb_${MODEL}/local_batch"*_timing.json 2>/dev/null || echo "  (없음)"
echo ""
echo "Manifest:"
python3 -c "import json; m=json.load(open('mlops/data/manifest.json')); print(f'  누적 PMIDs: {m[\"count\"]}')"
