#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT_ROOT=${RC_OUTPUT_DIR:-"$ROOT/perf/results/rc-$(date -u +%Y%m%dT%H%M%SZ)"}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}
REPEATS=${RC_REPEATS:-5}
MAX_ATTEMPTS=${RC_MAX_ATTEMPTS:-4}
DECISION_POLICY=${RC_DECISION_POLICY:-"$ROOT/perf/scenarios/decision-default.json"}

TYPICAL_STEPS=${RC_TYPICAL_STEPS:-"25,50,100,200,400,800,1200"}
TYPICAL_MAX_STREAMS=${RC_TYPICAL_MAX_STREAMS:-5000}
LARGE4M_STEPS=${RC_LARGE4M_STEPS:-"1,2,4,8,16,32,64"}
LARGE4M_MAX_STREAMS=${RC_LARGE4M_MAX_STREAMS:-256}
SLOW_STEPS=${RC_SLOW_STEPS:-"5,10,25,50,100,200"}
SLOW_MAX_STREAMS=${RC_SLOW_MAX_STREAMS:-1600}
LARGE8M_STEPS=${RC_LARGE8M_STEPS:-"1,2,4,8,16,32"}
LARGE8M_MAX_STREAMS=${RC_LARGE8M_MAX_STREAMS:-128}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "required command not found: $1" >&2; exit 2; }
}

require_file_var() {
  local name=$1
  local value=${!name:-}
  if [[ -z "$value" ]]; then
    echo "$name=/path/to/slo.json is required" >&2
    exit 2
  fi
  if [[ ! -f "$value" ]]; then
    echo "$name file not found: $value" >&2
    exit 2
  fi
}

require_positive_int() {
  local name=$1 value=$2 minimum=${3:-1}
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < minimum )); then
    echo "$name must be an integer >= $minimum" >&2
    exit 2
  fi
}

for cmd in git python3 docker taskset; do
  require_cmd "$cmd"
done

for name in PERF_GATEWAY_CPUSET PERF_BACKEND_CPUSET PERF_LOADGEN_CPUSET; do
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required for release-quality controlled runs" >&2
    exit 2
  fi
done

require_file_var RC_TYPICAL_SLO
require_file_var RC_LARGE4M_SLO
require_file_var RC_SLOW_SLO
if [[ -n "${RC_LARGE8M_SLO:-}" ]]; then
  require_file_var RC_LARGE8M_SLO
elif [[ -z "${RC_SKIP_LARGE8M_REASON:-}" ]]; then
  echo "set RC_LARGE8M_SLO or provide an explicit RC_SKIP_LARGE8M_REASON" >&2
  exit 2
fi
if [[ ! -f "$DECISION_POLICY" ]]; then
  echo "decision policy not found: $DECISION_POLICY" >&2
  exit 2
fi

require_positive_int RC_REPEATS "$REPEATS" 5
require_positive_int RC_MAX_ATTEMPTS "$MAX_ATTEMPTS" 1
for pair in \
  "RC_TYPICAL_MAX_STREAMS:$TYPICAL_MAX_STREAMS" \
  "RC_LARGE4M_MAX_STREAMS:$LARGE4M_MAX_STREAMS" \
  "RC_SLOW_MAX_STREAMS:$SLOW_MAX_STREAMS" \
  "RC_LARGE8M_MAX_STREAMS:$LARGE8M_MAX_STREAMS"; do
  require_positive_int "${pair%%:*}" "${pair#*:}" 1
done

if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "RC benchmark requires a clean git worktree" >&2
  exit 2
fi

mkdir -p "$OUTPUT_ROOT/inputs"
cp "$RC_TYPICAL_SLO" "$OUTPUT_ROOT/inputs/typical-slo.json"
cp "$RC_LARGE4M_SLO" "$OUTPUT_ROOT/inputs/large4m-slo.json"
cp "$RC_SLOW_SLO" "$OUTPUT_ROOT/inputs/slow-slo.json"
cp "$DECISION_POLICY" "$OUTPUT_ROOT/inputs/decision-policy.json"
if [[ -n "${RC_LARGE8M_SLO:-}" ]]; then
  cp "$RC_LARGE8M_SLO" "$OUTPUT_ROOT/inputs/large8m-slo.json"
fi

python3 "$ROOT/perf/host_info.py" \
  --output "$OUTPUT_ROOT/preflight.json" \
  --gateway-cpuset "$PERF_GATEWAY_CPUSET" \
  --backend-cpuset "$PERF_BACKEND_CPUSET" \
  --loadgen-cpuset "$PERF_LOADGEN_CPUSET" \
  --strict

SOURCE_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
export SOURCE_COMMIT
python3 - "$OUTPUT_ROOT/manifest.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

preflight = json.loads(Path(os.environ["RC_OUTPUT_DIR_RESOLVED"] + "/preflight.json").read_text())
out = Path(sys.argv[1])
data = {
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": os.environ["SOURCE_COMMIT"],
    "nginx_version": os.environ["NGINX_VERSION_RESOLVED"],
    "build_cc": os.environ["BUILD_CC_RESOLVED"],
    "repeats": int(os.environ["RC_REPEATS_RESOLVED"]),
    "max_attempts": int(os.environ["RC_MAX_ATTEMPTS_RESOLVED"]),
    "gateway_cpuset": os.environ["PERF_GATEWAY_CPUSET"],
    "backend_cpuset": os.environ["PERF_BACKEND_CPUSET"],
    "loadgen_cpuset": os.environ["PERF_LOADGEN_CPUSET"],
    "host_fingerprint": preflight["fingerprint"],
    "large8m": {
        "requested": bool(os.environ.get("RC_LARGE8M_SLO", "")),
        "skip_reason": os.environ.get("RC_SKIP_LARGE8M_REASON", ""),
    },
}
out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

declare -A SELECTED_SUMMARY
declare -A SELECTED_ATTEMPT

run_scenario() {
  local name=$1 slo=$2 steps=$3 max_streams=$4 transport=$5 payload=$6 messages=$7 delay=$8 consumer_delay=$9
  local scenario_root="$OUTPUT_ROOT/$name"
  local current_steps=$steps
  local attempt attempt_dir check_rc boundaries ready next_steps

  mkdir -p "$scenario_root"
  cp "$slo" "$scenario_root/slo-input.json"

  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    attempt_dir=$(printf '%s/attempt-%02d' "$scenario_root" "$attempt")
    echo "RC scenario=$name attempt=$attempt/$MAX_ATTEMPTS steps=$current_steps"

    NGINX_VERSION="$NGINX_VERSION" \
    BUILD_CC="$BUILD_CC" \
    PERF_FRONTEND=tls-h2 \
    PERF_GATEWAY_CPUSET="$PERF_GATEWAY_CPUSET" \
    PERF_BACKEND_CPUSET="$PERF_BACKEND_CPUSET" \
    PERF_LOADGEN_CPUSET="$PERF_LOADGEN_CPUSET" \
    PERF_CAPACITY_SLO="$slo" \
    PERF_CAPACITY_STEPS="$current_steps" \
    PERF_CAPACITY_TRANSPORT="$transport" \
    PERF_CAPACITY_PAYLOAD_BYTES="$payload" \
    PERF_CAPACITY_MESSAGES="$messages" \
    PERF_CAPACITY_DELAY_MS="$delay" \
    PERF_CAPACITY_CONSUMER_DELAY_MS="$consumer_delay" \
    PERF_CONTROLLED_REPEATS="$REPEATS" \
    PERF_CONTROLLED_STRICT=1 \
    PERF_DECISION_POLICY="$DECISION_POLICY" \
    PERF_CONTROLLED_OUTPUT_DIR="$attempt_dir" \
      bash "$ROOT/perf/run-controlled.sh"

    set +e
    python3 "$ROOT/perf/rc.py" check \
      --input "$attempt_dir" \
      --min-repeats "$REPEATS" \
      --output "$attempt_dir/rc-scenario.json" \
      --markdown "$attempt_dir/rc-scenario.md"
    check_rc=$?
    set -e

    if [[ "$check_rc" == "0" ]]; then
      cp "$attempt_dir/rc-scenario.json" "$scenario_root/selected.json"
      cp "$attempt_dir/rc-scenario.md" "$scenario_root/selected.md"
      python3 - "$scenario_root/selection.json" "$attempt" "$current_steps" "$attempt_dir" <<'PY'
import json
import sys
from pathlib import Path
out = Path(sys.argv[1])
out.write_text(json.dumps({
    "version": 1,
    "attempt": int(sys.argv[2]),
    "capacity_steps": sys.argv[3],
    "attempt_dir": sys.argv[4],
}, indent=2) + "\n", encoding="utf-8")
PY
      SELECTED_SUMMARY[$name]="$scenario_root/selected.json"
      SELECTED_ATTEMPT[$name]="$attempt_dir"
      echo "RC scenario=$name selected attempt=$attempt"
      return 0
    fi
    if [[ "$check_rc" != "3" ]]; then
      echo "RC scenario=$name evaluator failed with rc=$check_rc" >&2
      return "$check_rc"
    fi

    read -r boundaries ready < <(python3 - "$attempt_dir/rc-scenario.json" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text())
print(str(bool(value.get("boundaries_complete"))).lower(), str(bool(value.get("ready"))).lower())
PY
)
    if [[ "$boundaries" == "true" ]]; then
      echo "RC scenario=$name reached capacity boundaries but decision is not release-ready; refusing to extend staircase" >&2
      return 3
    fi
    if (( attempt >= MAX_ATTEMPTS )); then
      echo "RC scenario=$name capacity boundary not reached within RC_MAX_ATTEMPTS=$MAX_ATTEMPTS" >&2
      return 3
    fi

    next_steps=$(python3 "$ROOT/perf/rc.py" extend --steps "$current_steps" --max-streams "$max_streams")
    current_steps=$next_steps
  done

  echo "RC scenario=$name exhausted attempts unexpectedly" >&2
  return 3
}

# Resolve values for the immutable top-level manifest without depending on shell interpolation in Python.
export RC_OUTPUT_DIR_RESOLVED="$OUTPUT_ROOT"
export NGINX_VERSION_RESOLVED="$NGINX_VERSION"
export BUILD_CC_RESOLVED="$BUILD_CC"
export RC_REPEATS_RESOLVED="$REPEATS"
export RC_MAX_ATTEMPTS_RESOLVED="$MAX_ATTEMPTS"
# Re-write manifest now that all exported values are available.
python3 - "$OUTPUT_ROOT/manifest.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ["RC_OUTPUT_DIR_RESOLVED"])
preflight = json.loads((root / "preflight.json").read_text())
out = Path(sys.argv[1])
data = {
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": os.environ["SOURCE_COMMIT"],
    "nginx_version": os.environ["NGINX_VERSION_RESOLVED"],
    "build_cc": os.environ["BUILD_CC_RESOLVED"],
    "repeats": int(os.environ["RC_REPEATS_RESOLVED"]),
    "max_attempts": int(os.environ["RC_MAX_ATTEMPTS_RESOLVED"]),
    "gateway_cpuset": os.environ["PERF_GATEWAY_CPUSET"],
    "backend_cpuset": os.environ["PERF_BACKEND_CPUSET"],
    "loadgen_cpuset": os.environ["PERF_LOADGEN_CPUSET"],
    "host_fingerprint": preflight["fingerprint"],
    "large8m": {
        "requested": bool(os.environ.get("RC_LARGE8M_SLO", "")),
        "skip_reason": os.environ.get("RC_SKIP_LARGE8M_REASON", ""),
    },
}
out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

run_scenario typical "$RC_TYPICAL_SLO" "$TYPICAL_STEPS" "$TYPICAL_MAX_STREAMS" text 4096 20 20 0
run_scenario large4m "$RC_LARGE4M_SLO" "$LARGE4M_STEPS" "$LARGE4M_MAX_STREAMS" text 4194304 8 50 0
run_scenario slow "$RC_SLOW_SLO" "$SLOW_STEPS" "$SLOW_MAX_STREAMS" text 32768 20 1 25

aggregate_args=(
  --scenario "typical=${SELECTED_SUMMARY[typical]}"
  --scenario "large4m=${SELECTED_SUMMARY[large4m]}"
  --scenario "slow=${SELECTED_SUMMARY[slow]}"
)

if [[ -n "${RC_LARGE8M_SLO:-}" ]]; then
  run_scenario large8m "$RC_LARGE8M_SLO" "$LARGE8M_STEPS" "$LARGE8M_MAX_STREAMS" text 8388608 8 50 0
  aggregate_args+=(--scenario "large8m=${SELECTED_SUMMARY[large8m]}")
fi

python3 "$ROOT/perf/rc.py" aggregate \
  "${aggregate_args[@]}" \
  --output "$OUTPUT_ROOT/rc-benchmark.json" \
  --markdown "$OUTPUT_ROOT/rc-benchmark.md"

python3 - "$OUTPUT_ROOT/selected-attempts.json" <<PY
import json
from pathlib import Path
out = Path(${OUTPUT_ROOT@Q}) / "selected-attempts.json"
data = {
    "typical": ${SELECTED_ATTEMPT[typical]@Q},
    "large4m": ${SELECTED_ATTEMPT[large4m]@Q},
    "slow": ${SELECTED_ATTEMPT[slow]@Q},
}
large8 = ${RC_LARGE8M_SLO:-}
if large8:
    data["large8m"] = ${SELECTED_ATTEMPT[large8m]:-}
out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

printf 'RC benchmark output: %s\n' "$OUTPUT_ROOT"
printf 'RC summary:          %s\n' "$OUTPUT_ROOT/rc-benchmark.md"
printf 'M14 controlled input (typical selected attempt): %s\n' "${SELECTED_ATTEMPT[typical]}"
