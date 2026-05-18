#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$0")"

echo "=== Local 2000 papers (500 x 4 batches) 시작: $(date) ==="

for i in 1 2 3 4; do
  echo ""
  echo "=== Batch $i/4 시작: $(date) ==="

  python3 -m scripts.export_embeddings \
    --max-papers 500 \
    --max-per-category 15 \
    --output "data/embeddings_local_batch${i}.jsonl.gz" \
    --gzip \
    --update-manifest

  if [ $? -ne 0 ]; then
    echo "!!! Batch $i 실패: $(date)"
    exit 1
  fi

  echo "=== Batch $i 완료: $(date) ==="
done

echo ""
echo "=== 전체 완료: $(date) ==="
echo ""
echo "결과 파일:"
ls -lh data/embeddings_local_batch*.jsonl.gz
echo ""
echo "Manifest:"
python3 -c "import json; m=json.load(open('data/manifest.json')); print(f'  누적 PMIDs: {m[\"count\"]}')"
