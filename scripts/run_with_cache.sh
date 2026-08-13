#!/usr/bin/env bash
# Start API with semantic cache enabled (WBS 4.1).
# Prefers Docker Redis (--profile cache); falls back to memory:// for local smoke.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d venv ]]; then
  echo "缺少 venv。请先：python3 -m venv venv && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

PORT="${ANIMA_API_PORT:-${PORT:-8000}}"
HOST="${ANIMA_API_HOST:-${HOST:-127.0.0.1}}"

if [[ -z "${REDIS_URL:-}" ]]; then
  if command -v docker >/dev/null 2>&1; then
    echo "Starting Compose redis (profile cache)…"
    docker compose --profile cache up -d redis
    export REDIS_URL="redis://127.0.0.1:${REDIS_PORT:-6379}/0"
    for _ in $(seq 1 30); do
      if docker compose --profile cache exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
        break
      fi
      sleep 1
    done
  else
    echo "Docker not found — using in-process cache: REDIS_URL=memory://local"
    export REDIS_URL="memory://local"
  fi
fi

echo "────────────────────────────────────────"
echo " AnimaLink API + semantic cache"
echo " REDIS_URL: ${REDIS_URL}"
echo " UI:        http://${HOST}:${PORT}/"
echo " Health:    http://${HOST}:${PORT}/health  (cache_enabled)"
echo "────────────────────────────────────────"

python scripts/smoke_semantic_cache.py

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export ANIMA_API_HOST="${HOST}"
export ANIMA_API_PORT="${PORT}"

exec python scripts/07_api_server.py
