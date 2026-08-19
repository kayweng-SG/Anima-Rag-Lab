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

## Vector store (A + B/C)

Default load order:

1. `ANIMA_VECTOR_STORE_DIR` if set  
2. else `data/processed/merged_vector_store/` when present  
3. else Module A only: `data/processed/merck_vector_store/`

Lab API retrieval (`ANIMA_RETRIEVAL`, default `auto`):

- `auto` — call Supabase `match_knowledge_chunks` when URL + service_role are set; fall back to local numpy on RPC error  
- `supabase` — RPC only (no fallback)  
- `local` — numpy store only (pytest / eval)

Rebuild B/C merge (does **not** re-embed Merck):

```bash
python scripts/12_chunk_module_bc.py
MERCK_EMBEDDER=sentence_transformers python scripts/13_embed_module_bc.py
```

## Redis semantic cache (optional, WBS 4.1)

```bash
# One-shot (Docker Redis if present, else memory://local):
./scripts/run_with_cache.sh

# Or Compose:
docker compose --profile cache up --build -d
# in .env:
REDIS_URL=redis://127.0.0.1:6379/0
# inside Compose network: redis://redis:6379/0
# no Docker smoke: REDIS_URL=memory://local
```

Caches non-intercepted triage responses (~1h TTL). RED never served from cache. Without `REDIS_URL`, API behaves as before. `/health` reports `cache_enabled` + `cache_backend`.

```bash
python scripts/smoke_semantic_cache.py
```

## Public HTTPS (checklist)

| Step | Notes |
|------|--------|
| 1. VPS / Fly / Railway | Run `docker compose up -d` with `.env` secrets |
| 2. TLS | Cloudflare Tunnel **or** Caddy reverse proxy |
| 3. DNS | `api.yourdomain.com` → tunnel / proxy |
| 4. Smoke | `ANIMA_BASE_URL=https://api.yourdomain.com ./scripts/smoke_ios_api.sh` |
| 5. App | Point `VITE_ANIMA_TRIAGE_URL` / iOS Base URL at HTTPS |

### Quick public URL (no domain yet)

1. Start API locally (`./scripts/run_demo.sh` or `./scripts/run_with_cache.sh`)
2. In another terminal: `./scripts/run_public_tunnel.sh`  
   (downloads `cloudflared` into `tools/bin/` on first run)
3. Copy the printed `https://….trycloudflare.com` URL → iOS / `ANIMA_BASE_URL`
4. Smoke: `ANIMA_BASE_URL=https://….trycloudflare.com ./scripts/smoke_ios_api.sh`

Quick tunnels are ephemeral. For a stable hostname, use a named Cloudflare Tunnel or Caddy on an operator-owned VPS.

## Ops notes

- First container boot may download `paraphrase-multilingual-MiniLM-L12-v2` unless the HF cache volume is warm.
- RED intercept never calls OpenAI; GREEN/YELLOW quality improves with `OPENAI_API_KEY`.
- Rotate `ANIMA_API_KEY` by editing `.env` and recreating the container (`docker compose up -d --force-recreate`).
- Path alias `data/vector_store/` in older notes = `data/processed/merck_vector_store/` (or merged).
