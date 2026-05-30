#!/bin/bash
# 야간 무인 자동화: Curated paper export-batch → build_goldset → run_3k.sh 직렬 실행.
# flock 공유 자원 (mlops/data/.ingest.lock)으로 인해 직렬 실행이 필수.
#
# 사용:
#   nohup bash mlops/run_curated_then_3k.sh > /dev/null 2>&1 &
#   echo "PID=$!"
#
# 산출물 로그: mlops/data/combined_<TS>.log
#   step별 rc를 같은 로그에 기록.

set -euo pipefail

# repo root로 이동
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$SCRIPT_DIR/.."

LOCK="mlops/data/.ingest.lock"
mkdir -p mlops/data
exec 9>"$LOCK"
flock -n 9 || { echo "!!! another ingest is running (lock: $LOCK) — aborting" >&2; exit 1; }

VENV=".venv-gpu"
if [ ! -f "$VENV/bin/activate" ]; then
  echo "!!! venv not found at $VENV — aborting" >&2
  exit 2
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate" || { echo "!!! venv activate failed" >&2; exit 2; }

TS=$(date +%Y%m%d_%H%M%S)
LOG="mlops/data/combined_${TS}.log"

# 모든 출력을 로그에 누적
exec > >(tee -a "$LOG") 2>&1

echo "=== Combined run 시작: $(date) PID=$$ TAG=curated_${TS} ==="

# -------- Step 1: Curated paper ingest --export-batch (chunks + embeddings 파일 출력) --------
echo ""
echo "=== Step 1: ingest_curated_pmids --export-batch ==="
python3 -m mlops.scripts.ingest_curated_pmids \
  --provenance mlops/data/curated_provenance.json \
  --export-batch "curated_${TS}" \
  --embed-model bge-large
RC1=$?
echo ">>> Step 1 rc=$RC1"

# -------- Step 2: build_goldset (Method B: matchable expected_pmids) --------
echo ""
echo "=== Step 2: build_goldset ==="
python3 -m mlops.scripts.build_goldset \
  --seed mlops/eval/goldset_seed.jsonl \
  --provenance mlops/data/curated_provenance.json \
  --goldset mlops/eval/goldset.jsonl \
  --summary mlops/eval/goldset_summary.md
RC2=$?
echo ">>> Step 2 rc=$RC2"

# -------- Step 3: run_3k.sh (A 파이프라인 3000편 search-driven crawler) --------
# run_3k.sh가 자체 venv activate를 시도하지만, 이미 같은 venv가 활성화돼 있어도 안전 (idempotent).
echo ""
echo "=== Step 3: run_3k.sh ==="
bash mlops/run_3k.sh
RC3=$?
echo ">>> Step 3 rc=$RC3"

echo ""
echo "=== Combined done: $(date) ==="
echo "RC1=$RC1 (curated ingest) RC2=$RC2 (build_goldset) RC3=$RC3 (run_3k.sh)"

# 가장 큰 rc만 exit 코드로 노출 (모니터링 편의)
exit $(( RC1 > RC2 ? (RC1 > RC3 ? RC1 : RC3) : (RC2 > RC3 ? RC2 : RC3) ))
