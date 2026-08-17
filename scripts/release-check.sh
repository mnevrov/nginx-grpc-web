#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
RELEASE_VERSION=${RELEASE_VERSION:-v0.1.0}
NGINX_VERSION=${NGINX_VERSION:-1.30.4}
BUILD_CC=${BUILD_CC:-gcc}
RELEASE_OUTPUT_DIR=${RELEASE_OUTPUT_DIR:-"$ROOT/dist/release/${RELEASE_VERSION}-rc"}
RELEASE_GATES=${RELEASE_GATES:-}
RELEASE_CONTROLLED_DIR=${RELEASE_CONTROLLED_DIR:-}
RELEASE_SOAK_DIR=${RELEASE_SOAK_DIR:-}
RELEASE_ALLOW_INCONCLUSIVE=${RELEASE_ALLOW_INCONCLUSIVE:-0}
ARCH=$(uname -m)

require_path() {
  local value=$1 label=$2
  if [[ -z "$value" ]]; then
    echo "$label is required" >&2
    exit 2
  fi
  if [[ ! -e "$value" ]]; then
    echo "$label not found: $value" >&2
    exit 2
  fi
}

require_path "$RELEASE_GATES" RELEASE_GATES
require_path "$RELEASE_CONTROLLED_DIR" RELEASE_CONTROLLED_DIR
require_path "$RELEASE_SOAK_DIR" RELEASE_SOAK_DIR

case "$RELEASE_ALLOW_INCONCLUSIVE" in
  0|1) ;;
  *) echo "RELEASE_ALLOW_INCONCLUSIVE must be 0 or 1" >&2; exit 2 ;;
esac

rm -rf "$RELEASE_OUTPUT_DIR"
mkdir -p "$RELEASE_OUTPUT_DIR/artifacts" "$RELEASE_OUTPUT_DIR/controlled" "$RELEASE_OUTPUT_DIR/soak"

cp "$RELEASE_GATES" "$RELEASE_OUTPUT_DIR/gates.json"
cp -a "$RELEASE_CONTROLLED_DIR"/. "$RELEASE_OUTPUT_DIR/controlled/"
cp -a "$RELEASE_SOAK_DIR"/. "$RELEASE_OUTPUT_DIR/soak/"

revalidation_rc=0
if [[ "$RELEASE_ALLOW_INCONCLUSIVE" == "0" ]]; then
  set +e
  python3 "$ROOT/release/revalidate.py" \
    --repo-root "$ROOT" \
    --controlled-dir "$RELEASE_OUTPUT_DIR/controlled" \
    --soak-dir "$RELEASE_OUTPUT_DIR/soak" \
    --output "$RELEASE_OUTPUT_DIR/revalidation.json"
  revalidation_rc=$?
  set -e
  if [[ ! -f "$RELEASE_OUTPUT_DIR/revalidation.json" ]]; then
    cat > "$RELEASE_OUTPUT_DIR/revalidation.json" <<EOF
{
  "version": 1,
  "valid": false,
  "reason": "raw_revalidation",
  "error": "revalidation command exited with status ${revalidation_rc} without writing a result"
}
EOF
  fi
else
  cat > "$RELEASE_OUTPUT_DIR/revalidation.json" <<'EOF'
{
  "version": 1,
  "valid": null,
  "skipped": "harness_only"
}
EOF
fi

OUT_ROOT="$RELEASE_OUTPUT_DIR/artifacts" \
NGINX_VERSION="$NGINX_VERSION" \
BUILD_CC="$BUILD_CC" \
  bash "$ROOT/scripts/package-module.sh"

PACKAGE_DIR="$RELEASE_OUTPUT_DIR/artifacts/nginx-${NGINX_VERSION}-${BUILD_CC}-linux-${ARCH}"
args=(
  --repo-root "$ROOT"
  --release-version "$RELEASE_VERSION"
  --nginx-version "$NGINX_VERSION"
  --compiler "$BUILD_CC"
  --gates "$RELEASE_OUTPUT_DIR/gates.json"
  --package-dir "$PACKAGE_DIR"
  --controlled-dir "$RELEASE_OUTPUT_DIR/controlled"
  --soak-dir "$RELEASE_OUTPUT_DIR/soak"
  --revalidation "$RELEASE_OUTPUT_DIR/revalidation.json"
  --output "$RELEASE_OUTPUT_DIR/release-evidence.json"
  --markdown "$RELEASE_OUTPUT_DIR/release-evidence.md"
)
if [[ "$RELEASE_ALLOW_INCONCLUSIVE" == "1" ]]; then
  args+=(--allow-inconclusive)
fi

set +e
python3 "$ROOT/release/check.py" "${args[@]}"
check_rc=$?
set -e

printf 'release bundle:   %s\n' "$RELEASE_OUTPUT_DIR"
printf 'release evidence: %s\n' "$RELEASE_OUTPUT_DIR/release-evidence.md"

if [[ "$check_rc" != "0" ]]; then
  exit "$check_rc"
fi
if [[ "$revalidation_rc" != "0" ]]; then
  # Defensive: a successful final verdict must never mask a failed production revalidation process.
  echo "raw evidence revalidation failed with status $revalidation_rc" >&2
  exit "$revalidation_rc"
fi
