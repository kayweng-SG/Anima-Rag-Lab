#!/usr/bin/env bash
# One-click AnimaLink triage demo: start API + print URLs.
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
HOST="${HOST:-127.0.0.1}"

echo "────────────────────────────────────────"
echo " AnimaLink Demo"
echo " UI:      http://${HOST}:${PORT}/"
echo " Docs:    http://${HOST}:${PORT}/docs"
echo " Health:  http://${HOST}:${PORT}/health"
echo " 口播稿:  docs/DEMO_GUIDE.md"
echo "────────────────────────────────────────"
echo "启动中…（Ctrl+C 停止）"
echo

# Prefer offline Hugging Face cache when present (demo-friendly).
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"

exec python scripts/07_api_server.py
