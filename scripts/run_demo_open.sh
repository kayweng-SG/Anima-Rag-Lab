#!/usr/bin/env bash
# Open (no API key) demo — does NOT modify .env.
# Forces ANIMA_API_KEY empty so dotenv will not re-apply a stored key
# (07_api_server only loads .env keys that are missing from the environment).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d venv ]]; then
  echo "缺少 venv。请先：python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source venv/bin/activate

PORT="${PORT:-8000}"
HOST="${ANIMA_API_HOST:-0.0.0.0}"

export ANIMA_API_HOST="$HOST"
export ANIMA_API_PORT="${ANIMA_API_PORT:-$PORT}"
export ANIMA_API_KEY=
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

echo "────────────────────────────────────────"
echo " AnimaLink Demo · OPEN (no API key)"
echo " UI:      http://127.0.0.1:${ANIMA_API_PORT}/"
echo " Health:  http://127.0.0.1:${ANIMA_API_PORT}/health"
echo " Bind:    ${ANIMA_API_HOST}:${ANIMA_API_PORT}"
echo " 口播稿:  docs/DEMO_GUIDE.md"
echo " 恢复鉴权: ./scripts/run_demo.sh  （读取 .env 的 ANIMA_API_KEY）"
echo "────────────────────────────────────────"
echo "启动中…（Ctrl+C 停止）"
echo

exec python scripts/07_api_server.py
