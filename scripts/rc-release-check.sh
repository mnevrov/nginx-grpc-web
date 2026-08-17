#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

BENCH_DIR=${RC_BENCHMARK_DIR:-}
SOAK_DIR=${RC_SOAK_DIR:-}
GATES=${RELEASE_GATES:-}
OUTPUT_DIR=${RC_RELEASE_OUTPUT_DIR:-"$ROOT/dist/release/v0.1.0-rc"}
OUTPUT_DIR=$(python3 - "$OUTPUT_DIR" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).resolve())
PY
)

for pair in \
  "RC_BENCHMARK_DIR:$BENCH_DIR" \
  "RC_SOAK_DIR:$SOAK_DIR"; do
  name=${pair%%:*}
  value=${pair#*:}
  if [[ -z "$value" || ! -d "$value" ]]; then
    echo "$name must reference an existing directory" >&2
    exit 2
  fi
done
if [[ -z "$GATES" || ! -f "$GATES" ]]; then
  echo "RELEASE_GATES must reference an exact-commit controlled gates JSON" >&2
  exit 2
fi
for path in \
  "$BENCH_DIR/manifest.json" \
  "$BENCH_DIR/rc-benchmark.json" \
  "$BENCH_DIR/selected-attempts.json" \
  "$SOAK_DIR/rc-soak-link.json"; do
  if [[ ! -f "$path" ]]; then
    echo "required M15 evidence file not found: $path" >&2
    exit 2
  fi
done
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "RC release output already exists; refusing to overwrite evidence: $OUTPUT_DIR" >&2
  exit 2
fi

mapfile -t META < <(python3 - "$BENCH_DIR/manifest.json" "$BENCH_DIR/rc-benchmark.json" "$BENCH_DIR/selected-attempts.json" "$SOAK_DIR/rc-soak-link.json" "$BENCH_DIR" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text())
benchmark = json.loads(Path(sys.argv[2]).read_text())
selected = json.loads(Path(sys.argv[3]).read_text())
soak = json.loads(Path(sys.argv[4]).read_text())
if benchmark.get("ready") is not True or benchmark.get("blockers") not in ([], None):
    raise SystemExit("M15 RC benchmark is not ready")
if soak.get("ready") is not True:
    raise SystemExit("M15 RC soak linkage is not ready")
commit = manifest.get("git_commit")
host = manifest.get("host_fingerprint")
nginx = manifest.get("nginx_version")
compiler = manifest.get("build_cc")
typical = selected.get("typical")
for name, value in (("git_commit", commit), ("host_fingerprint", host), ("nginx_version", nginx), ("build_cc", compiler), ("selected typical attempt", typical)):
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"invalid benchmark {name}")
if benchmark.get("source_commit") != commit or soak.get("source_commit") != commit:
    raise SystemExit("M15 source commit mismatch across benchmark/soak")
if benchmark.get("host_fingerprint") != host or soak.get("host_fingerprint") != host:
    raise SystemExit("M15 host fingerprint mismatch across benchmark/soak")
bench_dir = Path(sys.argv[5]).resolve()
typical_path = Path(typical)
if not typical_path.is_absolute():
    typical_path = (bench_dir / typical_path).resolve()
else:
    typical_path = typical_path.resolve()
try:
    typical_path.relative_to(bench_dir)
except ValueError:
    raise SystemExit(f"selected typical attempt is outside benchmark directory: {typical_path}")
if not typical_path.is_dir():
    raise SystemExit(f"selected typical attempt does not exist: {typical_path}")
print(commit)
print(host)
print(nginx)
print(compiler)
print(typical_path)
PY
)
if [[ ${#META[@]} -ne 5 ]]; then
  echo "failed to resolve M15 release handoff metadata" >&2
  exit 2
fi

SOURCE_COMMIT=${META[0]}
HOST_FINGERPRINT=${META[1]}
NGINX_VERSION_RESOLVED=${META[2]}
BUILD_CC_RESOLVED=${META[3]}
CONTROLLED_DIR=${META[4]}
CURRENT_COMMIT=$(git rev-parse HEAD)
if [[ "$CURRENT_COMMIT" != "$SOURCE_COMMIT" ]]; then
  echo "current source commit $CURRENT_COMMIT does not match M15 evidence $SOURCE_COMMIT" >&2
  exit 2
fi

RELEASE_GATES="$GATES" \
RELEASE_CONTROLLED_DIR="$CONTROLLED_DIR" \
RELEASE_SOAK_DIR="$SOAK_DIR" \
RELEASE_OUTPUT_DIR="$OUTPUT_DIR" \
NGINX_VERSION="$NGINX_VERSION_RESOLVED" \
BUILD_CC="$BUILD_CC_RESOLVED" \
  bash "$ROOT/scripts/release-check.sh"

python3 - "$OUTPUT_DIR/release-evidence.json" "$SOURCE_COMMIT" "$HOST_FINGERPRINT" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text())
commit = sys.argv[2]
host = sys.argv[3]
assert value.get("source_commit") == commit, value
assert value.get("evidence_class") == "controlled", value
assert value.get("verdict") == "release_candidate", value
assert value.get("mechanics_pass") is True, value
assert value.get("blockers") == [], value
assert value.get("raw_revalidation", {}).get("valid") is True, value
assert value.get("controlled", {}).get("host_fingerprint") == host, value
assert value.get("soak", {}).get("host_fingerprint") == host, value
PY

mkdir -p "$OUTPUT_DIR/m15"
cp "$BENCH_DIR/manifest.json" "$OUTPUT_DIR/m15/rc-benchmark-manifest.json"
cp "$BENCH_DIR/rc-benchmark.json" "$OUTPUT_DIR/m15/rc-benchmark.json"
if [[ -f "$BENCH_DIR/rc-benchmark.md" ]]; then
  cp "$BENCH_DIR/rc-benchmark.md" "$OUTPUT_DIR/m15/rc-benchmark.md"
fi
cp "$BENCH_DIR/selected-attempts.json" "$OUTPUT_DIR/m15/selected-attempts.json"
cp "$SOAK_DIR/rc-soak-link.json" "$OUTPUT_DIR/m15/rc-soak-link.json"
if [[ -f "$SOAK_DIR/rc-soak-link.md" ]]; then
  cp "$SOAK_DIR/rc-soak-link.md" "$OUTPUT_DIR/m15/rc-soak-link.md"
fi

printf 'controlled M14 release bundle: %s\n' "$OUTPUT_DIR"
printf 'release evidence:              %s\n' "$OUTPUT_DIR/release-evidence.md"
printf 'deploy the exact package under: %s\n' "$OUTPUT_DIR/artifacts"
