# Supabase / pgvector merge (WBS Sprint 2)

Lab serves RAG from a **local** sentence-transformers index
(`data/processed/merged_vector_store/`, 384-d MiniLM).

## Path A — do it **in this Lab first** (recommended now)

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

## Path B — real Supabase / Postgres later

| Step | Command |
|------|---------|
| 1. Apply SQL | paste migration in Supabase SQL editor (then optional grants file) |
| 2. Export | `python scripts/14_export_pgvector.py` |
| 3. Upsert | set `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` → `python scripts/15_upsert_supabase.py --apply` |

```bash
# .env
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ…   # service_role only
```

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
