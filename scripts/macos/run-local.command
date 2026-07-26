#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display alert "python3가 필요합니다" message "먼저 Python 3를 설치해주세요."'
  exit 1
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -e .
PORT="${SERMON_SHORTS_PORT:-8787}"
URL="http://127.0.0.1:${PORT}"
( sleep 2; open "$URL" ) >/dev/null 2>&1 &
exec sermon-shorts-web --host 127.0.0.1 --port "$PORT"
