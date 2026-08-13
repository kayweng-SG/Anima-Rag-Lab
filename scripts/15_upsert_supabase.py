#!/usr/bin/env python3
"""Upsert exported knowledge_chunks JSONL into Supabase (WBS 2.2–2.3).

Requires env:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Dry-run by default (no network). Pass --apply to POST batches.

Usage:
  python scripts/15_upsert_supabase.py --jsonl data/processed/supabase_export/knowledge_chunks.jsonl
  python scripts/15_upsert_supabase.py --apply --batch-size 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("upsert_supabase")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSONL = (
    PROJECT_ROOT / "data" / "processed" / "supabase_export" / "knowledge_chunks.jsonl"
)


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def iter_rows(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Bad JSONL at line {line_no}: {exc}") from exc


def to_postgrest_row(row: Dict[str, Any]) -> Dict[str, Any]:
    emb = row.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise ValueError(f"row {row.get('id')}: missing embedding")
    # pgvector accepts stringified vector via PostgREST
    emb_str = "[" + ",".join(f"{float(x):.8f}" for x in emb) + "]"
    return {
        "id": row["id"],
        "content": row.get("content") or "",
        "metadata": row.get("metadata") or {},
        "embedding": emb_str,
        "module": str(row.get("module") or "A").upper(),
        "source": row.get("source"),
    }


def chunked(items: List[Any], size: int) -> Iterator[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def upsert_batch(
    url: str,
    key: str,
    rows: List[Dict[str, Any]],
    timeout: float = 120.0,
) -> None:
    import httpx

    endpoint = url.rstrip("/") + "/rest/v1/knowledge_chunks"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(endpoint, headers=headers, json=rows)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Upsert failed HTTP {resp.status_code}: {resp.text[:500]}"
            )


def main(argv: Optional[Iterable[str]] = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually POST to Supabase (requires env keys)",
    )
    p.add_argument("--sleep", type=float, default=0.15, help="Pause between batches")
    args = p.parse_args(list(argv) if argv is not None else None)

    if not args.jsonl.is_file():
        raise SystemExit(
            f"Missing {args.jsonl}. Run: python scripts/14_export_pgvector.py"
        )

    rows: List[Dict[str, Any]] = []
    for raw in iter_rows(args.jsonl):
        rows.append(to_postgrest_row(raw))
        if args.limit is not None and len(rows) >= args.limit:
            break

    logger.info("Prepared %s rows from %s", len(rows), args.jsonl)
    if not rows:
        return 0

    if not args.apply:
        sample = {k: rows[0][k] for k in ("id", "module", "source")}
        sample["embedding_preview"] = str(rows[0]["embedding"])[:60] + "…"
        logger.info("Dry-run OK. Sample: %s", sample)
        logger.info("Re-run with --apply after applying supabase/migrations/*.sql")
        return 0

    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in env or .env"
        )

    batches = list(chunked(rows, max(args.batch_size, 1)))
    for i, batch in enumerate(batches, 1):
        logger.info("Upserting batch %s/%s (%s rows)…", i, len(batches), len(batch))
        upsert_batch(url, key, batch)
        if args.sleep > 0 and i < len(batches):
            time.sleep(args.sleep)

    logger.info("Done: upserted %s rows into knowledge_chunks", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
