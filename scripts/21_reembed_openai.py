#!/usr/bin/env python3
"""Re-embed the merged store with OpenAI → pgvector JSONL (AnimaLink migration).

AnimaLink retrieves inside a Deno Edge Function, which cannot run
sentence-transformers. Query vectors therefore have to come from an HTTP
embedding API, and the corpus must be embedded with that same model.

Model: text-embedding-3-small at dimensions=384. Holding the dimension at 384
keeps the vector(384) column and the match_knowledge_chunks signature identical
to the Lab's, so the embedding model is the only variable that changes when the
eval suite is re-run against the new index.

Output is byte-compatible with scripts/14_export_pgvector.py, so
scripts/15_upsert_supabase.py consumes it unchanged.

Usage:
  python scripts/21_reembed_openai.py --dry-run
  OPENAI_API_KEY=sk-... python scripts/21_reembed_openai.py
  python scripts/21_reembed_openai.py --modules B,C --out /tmp/bc.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reembed_openai")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORE = PROJECT_ROOT / "data" / "processed" / "merged_vector_store"
DEFAULT_OUT = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "supabase_export"
    / "knowledge_chunks_openai.jsonl"
)

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSIONS = 384

# text-embedding-3-small accepts 2048 inputs / 300k tokens per request. Cap on
# characters too: a batch of long chunks can blow the token budget well before
# it reaches the input-count limit.
DEFAULT_BATCH_SIZE = 128
MAX_BATCH_CHARS = 400_000

# Rough char→token ratio for the mixed zh/en corpus, used only for estimates.
CHARS_PER_TOKEN = 3.5
USD_PER_MILLION_TOKENS = 0.02


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _parse_modules(raw: Optional[str]) -> Optional[Set[str]]:
    if not raw:
        return None
    mods = {m.strip().upper() for m in raw.split(",") if m.strip()}
    bad = mods - {"A", "B", "C"}
    if bad:
        raise SystemExit(f"Invalid --modules {bad}; use A,B,C")
    return mods


def iter_records(
    store_dir: Path,
    modules: Optional[Set[str]] = None,
    min_chars: int = 0,
) -> Iterator[Dict[str, Any]]:
    """Yield export rows (without embeddings) from the merged store."""
    records_path = store_dir / "records.json"
    if not records_path.is_file():
        raise SystemExit(f"Missing {records_path}")

    records = json.loads(records_path.read_text(encoding="utf-8"))
    for i, rec in enumerate(records):
        content = rec.get("content") or ""
        meta = dict(rec.get("metadata") or {})
        module = str(meta.get("module") or "").upper() or "A"
        if modules is not None and module not in modules:
            continue
        # The API rejects empty input; min_chars additionally drops table-cell
        # fragments ("Drug", "Uses") that are noise in a semantic index.
        if len(content.strip()) < max(min_chars, 1):
            continue
        yield {
            "id": rec.get("chunk_id") or f"chunk_{i}",
            "content": content,
            "metadata": meta,
            "module": module,
            "source": meta.get("source"),
        }


def load_done_ids(out_path: Path) -> Set[str]:
    """Collect ids already embedded, dropping any truncated trailing line.

    Re-embedding costs money and 14k rows take a while, so a crashed run must
    resume rather than start over.
    """
    if not out_path.is_file():
        return set()

    done: Set[str] = set()
    kept: List[str] = []
    dropped = 0
    for line in out_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            dropped += 1
            continue
        row_id = row.get("id")
        if not row_id or not row.get("embedding"):
            dropped += 1
            continue
        done.add(row_id)
        kept.append(line)

    if dropped:
        logger.warning("Rewriting %s to drop %s bad line(s)", out_path, dropped)
        out_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    if done:
        logger.info("Resuming: %s rows already embedded", len(done))
    return done


def _with_retry(
    call: Any,
    what: str,
    attempts: int = 5,
    base_delay: float = 2.0,
) -> Any:
    last: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 — retry on any transport error
            last = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "%s failed (attempt %s/%s): %s — retrying in %.1fs",
                what,
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}")


def embed_batch(
    texts: Sequence[str],
    api_key: str,
    model: str = DEFAULT_MODEL,
    dimensions: int = DEFAULT_DIMENSIONS,
    timeout: float = 120.0,
) -> List[List[float]]:
    """Embed one batch, preserving input order."""

    def _call() -> List[List[float]]:
        resp = requests.post(
            OPENAI_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": list(texts),
                "dimensions": dimensions,
                "encoding_format": "float",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:400]}")
        payload = resp.json()
        data = sorted(payload.get("data") or [], key=lambda d: d.get("index", 0))
        if len(data) != len(texts):
            raise RuntimeError(f"expected {len(texts)} embeddings, got {len(data)}")
        vectors = [d["embedding"] for d in data]
        for vec in vectors:
            if len(vec) != dimensions:
                raise RuntimeError(
                    f"model returned dim {len(vec)}, expected {dimensions}"
                )
        return vectors

    return _with_retry(_call, f"embed batch of {len(texts)}")


def batched(
    rows: Iterable[Dict[str, Any]],
    batch_size: int,
    max_chars: int = MAX_BATCH_CHARS,
) -> Iterator[List[Dict[str, Any]]]:
    batch: List[Dict[str, Any]] = []
    chars = 0
    for row in rows:
        row_chars = len(row["content"])
        if batch and (len(batch) >= batch_size or chars + row_chars > max_chars):
            yield batch
            batch, chars = [], 0
        batch.append(row)
        chars += row_chars
    if batch:
        yield batch


def estimate(rows: Sequence[Dict[str, Any]]) -> Tuple[int, int, float]:
    chars = sum(len(r["content"]) for r in rows)
    tokens = int(chars / CHARS_PER_TOKEN)
    return chars, tokens, tokens / 1e6 * USD_PER_MILLION_TOKENS


def run(
    store_dir: Path,
    out_path: Path,
    api_key: str,
    modules: Optional[Set[str]] = None,
    min_chars: int = 0,
    model: str = DEFAULT_MODEL,
    dimensions: int = DEFAULT_DIMENSIONS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_done_ids(out_path)

    pending = [
        row
        for row in iter_records(store_dir, modules, min_chars)
        if row["id"] not in done
    ]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        logger.info("Nothing to do: all %s rows already embedded", len(done))
        return len(done)

    _, tokens, usd = estimate(pending)
    logger.info(
        "Embedding %s rows with %s (dim=%s) — est %s tokens, ~$%.4f",
        len(pending),
        model,
        dimensions,
        f"{tokens:,}",
        usd,
    )

    written = 0
    started = time.time()
    with out_path.open("a", encoding="utf-8") as fh:
        for batch in batched(pending, batch_size):
            vectors = embed_batch(
                [r["content"] for r in batch], api_key, model, dimensions
            )
            for row, vec in zip(batch, vectors):
                fh.write(
                    json.dumps(
                        {
                            "id": row["id"],
                            "content": row["content"],
                            "metadata": row["metadata"],
                            "embedding": [float(x) for x in vec],
                            "module": row["module"],
                            "source": row["source"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            # Flush per batch so a crash loses at most one batch of paid work.
            fh.flush()
            written += len(batch)
            if written % (batch_size * 8) == 0 or written == len(pending):
                rate = written / max(time.time() - started, 0.001)
                logger.info(
                    "… %s/%s rows (%.0f rows/s)", written, len(pending), rate
                )

    total = len(done) + written
    sidecar = {
        "generated_from": str(store_dir),
        "embedder": f"openai:{model}",
        "dimension": dimensions,
        "rows": total,
        "rows_this_run": written,
        "modules_filter": sorted(modules) if modules else None,
        "min_chars": min_chars,
        "output": str(out_path),
    }
    out_path.with_suffix(".manifest.json").write_text(
        json.dumps(sidecar, indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "Wrote %s rows this run (%s total) → %s in %.1fs",
        written,
        total,
        out_path,
        time.time() - started,
    )
    return total


def main(argv: Optional[Iterable[str]] = None) -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store", type=Path, default=DEFAULT_STORE)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--modules", type=str, default=None, help="e.g. B,C or A")
    p.add_argument("--model", type=str, default=DEFAULT_MODEL)
    p.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--min-chars",
        type=int,
        default=0,
        help=(
            "Drop chunks shorter than this. Default 0 keeps the corpus identical "
            "to the Lab index so eval deltas are attributable to the model alone; "
            "342 table-cell fragments are removed at --min-chars 10."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row count and cost estimate without calling the API",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    modules = _parse_modules(args.modules)
    rows = list(iter_records(args.store, modules, args.min_chars))

    if args.dry_run:
        chars, tokens, usd = estimate(rows)
        by_module: Dict[str, int] = {}
        for row in rows:
            by_module[row["module"]] = by_module.get(row["module"], 0) + 1
        logger.info(
            "Dry run: %s rows %s, %s chars, est %s tokens, ~$%.4f with %s (dim=%s)",
            len(rows),
            dict(sorted(by_module.items())),
            f"{chars:,}",
            f"{tokens:,}",
            usd,
            args.model,
            args.dimensions,
        )
        return 0

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY in env or .env")

    run(
        store_dir=args.store,
        out_path=args.out,
        api_key=api_key,
        modules=modules,
        min_chars=args.min_chars,
        model=args.model,
        dimensions=args.dimensions,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
