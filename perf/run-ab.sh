#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE="$ROOT/perf/docker-compose.perf.yml"
LOADGEN="$ROOT/build/perf-loadgen"
PROFILE=${1:-smoke}
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$ROOT/perf/results/$(date -u +%Y%m%dT%H%M%SZ)"}
KEEP_STACK=${KEEP_STACK:-0}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}

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
      url=http://127.0.0.1:19080
      services=(native-nginx)
      ;;
    legacy)
      url=http://127.0.0.1:19081
      services=(legacy-nginx envoy)
      ;;
    *)
      echo "unknown architecture: $arch" >&2
      return 2
      ;;
  esac

  case_index=$((case_index + 1))
  local stem
  stem=$(printf '%03d-%s-%s-p%d-c%d-m%d-d%d-cons%d-%s' \
    "$case_index" "$arch" "$transport" "$payload" "$streams" "$messages" "$delay" "$consumer_delay" "$order")
  local result="$OUTPUT_DIR/$stem.json"
  local stats="$OUTPUT_DIR/$stem.stats.tsv"

  bash "$ROOT/perf/sample-stats.sh" "$COMPOSE" "$stats" "${services[@]}" &
  local sampler=$!
  sleep 0.5

  set +e
  "$LOADGEN" \
    -name "$arch" \
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
  *)
    echo "profile must be one of: smoke, typical, large, slow" >&2
    exit 2
    ;;
esac

python3 "$ROOT/perf/report.py" --input "$OUTPUT_DIR" --output "$OUTPUT_DIR/report.md" --json-output "$OUTPUT_DIR/report.json"
printf 'results: %s\n' "$OUTPUT_DIR"
printf 'report:  %s\n' "$OUTPUT_DIR/report.md"
