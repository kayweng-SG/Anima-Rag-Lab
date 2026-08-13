#!/usr/bin/env python3
"""Embed Module B/C chunks and merge into a combined vector store (WBS 1.2).

- Embeds only B/C chunks (does NOT re-embed Module A).
- Appends vectors to a copy of the existing Merck ST store.
- Writes data/processed/merged_vector_store/ (Module A untouched).

Requires MERCK_EMBEDDER=sentence_transformers and matching MERCK_EMBED_MODEL.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

from importlib.util import module_from_spec, spec_from_file_location  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _load_embed_mod():
    path = os.path.join(PROJECT_ROOT, "scripts", "05_embed_merck.py")
    spec = spec_from_file_location("embed_merck", path)
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed B/C chunks and merge with Merck store")
    parser.add_argument(
        "--bc-chunks",
        default=os.path.join(PROJECT_ROOT, "data", "processed", "module_bc_chunks.json"),
    )
    parser.add_argument(
        "--base-store",
        default=os.path.join(PROJECT_ROOT, "data", "processed", "merck_vector_store"),
        help="Existing Module A sentence-transformers store (read-only)",
    )
    parser.add_argument(
        "--out-store",
        default=os.path.join(PROJECT_ROOT, "data", "processed", "merged_vector_store"),
    )
    parser.add_argument(
        "--bc-only-store",
        default=os.path.join(PROJECT_ROOT, "data", "processed", "module_bc_vector_store"),
        help="Also write a B/C-only store for inspection",
    )
    args = parser.parse_args()

    embed_mod = _load_embed_mod()
    MerckVectorStore = embed_mod.MerckVectorStore
    SentenceTransformerEmbedder = embed_mod.SentenceTransformerEmbedder

    with open(args.bc_chunks, encoding="utf-8") as f:
        payload = json.load(f)
    bc_chunks: List[Dict[str, Any]] = payload.get("chunks") or []
    if not bc_chunks:
        raise SystemExit(f"No B/C chunks in {args.bc_chunks}")

    # Load A store
    base = MerckVectorStore(store_dir=args.base_store)
    base.load()
    assert base.vectors is not None and base.embedder is not None
    if not isinstance(base.embedder, SentenceTransformerEmbedder):
        raise SystemExit(
            f"Base store embedder is {base.embedder.name}; "
            "merge requires sentence_transformers to append without rebuild."
        )

    # Tag existing A records
    a_records = []
    for rec in base.records:
        meta = dict(rec.get("metadata") or {})
        meta.setdefault("module", "A")
        meta.setdefault("source", meta.get("source") or "merck")
        a_records.append(
            {"chunk_id": rec["chunk_id"], "content": rec["content"], "metadata": meta}
        )

    # Embed B/C with same model
    texts = [c["content"] for c in bc_chunks]
    start = time.perf_counter()
    logger.info("Embedding %d B/C chunks with %s …", len(texts), base.embedder.name)
    bc_raw = base.embedder.embed_texts(texts)
    bc_vectors = MerckVectorStore._sanitize_matrix(bc_raw)
    elapsed = (time.perf_counter() - start) * 1000

    bc_records = [
        {
            "chunk_id": c["chunk_id"],
            "content": c["content"],
            "metadata": c.get("metadata") or {},
        }
        for c in bc_chunks
    ]

    # B/C-only store
    os.makedirs(args.bc_only_store, exist_ok=True)
    np.save(os.path.join(args.bc_only_store, "vectors.npy"), bc_vectors)
    with open(os.path.join(args.bc_only_store, "records.json"), "w", encoding="utf-8") as f:
        json.dump(bc_records, f, ensure_ascii=False, indent=2)
    bc_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedder": base.embedder.name,
        "dimension": int(bc_vectors.shape[1]),
        "vector_count": len(bc_records),
        "build_elapsed_ms": round(elapsed, 2),
        "source_chunks_file": os.path.basename(args.bc_chunks),
        "modules": ["B", "C"],
    }
    with open(os.path.join(args.bc_only_store, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(bc_manifest, f, ensure_ascii=False, indent=2)

    # Merged store = A + B/C
    if args.out_store == args.base_store:
        raise SystemExit("Refusing to overwrite base Module A store; pick a different --out-store")

    if os.path.isdir(args.out_store):
        shutil.rmtree(args.out_store)
    os.makedirs(args.out_store, exist_ok=True)

    merged_vectors = np.vstack([base.vectors, bc_vectors]).astype(np.float32)
    merged_records = a_records + bc_records
    np.save(os.path.join(args.out_store, "vectors.npy"), merged_vectors)
    with open(os.path.join(args.out_store, "records.json"), "w", encoding="utf-8") as f:
        json.dump(merged_records, f, ensure_ascii=False, indent=2)
    merged_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "embedder": base.embedder.name,
        "dimension": int(merged_vectors.shape[1]),
        "vector_count": len(merged_records),
        "module_a_count": len(a_records),
        "module_bc_count": len(bc_records),
        "build_elapsed_ms": round(elapsed, 2),
        "base_store": os.path.basename(args.base_store.rstrip("/")),
        "source_chunks_file": os.path.basename(args.bc_chunks),
        "modules": ["A", "B", "C"],
    }
    with open(os.path.join(args.out_store, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(merged_manifest, f, ensure_ascii=False, indent=2)

    # Smoke search
    store = MerckVectorStore(store_dir=args.out_store)
    store.load()
    demos = [
        "Labrador Retriever temperament trainability",
        "C-BARQ stranger-directed aggression scoring",
        "AAHA feline senior life stage",
        "puppy vaccine ticks Asia climate",
    ]
    print(json.dumps(merged_manifest, indent=2))
    for q in demos:
        hits = store.search(q, top_k=3)
        print(f"\nQuery: {q}")
        for h in hits:
            m = h["metadata"]
            print(
                f"  #{h['rank']} {h['score']:.3f} "
                f"[module={m.get('module')} {m.get('chunk_type')}] "
                f"{h['content'][:90]}..."
            )


if __name__ == "__main__":
    main()
