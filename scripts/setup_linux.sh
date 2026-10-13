#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null || ! command -v npm >/dev/null; then
  echo 'Python 3.12+ and Node.js 20.19+ are required.'
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
if ! .venv/bin/python -m playwright install chromium; then
  echo 'Chromium download failed. Direct public-page retrieval remains available.'
  echo 'If browser dependencies are missing, try: .venv/bin/python -m playwright install --with-deps chromium'
fi
npm --prefix frontend install --no-package-lock
npm --prefix frontend run build
if [ ! -f .env ]; then cp .env.example .env; fi
echo 'Setup complete. Run ./scripts/run_local.sh to open Motorwise.'
