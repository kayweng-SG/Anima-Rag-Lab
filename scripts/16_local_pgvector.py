#!/usr/bin/env python3
"""Local pgvector-compatible store **inside this Lab** (no Docker / Homebrew).

Persists under ``data/pgvector_local/``:
  knowledge_chunks.sqlite3  — rows + metadata
  embeddings.npy            — float32 (N, 384)

Schema / RPC mirror ``supabase/migrations/20260813_knowledge_chunks.sql``.
When you later have Supabase or Docker Postgres, use 14_export + 15_upsert instead.

Commands:
  python scripts/16_local_pgvector.py bootstrap --modules B,C
  python scripts/16_local_pgvector.py load
  python scripts/16_local_pgvector.py smoke --query "AAHA senior"
  python scripts/16_local_pgvector.py info
  python scripts/16_local_pgvector.py reset
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("local_pgvector")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "pgvector_local"
DB_PATH = DATA_DIR / "knowledge_chunks.sqlite3"
EMB_PATH = DATA_DIR / "embeddings.npy"
ID_MAP_PATH = DATA_DIR / "id_index.json"
STORE_DIR = PROJECT_ROOT / "data" / "processed" / "merged_vector_store"
DIM = 384


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=WAL")
    return conn


def migrate() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            create table if not exists knowledge_chunks (
              id text primary key,
              content text not null,
              metadata text not null default '{}',
              module text not null check (module in ('A','B','C')),
              source text,
              emb_row integer not null unique,
              created_at text not null default (datetime('now')),
              updated_at text not null default (datetime('now'))
            );
            create index if not exists knowledge_chunks_module_idx
              on knowledge_chunks(module);
            create index if not exists knowledge_chunks_source_idx
              on knowledge_chunks(source);
            """
        )
    logger.info("Migrated schema → %s", DB_PATH)


def _parse_modules(raw: Optional[str]) -> Optional[Set[str]]:
    if not raw:
        return None
    mods = {m.strip().upper() for m in raw.split(",") if m.strip()}
    bad = mods - {"A", "B", "C"}
    if bad:
        raise SystemExit(f"Invalid --modules {bad}")
    return mods


def _load_embeddings() -> np.ndarray:
    if EMB_PATH.is_file():
        return np.load(EMB_PATH)
    return np.zeros((0, DIM), dtype=np.float32)


def load(modules: Optional[Set[str]] = None, limit: Optional[int] = None) -> int:
    migrate()
    records = json.loads((STORE_DIR / "records.json").read_text(encoding="utf-8"))
    vectors = np.load(STORE_DIR / "vectors.npy", mmap_mode="r")
    if vectors.shape[1] != DIM:
        raise SystemExit(f"Expected dim={DIM}, got {vectors.shape[1]}")

    selected: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for i, rec in enumerate(records):
        meta = dict(rec.get("metadata") or {})
        module = str(meta.get("module") or "A").upper()
        if modules is not None and module not in modules:
            continue
        selected.append((rec, np.asarray(vectors[i], dtype=np.float32)))
        if limit is not None and len(selected) >= limit:
            break

    if not selected:
        logger.warning("No rows selected")
        return 0

    emb = np.vstack([v for _, v in selected]).astype(np.float32)
    emb = np.nan_to_num(emb, nan=0.0, posinf=0.0, neginf=0.0)
    # L2-normalize for cosine via dot product
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms = np.clip(norms, 1e-12, None)
    emb = (emb / norms).astype(np.float32)

    with _connect() as conn:
        conn.execute("delete from knowledge_chunks")
        for row_i, (rec, _) in enumerate(selected):
            meta = dict(rec.get("metadata") or {})
            module = str(meta.get("module") or "A").upper()
            conn.execute(
                """
                insert into knowledge_chunks (id, content, metadata, module, source, emb_row, updated_at)
                values (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    rec.get("chunk_id") or f"chunk_{row_i}",
                    rec.get("content") or "",
                    json.dumps(meta, ensure_ascii=False),
                    module,
                    meta.get("source"),
                    row_i,
                ),
            )
        conn.commit()

    np.save(EMB_PATH, emb)
    id_index = {
        (rec.get("chunk_id") or f"chunk_{i}"): i for i, (rec, _) in enumerate(selected)
    }
    ID_MAP_PATH.write_text(json.dumps(id_index), encoding="utf-8")
    logger.info("Loaded %s rows → %s + %s", len(selected), DB_PATH.name, EMB_PATH.name)
    return len(selected)


def match(
    query_embedding: Sequence[float],
    match_count: int = 5,
    filter_module: Optional[str] = None,
) -> List[Dict[str, Any]]:
    emb = _load_embeddings()
    if emb.shape[0] == 0:
        return []
    q = np.nan_to_num(
        np.asarray(query_embedding, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0
    )
    if q.shape[0] != emb.shape[1]:
        raise ValueError(f"query dim {q.shape[0]} != store dim {emb.shape[1]}")
    qn = float(np.linalg.norm(q))
    if qn < 1e-12:
        return []
    q = q / qn
    # float64 matmul avoids rare float32 overflow warnings on large stores
    sims = np.asarray(emb, dtype=np.float64) @ np.asarray(q, dtype=np.float64)

    with _connect() as conn:
        sql = "select id, content, metadata, module, source, emb_row from knowledge_chunks"
        params: List[Any] = []
        if filter_module:
            sql += " where module = ?"
            params.append(filter_module.upper())
        rows = list(conn.execute(sql, params))

    scored: List[Tuple[float, sqlite3.Row]] = []
    for row in rows:
        scored.append((float(sims[int(row["emb_row"])]), row))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: List[Dict[str, Any]] = []
    for sim, row in scored[: max(match_count, 1)]:
        out.append(
            {
                "id": row["id"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "module": row["module"],
                "source": row["source"],
                "similarity": sim,
            }
        )
    return out


def info() -> Dict[str, Any]:
    migrate()
    with _connect() as conn:
        total = conn.execute("select count(*) from knowledge_chunks").fetchone()[0]
        by_mod = {
            r[0]: r[1]
            for r in conn.execute(
                "select module, count(*) from knowledge_chunks group by module"
            )
        }
    shape = None
    if EMB_PATH.is_file():
        shape = list(np.load(EMB_PATH, mmap_mode="r").shape)
    return {
        "db": str(DB_PATH),
        "embeddings": str(EMB_PATH),
        "rows": total,
        "by_module": by_mod,
        "embedding_shape": shape,
        "backend": "sqlite+numpy (lab-local; mirrors pgvector schema)",
    }


def smoke(query: str = "C-BARQ scoring", k: int = 5, filter_module: Optional[str] = None) -> int:
    records = json.loads((STORE_DIR / "records.json").read_text(encoding="utf-8"))
    vectors = np.load(STORE_DIR / "vectors.npy", mmap_mode="r")
    needle = query.lower()
    seed_i = 0
    # Prefer chunk whose source/content matches the probe text
    for i, rec in enumerate(records):
        meta = rec.get("metadata") or {}
        blob = f"{rec.get('content', '')} {meta.get('source', '')} {rec.get('chunk_id', '')}".lower()
        if needle in blob or any(tok in blob for tok in needle.replace("-", " ").split() if len(tok) > 3):
            seed_i = i
            if needle in blob or meta.get("source", "").lower() in needle.replace(" ", "_"):
                break
    else:
        for i, rec in enumerate(records):
            if (rec.get("metadata") or {}).get("module") in ("B", "C"):
                seed_i = i
                break

    hits = match(vectors[seed_i].tolist(), match_count=k, filter_module=filter_module)
    print(json.dumps(info(), indent=2, ensure_ascii=False))
    print(f"query_seed={records[seed_i].get('chunk_id')} needle={query!r}")
    for rank, h in enumerate(hits, 1):
        print(
            f"{rank}. id={h['id']} module={h['module']} source={h['source']} "
            f"sim={h['similarity']:.4f} :: {h['content'][:80]}"
        )
    if not hits:
        raise SystemExit("SMOKE FAIL: no hits")
    print("SMOKE PASS")
    return 0


def reset() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for p in (DB_PATH, EMB_PATH, ID_MAP_PATH):
        if p.is_file():
            p.unlink()
    # wal leftovers
    for extra in DATA_DIR.glob("knowledge_chunks.sqlite3*"):
        extra.unlink(missing_ok=True)
    logger.info("Reset %s", DATA_DIR)


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate")
    sub.add_parser("info")
    sub.add_parser("reset")

    for name in ("load", "bootstrap"):
        sp = sub.add_parser(name)
        sp.add_argument("--modules", default=None)
        sp.add_argument("--limit", type=int, default=None)

    sm = sub.add_parser("smoke")
    sm.add_argument("--query", default="C-BARQ scoring")
    sm.add_argument("--k", type=int, default=5)
    sm.add_argument("--filter-module", default=None)

    args = p.parse_args(list(argv) if argv is not None else None)

    if args.cmd == "migrate":
        migrate()
        return 0
    if args.cmd == "info":
        print(json.dumps(info(), indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "reset":
        reset()
        return 0
    if args.cmd == "load":
        load(_parse_modules(args.modules), args.limit)
        return 0
    if args.cmd == "bootstrap":
        reset()
        n = load(_parse_modules(args.modules), args.limit)
        if n == 0:
            return 1
        return smoke()
    if args.cmd == "smoke":
        return smoke(args.query, args.k, args.filter_module)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
