#!/usr/bin/env python3
"""Upsert exported knowledge_chunks JSONL into Supabase (WBS 2.2–2.3).

Requires env:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

Dry-run by default (no network). Pass --apply to POST batches.

Upsert uses `resolution=merge-duplicates`, which never deletes. Rows dropped
from the export (e.g. by de-dup) linger in the cloud until pruned, so
--verify reports the drift and --prune removes it.

Usage:
  python scripts/15_upsert_supabase.py --jsonl data/processed/supabase_export/knowledge_chunks.jsonl
  python scripts/15_upsert_supabase.py --apply --batch-size 50

  # compare cloud vs export without writing anything
  python scripts/15_upsert_supabase.py --verify

  # upsert, then delete in-scope cloud rows missing from the export
  python scripts/15_upsert_supabase.py --apply --prune
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


def _auth_headers(key: str) -> Dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _with_retry(
    call: Any,
    what: str,
    attempts: int = 4,
    base_delay: float = 1.0,
) -> Any:
    """Retry a request on transport errors (dropped TLS, reset, timeout).

    A full-store verify issues one request per 1000 ids, so a single blip
    would otherwise abort the whole run.
    """
    import httpx

    last: Optional[BaseException] = None
    for attempt in range(attempts):
        try:
            return call()
        except httpx.TransportError as exc:
            last = exc
            if attempt == attempts - 1:
                break
            delay = base_delay * (2**attempt)
            logger.warning(
                "%s failed (%s); retrying in %.1fs (%s/%s)",
                what,
                exc,
                delay,
                attempt + 1,
                attempts - 1,
            )
            time.sleep(delay)
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}") from last


def fetch_cloud_ids(
    url: str,
    key: str,
    modules: Iterable[str],
    page_size: int = 1000,
    timeout: float = 120.0,
) -> Dict[str, set]:
    """Return {module: {id, ...}} for the given modules."""
    import httpx

    endpoint = url.rstrip("/") + "/rest/v1/knowledge_chunks"
    out: Dict[str, set] = {}
    with httpx.Client(timeout=timeout) as client:
        for module in modules:
            ids: set = set()
            offset = 0
            while True:
                params = {
                    "select": "id",
                    "module": f"eq.{module}",
                    "order": "id.asc",
                    "limit": page_size,
                    "offset": offset,
                }
                resp = _with_retry(
                    lambda: client.get(
                        endpoint, headers=_auth_headers(key), params=params
                    ),
                    f"Fetch ids (module {module}, offset {offset})",
                )
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"Fetch ids failed HTTP {resp.status_code}: {resp.text[:300]}"
                    )
                page = resp.json()
                if not page:
                    break
                ids.update(row["id"] for row in page)
                if len(page) < page_size:
                    break
                offset += page_size
            out[module] = ids
    return out


def delete_ids(
    url: str,
    key: str,
    ids: List[str],
    timeout: float = 120.0,
) -> None:
    import httpx

    endpoint = url.rstrip("/") + "/rest/v1/knowledge_chunks"
    headers = dict(_auth_headers(key))
    headers["Prefer"] = "return=minimal"
    # PostgREST in.() takes a quoted, comma-separated list.
    quoted = ",".join('"' + i.replace('"', '""') + '"' for i in ids)
    with httpx.Client(timeout=timeout) as client:
        resp = _with_retry(
            lambda: client.delete(
                endpoint, headers=headers, params={"id": f"in.({quoted})"}
            ),
            "Delete batch",
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Delete failed HTTP {resp.status_code}: {resp.text[:300]}"
            )


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
        # Safe to retry: merge-duplicates makes the upsert idempotent.
        resp = _with_retry(
            lambda: client.post(endpoint, headers=headers, json=rows), "Upsert batch"
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Upsert failed HTTP {resp.status_code}: {resp.text[:500]}"
            )


def _drift(
    url: str,
    key: str,
    scope: List[str],
    local_by_module: Dict[str, set],
) -> Dict[str, Dict[str, set]]:
    cloud = fetch_cloud_ids(url, key, scope)
    return {
        m: {
            "stale": cloud[m] - local_by_module[m],
            "missing": local_by_module[m] - cloud[m],
            "cloud": cloud[m],
        }
        for m in scope
    }


def _report_drift(
    url: str,
    key: str,
    scope: List[str],
    local_by_module: Dict[str, set],
) -> int:
    drift = _drift(url, key, scope, local_by_module)
    clean = True
    for m in scope:
        stale, missing = drift[m]["stale"], drift[m]["missing"]
        logger.info(
            "module %s: cloud=%s export=%s | stale=%s missing=%s",
            m,
            len(drift[m]["cloud"]),
            len(local_by_module[m]),
            len(stale),
            len(missing),
        )
        for i in sorted(stale)[:20]:
            logger.info("    stale (cloud only): %s", i)
        for i in sorted(missing)[:20]:
            logger.info("    missing (export only): %s", i)
        if stale or missing:
            clean = False
    if clean:
        logger.info("In sync: cloud matches the export for modules %s", ",".join(scope))
        return 0
    logger.warning("Drift detected. Fix with: --apply --prune")
    return 1


def _prune(
    url: str,
    key: str,
    scope: List[str],
    local_by_module: Dict[str, set],
    batch_size: int,
    force: bool,
) -> None:
    drift = _drift(url, key, scope, local_by_module)
    for m in scope:
        stale = sorted(drift[m]["stale"])
        cloud_n = len(drift[m]["cloud"])
        if not stale:
            logger.info("module %s: nothing to prune", m)
            continue
        # A huge delete usually means the export was partial, not that the
        # cloud is dirty. Refuse unless the caller insists.
        if not force and cloud_n and len(stale) / cloud_n > 0.2:
            raise SystemExit(
                f"module {m}: prune would delete {len(stale)}/{cloud_n} rows "
                f"(>20%). Check the export covers this module, or pass --force."
            )
        logger.info("module %s: pruning %s stale rows…", m, len(stale))
        for batch in chunked(stale, max(batch_size, 1)):
            delete_ids(url, key, batch)
        logger.info("module %s: pruned %s rows", m, len(stale))


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
    p.add_argument(
        "--verify",
        action="store_true",
        help="Read-only: compare cloud rows against the export and exit",
    )
    p.add_argument(
        "--prune",
        action="store_true",
        help="Delete in-scope cloud rows missing from the export (needs --apply)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Allow --prune to exceed the 20%% safety threshold",
    )
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

    local_by_module: Dict[str, set] = {}
    for row in rows:
        local_by_module.setdefault(row["module"], set()).add(row["id"])
    scope = sorted(local_by_module)
    logger.info(
        "Export scope: modules %s (%s)",
        ",".join(scope),
        ", ".join(f"{m}={len(local_by_module[m])}" for m in scope),
    )

    if not args.apply and not args.verify:
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

    if args.verify:
        return _report_drift(url, key, scope, local_by_module)

    batches = list(chunked(rows, max(args.batch_size, 1)))
    for i, batch in enumerate(batches, 1):
        logger.info("Upserting batch %s/%s (%s rows)…", i, len(batches), len(batch))
        upsert_batch(url, key, batch)
        if args.sleep > 0 and i < len(batches):
            time.sleep(args.sleep)

    if args.prune:
        _prune(url, key, scope, local_by_module, args.batch_size, args.force)

    logger.info("Done: upserted %s rows into knowledge_chunks", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
