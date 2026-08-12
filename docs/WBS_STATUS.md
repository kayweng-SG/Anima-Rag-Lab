# Anima-RAG-Lab WBS 状态表（对照 Master WBS）

**来源：** [`BoAnima-RAG-Lab 專案管理主表 (Master WBS).xlsx`](./BoAnima-RAG-Lab%20專案管理主表%20(Master%20WBS).xlsx)  
**对照表：** 工作表「Anima-RAG-Lab 專案管理主表」（新表；OLD 表日程更早，仅作历史）  
**更新日期：** 2026-08-12  
**说明：** 本文件记录 **计划 vs 实际**，并写明与原表不同的执行路径（本地 FastAPI 向量库先行，Supabase 并入 AnimaLink 时再对齐）。

状态图例：

| 标记 | 含义 |
|------|------|
| ✅ Done | 已满足或等价完成验收 |
| 🟡 Partial | 有交付，但与原表路径/范围不完全一致 |
| ⬜ Todo | 未开始或明显未达标 |
| ⏸ Deferred | 刻意延后（改到 AnimaLink 合并阶段或后续 Sprint） |

---

## 总览

| 阶段 | 计划窗口（新表） | 总体状态 | 备注 |
|------|------------------|----------|------|
| Part 1 · 模块 A `0.1–0.3` | 8/3–8/5 | ✅ | Merck / ASPCA / 主诉映射已入库 |
| Part 1 · 模块 B `0.4–0.5` | 8/5–8/6 | ⬜ | 逾期；仅收料，不阻塞 A 本地 API |
| Part 1 · 模块 C `0.6–0.7` | 8/6–8/7 | ⬜ | 同上 |
| Sprint 1 · ETL `1.1–1.3` | 8/10–8/14 | 🟡 | A 侧实质超前；B/C 切块未做 |
| Sprint 2 · Supabase `2.1–2.4` | 8/17–8/21 | ⏸ | **路径调整**：本地 vector store 已可用；pgvector 并 AnimaLink 时做 |
| Sprint 3 · API `3.1–3.4` | 8/24–8/28 | ✅ / 🟡 | **日程提前完成**（本地 FastAPI）；TS Interface 在 examples |
| Sprint 4 · 收尾 `4.1–4.4` | 8/31–9/4 | 🟡 | 评测与交接文档已有；Redis / 公网 URL 未做 |

**Lab「模块 A 急症线」可交接 AnimaLink：** 见 [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md)。  
**整份 WBS 到 4.4 全绿：** 尚未完成（缺 B/C 收料、Supabase 2.x、Redis、正式对外部署）。

---

## Part 1：数据收集

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 0.1 | Merck 急诊资料 | 8/3–8/4 | ✅ | `data/raw/`、处理与向量化管线；急诊 + owner 扩展语料 |
| 0.2 | ASPCA 有毒植物 | 8/3–8/4 | ✅ | `data/triage_tree/aspca_toxic_plants.json`；Red-Light 匹配 |
| 0.3 | Kaggle / 主诉临床映射 | 8/4–8/5 | ✅ | `complaint_clinical_map`（CSV/JSON）；吐黄水等主诉扩展 |
| 0.4 | C-BARQ & MCPQ-R 常模 | 8/5–8/6 | ⬜ | 未下载 PDF 常模包 |
| 0.5 | AKC 品种 JSON | 8/5–8/6 | ⬜ | 未入库开源 breed dataset |
| 0.6 | AAHA Life Stage | 8/6–8/7 | ⬜ | 未归档官方 PDF |
| 0.7 | PetTalk 等亚洲卫教 URL | 8/6–8/7 | ⬜ | 未产出 URL 清单 |

**调整说明：** `0.4–0.7` 原排在 A 之后；A 本地急症 API 已可独立验收，B/C **只收料、暂不接 RAG**，不阻塞 AnimaLink 急症对接。

---

## Sprint 1：ETL 结构化清洗

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 1.1 | 症状树 JSON / Triage | 8/10–8/11 | 🟡→实质 ✅ | 原案「LLM 转 JSON」；实际为规则引擎 `03_red_light_intercept.py` + 结构化 metrics（RED/YELLOW/GREEN）。验收「明确分灯」已达成。 |
| 1.2 | 知识库切块与标註 | 8/11–8/12 | 🟡 | **A 语料**已 chunk + embed（本地）；**B/C** 依赖 0.4–0.7，未做。原案 LlamaIndex metadata 未全盘采用。 |
| 1.3 | 医疗防护边界抽验 | 8/13–8/14 | 🟡 | 有 `evals/cases.json`、`09_run_eval.py`、`smoke_demo_guide.sh`；非表定「人工抽检 10%」全文档化流程。致命类红灯有自动化覆盖。 |

---

## Sprint 2：数据库与向量（路径调整）

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 2.1 | Supabase 建表 + pgvector | 8/17 | ⏸ | **未建** `symptoms_tree` / `knowledge_chunks` 于 Supabase。 |
| 2.2 | HNSW + 检索 RPC | 8/18 | ⏸ | 未部署；本地检索在 Python vector store。 |
| 2.3 | 批次写入 + Embedding | 8/19–8/20 | 🟡 等价 | 本地 `sentence-transformers` + `data/vector_store/`（约 13.5k）；非 OpenAI embed 写入 Supabase。 |
| 2.4 | RLS | 8/21 | ⏸ | 改由 Lab `ANIMA_API_KEY` 守 API；表级 RLS 留给 AnimaLink / 合并阶段。 |

**调整说明（写进计划偏差）：**  
Sprint 2 原目标是 AnimaLink 同栈的 Supabase。Lab 为加速 A 验收，采用 **本地向量 + FastAPI**。合并时：要么 (a) 将 chunk 同步进 AnimaLink pgvector，要么 (b) AnimaLink HTTP 调用本 API，暂不迁库。

---

## Sprint 3：核心 API（日程提前）

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 3.1 | API 初始化 / health | 8/24 | ✅ 提前 | FastAPI；`GET /health` → 200 |
| 3.2 | Triage 红灯拦截 | 8/25–8/26 | ✅ 提前 | <500ms 拦截；RED 不耗 LLM |
| 3.3 | 双轨 RAG 检索 | 8/27–8/28 | 🟡 | 非红灯走 RAG + 可选 OpenAI；**尚未**「呼叫 Supabase RPC Top 3」。本地 Top-K 向量检索已通。 |
| 3.4 | 型別与防呆 | 8/28 | 🟡 | Python Pydantic + 统一 error body；TS 样例在 `examples/app_clients/`。完整 AnimaLink 内 Interface 合并时再落。 |

契约：[`APP_INTEGRATION.md`](./APP_INTEGRATION.md)

---

## Sprint 4：测试、优化与部署

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 4.1 | Semantic Cache (Redis) | 8/31–9/1 | ⬜ | 未接入 Upstash Redis |
| 4.2 | 自动化 RAG 品质评估 | 9/2 | 🟡 | 固定 eval + DEMO smoke；非完整 RAGAS 框架；「急诊 100%」靠规则用例覆盖，非全量证明 |
| 4.3 | CI/CD 对外部署 | 9/3 | ⬜ / 🟡 | 有 Docker Compose 草稿与 `run_staging.sh`；**无**正式公网 URL / Vercel 流水线 |
| 4.4 | API 文件与交接 | 9/4 | ✅ 提前 | `APP_INTEGRATION.md`、`MERGE_TO_ANIMALINK.md`、`DEPLOY.md`、DEMO_GUIDE |

---

## 建议的「改表」结论（给 PM）

1. **模块 A（0.1–0.3 + 本地 1.1/3.x + 交接文档）→ 标为 Done，可进 AnimaLink 急症对接。**  
2. **Sprint 2（2.1–2.4）→ 标 Deferred / 合并阶段**，验收改为「本地向量可检索」或「已写入 AnimaLink pgvector」。  
3. **0.4–0.7 → 仍 Todo**，下一执行窗专做收料（PDF/JSON/URL），不回头挡 A。  
4. **4.1 Redis、4.3 公网 URL → 按 AnimaLink 上线需要再排**，不作为 Lab 关闭必要条件。  
5. Excel 主表可保留计划日期；**以本 Markdown 为实际状态源（source of truth for status）**，避免和超前完成的 API 日程打架。

---

## 下一执行窗（建议）

| 优先级 | 动作 | 对应 WBS |
|--------|------|----------|
| P0 | AnimaLink 串 `POST /v1/triage/query` | 原 4.4 之后的产品工作 |
| P1 | 收集 0.4–0.7 原料并归档到 `data/raw/` | Part 1 B/C |
| P2 | （可选）chunk B/C → 本地或 Supabase | 1.2 / 2.3 |
| P3 | Redis 缓存、公网部署 | 4.1 / 4.3 |

---

## 修订记录

| 日期 | 变更 |
|------|------|
| 2026-08-12 | 初版：对照新表；记录本地 FastAPI 路径偏差与 A 线完成、B/C 与 Supabase 延后 |
