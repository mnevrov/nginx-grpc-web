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
interval=${PERF_STATS_INTERVAL:-0.10}

mkdir -p "$(dirname "$output")"
printf 'timestamp\tcontainer\tcpu_usage_usec\tmemory_bytes\n' > "$output"

declare -a names=()
declare -a cgroups=()

for service in "${services[@]}"; do
  id=$(docker compose -f "$compose_file" ps -q "$service")
  if [[ -z "$id" ]]; then
    echo "service $service has no running container" >&2
    exit 1
  fi

  pid=$(docker inspect -f '{{.State.Pid}}' "$id")
  if [[ -z "$pid" || "$pid" == "0" ]]; then
    echo "service $service has no running PID" >&2
    exit 1
  fi

  # cgroup v2 exposes one unified relative path as 0::<path>. Reading the
  # host cgroup files avoids docker-stats' ~1s sampling latency and, unlike
  # docker exec, does not add measurement work to the container's own CPU.
  cgroup_rel=$(awk -F: '$1 == "0" { print $3; exit }' "/proc/$pid/cgroup")
  if [[ -z "$cgroup_rel" ]]; then
    echo "cgroup v2 is required for performance CPU/RSS sampling ($service)" >&2
    exit 1
  fi

  cgroup_dir="/sys/fs/cgroup${cgroup_rel}"
  if [[ ! -r "$cgroup_dir/cpu.stat" || ! -r "$cgroup_dir/memory.current" ]]; then
    echo "cannot read cgroup v2 metrics for $service at $cgroup_dir" >&2
    exit 1
  fi

  names+=("$service")
  cgroups+=("$cgroup_dir")
done

while true; do
  ts=$(date +%s.%N)
  for i in "${!names[@]}"; do
    cpu=$(awk '$1 == "usage_usec" { print $2; exit }' "${cgroups[$i]}/cpu.stat")
    mem=$(cat "${cgroups[$i]}/memory.current")
    if [[ -z "$cpu" || -z "$mem" ]]; then
      echo "failed to read cgroup metrics for ${names[$i]}" >&2
      exit 1
    fi
    printf '%s\t%s\t%s\t%s\n' "$ts" "${names[$i]}" "$cpu" "$mem" >> "$output"
  done
  sleep "$interval"
done
