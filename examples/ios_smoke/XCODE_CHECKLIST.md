# Xcode 接线检查清单（iOS）

目标：模拟器 / 真机 5–10 分钟跑通黄灯 · 红灯 · 绿灯，并验证 Keychain 与错误态。

## A. 工程文件

- [ ] New App（SwiftUI）或现有 target
- [ ] 加入同一 target：
  - [ ] `examples/app_clients/AnimaTriageClient.swift`
  - [ ] `examples/app_clients/AnimaKeychain.swift`
  - [ ] `examples/ios_smoke/TriageSmokeView.swift`
- [ ] `Info.plist` 合并 `examples/ios_smoke/Info+LocalNetwork.plist`（Debug HTTP / 局域网）
- [ ] `ContentView` → `TriageSmokeView()`

## B. 本机 API

- [ ] `git pull` 后仓库含最新 client
- [ ] `.env` 有 `ANIMA_API_KEY`（与 App 将保存的 Key 一致）
- [ ] 启动：`export ANIMA_API_HOST=0.0.0.0 && ./scripts/run_demo.sh`
- [ ] 先跑服务端自检：`./scripts/smoke_ios_api.sh` → 3/3 PASS
- [ ] `curl -s http://127.0.0.1:8000/health | jq .auth_required` → `true`

## C. Base URL

| 目标 | Base URL |
|------|----------|
| Simulator | `http://127.0.0.1:8000` |
| 真机（同 Wi‑Fi） | `http://$(ipconfig getifaddr en0):8000` |

- [ ] App「连接」栏填对 Base URL
- [ ] 点 **检查 /health** → `status=ok`，`auth_required=true`

## D. API Key

- [ ] 从本机 `.env` 复制 `ANIMA_API_KEY`（勿截图进聊天 / 勿提交）
- [ ] App「鉴权」→ 粘贴 → **保存到 Keychain**
- [ ] 故意清空 Key 再分诊 → 应出现中文 **401 / Key** 提示
- [ ] 恢复 Key → 分诊成功

## E. 功能冒烟

| 示例按钮 | 期望 |
|----------|------|
| 黄灯 · 巧克力 | YELLOW；有症状 chips；可有 sources |
| 红灯 · 中毒 | RED；急诊横幅；不把 sources 当护理建议 |
| 绿灯 · 心率 | GREEN；有建议 / sources |
| （可选）黄灯 · 中暑轻 | YELLOW；chips 含「仍清醒能走」 |

- [ ] 底部固定免责声明始终可见（不随结果滚走）
- [ ] 断网或错 URL → 超时 / 离线中文提示

## F. 常见翻车

| 现象 | 处理 |
|------|------|
| health 失败 · 真机 | Mac 防火墙；API 未 `0.0.0.0`；IP 过期重查 `en0` |
| ATS 拦截 HTTP | 合并 Local Networking plist |
| 401 | Key 与 `.env` 不一致；未点保存 Keychain |
| 编译缺 `AnimaKeychain` | 未把 `AnimaKeychain.swift` 加进 target |
| 黄灯很慢 | 正常（LLM）；可先看 RED 路径是否秒回 |

## G. 通过标准

- [ ] 黄 / 红 / 绿各至少一次成功  
- [ ] Keychain 重启 App 后仍能分诊（无需重贴 Key）  
- [ ] 底部免责文案存在  

通过后 → Staging Base URL 换成 `docs/DEPLOY.md` / `./scripts/run_staging.sh` 地址，并去掉 Debug ATS（改 HTTPS）。

产品壳（3 Tab 首屏）：[`../ios_app/`](../ios_app/) · 入口 `AnimaRootView()`。
