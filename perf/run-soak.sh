#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE="$ROOT/perf/docker-compose.perf.yml"
LOADGEN="$ROOT/build/perf-loadgen"
CERT_DIR="$ROOT/perf/.certs"
STRICT=${SOAK_STRICT:-1}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}
KEEP_STACK=${KEEP_STACK:-0}

if [[ "$STRICT" != "0" && "$STRICT" != "1" ]]; then
  echo "SOAK_STRICT must be 0 or 1" >&2
  exit 2
fi

if [[ "$STRICT" == "1" ]]; then
  POLICY=${SOAK_POLICY:-"$ROOT/perf/scenarios/soak-default.json"}
  TARGET_DURATION=${SOAK_DURATION_SECONDS:-7200}
  STATS_INTERVAL=${SOAK_STATS_INTERVAL:-5}
else
  POLICY=${SOAK_POLICY:-"$ROOT/perf/scenarios/soak-smoke.json"}
  TARGET_DURATION=${SOAK_DURATION_SECONDS:-8}
  STATS_INTERVAL=${SOAK_STATS_INTERVAL:-0.10}
fi

OUTPUT_DIR=${SOAK_OUTPUT_DIR:-"$ROOT/perf/results/soak-$(date -u +%Y%m%dT%H%M%SZ)"}
STEADY_STREAMS=${SOAK_STEADY_STREAMS:-20}
STEADY_MESSAGES=${SOAK_STEADY_MESSAGES:-100}
STEADY_DELAY_MS=${SOAK_STEADY_DELAY_MS:-20}
STEADY_PAYLOAD_BYTES=${SOAK_STEADY_PAYLOAD_BYTES:-4096}
CHURN_STREAMS=${SOAK_CHURN_STREAMS:-50}
CHURN_MESSAGES=${SOAK_CHURN_MESSAGES:-2}
CHURN_DELAY_MS=${SOAK_CHURN_DELAY_MS:-1}
CANCEL_STREAMS=${SOAK_CANCEL_STREAMS:-20}
CANCEL_MESSAGES=${SOAK_CANCEL_MESSAGES:-100}
CANCEL_AFTER=${SOAK_CANCEL_AFTER:-2}
CANCEL_DELAY_MS=${SOAK_CANCEL_DELAY_MS:-20}
RESET_STREAMS=${SOAK_RESET_STREAMS:-8}
RESTART_STREAMS=${SOAK_RESTART_STREAMS:-10}
RESTART_MESSAGES=${SOAK_RESTART_MESSAGES:-200}
RESTART_DELAY_MS=${SOAK_RESTART_DELAY_MS:-20}
RESTART_AFTER_SECONDS=${SOAK_RESTART_AFTER_SECONDS:-0.30}
RESTART_EVERY_CYCLES=${SOAK_RESTART_EVERY_CYCLES:-60}
CYCLE_PAUSE_SECONDS=${SOAK_CYCLE_PAUSE_SECONDS:-0}

if [[ ! -f "$POLICY" ]]; then
  echo "soak policy not found: $POLICY" >&2
  exit 2
fi
if ! [[ "$TARGET_DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "SOAK_DURATION_SECONDS must be numeric" >&2
  exit 2
fi
if ! [[ "$RESTART_EVERY_CYCLES" =~ ^[1-9][0-9]*$ ]]; then
  echo "SOAK_RESTART_EVERY_CYCLES must be a positive integer" >&2
  exit 2
fi

mkdir -p "$ROOT/build" "$OUTPUT_DIR"
cp "$POLICY" "$OUTPUT_DIR/soak-policy.json"
SAMPLER_PID=""

cleanup() {
  if [[ -n "$SAMPLER_PID" ]]; then
    kill "$SAMPLER_PID" >/dev/null 2>&1 || true
    wait "$SAMPLER_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$KEEP_STACK" != "1" ]]; then
    docker compose -f "$COMPOSE" down -v >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT/perf/loadgen"
  go test ./...
  go build -trimpath -o "$LOADGEN" .
)
python3 "$ROOT/perf/test_soak.py" -q
bash "$ROOT/perf/generate-tls.sh" "$CERT_DIR"

host_args=(
  --output "$OUTPUT_DIR/host.json"
  --gateway-cpuset "${PERF_GATEWAY_CPUSET:-}"
  --backend-cpuset "${PERF_BACKEND_CPUSET:-}"
  --loadgen-cpuset "${PERF_LOADGEN_CPUSET:-}"
)
if [[ "$STRICT" == "1" ]]; then
  host_args+=(--strict)
fi
python3 "$ROOT/perf/host_info.py" "${host_args[@]}"

NGINX_VERSION="$NGINX_VERSION" BUILD_CC="$BUILD_CC" \
  docker compose -f "$COMPOSE" up -d --build backend fault-backend native-nginx

apply_cpuset() {
  local service=$1
  local cpuset=$2
  local container
  container=$(docker compose -f "$COMPOSE" ps -q "$service")
  if [[ -z "$container" ]]; then
    echo "cannot resolve container for CPU pinning: $service" >&2
    exit 1
  fi
  docker update --cpuset-cpus "$cpuset" "$container" >/dev/null
}

if [[ -n "${PERF_GATEWAY_CPUSET:-}" ]]; then
  apply_cpuset native-nginx "$PERF_GATEWAY_CPUSET"
fi
if [[ -n "${PERF_BACKEND_CPUSET:-}" ]]; then
  apply_cpuset backend "$PERF_BACKEND_CPUSET"
  apply_cpuset fault-backend "$PERF_BACKEND_CPUSET"
fi

healthy_url=https://localhost:19443
fault_url=https://localhost:19446
ready=0
for _ in $(seq 1 90); do
  if curl -sS --cacert "$CERT_DIR/ca.crt" -o /dev/null "$healthy_url/" 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "native TLS/H2 listener did not become reachable" >&2
  exit 1
fi

LOADGEN_PREFIX=()
if [[ -n "${PERF_LOADGEN_CPUSET:-}" ]]; then
  LOADGEN_PREFIX=(taskset -c "$PERF_LOADGEN_CPUSET")
fi
TLS_ARGS=(
  -frontend tls-h2
  -ca-file "$CERT_DIR/ca.crt"
  -tls-server-name localhost
  -require-http2
  -transport text
)

run_load() {
  local name=$1 url=$2 streams=$3 messages=$4 delay_ms=$5 payload_bytes=$6 cancel_after=$7 marker=$8 output=$9
  local args=(
    -name "$name"
    "${TLS_ARGS[@]}"
    -url "$url"
    -streams "$streams"
    -messages "$messages"
    -delay-ms "$delay_ms"
    -payload-bytes "$payload_bytes"
    -timeout 120
    -marker "$marker"
    -output "$output"
  )
  if [[ "$cancel_after" != "0" ]]; then
    args+=( -cancel-after "$cancel_after" )
  fi
  "${LOADGEN_PREFIX[@]}" "$LOADGEN" "${args[@]}"
}

summary_int() {
  local path=$1 field=$2
  python3 - "$path" "$field" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
field = sys.argv[2]
if not path.exists():
    print(0)
    raise SystemExit
try:
    data = json.loads(path.read_text())
    print(int(data.get("summary", {}).get(field, 0) or 0))
except Exception:
    print(0)
PY
}

run_probe() {
  local stem=$1
  local attempt output
  for attempt in $(seq 1 40); do
    output="$OUTPUT_DIR/${stem}-attempt-${attempt}.json"
    set +e
    run_load probe "$healthy_url" 1 3 5 4096 0 probe "$output"
    local rc=$?
    set -e
    if [[ "$rc" == "0" ]]; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

nginx_container=$(docker compose -f "$COMPOSE" ps -q native-nginx)
nginx_master_pid() {
  docker exec "$nginx_container" sh -c 'cat /tmp/nginx.pid 2>/dev/null || true' 2>/dev/null | tr -d '\r\n'
}
nginx_restart_count() {
  docker inspect -f '{{.RestartCount}}' "$nginx_container" 2>/dev/null || echo -1
}

master_start=$(nginx_master_pid)
restart_count_start=$(nginx_restart_count)

stats="$OUTPUT_DIR/nginx.stats.tsv"
PERF_STATS_INTERVAL="$STATS_INTERVAL" bash "$ROOT/perf/sample-stats.sh" "$COMPOSE" "$stats" native-nginx &
SAMPLER_PID=$!
for _ in $(seq 1 100); do
  if ! kill -0 "$SAMPLER_PID" >/dev/null 2>&1; then
    echo "soak sampler exited before first sample" >&2
    exit 1
  fi
  if [[ -f "$stats" ]] && [[ $(wc -l < "$stats") -ge 3 ]]; then
    break
  fi
  sleep 0.05
done

if ! run_probe warmup; then
  echo "initial healthy probe failed" >&2
  exit 1
fi

steady_runs=0
steady_errors=0
churn_runs=0
churn_errors=0
cancel_runs=0
cancel_expected=0
cancel_observed=0
cancel_errors=0
backend_attempted=0
backend_inflight_errors=0
backend_observed_disruption=0
backend_recovery_success=1
reset_attempted=0
reset_expected=0
reset_observed=0
reset_recovery_success=1
cycle=0
start_epoch=$(date +%s.%N)

while true; do
  cycle=$((cycle + 1))
  cycle_dir=$(printf '%s/cycle-%04d' "$OUTPUT_DIR" "$cycle")
  mkdir -p "$cycle_dir"

  steady_runs=$((steady_runs + 1))
  steady_out="$cycle_dir/steady.json"
  set +e
  run_load steady "$healthy_url" "$STEADY_STREAMS" "$STEADY_MESSAGES" "$STEADY_DELAY_MS" "$STEADY_PAYLOAD_BYTES" 0 steady "$steady_out"
  rc=$?
  set -e
  if [[ "$rc" != "0" ]]; then
    errors=$(summary_int "$steady_out" errors)
    steady_errors=$((steady_errors + (errors > 0 ? errors : 1)))
  fi

  churn_runs=$((churn_runs + 1))
  churn_out="$cycle_dir/churn.json"
  set +e
  run_load churn "$healthy_url" "$CHURN_STREAMS" "$CHURN_MESSAGES" "$CHURN_DELAY_MS" 1024 0 churn "$churn_out"
  rc=$?
  set -e
  if [[ "$rc" != "0" ]]; then
    errors=$(summary_int "$churn_out" errors)
    churn_errors=$((churn_errors + (errors > 0 ? errors : 1)))
  fi

  cancel_runs=$((cancel_runs + 1))
  cancel_expected=$((cancel_expected + CANCEL_STREAMS))
  cancel_out="$cycle_dir/cancel.json"
  set +e
  run_load cancel "$healthy_url" "$CANCEL_STREAMS" "$CANCEL_MESSAGES" "$CANCEL_DELAY_MS" 4096 "$CANCEL_AFTER" cancel "$cancel_out"
  rc=$?
  set -e
  cancel_observed=$((cancel_observed + $(summary_int "$cancel_out" streams_cancelled)))
  if [[ "$rc" != "0" ]]; then
    errors=$(summary_int "$cancel_out" errors)
    cancel_errors=$((cancel_errors + (errors > 0 ? errors : 1)))
  fi

  if [[ "$backend_attempted" == "0" || $((cycle % RESTART_EVERY_CYCLES)) == "0" ]]; then
    backend_attempted=$((backend_attempted + 1))
    disruption_out="$cycle_dir/backend-restart-inflight.json"
    (
      set +e
      run_load backend-restart "$healthy_url" "$RESTART_STREAMS" "$RESTART_MESSAGES" "$RESTART_DELAY_MS" 4096 0 restart "$disruption_out"
      echo $? > "$cycle_dir/backend-restart-loadgen.rc"
    ) &
    disruption_pid=$!
    sleep "$RESTART_AFTER_SECONDS"
    docker compose -f "$COMPOSE" restart backend >/dev/null
    wait "$disruption_pid" || true
    inflight_errors=$(summary_int "$disruption_out" errors)
    backend_inflight_errors=$((backend_inflight_errors + inflight_errors))
    if [[ "$inflight_errors" -gt 0 ]]; then
      backend_observed_disruption=1
    fi
    if ! run_probe "cycle-$(printf '%04d' "$cycle")-post-backend-restart"; then
      backend_recovery_success=0
    fi
  fi

  reset_attempted=$((reset_attempted + RESET_STREAMS))
  reset_expected=$((reset_expected + RESET_STREAMS))
  reset_out="$cycle_dir/transport-reset.json"
  set +e
  run_load transport-reset "$fault_url" "$RESET_STREAMS" 2 1 0 0 before-transport-fault "$reset_out"
  rc=$?
  set -e
  observed=$(summary_int "$reset_out" errors)
  reset_observed=$((reset_observed + observed))
  if [[ "$rc" == "0" && "$observed" == "0" ]]; then
    echo "warning: fault listener completed without transport errors in cycle $cycle" >&2
  fi
  if ! run_probe "cycle-$(printf '%04d' "$cycle")-post-transport-reset"; then
    reset_recovery_success=0
  fi

  now_epoch=$(date +%s.%N)
  elapsed=$(python3 - "$start_epoch" "$now_epoch" <<'PY'
import sys
print(float(sys.argv[2]) - float(sys.argv[1]))
PY
)
  if python3 - "$elapsed" "$TARGET_DURATION" <<'PY'
import sys
raise SystemExit(0 if float(sys.argv[1]) >= float(sys.argv[2]) else 1)
PY
  then
    break
  fi
  if [[ "$CYCLE_PAUSE_SECONDS" != "0" ]]; then
    sleep "$CYCLE_PAUSE_SECONDS"
  fi
done

final_probe_success=1
if ! run_probe final; then
  final_probe_success=0
fi
master_end=$(nginx_master_pid)
restart_count_end=$(nginx_restart_count)

# Ensure the sampler observes the final post-recovery state before stopping it.
sleep "$STATS_INTERVAL"
kill "$SAMPLER_PID" >/dev/null 2>&1 || true
wait "$SAMPLER_PID" >/dev/null 2>&1 || true
SAMPLER_PID=""

export SOAK_EVT_STEADY_RUNS=$steady_runs SOAK_EVT_STEADY_ERRORS=$steady_errors
export SOAK_EVT_CHURN_RUNS=$churn_runs SOAK_EVT_CHURN_ERRORS=$churn_errors
export SOAK_EVT_CANCEL_RUNS=$cancel_runs SOAK_EVT_CANCEL_EXPECTED=$cancel_expected SOAK_EVT_CANCEL_OBSERVED=$cancel_observed SOAK_EVT_CANCEL_ERRORS=$cancel_errors
export SOAK_EVT_BACKEND_ATTEMPTED=$backend_attempted SOAK_EVT_BACKEND_ERRORS=$backend_inflight_errors SOAK_EVT_BACKEND_DISRUPTION=$backend_observed_disruption SOAK_EVT_BACKEND_RECOVERY=$backend_recovery_success
export SOAK_EVT_RESET_ATTEMPTED=$reset_attempted SOAK_EVT_RESET_EXPECTED=$reset_expected SOAK_EVT_RESET_OBSERVED=$reset_observed SOAK_EVT_RESET_RECOVERY=$reset_recovery_success
export SOAK_EVT_FINAL_PROBE=$final_probe_success SOAK_EVT_MASTER_START=$master_start SOAK_EVT_MASTER_END=$master_end SOAK_EVT_RESTART_START=$restart_count_start SOAK_EVT_RESTART_END=$restart_count_end

python3 - "$OUTPUT_DIR/events.json" "$OUTPUT_DIR/host.json" <<'PY'
import json
import os
import sys
from pathlib import Path

host = json.loads(Path(sys.argv[2]).read_text())
def i(name):
    return int(os.environ.get(name, "0"))

events = {
    "host": {
        "strict": bool(host.get("strict")),
        "valid": bool(host.get("valid")),
        "fingerprint": host.get("fingerprint", ""),
    },
    "steady": {"runs": i("SOAK_EVT_STEADY_RUNS"), "unexpected_errors": i("SOAK_EVT_STEADY_ERRORS")},
    "churn": {"runs": i("SOAK_EVT_CHURN_RUNS"), "unexpected_errors": i("SOAK_EVT_CHURN_ERRORS")},
    "cancel": {
        "runs": i("SOAK_EVT_CANCEL_RUNS"),
        "expected_cancellations": i("SOAK_EVT_CANCEL_EXPECTED"),
        "observed_cancellations": i("SOAK_EVT_CANCEL_OBSERVED"),
        "unexpected_errors": i("SOAK_EVT_CANCEL_ERRORS"),
    },
    "backend_restart": {
        "attempted": i("SOAK_EVT_BACKEND_ATTEMPTED"),
        "observed_disruption": bool(i("SOAK_EVT_BACKEND_DISRUPTION")),
        "inflight_errors": i("SOAK_EVT_BACKEND_ERRORS"),
        "recovery_success": bool(i("SOAK_EVT_BACKEND_RECOVERY")),
    },
    "transport_reset": {
        "attempted": i("SOAK_EVT_RESET_ATTEMPTED"),
        "expected_failures": i("SOAK_EVT_RESET_EXPECTED"),
        "observed_failures": i("SOAK_EVT_RESET_OBSERVED"),
        "recovery_success": bool(i("SOAK_EVT_RESET_RECOVERY")),
    },
    "final_probe": {"success": bool(i("SOAK_EVT_FINAL_PROBE"))},
    "nginx": {
        "master_pid_start": os.environ.get("SOAK_EVT_MASTER_START", ""),
        "master_pid_end": os.environ.get("SOAK_EVT_MASTER_END", ""),
        "container_restart_count_start": i("SOAK_EVT_RESTART_START"),
        "container_restart_count_end": i("SOAK_EVT_RESTART_END"),
    },
}
Path(sys.argv[1]).write_text(json.dumps(events, indent=2) + "\n")
PY

commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
python3 - "$OUTPUT_DIR/manifest.json" <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
Path("$OUTPUT_DIR/manifest.json").write_text(json.dumps({
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": "$commit",
    "strict": "$STRICT" == "1",
    "nginx_version": "$NGINX_VERSION",
    "build_cc": "$BUILD_CC",
    "target_duration_seconds": float("$TARGET_DURATION"),
    "stats_interval_seconds": float("$STATS_INTERVAL"),
    "cycles": int("$cycle"),
    "frontend": "tls-h2",
    "transport": "text",
}, indent=2) + "\n")
PY

soak_args=(
  --stats "$stats"
  --events "$OUTPUT_DIR/events.json"
  --policy "$POLICY"
  --output "$OUTPUT_DIR/soak.json"
  --markdown "$OUTPUT_DIR/soak.md"
  --container native-nginx
)
if [[ "$STRICT" == "1" ]]; then
  soak_args+=(--strict)
fi
python3 "$ROOT/perf/soak.py" "${soak_args[@]}"

printf 'soak results: %s\n' "$OUTPUT_DIR"
printf 'report:       %s\n' "$OUTPUT_DIR/soak.md"
