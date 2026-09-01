# ANIMA-RAG-Lab 交接包（Lab Handoff）

**日期：** 2026-08-26  
**范围：** 仅本仓库 `anima-rag-lab`。  
**不包含：** AnimaLink App UI 接线、正式域名运维、真 Redis（延后到整合按需）。

本文件是对接时的 **单一入口**：交付物、验收命令、文档索引、已知缺口。

---

## 1. Lab 完成标准（已满足）

| 标准 | 证据 |
|------|------|
| 数据管线可用 | Module A/B/C 已入库；merged store **13998**；云端 Supabase `knowledge_chunks` **13998**（`--verify` In sync） |
| v1 契约稳定 | `POST /v1/triage/query` + C-BARQ / MCPQ-R 性格 API；见 [`APP_INTEGRATION.md`](./APP_INTEGRATION.md) |
| 评测可回归 | `evals/cases.json` **25** 案（含 Module B/C）全过 |
| 检索双轨 | `ANIMA_RETRIEVAL=auto`：有密钥走 Supabase RPC，失败回落本地 |
| 部署烟雾 | `memory://` cache + Cloudflare quick tunnel + `smoke_ios_api` 3/3 |

状态源：[`WBS_STATUS.md`](./WBS_STATUS.md)

---

## 2. 交付物清单

### 2.1 向量与检索

| 路径 | 说明 |
|------|------|
| `data/processed/merck_vector_store/` | Module A only |
| `data/processed/merged_vector_store/` | **默认**：A + B/C = **13998** |
| `data/processed/module_bc_chunks.json` | B/C 切块 |
| `data/pgvector_local/` | Lab 内 SQLite+numpy 镜像（schema 对齐 pgvector） |
| Supabase `knowledge_chunks` | 云端 **13998**（A 13572 / B 330 / C 96） |

API 加载顺序：`ANIMA_VECTOR_STORE_DIR` → `merged_vector_store/` → `merck_vector_store/`。

### 2.2 原始语料（B/C）

| WBS | 路径 | 要点 |
|-----|------|------|
| 0.4 | `data/raw/module_b_behavior/cbarq_mcpq_r/` | C-BARQ 14/14；MCPQ-R 26 词 + lab blank |
| 0.5 | `data/raw/module_b_behavior/akc_breeds/` | AKC 品种表 |
| 0.6 | `data/raw/module_c_husbandry/aaha/` | 犬/猫 PDF + Table 1 正文 |
| 0.7 | `data/raw/module_c_husbandry/pettalk_asia/` | URL 清单 + articles（狗优先过滤） |

### 2.3 急症闸门、性格与 API

| 路径 | 说明 |
|------|------|
| `scripts/03_red_light_intercept.py` | RED/YELLOW/GREEN |
| `scripts/06_rag_query.py` / `07_api_server.py` | RAG + FastAPI |
| `scripts/19_cbarq_personality.py` | C-BARQ → 主人报告 / 类 MBTI |
| `scripts/20_mcpq_personality.py` | MCPQ-R → 五维 + 主人报告 |
| `frontend/index.html` | 本机 demo UI |

### 2.4 Supabase（已上云）

| 路径 | 说明 |
|------|------|
| `supabase/migrations/20260813_knowledge_chunks.sql` | 表 + HNSW + RPC |
| `scripts/14_export_pgvector.py` / `15_upsert_supabase.py` | 导出 / upsert |
| [`SUPABASE_MERGE.md`](./SUPABASE_MERGE.md) | 步骤说明 |

### 2.5 评测与烟雾

| 命令 | 期望 |
|------|------|
| `HF_HUB_OFFLINE=1 python scripts/09_run_eval.py` | **25/25** |
| `REDIS_URL=memory://local python scripts/smoke_semantic_cache.py` | PASS |
| `./scripts/smoke_ios_api.sh` | 3/3（需 API 已起） |
| `./scripts/run_public_tunnel.sh` | 临时 HTTPS（API 已起后） |

---

## 3. 重建 / 验收命令（Lab 内）

```bash
cd anima-rag-lab
source venv/bin/activate

# 评测
HF_HUB_OFFLINE=1 ANIMA_RETRIEVAL=local python scripts/09_run_eval.py

# API（本机；可选 memory cache）
REDIS_URL=memory://local ./scripts/run_demo.sh
# health: http://127.0.0.1:8000/health

# 临时公网
./scripts/run_public_tunnel.sh
ANIMA_BASE_URL=https://….trycloudflare.com ./scripts/smoke_ios_api.sh
```

机器可读清单：

```bash
python scripts/18_handoff_manifest.py
# → docs/handoff_manifest.json
```

---

## 4. 文档索引

| 文档 | 用途 |
|------|------|
| **本文件** `LAB_HANDOFF.md` | 交接入口 |
| [`WBS_STATUS.md`](./WBS_STATUS.md) | 计划 vs 实际 |
| [`APP_INTEGRATION.md`](./APP_INTEGRATION.md) | HTTP 契约（含性格 API） |
| [`SUPABASE_MERGE.md`](./SUPABASE_MERGE.md) | pgvector 上云 |
| [`DEPLOY.md`](./DEPLOY.md) | Docker / Redis / Tunnel（整合时按需） |
| [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md) | 产品合并说明 |
| [`DEMO_GUIDE.md`](./DEMO_GUIDE.md) | 口播 |

---

## 5. 已知缺口（延后到整合，不挡 Lab 关闭）

| 项 | 说明 |
|----|------|
| **Supabase 免费方案自动暂停** | 闲置 7 天即暂停（2026-08-27 已中招一次）。暂停时 `ANIMA_RETRIEVAL=auto` 会静默回落本地，服务不报错。**监控方式：** `/health` 的 `retrieval_last` 变 `local` 且 `retrieval_fallbacks` 增长。整合前需升级方案或加定期保活 |
| 真 Redis / Docker Compose cache | **延后**；Lab 用 `memory://` 已验收路径 |
| 正式域名 / named Tunnel | **延后**；quick tunnel 仅临时 |
| 完整 RAGAS | 可选加厚；现有固定 25 案回归已够 Lab |
| Monash MCPQ-R 官方空白 PDF | 本仓用 Ley 词表 lab blank |
| PetTalk / AAHA 全量 | 抽样 + Table 1；非全站 OCR |
| AnimaLink UI / Edge 接线 | **不在本仓执行** |

---

## 6. 整合时建议顺序

1. Lab API 起服 + `ANIMA_API_KEY`；App 设 Base URL  
2. 手测红/黄/绿 + 性格交卷 API  
3. （按需）Docker Redis → `REDIS_URL=redis://…`  
4. （按需）正式 HTTPS 域名  
5. 确认云端 RPC：`ANIMA_RETRIEVAL=auto` + `SUPABASE_*`

详见 [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md)。
