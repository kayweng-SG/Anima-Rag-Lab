# AnimaLink iOS App — 信息架构（首版）

配套代码草稿：本目录 SwiftUI 壳。冒烟仍用 [`../ios_smoke/`](../ios_smoke/)。

## 导航（3 Tab）

```
TabView
├─ 分诊   AnimaTriageHomeView     ← 首屏 / 主路径
├─ 记录   AnimaHistoryView        ← GET /v1/triage/results
└─ 设置   AnimaSettingsView       ← Base URL + Keychain Key
```

## 分诊主路径

```
Home（主诉 + 可选体征）
  → 提交 POST /v1/triage/query
  → Result（TriageScreenModel）
       RED  → 急诊横幅 + 结论；无 sources 建议
       YELLOW/GREEN → 结论 + 可选来源
  → 底部固定免责（全 App）
```

## 首屏内容预算（必须遵守）

第一屏只放：

1. 品牌 **AnimaLink**  
2. 一句说明（紧急分诊辅助，非诊疗）  
3. 主诉输入（必填）  
4. 次要：物种 / 体型（折叠或一行）  
5. 主 CTA「开始分诊」  
6. 固定免责条  

**不要**塞：统计条、多卡片营销、来源列表、历史摘要。

## 屏幕 ↔ API

| 屏 | API | 关键字段 |
|----|-----|----------|
| Home → Result | `POST /v1/triage/query` | `question`, vitals, `client_request_id` |
| Result | — | `red_light_status`, `answer_zh`, `extracted_symptoms`, `sources` |
| 记录 | `GET /v1/triage/results` | `record_id`, status, preview |
| 设置 | `GET /health` | `auth_required`, `llm_enabled` |

## 状态机（UI）

| 状态 | UI |
|------|-----|
| idle | Home 可提交 |
| loading | CTA disabled；短文案「分诊中…」 |
| success | Push/Sheet Result |
| error | 横幅用 `AnimaTriageError.userMessageZh`；可重试 |

## 里程碑

| M1 | 本目录壳 + 冒烟三灯 + Keychain |
| M2 | 历史列表 + 详情回看 |
| M3 | Staging HTTPS Base URL + 去掉 ATS 例外 |
| M4 | TestFlight 内测 |

接线清单：[`../ios_smoke/XCODE_CHECKLIST.md`](../ios_smoke/XCODE_CHECKLIST.md)
