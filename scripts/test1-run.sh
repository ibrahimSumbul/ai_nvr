#!/usr/bin/env bash
# Test 1 perf koşumu — make perf sarmalayıcı.
# Kullanım: ./scripts/test1-run.sh [run_id] [duration_seconds]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_ID="${1:-trial-$(date +%Y%m%d-%H%M)}"
DURATION="${2:-600}"
INTERVAL="${TEST1_INTERVAL:-30}"
OUT="perf/runs/test1/${RUN_ID}"
LOG="${OUT}.stdout.log"

mkdir -p perf/runs/test1

echo "Test 1 run_id=$RUN_ID duration=${DURATION}s interval=${INTERVAL}s"
echo "  out=${OUT}.{csv,json}"
echo "  log=$LOG"

if ! curl -sf --max-time 5 http://localhost:5100/api/stats >/dev/null; then
  echo "Frigate erişilemiyor. Önce: ./scripts/test1-prepare.sh" >&2
  exit 1
fi

cd bridge
if command -v uv >/dev/null 2>&1; then
  uv run python -m bridge.perf \
    --duration "$DURATION" \
    --interval "$INTERVAL" \
    --out "../${OUT}" 2>&1 | tee "../${LOG}"
else
  python3 -m bridge.perf \
    --duration "$DURATION" \
    --interval "$INTERVAL" \
    --out "../${OUT}" 2>&1 | tee "../${LOG}"
fi
EXIT=${PIPESTATUS[0]}
cd "$ROOT"

echo ""
echo "Çıktılar:"
ls -la "${OUT}.csv" "${OUT}.json" "${LOG}" 2>/dev/null || true
echo "exit_code=$EXIT"
exit "$EXIT"
