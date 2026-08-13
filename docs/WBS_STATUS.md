# Anima-RAG-Lab WBS 状态表（对照 Master WBS）

**来源：** [`BoAnima-RAG-Lab 專案管理主表 (Master WBS).xlsx`](./BoAnima-RAG-Lab%20專案管理主表%20(Master%20WBS).xlsx)  
**对照表：** 工作表「Anima-RAG-Lab 專案管理主表」（新表；OLD 表日程更早，仅作历史）  
**更新日期：** 2026-08-13  
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
| Part 1 · 模块 B `0.4–0.5` | 8/5–8/6 | ✅ | 0.4 C-BARQ/MCPQ-R 计分可落地；0.5 AKC 已入库 |
| Part 1 · 模块 C `0.6–0.7` | 8/6–8/7 | ✅ | 0.6 AAHA 犬/猫 Life Stage PDF 已入库；0.7 URL 清单已有 |
| Sprint 1 · ETL `1.1–1.3` | 8/10–8/14 | 🟡→实质 ✅ | A 已 chunk；**B/C 已入库** `merged_vector_store`（A 13572 + B/C 381） |
| Sprint 2 · Supabase `2.1–2.4` | 8/17–8/21 | 🟡 | **本仓已跑通** `16_local_pgvector`（SQLite+numpy 镜像 schema）；云端 SQL/upsert 脚本已备 |
| Sprint 3 · API `3.1–3.4` | 8/24–8/28 | ✅ / 🟡 | 本地 FastAPI；默认可加载 merged store |
| Sprint 4 · 收尾 `4.1–4.4` | 8/31–9/4 | 🟡 | Redis 路径可跑（Compose / `memory://` / `run_with_cache.sh`）；公网可用 quick tunnel 脚本 |

**Lab「模块 A 急症线」可交接 AnimaLink：** 见 [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md)。**产品侧接线（2026-08-12）：** AnimaLink `src/lib/triage/triageQuery.ts` + `sendRagMessage` RED 短路已落地；设 `VITE_ANIMA_TRIAGE_URL` 启用。  
**整份 WBS 到 4.4 全绿：** 尚未完成（缺 Supabase 2.x、Redis、正式对外部署；B/C 切块入库可选）。

---

## Part 1：数据收集

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 0.1 | Merck 急诊资料 | 8/3–8/4 | ✅ | `data/raw/`、处理与向量化管线；急诊 + owner 扩展语料 |
| 0.2 | ASPCA 有毒植物 | 8/3–8/4 | ✅ | `data/triage_tree/aspca_toxic_plants.json`；Red-Light 匹配 |
| 0.3 | Kaggle / 主诉临床映射 | 8/4–8/5 | ✅ | `complaint_clinical_map`（CSV/JSON）；吐黄水等主诉扩展 |
| 0.4 | C-BARQ & MCPQ-R 常模 | 8/5–8/6 | ✅ | C-BARQ42 完整；C-BARQ(101) **14/14**（Serpell 4 条 + Duffy 2012 补齐）；MCPQ-R 26 形容词 + POMP（Ley 2008/2009）；见 `norms_and_scoring.json` |
| 0.5 | AKC 品种 JSON | 8/5–8/6 | ✅ | `module_b_behavior/akc_breeds/`（tmfilho/akcdata CSV+JSON） |
| 0.6 | AAHA Life Stage | 8/6–8/7 | ✅ | `module_c_husbandry/aaha/pdfs/`（2019 canine + 2021 feline）+ `life_stages.json` |
| 0.7 | PetTalk 等亚洲卫教 URL | 8/6–8/7 | ✅ | `module_c_husbandry/pettalk_asia/url_inventory.json` |

**调整说明：** `0.4–0.7` 原排在 A 之后；A 本地急症 API 已可独立验收，B/C **只收料、暂不接 RAG**，不阻塞 AnimaLink 急症对接。详见 `data/raw/README_MODULE_BC.md`。

---

## Sprint 1：ETL 结构化清洗

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 1.1 | 症状树 JSON / Triage | 8/10–8/11 | 🟡→实质 ✅ | 原案「LLM 转 JSON」；实际为规则引擎 `03_red_light_intercept.py` + 结构化 metrics（RED/YELLOW/GREEN）。验收「明确分灯」已达成。 |
| 1.2 | 知识库切块与标註 | 8/11–8/12 | ✅ | A：`04/05`；B/C：`12_chunk_module_bc.py` + `13_embed_module_bc.py` → `merged_vector_store`（metadata.module A/B/C） |
| 1.3 | 医疗防护边界抽验 | 8/13–8/14 | 🟡 | 有 `evals/cases.json`、`09_run_eval.py`、`smoke_demo_guide.sh`；非表定「人工抽检 10%」全文档化流程。致命类红灯有自动化覆盖。 |

---

## Sprint 2：数据库与向量（路径调整）

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 2.1 | Supabase 建表 + pgvector | 8/17 | 🟡 | SQL：`supabase/migrations/`；本仓等价表：`data/pgvector_local/` via `16_local_pgvector.py` |
| 2.2 | HNSW + 检索 RPC | 8/18 | 🟡 | SQL 含 HNSW+RPC；本仓 `match()` 余弦检索已 smoke |
| 2.3 | 批次写入 + Embedding | 8/19–8/20 | 🟡 | 本地 ST + `16_local_pgvector load`；云端 `14/15_*` 待密钥 |
| 2.4 | RLS | 8/21 | 🟡 | 云端 grants SQL 已分拆；本仓无 RLS（单机） |

**调整说明（写进计划偏差）：**  
Sprint 2 原目标是 AnimaLink 同栈的 Supabase。Lab 为加速 A 验收，采用 **本地向量 + FastAPI**。合并时：要么 (a) 将 chunk 同步进 AnimaLink pgvector，要么 (b) AnimaLink HTTP 调用本 API，暂不迁库。

---

## Sprint 3：核心 API（日程提前）

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 3.1 | API 初始化 / health | 8/24 | ✅ 提前 | FastAPI；`GET /health` → 200 |
| 3.2 | Triage 红灯拦截 | 8/25–8/26 | ✅ 提前 | <500ms 拦截；RED 不耗 LLM |
| 3.3 | 双轨 RAG 检索 | 8/27–8/28 | 🟡 | 非红灯走 RAG + 可选 OpenAI；**尚未**「呼叫 Supabase RPC Top 3」。本地 Top-K 向量检索已通。 |
| 3.4 | 型別与防呆 | 8/28 | 🟡→实质 ✅ | Python Pydantic + 统一 error；AnimaLink `src/lib/triage/triageQuery.ts` 已迁入（原 `examples/app_clients`）。 |

契约：[`APP_INTEGRATION.md`](./APP_INTEGRATION.md)

---

## Sprint 4：测试、优化与部署

| ID | 任务 | 计划 | 状态 | 实际交付 / 差距 |
|----|------|------|------|-----------------|
| 4.1 | Semantic Cache (Redis) | 8/31–9/1 | 🟡 | `semantic_cache.py` + Compose/`memory://`/`run_with_cache.sh`；`/health.cache_*`；真 Redis 需 Docker |
| 4.2 | 自动化 RAG 品质评估 | 9/2 | 🟡 | 急症用例 + **Module B/C 5 案**（`group=module_bc`）；非完整 RAGAS |
| 4.3 | CI/CD 对外部署 | 9/3 | 🟡 | Compose + `run_staging.sh` + **`run_public_tunnel.sh`**（trycloudflare）；稳定域名仍需运营商主机 |
| 4.4 | API 文件与交接 | 9/4 | ✅ | `APP_INTEGRATION`、`MERGE_TO_ANIMALINK`、`DEPLOY`、**`LAB_HANDOFF`**、DEMO |

---

## 建议的「改表」结论（给 PM）

1. **模块 A（0.1–0.3 + 本地 1.1/3.x + 交接文档）→ 标为 Done，可进 AnimaLink 急症对接。**  
2. **Sprint 2（2.1–2.4）→ 标 Deferred / 合并阶段**，验收改为「本地向量可检索」或「已写入 AnimaLink pgvector」。  
3. **0.4–0.7 → 仍 Todo**，下一执行窗专做收料（PDF/JSON/URL），不回头挡 A。  
4. **4.1 Redis、4.3 公网 URL → 按 AnimaLink 上线需要再排**，不作为 Lab 关闭必要条件。  
5. Excel 主表可保留计划日期；**以本 Markdown 为实际状态源（source of truth for status）**，避免和超前完成的 API 日程打架。

---

## 范围约束（2026-08-13 起）

**只做本仓库 `anima-rag-lab`。**  
不做 AnimaLink 代码改动、不做 App 联调、不两边同时动。  
产品对接整段 **延后**，等本仓数据与向量工作收完再开。

## 下一执行窗（Lab 内 · 数据）

| 优先级 | 动作 | 对应 WBS |
|--------|------|----------|
| L0 | 本仓验收：`16_local_pgvector` smoke + merged store + Lab API 自测（**不含 App**） | 1.2 / 2.x 等价 |
| L1 | ~~补 B/C 语料缺口~~ → **已做**（PetTalk 正文、AAHA Table1、MCPQ blank） | 0.4–0.7 |
| L2 | ~~B/C 检索用例写入 `evals/`~~ → **已做**（`group=module_bc` 5 案；检索污染已修） | 4.2 |
| L3 | ~~文档/导出包整理~~ → **已做**（`LAB_HANDOFF.md` + `handoff_manifest.json`） | 交接 |
| — | ~~联调 Lab API + App~~ | **⏸ 延后** |
| — | ~~AnimaLink Supabase 真写入~~ | **⏸ 延后** |

---

## 修订记录

| 日期 | 变更 |
|------|------|
| 2026-08-13 | **L3** 交接包：`docs/LAB_HANDOFF.md`、`docs/README.md`、`18_handoff_manifest.py` |
| 2026-08-13 | **L2** Module B/C eval 5/5；修 corpus-meta 问句不被 complaint 扩展污染 |
| 2026-08-13 | **L1** B/C 补洞：AAHA Table1 正文、PetTalk 30 篇、MCPQ blank；B/C chunks 428 → merged 14000 |
| 2026-08-13 | **范围锁定：仅 anima-rag-lab；App 联调 / AnimaLink 改码一律延后** |
| 2026-08-13 | Sprint 2：本仓 `16_local_pgvector` 全量 13953 入库 + match smoke；云端 SQL/upsert 仍备 |
| 2026-08-13 | Sprint 2：Lab 侧 pgvector SQL + export/upsert 脚本 |
| 2026-08-13 | 4.1/4.3：cache smoke + memory backend；公网 quick tunnel 脚本 |
| 2026-08-12 | 初版：对照新表；记录本地 FastAPI 路径偏差与 A 线完成、B/C 与 Supabase 延后 |
