#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r tests/protocol/requirements.txt

(
  cd tests/browser
  npm install
  npx playwright install chromium
)

echo "bootstrap complete"
