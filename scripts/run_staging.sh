#!/usr/bin/env bash
# Staging-oriented API bring-up (Docker Compose).
# Does not commit secrets. Requires Docker Desktop / engine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "缺少 .env。先：cp .env.example .env 并填写 ANIMA_API_KEY（及可选 OPENAI_API_KEY）"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "未找到 docker。请安装 Docker Desktop 后重试。"
  exit 1
fi

# Ensure host bind for LAN / iPhone; compose maps host port.
export ANIMA_API_PORT="${ANIMA_API_PORT:-8000}"
# Native iOS does not need CORS; keep defaults unless you also ship web.
export ANIMA_CORS_ORIGINS="${ANIMA_CORS_ORIGINS:-}"

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"

echo "────────────────────────────────────────"
echo " AnimaLink Staging (Docker Compose)"
echo " Local:   http://127.0.0.1:${ANIMA_API_PORT}/"
if [[ -n "${LAN_IP}" ]]; then
  echo " LAN:     http://${LAN_IP}:${ANIMA_API_PORT}/  ← iPhone Base URL"
fi
echo " Health:  http://127.0.0.1:${ANIMA_API_PORT}/health"
echo " Docs:    docs/DEPLOY.md"
echo "────────────────────────────────────────"

docker compose config -q
docker compose up --build -d

echo
echo "Waiting for /health…"
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${ANIMA_API_PORT}/health" >/dev/null 2>&1; then
    curl -s "http://127.0.0.1:${ANIMA_API_PORT}/health" | python3 -m json.tool | head -20
    echo
    echo "Smoke:"
    ANIMA_BASE_URL="http://127.0.0.1:${ANIMA_API_PORT}" ./scripts/smoke_ios_api.sh || true
    echo
    echo "iOS：Base URL 用 LAN 地址；Key 用 .env 的 ANIMA_API_KEY（Keychain）。"
    echo "停服：docker compose down"
    exit 0
  fi
  sleep 5
done

echo "TIMEOUT: /health not ready. Check: docker compose logs -f api" >&2
docker compose ps >&2 || true
exit 1
