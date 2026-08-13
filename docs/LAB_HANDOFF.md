# ANIMA-RAG-Lab 交接包（Lab Handoff）

**日期：** 2026-08-13  
**范围：** 仅本仓库 `anima-rag-lab`。  
**不包含：** AnimaLink 改码、App 联调、云端 Supabase 真写入（一律延后）。

本文件是日后对接时的 **单一入口**：交付物、验收命令、文档索引、已知缺口。

---

## 1. Lab 完成标准（已满足）

| 标准 | 证据 |
|------|------|
| 数据管线可用 | Module A/B/C 已入库；merged store **14000** 向量 |
| v1 契约稳定 | `POST /v1/triage/query` + [`APP_INTEGRATION.md`](./APP_INTEGRATION.md) |
| 评测可回归 | `evals/cases.json` **23** 案（含 `module_bc`×5）全过 |

状态源：[`WBS_STATUS.md`](./WBS_STATUS.md)

---

## 2. 交付物清单

### 2.1 向量与检索

| 路径 | 说明 |
|------|------|
| `data/processed/merck_vector_store/` | Module A only（未改） |
| `data/processed/merged_vector_store/` | **默认**：A 13572 + B/C 428 = **14000** |
| `data/processed/module_bc_chunks.json` | B/C 切块（428） |
| `data/pgvector_local/` | Lab 内 SQLite+numpy 镜像（schema 对齐 pgvector） |

API 加载顺序：`ANIMA_VECTOR_STORE_DIR` → `merged_vector_store/` → `merck_vector_store/`。

### 2.2 原始语料（B/C）

| WBS | 路径 | 要点 |
|-----|------|------|
| 0.4 | `data/raw/module_b_behavior/cbarq_mcpq_r/` | C-BARQ 14/14；MCPQ-R 26 词 + **lab blank**（非 Monash 官方 PDF） |
| 0.5 | `data/raw/module_b_behavior/akc_breeds/` | AKC 品种表 |
| 0.6 | `data/raw/module_c_husbandry/aaha/` | 犬/猫 PDF + Table 1 正文抽取 |
| 0.7 | `data/raw/module_c_husbandry/pettalk_asia/` | URL 清单 + **articles.jsonl（~30 篇）** |

总览：[`data/raw/README_MODULE_BC.md`](../data/raw/README_MODULE_BC.md)

### 2.3 急症闸门与 API

| 路径 | 说明 |
|------|------|
| `scripts/03_red_light_intercept.py` | RED/YELLOW/GREEN |
| `data/triage_tree/aspca_toxic_plants.json` | 有毒植物 |
| `data/triage_tree/complaint_clinical_map.json` | 主诉→临床词 |
| `scripts/06_rag_query.py` / `07_api_server.py` | RAG + FastAPI |
| `frontend/index.html` | 本机 demo UI |

### 2.4 日后对接预备（本仓已备，未对云执行）

| 路径 | 说明 |
|------|------|
| `supabase/migrations/20260813_knowledge_chunks.sql` | 表 + HNSW + RPC |
| `…_supabase_grants.sql` | 云端 RLS / service_role（可选） |
| `scripts/14_export_pgvector.py` | 本地 → JSONL |
| `scripts/15_upsert_supabase.py` | JSONL → PostgREST（需密钥） |
| `scripts/16_local_pgvector.py` | 本仓等价 store |
| [`SUPABASE_MERGE.md`](./SUPABASE_MERGE.md) | 步骤说明 |

### 2.5 评测与烟雾

| 命令 | 期望 |
|------|------|
| `HF_HUB_OFFLINE=1 python scripts/09_run_eval.py` | **23/23** |
| `python scripts/09_run_eval.py --group module_bc` | **5/5** |
| `python scripts/16_local_pgvector.py smoke --query cbarq` | SMOKE PASS |
| `./scripts/smoke_demo_guide.sh` | 绿/黄/红口播自检 |

---

## 3. 重建 / 验收命令（Lab 内）

```bash
cd anima-rag-lab
source venv/bin/activate

# B/C 补洞（可选重跑）
python scripts/17_enrich_module_bc_gaps.py

# 切块 → 嵌入（不重算 Module A）
python scripts/12_chunk_module_bc.py
HF_HUB_OFFLINE=1 MERCK_EMBEDDER=sentence_transformers python scripts/13_embed_module_bc.py

# Lab-local pgvector 镜像
python scripts/16_local_pgvector.py bootstrap

# 评测
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py

# API（本机）
./scripts/run_demo.sh
# health: http://127.0.0.1:8000/health  → vector_count≈14000
```

生成机器可读清单：

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
| [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md) | 产品合并说明（对接延后） |
| [`APP_INTEGRATION.md`](./APP_INTEGRATION.md) | HTTP 契约 |
| [`SUPABASE_MERGE.md`](./SUPABASE_MERGE.md) | pgvector 路径 A/B |
| [`DEPLOY.md`](./DEPLOY.md) | Docker / Redis / Tunnel |
| [`DEMO_GUIDE.md`](./DEMO_GUIDE.md) | 口播 |
| [`evals/README.md`](../evals/README.md) | 评测用法 |

---

## 5. 已知缺口（不挡 Lab 关闭）

| 项 | 说明 |
|----|------|
| Monash MCPQ-R 官方空白 PDF | 未公开镜像；本仓用 Ley 词表 lab blank |
| PetTalk 全站全文 | 已抽样 ~30 篇，非全站 |
| AAHA 细表图元 OCR | Table 1 **已有正文**；其余图表仍以 PDF 为准 |
| 真 Redis / 稳定公网 | 可选；见 DEPLOY |
| 云端 Supabase upsert | 需 `SUPABASE_*`；对接阶段再做 |
| AnimaLink UI / Edge | **延后**，不在本仓执行 |

---

## 6. 日后对接时建议顺序（提醒，勿现在做）

1. Lab API 起服 + `ANIMA_API_KEY`  
2. AnimaLink 设 `VITE_ANIMA_TRIAGE_URL`（或 Edge 代理）  
3. 手测红/黄/绿  
4. （可选）执行 SQL migration + `15_upsert_supabase.py --apply`

详见 [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md)。
