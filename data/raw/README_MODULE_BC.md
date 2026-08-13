# Module B / C raw collection (WBS 0.4–0.7)

Collected for Anima-RAG-Lab Part 1. **Ingested into local merged vector store.** Supabase cloud deferred — see `docs/SUPABASE_MERGE.md`. Lab-local mirror: `scripts/16_local_pgvector.py`.

| WBS | Folder | Status (2026-08-13 L1) |
|-----|--------|------------------------|
| 0.4 C-BARQ / MCPQ-R | `module_b_behavior/cbarq_mcpq_r/` | ✅ 14/14 + MCPQ-R 26 词 + **lab blank form**（非 Monash 官方 PDF） |
| 0.5 AKC breeds | `module_b_behavior/akc_breeds/` | ✅ |
| 0.6 AAHA life stage | `module_c_husbandry/aaha/` | ✅ PDF + **Table 1 正文抽取**（`pdf_extracts/table1.json`） |
| 0.7 PetTalk / Asia edu | `module_c_husbandry/pettalk_asia/` | ✅ URL 清单 + **articles.jsonl（~30 篇正文）** |

L1 补洞脚本：`python scripts/17_enrich_module_bc_gaps.py`  
再入库：`12_chunk_module_bc.py` → `13_embed_module_bc.py` → `16_local_pgvector.py bootstrap`
