#!/usr/bin/env bash
# Expose local triage API via Cloudflare quick tunnel (WBS 4.3).
# Requires: API already listening on ANIMA_API_PORT (default 8000).
# Does not need a Cloudflare account for trycloudflare.com URLs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${ANIMA_API_PORT:-8000}"
BIN_DIR="${ROOT}/tools/bin"
CF="${BIN_DIR}/cloudflared"
ARCH="$(uname -m)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"

case "${OS}-${ARCH}" in
  darwin-arm64) ASSET="cloudflared-darwin-arm64.tgz" ;;
  darwin-x86_64) ASSET="cloudflared-darwin-amd64.tgz" ;;
  linux-x86_64|linux-amd64) ASSET="cloudflared-linux-amd64" ;;
  linux-aarch64|linux-arm64) ASSET="cloudflared-linux-arm64" ;;
  *)
    echo "Unsupported platform: ${OS}-${ARCH}. Install cloudflared manually:" >&2
    echo "  https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/" >&2
    exit 1
    ;;
esac

mkdir -p "${BIN_DIR}"

if [[ ! -x "${CF}" ]]; then
  echo "Downloading cloudflared (${ASSET})…"
  VER="${CLOUDFLARED_VERSION:-2025.2.1}"
  BASE="https://github.com/cloudflare/cloudflared/releases/download/${VER}"
  TMP="$(mktemp -d)"
  trap 'rm -rf "${TMP}"' EXIT
  if [[ "${ASSET}" == *.tgz ]]; then
    curl -fsSL "${BASE}/${ASSET}" -o "${TMP}/cf.tgz"
    tar -xzf "${TMP}/cf.tgz" -C "${TMP}"
    # tarball usually contains ./cloudflared
    SRC="$(find "${TMP}" -type f -name cloudflared | head -1)"
    cp "${SRC}" "${CF}"
  else
    curl -fsSL "${BASE}/${ASSET}" -o "${CF}"
  fi
  chmod +x "${CF}"
fi

if ! curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "API not healthy on :${PORT}. Start it first, e.g.:" >&2
  echo "  ./scripts/run_demo.sh" >&2
  echo "  # or: REDIS_URL=memory://local ./scripts/run_demo.sh" >&2
  exit 1
fi

echo "────────────────────────────────────────"
echo " Cloudflare quick tunnel → http://127.0.0.1:${PORT}"
echo " After URL appears, smoke with:"
echo "   ANIMA_BASE_URL=https://<trycloudflare-host> ./scripts/smoke_ios_api.sh"
echo " Ctrl+C stops the tunnel (API keeps running)."
echo "────────────────────────────────────────"
exec "${CF}" tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate
