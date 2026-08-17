#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

BENCH_DIR=${RC_BENCHMARK_DIR:-}
SOAK_DIR=${RC_SOAK_DIR:-}
RELEASE_DIR=${RC_RELEASE_DIR:-}
STAGING_FILE=${STAGING_EVIDENCE_FILE:-}
WAIVER_FILE=${RC_8H_WAIVER:-}

require_dir_var() {
  local name=$1 value=${!name:-}
  if [[ -z "$value" || ! -d "$value" ]]; then
    echo "$name must reference an existing directory" >&2
    exit 2
  fi
}

require_file_var() {
  local name=$1 value=${!name:-}
  if [[ -z "$value" || ! -f "$value" ]]; then
    echo "$name must reference an existing file" >&2
    exit 2
  fi
}

require_dir_var RC_BENCHMARK_DIR
require_dir_var RC_SOAK_DIR
require_dir_var RC_RELEASE_DIR
require_file_var STAGING_EVIDENCE_FILE

for path in \
  "$BENCH_DIR/manifest.json" \
  "$BENCH_DIR/rc-benchmark.json" \
  "$SOAK_DIR/rc-soak-link.json" \
  "$RELEASE_DIR/release-evidence.json"; do
  if [[ ! -f "$path" ]]; then
    echo "required M15 evidence file not found: $path" >&2
    exit 2
  fi
done
if [[ -n "$WAIVER_FILE" && ! -f "$WAIVER_FILE" ]]; then
  echo "RC_8H_WAIVER file not found: $WAIVER_FILE" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "M15 final check requires a clean git worktree" >&2
  exit 2
fi

SOURCE_COMMIT=$(python3 - "$BENCH_DIR/manifest.json" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text())
commit = value.get("git_commit")
if not isinstance(commit, str) or not commit.strip():
    raise SystemExit("benchmark manifest git_commit must be non-empty")
print(commit.strip())
PY
)
CURRENT_COMMIT=$(git rev-parse HEAD)
if [[ "$CURRENT_COMMIT" != "$SOURCE_COMMIT" ]]; then
  echo "current source commit $CURRENT_COMMIT does not match M15 evidence $SOURCE_COMMIT" >&2
  exit 2
fi

OUTPUT_DIR=${M15_OUTPUT_DIR:-"$RELEASE_DIR/m15-final"}
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "M15 output already exists; refusing to overwrite evidence: $OUTPUT_DIR" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR/inputs"

args=(
  --benchmark-manifest "$BENCH_DIR/manifest.json"
  --benchmark "$BENCH_DIR/rc-benchmark.json"
  --soak "$SOAK_DIR/rc-soak-link.json"
  --staging "$STAGING_FILE"
  --release-evidence "$RELEASE_DIR/release-evidence.json"
  --output "$OUTPUT_DIR/m15-evidence.json"
  --markdown "$OUTPUT_DIR/m15-evidence.md"
)
if [[ -n "$WAIVER_FILE" ]]; then
  args+=(--eight-hour-waiver "$WAIVER_FILE")
fi

set +e
python3 "$ROOT/release/m15.py" "${args[@]}"
check_rc=$?
set -e

# Preserve the exact compact inputs even when the final verdict is blocked.
cp "$BENCH_DIR/manifest.json" "$OUTPUT_DIR/inputs/rc-benchmark-manifest.json"
cp "$BENCH_DIR/rc-benchmark.json" "$OUTPUT_DIR/inputs/rc-benchmark.json"
cp "$SOAK_DIR/rc-soak-link.json" "$OUTPUT_DIR/inputs/rc-soak-link.json"
cp "$STAGING_FILE" "$OUTPUT_DIR/inputs/staging-evidence.json"
cp "$RELEASE_DIR/release-evidence.json" "$OUTPUT_DIR/inputs/release-evidence.json"
if [[ -n "$WAIVER_FILE" ]]; then
  cp "$WAIVER_FILE" "$OUTPUT_DIR/inputs/8h-soak-waiver.txt"
fi
printf '%s\n' "$check_rc" > "$OUTPUT_DIR/m15-exit-code.txt"

if [[ ! -f "$OUTPUT_DIR/m15-evidence.json" ]]; then
  echo "M15 evaluator did not produce machine-readable evidence" >&2
  exit "$check_rc"
fi

printf 'M15 final evidence: %s\n' "$OUTPUT_DIR"
if [[ "$check_rc" == "0" ]]; then
  printf 'M15 verdict: ready_for_manual_release\n'
  printf 'No tag, GitHub Release or production rollout was created.\n'
else
  printf 'M15 verdict is blocked; inspect %s\n' "$OUTPUT_DIR/m15-evidence.md" >&2
fi
exit "$check_rc"
