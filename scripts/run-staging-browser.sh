#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BROWSER=${STAGING_BROWSER:-chromium}
LABEL=${STAGING_LABEL:-native-module}
OUTPUT_DIR=${STAGING_OUTPUT_DIR:-"$ROOT/perf/results/staging-$(date -u +%Y%m%dT%H%M%SZ)-$LABEL"}

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

SOURCE_COMMIT=$(git -C "$ROOT" rev-parse HEAD)
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
    "label": os.environ.get("STAGING_LABEL", "native-module"),
    "browser": os.environ.get("STAGING_BROWSER", "chromium"),
    "endpoints": endpoints,
}, indent=2) + "\n", encoding="utf-8")
PY

rm -rf "$ROOT/tests/browser/test-results"
(
  cd "$ROOT/tests/browser"
  npm install --package-lock=false --no-audit --no-fund
  set +e
  npx playwright test -c playwright.staging.config.ts --project="$BROWSER"
  test_rc=$?
  set -e
  printf '%s\n' "$test_rc" > "$OUTPUT_DIR/playwright-exit-code.txt"
  if [[ -d test-results ]]; then
    cp -a test-results "$OUTPUT_DIR/browser-test-results"
  fi
  exit "$test_rc"
)

python3 - "$OUTPUT_DIR/manifest.json" "$OUTPUT_DIR/playwright-exit-code.txt" <<'PY'
import json
import sys
from pathlib import Path
manifest_path = Path(sys.argv[1])
value = json.loads(manifest_path.read_text())
value["playwright_exit_code"] = int(Path(sys.argv[2]).read_text().strip())
value["browser_acceptance_passed"] = value["playwright_exit_code"] == 0
manifest_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
PY

printf 'staging browser evidence: %s\n' "$OUTPUT_DIR"
