# Anima-Rag-Lab → AnimaLink 交接说明

**AnimaLink 是主产品。** 本 Lab 降级为离线语料生产工具：抓取、切块、嵌入、评测。  
运行时（红灯分流、向量检索、LLM 串流、聊天 UI）已在 AnimaLink。

主产品：`/Documents/Works/AnimaLink`（Vite + React SPA + Supabase）。

## 现在怎么跑（2026-09）

```
饲主主诉
  → AnimaLink 本地 Red-Light（shared/redLight）
      RED        → 拦截，不走 rag-stream
      YELLOW/GREEN → Edge Function rag-stream
                      1. 主诉展开 + 模块路由 A/B/C
                      2. OpenAI text-embedding-3-small（384）
                      3. match_knowledge_chunks
                      4. SSE 串流回答
```

不再需要 HTTP 调用本仓 FastAPI。

## Lab 还负责什么

| 类别 | 路径 | 说明 |
|------|------|------|
| 合并语料 | `data/processed/merged_vector_store/` | 13998 切块（A 13572 + B 330 + C 96） |
| OpenAI 重嵌 | `scripts/21_reembed_openai.py` | `text-embedding-3-small` dim=384 |
| 灌 AnimaLink | `scripts/15_upsert_supabase.py --target animalink` | 需 `ANIMALINK_SUPABASE_*` |
| 检索评测 | `scripts/22_eval_animalink_retrieval.py` | 对 AnimaLink pgvector |
| 红灯规则源 | `scripts/03_red_light_intercept.py` | AnimaLink 已移植；改规则先改这里再对拍 |
| 主诉映射 | `data/triage_tree/complaint_clinical_map.json` | 重新产生后同步 AnimaLink `shared/rag/` |
| 有毒植物 | `data/triage_tree/aspca_toxic_plants.json` | 同步 `shared/redLight/toxicPlantAliases.ts` |

## AnimaLink 已落地

- `supabase/migrations/20260902000000_knowledge_chunks_pgvector.sql`
- 云端 `knowledge_chunks`：**13998**，与 OpenAI JSONL 对齐
- 本地红灯 + 繁简正规化 + ASPCA 碎片假阳性修正
- `rag-stream` 向量检索（部署后生效）

## 检索评测（换模型后）

```bash
cd anima-rag-lab
source venv/bin/activate
python scripts/22_eval_animalink_retrieval.py
```

2026-09-03：13 个有检索断言的案例 **13/13 通过**（12 个 RED / 无检索断言跳过）。  
最低 top 相似度约 **0.44**，暂不降 match 门槛。

Lab 原 25 案完整管线（抽取式答案）仍用 `09_run_eval.py`，需要本机 sentence-transformers 缓存。

## 不要再做的事

- 把 AnimaLink 聊天指回 `POST {LAB}/v1/triage/query`
- 在浏览器暴露 `service_role` 或 OpenAI key
- 用 Lab 的 `SUPABASE_*` 灌 AnimaLink（默认 `--target animalink`）
