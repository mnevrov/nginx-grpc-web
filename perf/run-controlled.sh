#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
FRONTEND=${PERF_FRONTEND:-tls-h2}
REPEATS=${PERF_CONTROLLED_REPEATS:-5}
OUTPUT_DIR=${PERF_CONTROLLED_OUTPUT_DIR:-"$ROOT/perf/results/controlled-$(date -u +%Y%m%dT%H%M%SZ)-$FRONTEND"}
POLICY=${PERF_DECISION_POLICY:-"$ROOT/perf/scenarios/decision-default.json"}
STRICT=${PERF_CONTROLLED_STRICT:-1}
SLO=${PERF_CAPACITY_SLO:-}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}

if [[ -z "$SLO" ]]; then
  echo "PERF_CAPACITY_SLO=/path/to/slo.json is required" >&2
  exit 2
fi
if [[ ! -f "$SLO" ]]; then
  echo "capacity SLO file not found: $SLO" >&2
  exit 2
fi
if [[ ! -f "$POLICY" ]]; then
  echo "decision policy file not found: $POLICY" >&2
  exit 2
fi
if [[ ! "$REPEATS" =~ ^[1-9][0-9]*$ ]]; then
  echo "PERF_CONTROLLED_REPEATS must be a positive integer" >&2
  exit 2
fi
if [[ "$STRICT" == "1" && -n "${PERF_LOADGEN_CPUSET:-}" ]] && ! command -v taskset >/dev/null 2>&1; then
  echo "strict controlled benchmark requires taskset for PERF_LOADGEN_CPUSET" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cp "$SLO" "$OUTPUT_DIR/slo.json"
cp "$POLICY" "$OUTPUT_DIR/decision-policy.json"

commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
python3 - "$OUTPUT_DIR/manifest.json" <<PY
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

out = Path(sys.argv[1])
data = {
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": ${commit@Q},
    "frontend": ${FRONTEND@Q},
    "repeats": int(${REPEATS@Q}),
    "nginx_version": ${NGINX_VERSION@Q},
    "build_cc": ${BUILD_CC@Q},
    "gateway_cpuset": os.environ.get("PERF_GATEWAY_CPUSET", ""),
    "backend_cpuset": os.environ.get("PERF_BACKEND_CPUSET", ""),
    "loadgen_cpuset": os.environ.get("PERF_LOADGEN_CPUSET", ""),
    "capacity_steps": os.environ.get("PERF_CAPACITY_STEPS", "10,25,50,100,200,400"),
    "transport": os.environ.get("PERF_CAPACITY_TRANSPORT", "text"),
    "payload_bytes": int(os.environ.get("PERF_CAPACITY_PAYLOAD_BYTES", "4096")),
    "messages": int(os.environ.get("PERF_CAPACITY_MESSAGES", "20")),
    "backend_delay_ms": int(os.environ.get("PERF_CAPACITY_DELAY_MS", "20")),
    "consumer_delay_ms": int(os.environ.get("PERF_CAPACITY_CONSUMER_DELAY_MS", "0")),
    "strict_preflight": ${STRICT@Q} == "1",
}
out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

for i in $(seq 1 "$REPEATS"); do
  repeat_dir=$(printf '%s/repeat-%02d' "$OUTPUT_DIR" "$i")
  mkdir -p "$repeat_dir"

  host_args=(
    --output "$repeat_dir/host.json"
    --gateway-cpuset "${PERF_GATEWAY_CPUSET:-}"
    --backend-cpuset "${PERF_BACKEND_CPUSET:-}"
    --loadgen-cpuset "${PERF_LOADGEN_CPUSET:-}"
  )
  if [[ "$STRICT" == "1" ]]; then
    host_args+=(--strict)
  fi
  python3 "$ROOT/perf/host_info.py" "${host_args[@]}"

  echo "controlled repeat $i/$REPEATS frontend=$FRONTEND output=$repeat_dir"
  if [[ -n "${PERF_LOADGEN_CPUSET:-}" ]]; then
    NGINX_VERSION="$NGINX_VERSION" \
    BUILD_CC="$BUILD_CC" \
    PERF_FRONTEND="$FRONTEND" \
    PERF_OUTPUT_DIR="$repeat_dir" \
    PERF_CAPACITY_SLO="$SLO" \
      taskset -c "$PERF_LOADGEN_CPUSET" bash "$ROOT/perf/run-ab.sh" capacity
  else
    NGINX_VERSION="$NGINX_VERSION" \
    BUILD_CC="$BUILD_CC" \
    PERF_FRONTEND="$FRONTEND" \
    PERF_OUTPUT_DIR="$repeat_dir" \
    PERF_CAPACITY_SLO="$SLO" \
      bash "$ROOT/perf/run-ab.sh" capacity
  fi

  if [[ "${PERF_CONTROLLED_PAUSE_SECONDS:-0}" != "0" ]]; then
    sleep "${PERF_CONTROLLED_PAUSE_SECONDS}"
  fi
done

python3 "$ROOT/perf/decision.py" \
  --input "$OUTPUT_DIR" \
  --policy "$POLICY" \
  --output "$OUTPUT_DIR/decision.json" \
  --markdown "$OUTPUT_DIR/decision.md"

printf 'controlled results: %s\n' "$OUTPUT_DIR"
printf 'decision:           %s\n' "$OUTPUT_DIR/decision.md"
