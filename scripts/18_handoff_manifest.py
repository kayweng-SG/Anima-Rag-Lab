#!/usr/bin/env python3
"""Write docs/handoff_manifest.json — machine-readable Lab deliverable inventory."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "handoff_manifest.json"


def _count_jsonl(path: Path) -> Optional[int]:
    if not path.is_file():
        return None
    n = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    merged_man = _load_json(ROOT / "data/processed/merged_vector_store/manifest.json") or {}
    bc_chunks = _load_json(ROOT / "data/processed/module_bc_chunks.json") or {}
    cases = _load_json(ROOT / "evals/cases.json") or {}
    case_list = cases.get("cases") or []
    bc_cases = [c for c in case_list if c.get("group") == "module_bc"]

    paths_exist: Dict[str, bool] = {}
    for rel in [
        "data/processed/merged_vector_store/manifest.json",
        "data/processed/module_bc_chunks.json",
        "data/pgvector_local/knowledge_chunks.sqlite3",
        "supabase/migrations/20260813_knowledge_chunks.sql",
        "scripts/12_chunk_module_bc.py",
        "scripts/13_embed_module_bc.py",
        "scripts/14_export_pgvector.py",
        "scripts/15_upsert_supabase.py",
        "scripts/16_local_pgvector.py",
        "scripts/17_enrich_module_bc_gaps.py",
        "docs/LAB_HANDOFF.md",
        "docs/APP_INTEGRATION.md",
        "docs/SUPABASE_MERGE.md",
        "evals/cases.json",
        "data/raw/module_c_husbandry/pettalk_asia/articles.jsonl",
        "data/raw/module_c_husbandry/aaha/pdf_extracts/table1.json",
        "data/raw/module_b_behavior/cbarq_mcpq_r/related_instruments/mcpq_r_blank_form.json",
    ]:
        paths_exist[rel] = (ROOT / rel).is_file() or (ROOT / rel).is_dir()

    manifest: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lab": "anima-rag-lab",
        "scope": "lab_only_no_animalink_wiring",
        "handoff_doc": "docs/LAB_HANDOFF.md",
        "vectors": {
            "merged_count": merged_man.get("vector_count"),
            "module_a_count": merged_man.get("module_a_count"),
            "module_bc_count": merged_man.get("module_bc_count"),
            "embedder": merged_man.get("embedder"),
            "dimension": merged_man.get("dimension"),
            "store_dir": "data/processed/merged_vector_store",
        },
        "module_bc_chunks": {
            "count": bc_chunks.get("chunk_count"),
            "sources": bc_chunks.get("sources"),
            "path": "data/processed/module_bc_chunks.json",
        },
        "pettalk_articles": _count_jsonl(
            ROOT / "data/raw/module_c_husbandry/pettalk_asia/articles.jsonl"
        ),
        "evals": {
            "total_cases": len(case_list),
            "module_bc_cases": len(bc_cases),
            "module_bc_ids": [c.get("id") for c in bc_cases],
        },
        "paths": paths_exist,
        "deferred": [
            "AnimaLink code / App联调",
            "Supabase cloud upsert (needs SUPABASE_*)",
            "Stable public HTTPS",
            "Official Monash MCPQ-R blank PDF",
        ],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
