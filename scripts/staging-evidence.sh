#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT_DIR=${STAGING_EVIDENCE_OUTPUT_DIR:-"$ROOT/perf/results/staging-evidence-$(date -u +%Y%m%dT%H%M%SZ)"}

require_file_var() {
  local name=$1
  local value=${!name:-}
  if [[ -z "$value" ]]; then
    echo "$name is required" >&2
    exit 2
  fi
  if [[ ! -f "$value" ]]; then
    echo "$name file not found: $value" >&2
    exit 2
  fi
}

require_dir_var() {
  local name=$1
  local value=${!name:-}
  if [[ -z "$value" ]]; then
    echo "$name is required" >&2
    exit 2
  fi
  if [[ ! -d "$value" ]]; then
    echo "$name directory not found: $value" >&2
    exit 2
  fi
}

require_dir_var STAGING_PACKAGE_DIR
require_dir_var STAGING_NATIVE_BROWSER_DIR
require_dir_var STAGING_ROLLBACK_BROWSER_DIR
require_file_var STAGING_NGINX_V
require_file_var STAGING_NGINX_T
require_file_var STAGING_DEPLOYED_SHA256
require_file_var STAGING_RSS_EVIDENCE
require_file_var STAGING_ROLLBACK_EVIDENCE

if [[ -e "$OUTPUT_DIR" ]]; then
  echo "staging evidence output already exists: $OUTPUT_DIR" >&2
  exit 2
fi
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "staging evidence generation requires a clean git worktree" >&2
  exit 2
fi

SOURCE_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
mkdir -p "$OUTPUT_DIR"
python3 "$ROOT/staging/evidence.py" \
  --source-commit "$SOURCE_COMMIT" \
  --package-dir "$STAGING_PACKAGE_DIR" \
  --native-browser-dir "$STAGING_NATIVE_BROWSER_DIR" \
  --rollback-browser-dir "$STAGING_ROLLBACK_BROWSER_DIR" \
  --nginx-v "$STAGING_NGINX_V" \
  --nginx-t "$STAGING_NGINX_T" \
  --deployed-sha256 "$STAGING_DEPLOYED_SHA256" \
  --rss-evidence "$STAGING_RSS_EVIDENCE" \
  --rollback-evidence "$STAGING_ROLLBACK_EVIDENCE" \
  --output "$OUTPUT_DIR/staging-evidence.json" \
  --markdown "$OUTPUT_DIR/staging-evidence.md"

printf 'staging evidence: %s\n' "$OUTPUT_DIR"
