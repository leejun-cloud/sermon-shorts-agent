#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -e .
exec sermon-shorts-web --host 127.0.0.1 --port "${SERMON_SHORTS_PORT:-8787}"
