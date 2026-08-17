#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BENCH_DIR=${RC_BENCHMARK_DIR:-}
DURATION=${RC_SOAK_DURATION_SECONDS:-7200}
OUTPUT_DIR=${RC_SOAK_OUTPUT_DIR:-"$ROOT/perf/results/rc-soak-$(date -u +%Y%m%dT%H%M%SZ)"}
SOAK_POLICY_PATH=${RC_SOAK_POLICY:-"$ROOT/perf/scenarios/soak-default.json"}

if [[ -z "$BENCH_DIR" ]]; then
  echo "RC_BENCHMARK_DIR=/path/to/completed/rc-benchmark is required" >&2
  exit 2
fi
if [[ ! -f "$BENCH_DIR/manifest.json" || ! -f "$BENCH_DIR/rc-benchmark.json" ]]; then
  echo "RC_BENCHMARK_DIR must contain manifest.json and rc-benchmark.json: $BENCH_DIR" >&2
  exit 2
fi
if [[ ! -f "$SOAK_POLICY_PATH" ]]; then
  echo "RC soak policy not found: $SOAK_POLICY_PATH" >&2
  exit 2
fi
if ! [[ "$DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "RC_SOAK_DURATION_SECONDS must be numeric" >&2
  exit 2
fi
python3 - "$DURATION" <<'PY'
import sys
value = float(sys.argv[1])
if value < 7200:
    raise SystemExit("RC soak duration must be >= 7200 seconds")
PY

if [[ -e "$OUTPUT_DIR" ]]; then
  echo "RC soak output already exists; refusing to overwrite evidence: $OUTPUT_DIR" >&2
  exit 2
fi
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "RC soak requires a clean git worktree" >&2
  exit 2
fi

mapfile -t BENCH < <(python3 - "$BENCH_DIR/manifest.json" "$BENCH_DIR/rc-benchmark.json" <<'PY'
import json
import sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
summary = json.loads(Path(sys.argv[2]).read_text())
if summary.get("ready") is not True:
    raise SystemExit("RC benchmark summary is not ready")
for key in ("git_commit", "nginx_version", "build_cc", "gateway_cpuset", "backend_cpuset", "loadgen_cpuset", "host_fingerprint"):
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"benchmark manifest field {key} must be a non-empty string")
if summary.get("source_commit") != manifest["git_commit"]:
    raise SystemExit("RC benchmark summary/source manifest commit mismatch")
if summary.get("host_fingerprint") != manifest["host_fingerprint"]:
    raise SystemExit("RC benchmark summary/source manifest host mismatch")
print(manifest["git_commit"])
print(manifest["nginx_version"])
print(manifest["build_cc"])
print(manifest["gateway_cpuset"])
print(manifest["backend_cpuset"])
print(manifest["loadgen_cpuset"])
print(manifest["host_fingerprint"])
PY
)
if [[ ${#BENCH[@]} -ne 7 ]]; then
  echo "failed to read RC benchmark provenance" >&2
  exit 2
fi

BENCH_COMMIT=${BENCH[0]}
BENCH_NGINX=${BENCH[1]}
BENCH_CC=${BENCH[2]}
BENCH_GATEWAY_CPUSET=${BENCH[3]}
BENCH_BACKEND_CPUSET=${BENCH[4]}
BENCH_LOADGEN_CPUSET=${BENCH[5]}
BENCH_FINGERPRINT=${BENCH[6]}
CURRENT_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
if [[ "$CURRENT_COMMIT" != "$BENCH_COMMIT" ]]; then
  echo "current source commit $CURRENT_COMMIT does not match RC benchmark $BENCH_COMMIT" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cp "$SOAK_POLICY_PATH" "$OUTPUT_DIR/rc-soak-policy-input.json"

# Fail before a multi-hour run if the host changed since the controlled benchmark.
python3 "$ROOT/perf/host_info.py" \
  --output "$OUTPUT_DIR/rc-preflight.json" \
  --gateway-cpuset "$BENCH_GATEWAY_CPUSET" \
  --backend-cpuset "$BENCH_BACKEND_CPUSET" \
  --loadgen-cpuset "$BENCH_LOADGEN_CPUSET" \
  --strict
python3 - "$OUTPUT_DIR/rc-preflight.json" "$BENCH_FINGERPRINT" <<'PY'
import json
import sys
from pathlib import Path
host = json.loads(Path(sys.argv[1]).read_text())
expected = sys.argv[2]
if host.get("fingerprint") != expected:
    raise SystemExit(
        f"current strict host fingerprint {host.get('fingerprint')} does not match benchmark {expected}"
    )
PY

NGINX_VERSION="$BENCH_NGINX" \
BUILD_CC="$BENCH_CC" \
PERF_GATEWAY_CPUSET="$BENCH_GATEWAY_CPUSET" \
PERF_BACKEND_CPUSET="$BENCH_BACKEND_CPUSET" \
PERF_LOADGEN_CPUSET="$BENCH_LOADGEN_CPUSET" \
SOAK_STRICT=1 \
SOAK_POLICY="$SOAK_POLICY_PATH" \
SOAK_DURATION_SECONDS="$DURATION" \
SOAK_OUTPUT_DIR="$OUTPUT_DIR" \
  bash "$ROOT/perf/run-soak.sh"

python3 "$ROOT/perf/rc_soak.py" \
  --benchmark-manifest "$BENCH_DIR/manifest.json" \
  --soak-dir "$OUTPUT_DIR" \
  --min-duration-seconds "$DURATION" \
  --output "$OUTPUT_DIR/rc-soak-link.json" \
  --markdown "$OUTPUT_DIR/rc-soak-link.md"

printf 'RC soak output: %s\n' "$OUTPUT_DIR"
printf 'RC soak link:   %s\n' "$OUTPUT_DIR/rc-soak-link.md"
printf 'M14 soak input: %s\n' "$OUTPUT_DIR"
