#!/bin/bash
set -uo pipefail

# repo root로 이동 (mlops가 패키지로 설치되어 있지 않으므로
# `python3 -m mlops.scripts.export_embeddings`가 import를 해석하려면
# sys.path[0]에 repo root가 있어야 한다).
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$SCRIPT_DIR/.."

# venv 자체 활성화 (nohup/cron 안전)
VENV=".venv-gpu"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "!!! venv not found at $VENV — aborting" >&2
  exit 2
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate" || { echo "!!! venv activate failed" >&2; exit 2; }

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

mkdir -p mlops/data
TS=$(date +%Y%m%d_%H%M%S)
TAG="3k_${TS}"
LOG="mlops/data/ingest_${TAG}.log"

{
  echo "=== 3000편 단일 배치 ingest 시작: $(date) ==="
  echo "PID=$$  TAG=$TAG  PWD=$(pwd)  VENV=$VIRTUAL_ENV"
  echo "MANIFEST(before)=$(python3 -c 'import json; m=json.load(open("mlops/data/manifest.json")); print(m.get("stats",{}))')"
  echo "---"
} | tee -a "$LOG"

python3 -m mlops.scripts.export_embeddings \
  --batch-tag "$TAG" \
  --model bge-large \
  --max-papers 3000 \
  --max-per-category 600 \
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
    find mlops/data -name "*${TAG}*" -type f -exec ls -lh {} \;
    echo "MANIFEST(after)=$(python3 -c 'import json; m=json.load(open("mlops/data/manifest.json")); print(m.get("stats",{}))')"
  fi
} | tee -a "$LOG"

exit "$RC"
