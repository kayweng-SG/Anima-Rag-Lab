# iOS 真机 / 模拟器冒烟

把 [`../app_clients/AnimaTriageClient.swift`](../app_clients/AnimaTriageClient.swift) 与本目录的 `TriageSmokeView.swift` 拖进 Xcode App target，按下面 5 分钟跑通红/黄/绿。

## 1. 启动 API（带鉴权）

```bash
cd anima-rag-lab
# .env 已有 ANIMA_API_KEY
export ANIMA_API_HOST=0.0.0.0 ANIMA_API_PORT=8000
./scripts/run_demo.sh
```

开放演示（临时关鉴权，不改 `.env`）：

```bash
./scripts/run_demo_open.sh
```

## 2. Base URL + Key

| 环境 | Base URL |
|------|----------|
| iOS Simulator | `http://127.0.0.1:8000` |
| 真机（同 Wi‑Fi） | `http://<Mac局域网IP>:8000` |

查 IP：`ipconfig getifaddr en0`  
Key：与 `.env` 里 `ANIMA_API_KEY` 相同（Xcode Scheme → Environment Variables，或写在 `Config` 里，**勿提交**）。

## 3. ATS（仅 Debug HTTP）

将 `Info+LocalNetwork.plist` 片段合并进 App 的 Info，或在 target Info 勾选 **App Transport Security → Allow Local Networking**。

## 4. 接线

```swift
let client = AnimaTriageClient(
  baseURL: URL(string: ProcessInfo.processInfo.environment["ANIMA_BASE_URL"]
    ?? "http://127.0.0.1:8000")!,
  apiKey: ProcessInfo.processInfo.environment["ANIMA_API_KEY"]
)
// ContentView → TriageSmokeView(client: client)
```

## 5. 期望结果

| 按钮 | `red_light_status` | UI |
|------|--------------------|-----|
| 巧克力 · 精神还行 | YELLOW | 无急诊横幅；可看 sources |
| 中毒 · 老鼠药+呕吐 | RED | 急诊横幅；`showSourcesAsAdvice=false` |
| 正常心率 | GREEN | 建议 + sources |

服务端也可先自检（不依赖 Xcode）：

```bash
./scripts/smoke_ios_api.sh
```
