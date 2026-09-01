# Supabase / pgvector（WBS Sprint 2 ✅ · S4 检索已接）

专案目标：数据进 **Supabase pgvector**，Lab API 经 RPC 检索。  
本地 `merged_vector_store/`（384-d MiniLM）是 embed 源；云端 `knowledge_chunks` = **13998**。

## Path A — 本机 schema 镜像（已完成，作对照）

No Docker / Homebrew required. Mirrors the `knowledge_chunks` schema +
`match_knowledge_chunks` behaviour with SQLite + numpy:

```bash
cd anima-rag-lab
source venv/bin/activate

# B/C pilot (~381 rows)
python scripts/16_local_pgvector.py bootstrap --modules B,C

# or full A+B+C (~14k)
python scripts/16_local_pgvector.py bootstrap

python scripts/16_local_pgvector.py smoke --query "AAHA senior"
python scripts/16_local_pgvector.py info
```

Data lives under `data/pgvector_local/` (gitignored).

| Artifact | Path |
|----------|------|
| Local loader / match | `scripts/16_local_pgvector.py` |
| SQL (for real Postgres/Supabase) | [`supabase/migrations/20260813_knowledge_chunks.sql`](../supabase/migrations/20260813_knowledge_chunks.sql) |
| Supabase-only RLS grants | [`…_supabase_grants.sql`](../supabase/migrations/20260813_knowledge_chunks_supabase_grants.sql) |

## Path B — 云端 Supabase（**已完成** 2026-08-13）

| Step | Command |
|------|---------|
| 1. Apply SQL | paste migration in Supabase SQL editor（再跑 grants 文件） |
| 2. Export | `python scripts/14_export_pgvector.py` |
| 3. Upsert | set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` → `python scripts/15_upsert_supabase.py --apply` |
| 4. Verify | `python scripts/15_upsert_supabase.py --verify` |

### 云端与导出对不齐时

upsert 用 `Prefer: resolution=merge-duplicates`，**只增不删**。导出档移除的 chunk（例如去重）会一直留在云端，直到 prune：

```bash
# 只读比对，不写任何东西；一致回 0，有漂移回 1 并列出 id
python scripts/15_upsert_supabase.py --verify

# 上传后删掉「云端有、导出没有」的列
python scripts/15_upsert_supabase.py --apply --prune
```

比对范围**只涵盖导出档里出现过的 module**。预设导出是全量；若用 `--modules B,C` 只导 B/C，prune 就不会碰 Module A。另有 20% 安全阈值：单一 module 要删超过两成时会中止（通常代表导出档不完整），确认无误再加 `--force`。

```bash
# .env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ…   # service_role only
ANIMA_RETRIEVAL=auto             # Lab API: RPC if keys else local numpy
```

`ANIMA_RETRIEVAL`：`local` | `supabase` | `auto`（默认 auto）。eval / pytest 强制 `local`。

Query embeddings **must** use the same model:
`paraphrase-multilingual-MiniLM-L12-v2`.

## Cutover options for AnimaLink

1. Keep calling Lab `POST /v1/triage/query` (Red-Light stays in Python).
2. Or point Edge `rag-stream` at Supabase `match_knowledge_chunks` after Path B upsert.

## Out of scope here

- Replacing Red-Light with SQL  
- Migrating triage SQLite history  
- AnimaLink product UI for B/C  

See also: [`MERGE_TO_ANIMALINK.md`](./MERGE_TO_ANIMALINK.md), [`WBS_STATUS.md`](./WBS_STATUS.md).
