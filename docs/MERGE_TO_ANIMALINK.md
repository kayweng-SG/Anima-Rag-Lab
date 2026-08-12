# Anima-Rag-Lab → AnimaLink 交接说明

本仓库（**ANIMA-RAG-Lab**）定位：为 AnimaLink 准备 **急症语料、Red-Light 闸门、可调用 RAG 分诊 API**。  
主产品在：`/Documents/Works/AnimaLink`（React + Supabase）。  
**本 Lab 完成标准 = 数据管线可用 + v1 契约稳定 + 评测可回归**；不包含 AnimaLink UI 合并实现。

## 合并进 AnimaLink 时怎么用

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

TS 样例可参考：`examples/app_clients/triage_query.ts`（可迁入 AnimaLink `src/lib/`）。

## 本仓库交付物清单（Lab Done）

| 类别 | 路径 / 命令 | 说明 |
|------|-------------|------|
| 急症语料 | `data/raw/`、`data/processed/`、`data/vector_store/` | Merck 等；向量约 13.5k |
| 有毒植物 | `data/triage_tree/aspca_toxic_plants.json` | Red-Light 匹配 |
| 主诉映射 | `data/triage_tree/complaint_clinical_map.json` | Task 0.3 |
| 红灯引擎 | `scripts/03_red_light_intercept.py` | <500ms 目标 |
| RAG + API | `scripts/06_rag_query.py`、`07_api_server.py` | `POST /v1/triage/query` |
| Web 验收 UI | `frontend/index.html` + `./scripts/run_demo.sh` | 口播用 |
| 契约 | `docs/APP_INTEGRATION.md` | App / AnimaLink 对接 |
| 部署 | `docs/DEPLOY.md`、`Dockerfile`、`./scripts/run_staging.sh` | Staging 可选 |
| 回归 | `evals/cases.json`、`python scripts/09_run_eval.py` | 固定评测 |
| 口播自检 | `./scripts/smoke_demo_guide.sh` | 绿/黄/红 × 6 |

## 本地验收（合并前跑一遍）

```bash
cd anima-rag-lab
source venv/bin/activate
./scripts/run_demo.sh          # 或 run_demo_open.sh 仅本地口播
./scripts/smoke_demo_guide.sh  # 6/6
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py
```

## 明确不在本仓库范围（交给 AnimaLink）

- Supabase Auth / 宠物档案 / C-BARQ·MCPQ-R 产品 UI  
- `rag-stream` Edge Function 与一方数据会话记忆  
- TestFlight / 正式域名（可用本 API 作后端服务）  
- 模块 B/C **产品化**（本 Lab 仅可后续继续「收料」；入库进 AnimaLink pgvector 在主项目做）

## 建议的 AnimaLink 合并顺序（本仓完成后）

1. ~~AnimaLink 环境变量 + `triageQuery()`~~ → **已落地**（`AnimaLink/src/lib/triage/triageQuery.ts`，`VITE_ANIMA_TRIAGE_URL`；生产金钥仍建议 Edge 代理）  
2. ~~聊天入口：先 triage，RED 短路~~ → **已落地**（`sendRagMessage`）  
3. （可选）将 Merck chunk 同步进 Supabase `pgvector`，与现有语料分区  
4. 联调：Lab `./scripts/run_demo_open.sh` + AnimaLink `.env` 指向 `http://127.0.0.1:8000`

## 模块 B / C 与本仓关系

| Lab 表 | 本仓状态 | 说明 |
|--------|----------|------|
| A 急症 | **完成** | 可交接 AnimaLink（产品侧已接线） |
| B 行为常模 | **0.4/0.5 收料完成** | OA 文献 + AKC；付费原版未镜像；产品常模在 AnimaLink |
| C 日常育养 | **收料中** | 0.7 URL 清单 ✅；0.6 AAHA 需人工下 PDF |

**结论：A 线可交接且产品已短路接线；B/C 继续收料不阻塞 A。**  
完整计划 vs 实际进度：[`WBS_STATUS.md`](./WBS_STATUS.md)。
