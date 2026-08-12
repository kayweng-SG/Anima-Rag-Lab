# AnimaLink App client samples

Copy-paste clients for `POST /v1/triage/query`.

| File | Platform | Notes |
|------|----------|--------|
| [`AnimaTriageClient.swift`](AnimaTriageClient.swift) | iOS | URLSession + Codable |
| [`AnimaTriageClient.kt`](AnimaTriageClient.kt) | Android | OkHttp + kotlinx.serialization |
| [`triage_query.ts`](triage_query.ts) | TypeScript / RN | `fetch` |
| [`../ios_smoke/`](../ios_smoke/) | iOS smoke UI | SwiftUI + ATS + 红黄绿按钮 |

Full contract: [`docs/APP_INTEGRATION.md`](../../docs/APP_INTEGRATION.md)

## Quick test against local demo

```bash
# Terminal: start API (binds 127.0.0.1 by default)
./scripts/run_demo.sh
```

| Client | Base URL |
|--------|----------|
| iOS Simulator | `http://127.0.0.1:8000` |
| Android Emulator | `http://10.0.2.2:8000` |
| Physical phone | `http://<Mac-LAN-IP>:8000` + set `ANIMA_API_HOST=0.0.0.0` |

## UI mapping (must follow)

Use the shared mapper in each client — do not invent per-screen `if` trees:

| Platform | Helper |
|----------|--------|
| iOS | `result.screen` → `TriageScreenModel` |
| Android | `result.screen()` → `TriageScreenModel` |
| TS / RN | `mapTriageScreen(result)` |

| Flag | RED | YELLOW | GREEN |
|------|-----|--------|-------|
| `showEmergencyBanner` | ✅ | — | — |
| `showInterceptedHint` | if `intercepted` | — | — |
| `showSourcesAsAdvice` | ❌ never | ✅ | ✅ |
| Primary copy | `answerZh` | `answerZh` | `answerZh` |
| Chips | `symptomChips` | same | same |

Always show `disclaimer`（不能替代执业兽医诊断与治疗）。

```swift
let ui = result.screen
if ui.showEmergencyBanner { /* 急诊横幅 */ }
Text(ui.badge)
Text(ui.answerZh)
if ui.showSourcesAsAdvice { /* 才展示 sources 作参考 */ }
```

## API Key（App / 生产）

服务端 `.env` 设置 `ANIMA_API_KEY` 后，`/health` 会返回 `"auth_required": true`。

| Client | 传入方式 |
|--------|----------|
| iOS | `AnimaTriageClient(baseURL:…, apiKey: "…")` |
| Android | `AnimaTriageClient(baseUrl=…, apiKey="…")` |
| TS | `new AnimaTriageClient({ baseUrl, apiKey })` |
| 本地 Web demo | 顶部输入框 → localStorage |

密钥只放本机 `.env` / App 安全存储，**不要**提交到 git。