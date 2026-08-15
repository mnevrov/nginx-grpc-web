#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <compose-file> <output.tsv> <service> [service ...]" >&2
  exit 2
fi

compose_file=$1
output=$2
shift 2
services=("$@")
interval=${PERF_STATS_INTERVAL:-0.25}

mkdir -p "$(dirname "$output")"
printf 'timestamp\tcontainer\tcpu_percent\tmemory\n' > "$output"

ids=()
for service in "${services[@]}"; do
  id=$(docker compose -f "$compose_file" ps -q "$service")
  if [[ -z "$id" ]]; then
    echo "service $service has no running container" >&2
    exit 1
  fi
  ids+=("$id")
done

while true; do
  ts=$(date +%s.%N)
  docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' "${ids[@]}" 2>/dev/null |
    while IFS=$'\t' read -r name cpu mem; do
      printf '%s\t%s\t%s\t%s\n' "$ts" "$name" "$cpu" "$mem" >> "$output"
    done
  sleep "$interval"
done
