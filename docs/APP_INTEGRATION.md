# AnimaLink App Integration Guide

Contract version: **v1**  
Primary endpoint: `POST /v1/triage/query`

## Base URL

| Environment | Example |
|-------------|---------|
| Local demo | `http://127.0.0.1:8000` |
| Staging / prod | set by your deployment |

OpenAPI: `{BASE}/docs` · Machine schema: `{BASE}/openapi.json`

## Authentication

If server env `ANIMA_API_KEY` is set, every triage endpoint requires a key.

```http
X-API-Key: <ANIMA_API_KEY>
```

or

```http
Authorization: Bearer <ANIMA_API_KEY>
```

| Mode | When | Behavior |
|------|------|----------|
| Dev / open | `ANIMA_API_KEY` empty | No auth required (local UI works) |
| App / prod | `ANIMA_API_KEY` set | Missing/invalid key → `401 unauthorized` |

`GET /health`, `GET /`, `GET /docs` stay public.

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | no | Liveness + capability flags |
| GET | `/v1` | no | Contract discovery |
| POST | `/v1/triage/query` | if configured | **App triage call** |
| GET | `/v1/triage/results` | if configured | Recent saved results |
| GET | `/v1/triage/results/{id}` | if configured | Fetch one result |
| POST | `/triage/query` | if configured | Legacy alias (same body/response) |

## Request — `POST /v1/triage/query`

```json
{
  "question": "中暑怎么办？散步后喘气、流口水，仍清醒能走。",
  "species": "dog",
  "size": "large",
  "heart_rate_bpm": 120,
  "crt_seconds": 1.5,
  "rectal_temp_f": 102.8,
  "rectal_temp_c": 39.3,
  "map_mmhg": null,
  "symptoms": [],
  "chief_complaint": "",
  "top_k": 5,
  "client_request_id": "app-session-abc-001"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `question` | string | **yes** | Free-text situation (症状 + 问题). 1–4000 chars |
| `species` | string | no | `dog` \| `cat` \| `unknown` |
| `size` | string | no | `small` \| `large` (dogs) |
| `heart_rate_bpm` | number | no | 0–400 |
| `crt_seconds` | number | no | Capillary refill, 0–10 |
| `rectal_temp_f` | number | no | °F |
| `rectal_temp_c` | number | no | °C |
| `map_mmhg` | number | no | Mean arterial pressure |
| `symptoms` | string[] | no | Optional; usually auto-extracted |
| `chief_complaint` | string | no | Deprecated; prefer `question` |
| `top_k` | int | no | Retrieval depth, default 5 (1–20) |
| `client_request_id` | string | no | App tracing / correlation id |

Optional header: `X-Request-Id` (server echoes it; generates UUID if absent).

## Response — success `200`

```json
{
  "api_version": "v1",
  "request_id": "app-session-abc-001",
  "record_id": "uuid…",
  "answer": "分诊结论：YELLOW\n\n…",
  "answer_zh": "分诊结论：YELLOW\n\n…",
  "answer_en": "Triage: YELLOW\n\n…",
  "recommendation_zh": "…",
  "recommendation_en": "…",
  "intercepted": false,
  "red_light_status": "YELLOW",
  "red_light": { "status": "YELLOW", "alerts": [], "elapsed_ms": 0.1 },
  "sources": [
    {
      "rank": 1,
      "score": 0.74,
      "content": "…",
      "content_zh": "…",
      "chunk_type_zh": "段落",
      "metadata": {}
    }
  ],
  "retrieval_query": "…",
  "model_used": "gpt-4o-mini",
  "elapsed_ms": 420.5,
  "evaluated_at": "2026-08-11T01:00:00+00:00",
  "extracted_symptoms": ["喘气", "流口水", "中暑"]
}
```

### App rendering rules

Prefer the shared screen mapper in [`examples/app_clients/`](../examples/app_clients/)
(`TriageScreenModel` / `mapTriageScreen`) instead of ad-hoc conditionals.

| `red_light_status` | `intercepted` | UI behavior |
|--------------------|---------------|-------------|
| `RED` | `true` | Emergency banner; **do not** show sources as “advice”; emphasize clinic now |
| `YELLOW` | `false` | Caution + structured guidance + sources |
| `GREEN` | `false` | Informational guidance + sources |

Always show disclaimer: not a substitute for licensed veterinary care.

Prefer `answer_zh` for CN App; keep `answer_en` for bilingual screens.

## Errors

All errors use:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid API key…",
    "request_id": "…",
    "details": null
  }
}
```

| HTTP | `error.code` | When |
|------|--------------|------|
| 401 | `unauthorized` | Bad/missing API key |
| 404 | `not_found` | Unknown `record_id` |
| 422 | `validation_error` | Bad body (empty question, out-of-range vitals) |
| 500 | `internal_error` | Pipeline failure |
| 503 | `service_unavailable` | Store/vector not loaded |

## curl examples

```bash
# Health (public)
curl -s http://127.0.0.1:8000/health | jq

# Triage (dev — no key)
curl -s -X POST http://127.0.0.1:8000/v1/triage/query \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "小狗正常心率是多少？",
    "species": "dog",
    "size": "small",
    "heart_rate_bpm": 95
  }' | jq '.red_light_status, .answer_zh'

# Triage (prod — with key)
export ANIMA_API_KEY=replace-me
curl -s -X POST http://127.0.0.1:8000/v1/triage/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ANIMA_API_KEY" \
  -H "X-Request-Id: demo-001" \
  -d '{
    "question": "猫吃了百合叶子，现在在吐",
    "species": "cat",
    "client_request_id": "demo-001"
  }' | jq
```

## App client samples (copy-paste)

完整可落地代码在 [`examples/app_clients/`](../examples/app_clients/)：

| File | Platform |
|------|----------|
| `AnimaTriageClient.swift` | iOS（URLSession + Codable；灯号模型 + `userMessageZh`） |
| `AnimaKeychain.swift` | iOS API Key → Keychain |
| `AnimaTriageClient.kt` | Android（OkHttp + kotlinx.serialization） |
| `triage_query.ts` | TypeScript / React Native |

iOS 冒烟 UI：[`examples/ios_smoke/`](../examples/ios_smoke/)（Keychain、401/超时、底部固定免责）  
iOS 产品壳：[`examples/ios_app/`](../examples/ios_app/)（3 Tab + 首屏预算）  
Xcode 清单：[`examples/ios_smoke/XCODE_CHECKLIST.md`](../examples/ios_smoke/XCODE_CHECKLIST.md)  
部署：[`docs/DEPLOY.md`](DEPLOY.md) · `./scripts/run_staging.sh` · `./scripts/smoke_ios_api.sh`

### Swift（摘要）

```swift
let client = AnimaTriageClient(
  baseURL: URL(string: "http://127.0.0.1:8000")!,
  apiKey: nil  // 生产环境填 ANIMA_API_KEY
)
let result = try await client.query(
  TriageQueryRequest(
    question: "小狗吃了巧克力，精神还行，有点担心。",
    species: "dog",
    size: "small"
  )
)
print(result.redLightStatus ?? "?", result.statusExplain.title, result.answerZh)
```

### Kotlin（摘要）

```kotlin
val client = AnimaTriageClient(
  baseUrl = "http://10.0.2.2:8000", // 模拟器访问宿主机
  apiKey = null
)
val result = client.query(
  TriageQueryRequest(
    question = "小狗吃了巧克力，精神还行，有点担心。",
    species = "dog",
    size = "small"
  )
)
val (title, _) = result.statusExplain()
```

### 真机 / 模拟器 Base URL

| 运行环境 | Base URL |
|----------|----------|
| iOS Simulator | `http://127.0.0.1:8000` |
| Android Emulator | `http://10.0.2.2:8000` |
| 真机 | `http://<电脑局域网IP>:8000`，且服务端 `ANIMA_API_HOST=0.0.0.0` |

iOS 本地 HTTP 需在 Info.plist 允许 App Transport Security 例外（仅 debug）。

## Server env for App deployment

```bash
# .env  （勿提交；已在 .gitignore）
ANIMA_API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
ANIMA_CORS_ORIGINS=https://app.animalink.example,http://localhost:3000
ANIMA_API_HOST=0.0.0.0
ANIMA_API_PORT=8000
OPENAI_API_KEY=...          # optional; improves GREEN/YELLOW answers
ANIMA_LLM_MODEL=gpt-4o-mini
```

### App 鉴权检查清单

1. `.env` 写入 `ANIMA_API_KEY`（长随机串），重启 API  
2. `GET /health` → `"auth_required": true`  
3. 无 Key 调 `POST /v1/triage/query` → `401 unauthorized`  
4. App client 传入同一把 key：

```swift
AnimaTriageClient(
  baseURL: URL(string: "http://192.168.88.6:8000")!,
  apiKey: "«与 .env 中 ANIMA_API_KEY 相同»"
)
```

5. 本地 Web demo：顶部会出现 API Key 输入框（存 localStorage）；真机 App 用 client 构造参数，不要把 key 写进仓库  

开发时若只想跑开放 demo：注释掉 / 清空 `ANIMA_API_KEY` 再重启即可。

## Compatibility notes

- Local demo UI continues to call `/triage/query` (alias of `/v1/triage/query`) and sends `X-API-Key` when the browser has a saved key.
- `api_version` is always `"v1"` in success payloads.
- Response headers include `X-Request-Id` and `X-API-Version: v1`.