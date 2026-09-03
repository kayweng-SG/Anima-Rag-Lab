#!/usr/bin/env python3
"""Retrieval-only eval of AnimaLink pgvector after OpenAI re-embedding.

Does not run the Lab extractive answerer or sentence-transformers.
For each evals/cases.json row that expects sources, embed with
text-embedding-3-small (384) and call match_knowledge_chunks.

RED intercept cases are skipped (AnimaLink never retrieves on RED).

Usage:
  python scripts/22_eval_animalink_retrieval.py
  python scripts/22_eval_animalink_retrieval.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = PROJECT_ROOT / "evals" / "cases.json"
DEFAULT_REPORT = PROJECT_ROOT / "evals" / "animalink_retrieval_report.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("animalink_retrieval_eval")


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _load_script(name: str, filename: str) -> Any:
    path = PROJECT_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)]


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    hay = text or ""
    hay_l = hay.lower()
    return any(n.lower() in hay_l or n in hay for n in needles if n)


def embed_query(api_key: str, text: str) -> List[float]:
    payload = json.dumps(
        {
            "model": "text-embedding-3-small",
            "input": text,
            "dimensions": 384,
            "encoding_format": "float",
        }
    ).encode()
    req = Request(
        "https://api.openai.com/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    vec = body["data"][0]["embedding"]
    if len(vec) != 384:
        raise RuntimeError(f"expected dim 384, got {len(vec)}")
    return [float(x) for x in vec]


def match_chunks(
    url: str,
    key: str,
    embedding: Sequence[float],
    module: str,
    match_count: int = 5,
) -> List[Dict[str, Any]]:
    emb = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
    payload = json.dumps(
        {
            "query_embedding": emb,
            "match_count": match_count,
            "filter_module": module,
        }
    ).encode()
    req = Request(
        url.rstrip("/") + "/rest/v1/rpc/match_knowledge_chunks",
        data=payload,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=60) as resp:
        rows = json.loads(resp.read())
    return rows if isinstance(rows, list) else []


def evaluate_retrieval_case(
    case: Dict[str, Any],
    rag_mod: Any,
    api_key: str,
    url: str,
    key: str,
) -> Dict[str, Any]:
    case_id = str(case.get("id") or "unnamed")
    expect = case.get("expect") or {}
    request = case.get("request") or {}
    question = str(request.get("question") or request.get("chief_complaint") or "")

    if expect.get("intercepted") is True:
        return {
            "id": case_id,
            "group": case.get("group"),
            "skipped": True,
            "reason": "RED intercept — AnimaLink does not retrieve",
            "passed": True,
        }

    source_needles = _as_list(expect.get("sources_content_must_match_any"))
    must_src = _as_list(expect.get("sources_source_must_include_any"))
    must_mod = _as_list(expect.get("sources_module_must_include_any"))
    min_sources = expect.get("min_sources")
    has_retrieval_expect = bool(
        source_needles or must_src or must_mod or min_sources is not None
    )
    if not has_retrieval_expect:
        return {
            "id": case_id,
            "group": case.get("group"),
            "skipped": True,
            "reason": "no retrieval assertions",
            "passed": True,
        }

    module = rag_mod.retrieval_module_for(question)
    terms = rag_mod.expand_complaint_to_clinical(question)
    embed_input = question if not terms else f"{question}\n{' '.join(terms)}"

    started = time.perf_counter()
    vec = embed_query(api_key, embed_input)
    rows = match_chunks(url, key, vec, module)
    elapsed_ms = (time.perf_counter() - started) * 1000

    blob_parts: List[str] = []
    sources: List[str] = []
    modules: List[str] = []
    sims: List[float] = []
    for row in rows:
        content = str(row.get("content") or "")
        meta = row.get("metadata") or {}
        blob_parts.append(content)
        blob_parts.append(json.dumps(meta, ensure_ascii=False))
        sources.append(str(row.get("source") or meta.get("source") or ""))
        modules.append(str(row.get("module") or meta.get("module") or ""))
        if row.get("similarity") is not None:
            sims.append(float(row["similarity"]))
    source_blob = " ".join(blob_parts)

    failures: List[str] = []
    if min_sources is not None and len(rows) < int(min_sources):
        failures.append(f"min_sources expected >= {min_sources}, got {len(rows)}")
    if source_needles and not _contains_any(source_blob, source_needles):
        failures.append(f"content miss: none of {source_needles}")
    if must_src and not any(
        any(needle.lower() == src.lower() for needle in must_src) for src in sources
    ):
        failures.append(f"source miss: expected {must_src}, got {sources}")
    if must_mod and not any(
        any(needle.upper() == mod.upper() for needle in must_mod) for mod in modules
    ):
        failures.append(f"module miss: expected {must_mod}, got {modules}")

    return {
        "id": case_id,
        "group": case.get("group"),
        "skipped": False,
        "passed": not failures,
        "failures": failures,
        "module": module,
        "expanded_terms": terms,
        "hit_count": len(rows),
        "top_similarity": max(sims) if sims else None,
        "min_similarity": min(sims) if sims else None,
        "sources": sources,
        "elapsed_ms": round(elapsed_ms, 1),
        "top_title": (rows[0].get("metadata") or {}).get("article_title")
        if rows
        else None,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    url = (os.getenv("ANIMALINK_SUPABASE_URL") or "").strip()
    key = (os.getenv("ANIMALINK_SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("Set ANIMALINK_SUPABASE_URL and ANIMALINK_SUPABASE_SERVICE_ROLE_KEY")
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY")

    rag_mod = _load_script("anima_rag_query", "06_rag_query.py")
    cases = json.loads(args.cases.read_text(encoding="utf-8")).get("cases") or []

    results = [
        evaluate_retrieval_case(case, rag_mod, api_key, url, key) for case in cases
    ]
    scored = [r for r in results if not r.get("skipped")]
    passed = sum(1 for r in scored if r["passed"])
    failed = len(scored) - passed
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "target": urlparse(url).netloc,
        "embedder": "openai:text-embedding-3-small",
        "dimension": 384,
        "total_cases": len(results),
        "scored": len(scored),
        "skipped": len(results) - len(scored),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "AnimaLink retrieval: %s/%s scored passed (%s skipped) → %s",
        passed,
        len(scored),
        report["skipped"],
        args.report,
    )
    for row in scored:
        mark = "PASS" if row["passed"] else "FAIL"
        logger.info(
            "  %s %-32s module=%s hits=%s top=%.3f %s",
            mark,
            row["id"],
            row.get("module"),
            row.get("hit_count"),
            row.get("top_similarity") or 0.0,
            "; ".join(row.get("failures") or []) or (row.get("top_title") or ""),
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
