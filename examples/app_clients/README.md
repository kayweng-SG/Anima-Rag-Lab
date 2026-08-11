# AnimaLink App client samples

Copy-paste clients for `POST /v1/triage/query`.

| File | Platform | Notes |
|------|----------|--------|
| [`AnimaTriageClient.swift`](AnimaTriageClient.swift) | iOS | URLSession + Codable |
| [`AnimaTriageClient.kt`](AnimaTriageClient.kt) | Android | OkHttp + kotlinx.serialization |
| [`triage_query.ts`](triage_query.ts) | TypeScript / RN | `fetch` |

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

| `red_light_status` | `intercepted` | App should |
|--------------------|---------------|------------|
| `RED` | `true` | Emergency banner + `statusExplain` + `answer_zh`; **do not** treat `sources` as care advice |
| `YELLOW` | `false` | Caution + answer + optional sources |
| `GREEN` | `false` | Info + answer + sources |

Always show: 不能替代执业兽医诊断.
