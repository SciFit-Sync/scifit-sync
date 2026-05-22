#!/bin/bash
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# venv 자체 활성화 (nohup/cron 안전)
VENV="../.venv-gpu"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "!!! venv not found at $VENV — aborting" >&2
  exit 2
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 의존성 + GPU 사전 점검
python3 - <<'PY' || exit 3
import sys, os
import pydantic, chromadb, sentence_transformers, torch
print(f"venv={os.environ.get('VIRTUAL_ENV','?')}")
print(f"torch={torch.__version__} cuda={torch.cuda.is_available()} device_count={torch.cuda.device_count()}")
if not torch.cuda.is_available():
    print("!!! CUDA unavailable — abort", file=sys.stderr); sys.exit(3)
print(f"gpu0={torch.cuda.get_device_name(0)}")
print("deps OK")
PY

mkdir -p data
TS=$(date +%Y%m%d_%H%M%S)
TAG="2k_${TS}"
LOG="data/ingest_${TAG}.log"

{
  echo "=== 2000편 단일 배치 ingest 시작: $(date) ==="
  echo "PID=$$  TAG=$TAG  PWD=$(pwd)  VENV=$VIRTUAL_ENV"
  echo "MANIFEST(before)=$(python3 -c 'import json; m=json.load(open(\"data/manifest.json\")); print(m.get(\"stats\",{}))')"
  echo "---"
} | tee -a "$LOG"

python3 -m scripts.export_embeddings \
  --batch-tag "$TAG" \
  --model bge-large \
  --max-papers 2000 \
  --max-per-category 400 \
  --update-manifest \
  --require-gpu 2>&1 | tee -a "$LOG"

RC=${PIPESTATUS[0]}

{
  echo "---"
  if [ "$RC" -ne 0 ]; then
    echo "!!! 실패 (rc=$RC): $(date)"
  else
    echo "=== 성공: $(date) ==="
    echo "산출물 후보:"
    find data -name "*${TAG}*" -type f -exec ls -lh {} \;
    echo "MANIFEST(after)=$(python3 -c 'import json; m=json.load(open(\"data/manifest.json\")); print(m.get(\"stats\",{}))')"
  fi
} | tee -a "$LOG"

exit "$RC"
