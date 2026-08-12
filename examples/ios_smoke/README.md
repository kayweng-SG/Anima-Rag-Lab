# iOS 真机 / 模拟器冒烟（含产品打磨）

拖进同一 Xcode App target：

| 文件 | 作用 |
|------|------|
| [`../app_clients/AnimaTriageClient.swift`](../app_clients/AnimaTriageClient.swift) | API + 灯号 UI 模型 + 错误文案 |
| [`../app_clients/AnimaKeychain.swift`](../app_clients/AnimaKeychain.swift) | API Key → Keychain |
| [`TriageSmokeView.swift`](TriageSmokeView.swift) | 冒烟 UI（鉴权 / 红黄绿 / 固定免责） |
| [`Info+LocalNetwork.plist`](Info+LocalNetwork.plist) | Debug HTTP ATS |

## 1. 启动 API

```bash
cd anima-rag-lab
export ANIMA_API_HOST=0.0.0.0
./scripts/run_demo.sh          # 带 ANIMA_API_KEY
# ./scripts/run_demo_open.sh   # 临时开放、不改 .env
```

## 2. Base URL

| 环境 | Base URL |
|------|----------|
| Simulator | `http://127.0.0.1:8000` |
| 真机 | `http://<Mac局域网IP>:8000`（`ipconfig getifaddr en0`） |

## 3. 接线

```swift
// ContentView
TriageSmokeView()   // 默认读 ANIMA_BASE_URL，Key 从 Keychain 解析
```

在 App 内「鉴权」区粘贴与 `.env` 相同的 `ANIMA_API_KEY` → **保存到 Keychain**。

## 4. 产品行为（已内建）

| 项 | 行为 |
|----|------|
| Key | Keychain（`AfterFirstUnlockThisDeviceOnly`），不写 UserDefaults |
| 401 | 中文提示：请填写/检查 API Key |
| 超时 / 离线 | 中文提示：检查同网与网络 |
| 免责声明 | 底部固定条：`TriageScreenModel.defaultDisclaimer` |
| RED sources | `showSourcesAsAdvice == false`，不当护理建议展示 |

## 5. 期望结果

| 按钮 | 灯号 |
|------|------|
| 巧克力 · 精神还行 | YELLOW |
| 中毒 · 老鼠药+呕吐 | RED + 急诊横幅 |
| 正常心率 | GREEN |

服务端自检：

```bash
./scripts/smoke_ios_api.sh
```
