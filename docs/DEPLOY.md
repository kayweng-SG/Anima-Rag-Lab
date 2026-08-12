# Deploy AnimaLink triage API (iOS-ready)

Lab → staging checklist for a fixed Base URL that an iOS App can call.

## What to ship

| Piece | Notes |
|-------|--------|
| API | `scripts/07_api_server.py` (FastAPI) |
| Data | `data/vector_store/` + triage SQLite under `data/` |
| Secrets | `.env` only — never bake `ANIMA_API_KEY` / `OPENAI_API_KEY` into the image |

## Quick path: Docker Compose on a VPS / Mac

```bash
cd anima-rag-lab
cp .env.example .env
# edit: ANIMA_API_KEY, OPENAI_API_KEY (optional), ANIMA_CORS_ORIGINS

./scripts/run_staging.sh
# 或：docker compose up --build -d
curl -s http://127.0.0.1:8000/health | jq .auth_required   # true when key set
./scripts/smoke_ios_api.sh
```
### Required `.env`

```bash
ANIMA_API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
ANIMA_API_HOST=0.0.0.0
ANIMA_API_PORT=8000
# App / web origins (comma-separated). Native iOS URLSession is not CORS-bound,
# but keep this set if you also ship a web client.
ANIMA_CORS_ORIGINS=https://app.animalink.example,http://localhost:3000
OPENAI_API_KEY=...          # optional
ANIMA_LLM_MODEL=gpt-4o-mini
```

## iOS Base URL matrix

| Where API runs | iOS target | Base URL |
|----------------|------------|----------|
| Same Mac, demo | Simulator | `http://127.0.0.1:8000` |
| Same LAN | Physical iPhone | `http://<Mac-or-VPS-LAN-IP>:8000` |
| Public HTTPS | TestFlight / prod | `https://api.yourdomain.com` |

Client:

```swift
AnimaTriageClient(
  baseURL: URL(string: "https://api.yourdomain.com")!,
  apiKey: /* Keychain / xcconfig — not in git */
)
```

Use [`examples/ios_smoke/`](../examples/ios_smoke/) for first paint; TLS in production (no ATS exception).

## Open demo vs secured App

| Mode | Command | `auth_required` |
|------|---------|-----------------|
| Secured (App) | `./scripts/run_demo.sh` or Compose with key | `true` |
| Open (live talk) | `./scripts/run_demo_open.sh` | `false` |

`run_demo_open.sh` forces an empty `ANIMA_API_KEY` in-process and **does not** rewrite `.env`.

## Smoke before handing to iOS

```bash
./scripts/smoke_ios_api.sh
# Expect: yellow_chocolate / red_poison / green_hr → PASS
```

## Reverse proxy (optional)

Terminate TLS at Caddy / nginx / Cloudflare Tunnel → `127.0.0.1:8000`.  
Forward `X-API-Key` and `X-Request-Id` unchanged.

## Ops notes

- First container boot may download `paraphrase-multilingual-MiniLM-L12-v2` unless the HF cache volume is warm.
- RED intercept never calls OpenAI; GREEN/YELLOW quality improves with `OPENAI_API_KEY`.
- Rotate `ANIMA_API_KEY` by editing `.env` and recreating the container (`docker compose up -d --force-recreate`).
