#!/usr/bin/env python3
"""Export local merged vector store → pgvector-ready JSONL (WBS 2.2).

Default input: data/processed/merged_vector_store/
Default output: data/processed/supabase_export/knowledge_chunks.jsonl

Each line:
  {"id","content","metadata","embedding":[float×384],"module","source"}

Usage:
  python scripts/14_export_pgvector.py
  python scripts/14_export_pgvector.py --modules B,C --limit 100
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional, Set

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("export_pgvector")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = PROJECT_ROOT / "data" / "processed" / "merged_vector_store"
DEFAULT_OUT = (
    PROJECT_ROOT / "data" / "processed" / "supabase_export" / "knowledge_chunks.jsonl"
)


def _parse_modules(raw: Optional[str]) -> Optional[Set[str]]:
    if not raw:
        return None
    mods = {m.strip().upper() for m in raw.split(",") if m.strip()}
    bad = mods - {"A", "B", "C"}
    if bad:
        raise SystemExit(f"Invalid --modules {bad}; use A,B,C")
    return mods


def export(
    store_dir: Path,
    out_path: Path,
    modules: Optional[Set[str]] = None,
    limit: Optional[int] = None,
) -> int:
    records_path = store_dir / "records.json"
    vectors_path = store_dir / "vectors.npy"
    manifest_path = store_dir / "manifest.json"

    if not records_path.is_file() or not vectors_path.is_file():
        raise SystemExit(f"Missing store files under {store_dir}")

    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dim = int(manifest.get("dimension") or 384)

    logger.info("Loading records from %s", records_path)
    records = json.loads(records_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path, mmap_mode="r")
    if len(records) != vectors.shape[0]:
        raise SystemExit(
            f"records/vectors length mismatch: {len(records)} vs {vectors.shape[0]}"
        )
    if vectors.shape[1] != dim:
        logger.warning("manifest dim=%s but vectors.shape[1]=%s", dim, vectors.shape[1])
        dim = int(vectors.shape[1])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0

    with out_path.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(records):
            meta = dict(rec.get("metadata") or {})
            module = str(meta.get("module") or "").upper() or "A"
            if modules is not None and module not in modules:
                skipped += 1
                continue
            source = meta.get("source")
            row = {
                "id": rec.get("chunk_id") or f"chunk_{i}",
                "content": rec.get("content") or "",
                "metadata": meta,
                "embedding": [float(x) for x in vectors[i].tolist()],
                "module": module,
                "source": source,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            if limit is not None and written >= limit:
                break
            if written % 2000 == 0:
                logger.info("… wrote %s rows", written)

    sidecar = {
        "generated_from": str(store_dir),
        "embedder": manifest.get("embedder"),
        "dimension": dim,
        "rows": written,
        "skipped": skipped,
        "modules_filter": sorted(modules) if modules else None,
        "limit": limit,
        "output": str(out_path),
    }
    sidecar_path = out_path.with_suffix(".manifest.json")
    sidecar_path.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    logger.info(
        "Wrote %s rows (%s skipped) → %s (dim=%s)",
        written,
        skipped,
        out_path,
        dim,
    )
    return written


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", type=Path, default=DEFAULT_STORE)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--modules", type=str, default=None, help="e.g. B,C or A")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(list(argv) if argv is not None else None)
    export(args.store, args.out, _parse_modules(args.modules), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
