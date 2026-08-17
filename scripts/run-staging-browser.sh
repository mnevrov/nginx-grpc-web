#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BROWSER=${STAGING_BROWSER:-chromium}
LABEL=${STAGING_LABEL:-native-module}
OUTPUT_DIR=${STAGING_OUTPUT_DIR:-"$ROOT/perf/results/staging-$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"}
OUTPUT_DIR=$(python3 - "$OUTPUT_DIR" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).resolve())
PY
)

for name in STAGING_ENDPOINT STAGING_UNAVAILABLE_ENDPOINT STAGING_TIMEOUT_ENDPOINT; do
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required" >&2
    exit 2
  fi
done
case "$BROWSER" in
  chromium|firefox|webkit) ;;
  *) echo "STAGING_BROWSER must be chromium, firefox or webkit" >&2; exit 2 ;;
esac
if [[ ! "$LABEL" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "STAGING_LABEL must contain only letters, numbers, dot, underscore or dash" >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
  echo "staging evidence output already exists: $OUTPUT_DIR" >&2
  exit 2
fi
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "staging acceptance requires a clean git worktree before execution" >&2
  exit 2
fi
if [[ ! -f "$ROOT/tests/browser/package-lock.json" ]]; then
  echo "tests/browser/package-lock.json is required for reproducible staging acceptance" >&2
  exit 2
fi

SOURCE_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
export SOURCE_COMMIT
export STAGING_BROWSER_RESOLVED="$BROWSER"
export STAGING_LABEL_RESOLVED="$LABEL"
mkdir -p "$OUTPUT_DIR"

python3 - "$OUTPUT_DIR/manifest.json" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

endpoints = {}
for name in ("STAGING_ENDPOINT", "STAGING_UNAVAILABLE_ENDPOINT", "STAGING_TIMEOUT_ENDPOINT"):
    value = os.environ[name]
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit(f"{name} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise SystemExit(f"{name} must not embed credentials in the URL")
    endpoints[name.lower()] = value.rstrip("/")

Path(sys.argv[1]).write_text(json.dumps({
    "version": 1,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_commit": os.environ["SOURCE_COMMIT"],
    "label": os.environ["STAGING_LABEL_RESOLVED"],
    "browser": os.environ["STAGING_BROWSER_RESOLVED"],
    "endpoints": endpoints,
}, indent=2) + "\n", encoding="utf-8")
PY

rm -rf "$ROOT/tests/browser/test-results"
set +e
(
  cd "$ROOT/tests/browser"
  npm ci --no-audit --no-fund
  npx playwright test -c playwright.staging.config.ts --project="$BROWSER"
)
test_rc=$?
set -e

printf '%s\n' "$test_rc" > "$OUTPUT_DIR/playwright-exit-code.txt"
if [[ -d "$ROOT/tests/browser/test-results" ]]; then
  cp -a "$ROOT/tests/browser/test-results" "$OUTPUT_DIR/browser-test-results"
fi

python3 - "$OUTPUT_DIR/manifest.json" "$test_rc" <<'PY'
import json
import sys
from pathlib import Path
manifest_path = Path(sys.argv[1])
value = json.loads(manifest_path.read_text())
value["playwright_exit_code"] = int(sys.argv[2])
value["browser_acceptance_passed"] = value["playwright_exit_code"] == 0
manifest_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
PY

printf 'staging browser evidence: %s\n' "$OUTPUT_DIR"
exit "$test_rc"
