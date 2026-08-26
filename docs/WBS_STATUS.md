# Anima-RAG-Lab WBS 状态表（对照 Master WBS）

**来源：** [`BoAnima-RAG-Lab 專案管理主表 (Master WBS).xlsx`](./BoAnima-RAG-Lab%20專案管理主表%20(Master%20WBS).xlsx)  
**对照表：** 工作表「Anima-RAG-Lab 專案管理主表」  
**更新日期：** 2026-08-18  
**专案定位：** **把数据准备好**（收集 → ETL → **写入 Supabase pgvector** → Lab API 可检索）。  
**不包含：** AnimaLink App UI / 聊天接线（主表 4.4 仅要求「产出 API 文件供后续串接」，不是本仓执行项）。

**模块用途（分开，不混用）：**

| 模块 | 用途 | 语料 | 检索 |
|------|------|------|------|
| **A** | **急症分诊** | Merck、ASPCA 毒物、主诉映射、红灯生理阈值 | 分诊 API **默认只搜 A** |
| **B** | **性格测评（类 MBTI）** | 饲主填 **C-BARQ** → 分量表分数 → **性格描述 + 照护需求**（MCPQ-R / AKC 气质作辅） | **不是问诊**；不进分诊检索 |
| **C** | 育养 / 生命阶段 | AAHA Life Stage、PetTalk | 仅育养题搜 C |

**Module B 应用（类人类 MBTI，不是看病）：**

```
饲主填 C-BARQ 问卷  →  14 个行为分量表计分  →  性格画像 + 照护建议
（兴奋/恐惧/攻击/依恋/精力/可训练性…）     （怎么相处、运动量、训练、环境）
```

- 体验对标：人类做 MBTI 得到类型说明与相处建议；这里 **L1=14 维连续分数（主）→ L2=日常四个重点 → L3=可选 16 型贴纸**（类比层，不是科学分型）。  
- Lab **已有：** 问卷计分公式；`POST /v1/personality/cbarq/score` 交卷出报告（`subscales` + `facets` + `mbti_like`）；分档文案在 `cbarq42_profile_copy.json`；面向/16 型在 `cbarq42_mbti_types.json`。  
- **不含** 官方题面（版权宾大）；App 需自行呈现授权问卷，只把题号分数 POST 回来。  
- 分诊仍走 `/v1/triage/query`（Module A），两条 API 分开。

状态图例：

| 标记 | 含义 |
|------|------|
| ✅ Done | 已满足主表验收或等价完成 |
| 🟡 Partial | 有交付，但未达主表原路径验收 |
| ⬜ Todo | 未开始或未达标 |
| 🔴 Blocked | 缺前置条件（如云端密钥） |

---

## 总览（对照主表）

| 阶段 | 计划窗口 | 总体状态 | 一句话 |
|------|----------|----------|--------|
| Part 1 · 数据收集 `0.1–0.7` | 8/3–8/7 | ✅ | 语料已收齐（A/B/C） |
| Sprint 1 · ETL `1.1–1.3` | 8/10–8/14 | ✅ / 🟡 | 切块标注完成；抽验靠自动化 eval，非人工 10% 全文档 |
| Sprint 2 · **Supabase 向量库** `2.1–2.4` | 8/17–8/21 | ✅ | 云端 `knowledge_chunks` **14000**；RPC + RLS 烟雾通过 |
| Sprint 3 · API `3.1–3.4` | 8/24–8/28 | ✅ | FastAPI + Red-Light + **Supabase RPC 检索**（无密钥/失败则本地） |
| Sprint 4 · 测试与部署 `4.1–4.4` | 8/31–9/4 | 🟡 | 4.4✅；cache/eval/tunnel 有代码；本机无 Docker → 真 Redis/公网未跑通 |

**数据存放真相：**

| 层 | 状态 | 说明 |
|----|------|------|
| 原始 / 处理后文件 | ✅ | `data/raw/`、`data/processed/` |
| 本机向量文件 | ✅ | `merged_vector_store/` **14000**（A 13572 + B/C 428） |
| 本机 schema 镜像 | ✅ | `data/pgvector_local/`（SQLite+numpy，非云） |
| **Supabase 云端 pgvector** | ✅ | 项目 `aunzslhgsyjyxsefbveb`；**14000** 行（A 13572 / B 330 / C 98） |

---

## Part 1：数据收集

| ID | 任务 | 计划 | 状态 | 实际 |
|----|------|------|------|------|
| 0.1 | Merck 急诊 | 8/3–8/4 | ✅ | 爬取/seed + 处理管线 |
| 0.2 | ASPCA 有毒植物 | 8/3–8/4 | ✅ | `aspca_toxic_plants.json` |
| 0.3 | Kaggle / 主诉映射 | 8/4–8/5 | ✅ | `complaint_clinical_map` |
| 0.4 | C-BARQ & MCPQ-R | 8/5–8/6 | ✅ | 14/14 计分 + MCPQ-R 26 词 + lab blank |
| 0.5 | AKC 品种 JSON | 8/5–8/6 | ✅ | `akc_breeds/` |
| 0.6 | AAHA Life Stage | 8/6–8/7 | ✅ | 犬/猫 PDF + Table 1 正文 |
| 0.7 | PetTalk 等 URL/正文 | 8/6–8/7 | ✅ | URL 清单 + ~30 篇 articles |

---

## Sprint 1：ETL

| ID | 任务 | 计划 | 状态 | 实际 |
|----|------|------|------|------|
| 1.1 | 症状树 / Triage 结构 | 8/10–8/11 | ✅ | Red-Light 规则引擎（等价验收：明确分灯） |
| 1.2 | 切块与标注 | 8/11–8/12 | ✅ | A + B/C → `module_bc_chunks` + merged store |
| 1.3 | 医疗边界抽验 | 8/13–8/14 | ✅ | `scripts/09_run_eval.py` 全量回归：Eval 25/25 passed（LLM=off） |

---

## Sprint 2：Supabase 向量库

主表验收要点：建表 + HNSW + `match` RPC + 批次写入 + RLS。**2026-08-13 关闭。**

| ID | 任务 | 计划 | 状态 | 实际 |
|----|------|------|------|------|
| 2.1 | 启用 pgvector + 建表 | 8/17 | ✅ | 云端已执行 `20260813_knowledge_chunks.sql` |
| 2.2 | HNSW + 检索函数 | 8/18 | ✅ | `match_knowledge_chunks` 已部署；C-BARQ 查询 Top-3 合理 |
| 2.3 | 批次 Embedding 写入 | 8/19–8/20 | ✅ | `15_upsert --apply` 280 批全部 201；行数 **14000** |
| 2.4 | RLS | 8/21 | ✅ | grants 已执行；anon 写 401；anon 读 0 行；service_role 可写/可 RPC |

---

## Sprint 3：核心 API

| ID | 任务 | 计划 | 状态 | 实际 |
|----|------|------|------|------|
| 3.1 | API 初始化 / health | 8/24 | ✅ | FastAPI `GET /health` |
| 3.2 | Triage 红灯 | 8/25–8/26 | ✅ | RED 不走 LLM |
| 3.3 | 双轨 RAG | 8/27–8/28 | ✅ | `ANIMA_RETRIEVAL=auto`：有密钥则呼叫 `match_knowledge_chunks`，失败回落本地；eval/tests 强制 local |
| 3.4 | 型別与防呆 | 8/28 | ✅ | Pydantic + 统一 error；`APP_INTEGRATION.md` |

---

## Sprint 4：测试优化与部署

| ID | 任务 | 计划 | 状态 | 实际 |
|----|------|------|------|------|
| 4.1 | Semantic Cache (Redis) | 8/31–9/1 | 🟡 | 代码+Compose profile+`memory://` smoke ✅；真 Redis 需 Docker（本机暂无） |
| 4.2 | RAG 品质评估 | 9/2 | 🟡 | 固定 eval **25/25** 通过（LLM=off）；非完整 RAGAS |
| 4.3 | CI/CD 对外部署 | 9/3 | 🟡 | Compose / Tunnel 脚本；无正式域名流水线 |
| 4.4 | API 文件与交接 | 9/4 | ✅ | `APP_INTEGRATION`、`LAB_HANDOFF`、`DEPLOY` 等 |

> 4.4「供后续 AnimalLink 串接」= **交付 API 文档**，不是本仓去做产品接线。

---

## 下一执行窗

Sprint 2–3 检索路径已关闭。Module B（C-BARQ + MCPQ-R）性格报告 API 已可测。

| 优先级 | 动作 | 对应 WBS |
|--------|------|----------|
| S4 | 全量 eval 回归（本机 HF cache 已暖） | 4.2 |
| S5 | Docker Redis + 公网 tunnel staging | 4.1 / 4.3 |

**Sprint 2 验收（已满足）：**

1. `knowledge_chunks` = **14000**（A 13572 / B 330 / C 98）  
2. `match_knowledge_chunks` C-BARQ 种子查询 Top-3（自匹配 similarity=1.0）  
3. RLS：anon 写 401；anon 读 0 行；service_role 可写/可 RPC  

---

## 修订记录

| 2026-08-26 | **Sprint 4.2：** 全量 `09_run_eval.py` 回归 **25/25**（HF cache 已暖、LLM=off） |
| 2026-08-26 | **续作：** 还原 800MB 临时 tfidf 向量；ST embedder 离线快速失败；HF cache 已暖；Sprint 3 API/RPC/cache/MCPQ 测试 19/19 |
| 2026-08-26 | **Sprint 4 启动：** `memory://` semantic cache smoke ✅；本机无 Docker，真 Redis / Compose cache 暂搁 |
| 2026-08-19 | **Module B 人话重点：** 四个重点改成 B 组短标签（熟不熟得起来 / 精力 / 防卫 / 听话程度） |
| 2026-08-19 | **Module B MCPQ-R：** 新增 `GET/POST /v1/personality/mcpq`，26 词交卷后输出五维结果 + 主人报告 |
| 2026-08-19 | **Module C 育养体验版：** `06_rag_query.py` 增加生命阶段专用 checklist（更像育养报告）；UI/整合改屏幕先延后 |
| 2026-08-19 | **Sprint 1（ETL）1.3 医疗边界抽验：** 全量 `scripts/09_run_eval.py` 回归通过（25/25） |
| 2026-08-19 | **Sprint 2：** Supabase `knowledge_chunks` 上云刷新 B/C（426 rows） |
| 2026-08-18 | **Module B 主人报告：** `owner_report` 分段（个性/特色/对人狗/家里出门/教养/别做）；16 型文案加厚 |
| 2026-08-18 | **Module B 三层报告：** `facets`（社交/引擎/界限/配合）+ 贴纸由面向派生；中线→均衡陪伴型 |
| 2026-08-14 | **Module B 类 MBTI：** 三种恐惧整块→I、四种攻击整块→T（对称）；怕环境不再进 J/P |
| 2026-08-14 | **Module B 类 MBTI 方案 A：** 互斥均权（兴奋/精力只进 N；非社交恐惧进 J/P） |
| 2026-08-14 | **Module B 类 MBTI：** 14 维 → 4 轴 → 16 狗狗角色（`mbti_like`）；14 维报告仍是主结果 |
| 2026-08-13 | **Module B 应用：** C-BARQ 问卷 → 性格描述 + 照护需求（类 MBTI；非问诊） |
| 2026-08-13 | **模块分轨：** A=分诊、B=性格判断、C=育养；检索按问题过滤，分诊默认只搜 A |
| 2026-08-13 | **S4：** Lab API `ANIMA_RETRIEVAL=auto` 走 Supabase `match_knowledge_chunks`，失败回落本地 |
| 2026-08-13 | **Sprint 2 关闭：** 云端 upsert 14000 + RPC/RLS 烟雾通过 |
| 2026-08-13 | **纠正：** Sprint 2 Supabase 云端标为必做下一窗；去掉「延后到 AnimaLink」表述；重写完成度对照主表 |
| 2026-08-13 | L1–L3 本机数据/eval/交接包完成；merged 14000 |
| 2026-08-12 | 初版对照表 |
