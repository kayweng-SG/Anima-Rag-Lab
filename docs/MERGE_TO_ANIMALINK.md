# Anima-Rag-Lab → AnimaLink 交接说明

本仓库（**ANIMA-RAG-Lab**）定位：为 AnimaLink 准备 **急症语料、Red-Light 闸门、可调用 RAG 分诊 API，以及 B/C 行为/育养语料**。  
主产品在：`/Documents/Works/AnimaLink`（React + Supabase）。  
**本 Lab 完成标准 = 数据管线可用 + v1 契约稳定 + 评测可回归**；不包含 AnimaLink UI 合并实现。

> **操作约束（2026-08-13）：只动本仓。** App 联调 / AnimaLink 改码 **整段延后**。  
> 交接入口：[`LAB_HANDOFF.md`](./LAB_HANDOFF.md)

## 合并进 AnimaLink 时怎么用（日后）

推荐：**AnimaLink（或 Edge Function）HTTP 调用本 API**，急症先过红灯，再决定是否走现有 `rag-stream`。

```
饲主主诉 / 预警事件
  → POST {LAB}/v1/triage/query
      RED + intercepted=true  → 急诊文案（勿当 sources 为护理建议）
      YELLOW / GREEN          → 可再调 AnimaLink 双轨 RAG / 一方数据
```

契约全文：[`APP_INTEGRATION.md`](APP_INTEGRATION.md)  
OpenAPI：`{BASE}/docs` · `{BASE}/openapi.json`

### 最小对接字段

| 方向 | 字段 |
|------|------|
| 请求 | `question`（必填）、`species`、`size`、体征可选、`client_request_id` |
| 响应 | `red_light_status`、`intercepted`、`answer_zh`、`extracted_symptoms`、`sources`、`record_id` |
| 鉴权 | Header `X-API-Key`（当 Lab `.env` 设了 `ANIMA_API_KEY`） |

TS 样例：`examples/app_clients/triage_query.ts`（对接阶段再迁入 AnimaLink）。

## 本仓库交付物清单（Lab Done · 2026-08-13）

| 类别 | 路径 / 命令 | 说明 |
|------|-------------|------|
| 急症 + B/C 向量 | `data/processed/merged_vector_store/` | **13998**（A 13572 + B 330 + C 96） |
| B/C 切块 | `data/processed/module_bc_chunks.json` | AKC / C-BARQ / MCPQ / AAHA / PetTalk |
| Lab pgvector 镜像 | `scripts/16_local_pgvector.py` | SQLite+numpy，schema 对齐 |
| 有毒植物 | `data/triage_tree/aspca_toxic_plants.json` | Red-Light |
| 主诉映射 | `data/triage_tree/complaint_clinical_map.json` | Task 0.3 |
| 红灯引擎 | `scripts/03_red_light_intercept.py` | <500ms |
| RAG + API | `scripts/06_rag_query.py`、`07_api_server.py` | `POST /v1/triage/query` |
| Web 验收 UI | `frontend/` + `./scripts/run_demo.sh` | 口播 |
| 契约 | `docs/APP_INTEGRATION.md` | App 契约（延后接线） |
| 部署预备 | `docs/DEPLOY.md`、Compose、Tunnel 脚本 | 可选 |
| 回归 | `evals/cases.json`（23 案，含 module_bc×5） | `09_run_eval.py` |
| 云端预备 | `supabase/migrations/` + `14/15_*` | 未对真实项目执行 |
| 交接包 | [`LAB_HANDOFF.md`](./LAB_HANDOFF.md) + `handoff_manifest.json` | L3 |

## 本地验收（合并前跑一遍 · 仅 Lab）

```bash
cd anima-rag-lab
source venv/bin/activate
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py          # 23/23
python scripts/16_local_pgvector.py smoke --query cbarq
./scripts/run_demo.sh
./scripts/smoke_demo_guide.sh                           # 可选口播
```

## 明确不在本仓库范围（交给 AnimaLink · 延后）

- Supabase Auth / 宠物档案 / C-BARQ·MCPQ-R **产品 UI**  
- `rag-stream` Edge Function 与一方数据会话记忆  
- TestFlight / 正式域名  
- 在 AnimaLink 项目执行 pgvector migration + upsert  

## 建议的 AnimaLink 合并顺序（**整段延后**）

1. AnimaLink 环境变量 / Edge 代理 → Lab Base URL  
2. 聊天入口：先 triage，RED 短路  
3. （可选）chunk 同步进 Supabase pgvector — 见 [`SUPABASE_MERGE.md`](SUPABASE_MERGE.md)  
4. 联调：红 / 黄 / 绿各一案  

## 模块 A / B / C

| Lab 表 | 本仓状态 | 说明 |
|--------|----------|------|
| A 急症 | **完成** | Merck + Red-Light + API |
| B 行为 | **收料 + 入库 + eval** | C-BARQ / MCPQ-R / AKC |
| C 育养 | **收料 + 入库 + eval** | AAHA Table1 + PetTalk 正文抽样 |

完整计划 vs 实际：[`WBS_STATUS.md`](./WBS_STATUS.md)。  
机器清单：`python scripts/18_handoff_manifest.py` → `docs/handoff_manifest.json`。
