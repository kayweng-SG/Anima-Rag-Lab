# AnimaLink App client samples

Copy-paste clients for `POST /v1/triage/query`.

| File | Platform | Notes |
|------|----------|--------|
| [`AnimaTriageClient.swift`](AnimaTriageClient.swift) | iOS | URLSession + Codable + 错误文案 |
| [`AnimaKeychain.swift`](AnimaKeychain.swift) | iOS | API Key → Keychain |
| [`AnimaTriageClient.kt`](AnimaTriageClient.kt) | Android | OkHttp + kotlinx.serialization |
| [`triage_query.ts`](triage_query.ts) | TypeScript / RN | `fetch` |
| [`../ios_smoke/`](../ios_smoke/) | iOS smoke UI | Keychain + 401/超时 + 固定免责 |

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
| iOS | **Keychain**（`AnimaKeychain.setAPIKey`）或 `AnimaTriageClient(..., apiKey:)`；Debug 可用 Scheme env |
| Android | `AnimaTriageClient(baseUrl=…, apiKey="…")`（建议 EncryptedSharedPreferences） |
| TS | `new AnimaTriageClient({ baseUrl, apiKey })` |
| 本地 Web demo | 顶部输入框 → localStorage |

密钥只放本机 Keychain / `.env` / App 安全存储，**不要**提交到 git。

### iOS 错误态（`AnimaTriageError.userMessageZh`）

| 情况 | 文案要点 |
|------|----------|
| 401 / unauthorized | 请填写/检查 API Key |
| 超时 | 确认同网后重试 |
| 离线 | 检查 Wi‑Fi / 蜂窝 |
| 503 | 服务未就绪 |

UI 固定展示 `TriageScreenModel.defaultDisclaimer`（底部条，不随结果滚动消失）。