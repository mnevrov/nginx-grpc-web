#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE="$ROOT/perf/docker-compose.perf.yml"
LOADGEN="$ROOT/build/perf-loadgen"
PROFILE=${1:-smoke}
FRONTEND=${PERF_FRONTEND:-http1}
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$ROOT/perf/results/$(date -u +%Y%m%dT%H%M%SZ)-$FRONTEND"}
KEEP_STACK=${KEEP_STACK:-0}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}
CERT_DIR="$ROOT/perf/.certs"
CAPACITY_MODE=0

mkdir -p "$ROOT/build" "$OUTPUT_DIR"

cleanup() {
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
python3 "$ROOT/perf/test_capacity.py" -q

bash "$ROOT/perf/generate-tls.sh" "$CERT_DIR"

NGINX_VERSION="$NGINX_VERSION" BUILD_CC="$BUILD_CC" \
  docker compose -f "$COMPOSE" up -d --build backend envoy native-nginx legacy-nginx

for url in http://127.0.0.1:19080/ http://127.0.0.1:19081/; do
  ready=0
  for _ in $(seq 1 60); do
    if curl -sS -o /dev/null "$url" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" != "1" ]]; then
    echo "gateway did not become ready: $url" >&2
    exit 1
  fi
done

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
  # Both architectures receive the same CPU set. Legacy NGINX and Envoy share
  # that set, so the legacy path does not silently get twice the CPU budget.
  apply_cpuset native-nginx "$PERF_GATEWAY_CPUSET"
  apply_cpuset legacy-nginx "$PERF_GATEWAY_CPUSET"
  apply_cpuset envoy "$PERF_GATEWAY_CPUSET"
fi
if [[ -n "${PERF_BACKEND_CPUSET:-}" ]]; then
  apply_cpuset backend "$PERF_BACKEND_CPUSET"
fi

case "$FRONTEND" in
  http1)
    native_url=http://127.0.0.1:19080
    legacy_url=http://127.0.0.1:19081
    loadgen_frontend_args=(-frontend http1)
    ;;
  tls-h2)
    native_url=https://localhost:19443
    legacy_url=https://localhost:19444
    loadgen_frontend_args=(
      -frontend tls-h2
      -ca-file "$CERT_DIR/ca.crt"
      -tls-server-name localhost
      -require-http2
    )
    ;;
  *)
    echo "PERF_FRONTEND must be one of: http1, tls-h2" >&2
    exit 2
    ;;
esac

# Warm both gateway paths and the common backend before any measured run.
# Retain warmup JSON on failure so CI shows the exact per-stream error.
warm_index=0
for warm_url in "$native_url" "$legacy_url"; do
  warm_index=$((warm_index + 1))
  warm_result="$OUTPUT_DIR/000-warmup-${FRONTEND}-${warm_index}.json"
  set +e
  "$LOADGEN" \
    -name warmup \
    "${loadgen_frontend_args[@]}" \
    -url "$warm_url" \
    -transport text \
    -streams "${PERF_WARMUP_STREAMS:-4}" \
    -messages "${PERF_WARMUP_MESSAGES:-5}" \
    -delay-ms 10 \
    -payload-bytes 4096 \
    -timeout 30 \
    -output "$warm_result"
  warm_rc=$?
  set -e
  if [[ "$warm_rc" != "0" ]]; then
    python3 - "$warm_result" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.exists():
    data = json.loads(path.read_text())
    for stream in data.get("streams", []):
        if stream.get("error"):
            print(
                f"warmup stream={stream.get('id')} error={stream.get('error')} "
                f"http={stream.get('http_protocol', '')} alpn={stream.get('tls_alpn', '')}",
                file=sys.stderr,
            )
PY
    exit "$warm_rc"
  fi
done

case_index=0
run_one() {
  local arch=$1
  local transport=$2
  local payload=$3
  local streams=$4
  local messages=$5
  local delay=$6
  local consumer_delay=$7
  local order=$8

  local url services
  case "$arch" in
    native)
      url=$native_url
      services=(native-nginx)
      ;;
    legacy)
      url=$legacy_url
      services=(legacy-nginx envoy)
      ;;
    *)
      echo "unknown architecture: $arch" >&2
      return 2
      ;;
  esac

  case_index=$((case_index + 1))
  local stem
  stem=$(printf '%03d-%s-%s-%s-p%d-c%d-m%d-d%d-cons%d-%s' \
    "$case_index" "$FRONTEND" "$arch" "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" "$order")
  local result="$OUTPUT_DIR/$stem.json"
  local stats="$OUTPUT_DIR/$stem.stats.tsv"

  bash "$ROOT/perf/sample-stats.sh" "$COMPOSE" "$stats" "${services[@]}" &
  local sampler=$!

  local stats_ready=0
  for _ in $(seq 1 50); do
    if ! kill -0 "$sampler" >/dev/null 2>&1; then
      break
    fi
    if [[ -f "$stats" ]] && [[ $(wc -l < "$stats") -gt 1 ]]; then
      stats_ready=1
      break
    fi
    sleep 0.05
  done
  if [[ "$stats_ready" != "1" ]]; then
    kill "$sampler" >/dev/null 2>&1 || true
    wait "$sampler" >/dev/null 2>&1 || true
    echo "gateway sampler did not produce a baseline: $stem" >&2
    return 1
  fi

  set +e
  "$LOADGEN" \
    -name "$arch" \
    "${loadgen_frontend_args[@]}" \
    -url "$url" \
    -transport "$transport" \
    -streams "$streams" \
    -messages "$messages" \
    -delay-ms "$delay" \
    -payload-bytes "$payload" \
    -consumer-delay-ms "$consumer_delay" \
    -timeout "${PERF_TIMEOUT:-180}" \
    -output "$result"
  local rc=$?
  set -e

  sleep "${PERF_STATS_SETTLE:-0.15}"
  kill "$sampler" >/dev/null 2>&1 || true
  wait "$sampler" >/dev/null 2>&1 || true

  if [[ "$rc" != "0" ]]; then
    echo "loadgen failed: $stem" >&2
    return "$rc"
  fi
}

run_abba() {
  local transport=$1 payload=$2 streams=$3 messages=$4 delay=$5 consumer_delay=$6
  run_one native "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" A1
  run_one legacy "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" B1
  run_one legacy "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" B2
  run_one native "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" A2
}

capacity_report() {
  local probe_streams=${1:-}
  python3 "$ROOT/perf/report.py" --input "$OUTPUT_DIR" --output "$OUTPUT_DIR/report.md" --json-output "$OUTPUT_DIR/report.json"

  local args=(
    --report "$OUTPUT_DIR/report.json"
    --slo "$PERF_CAPACITY_SLO"
    --output "$OUTPUT_DIR/capacity.json"
    --markdown "$OUTPUT_DIR/capacity.md"
    --frontend "$FRONTEND"
    --transport "$PERF_CAPACITY_TRANSPORT"
    --payload-bytes "$PERF_CAPACITY_PAYLOAD_BYTES"
    --messages "$PERF_CAPACITY_MESSAGES"
    --delay-ms "$PERF_CAPACITY_DELAY_MS"
    --consumer-delay-ms "$PERF_CAPACITY_CONSUMER_DELAY_MS"
  )
  if [[ -n "${PERF_GATEWAY_CPUSET:-}" ]]; then
    args+=(--gateway-cpuset "$PERF_GATEWAY_CPUSET")
  fi
  if [[ -n "$probe_streams" ]]; then
    args+=(--probe-streams "$probe_streams" --exit-both-failed)
  fi
  python3 "$ROOT/perf/capacity.py" "${args[@]}"
}

case "$PROFILE" in
  smoke)
    run_one native text 4096 2 3 20 0 A
    run_one legacy text 4096 2 3 20 0 B
    ;;
  typical)
    for streams in 10 50 100 200; do
      run_abba text 4096 "$streams" 20 20 0
    done
    ;;
  large)
    for transport in text binary; do
      for payload in 1048576 4194304 8388608; do
        for streams in 1 4 16; do
          run_abba "$transport" "$payload" "$streams" 8 50 0
        done
      done
    done
    ;;
  slow)
    for payload in 32768 4194304; do
      for streams in 1 10 50; do
        run_abba text "$payload" "$streams" 20 1 25
      done
    done
    ;;
  capacity)
    CAPACITY_MODE=1
    PERF_CAPACITY_SLO=${PERF_CAPACITY_SLO:-"$ROOT/perf/scenarios/capacity-smoke-slo.json"}
    PERF_CAPACITY_STEPS=${PERF_CAPACITY_STEPS:-"10,25,50,100,200,400"}
    PERF_CAPACITY_TRANSPORT=${PERF_CAPACITY_TRANSPORT:-text}
    PERF_CAPACITY_PAYLOAD_BYTES=${PERF_CAPACITY_PAYLOAD_BYTES:-4096}
    PERF_CAPACITY_MESSAGES=${PERF_CAPACITY_MESSAGES:-20}
    PERF_CAPACITY_DELAY_MS=${PERF_CAPACITY_DELAY_MS:-20}
    PERF_CAPACITY_CONSUMER_DELAY_MS=${PERF_CAPACITY_CONSUMER_DELAY_MS:-0}

    if [[ ! -f "$PERF_CAPACITY_SLO" ]]; then
      echo "capacity SLO file not found: $PERF_CAPACITY_SLO" >&2
      exit 2
    fi

    IFS=',' read -r -a capacity_steps <<< "$PERF_CAPACITY_STEPS"
    previous=0
    for streams in "${capacity_steps[@]}"; do
      if [[ ! "$streams" =~ ^[1-9][0-9]*$ ]] || (( streams <= previous )); then
        echo "PERF_CAPACITY_STEPS must be strictly increasing positive integers: $PERF_CAPACITY_STEPS" >&2
        exit 2
      fi
      previous=$streams
      run_abba \
        "$PERF_CAPACITY_TRANSPORT" \
        "$PERF_CAPACITY_PAYLOAD_BYTES" \
        "$streams" \
        "$PERF_CAPACITY_MESSAGES" \
        "$PERF_CAPACITY_DELAY_MS" \
        "$PERF_CAPACITY_CONSUMER_DELAY_MS"

      set +e
      capacity_report "$streams"
      capacity_rc=$?
      set -e
      if [[ "$capacity_rc" == "3" ]]; then
        echo "capacity staircase stop: both architectures failed SLO at streams=$streams"
        break
      fi
      if [[ "$capacity_rc" != "0" ]]; then
        exit "$capacity_rc"
      fi
    done
    ;;
  *)
    echo "profile must be one of: smoke, typical, large, slow, capacity" >&2
    exit 2
    ;;
esac

python3 "$ROOT/perf/report.py" --input "$OUTPUT_DIR" --output "$OUTPUT_DIR/report.md" --json-output "$OUTPUT_DIR/report.json"
if [[ "$CAPACITY_MODE" == "1" ]]; then
  capacity_report
fi
printf 'frontend: %s\n' "$FRONTEND"
printf 'results:  %s\n' "$OUTPUT_DIR"
printf 'report:   %s\n' "$OUTPUT_DIR/report.md"
if [[ "$CAPACITY_MODE" == "1" ]]; then
  printf 'capacity: %s\n' "$OUTPUT_DIR/capacity.md"
fi
