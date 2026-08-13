#!/usr/bin/env python3
"""Smoke: SemanticCache get/set with memory:// or REDIS_URL."""

from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from semantic_cache import SemanticCache  # noqa: E402


def main() -> int:
    url = (os.getenv("REDIS_URL") or "memory://local").strip()
    cache = SemanticCache(redis_url=url, ttl_seconds=120)
    if not cache.enabled:
        print(f"FAIL: cache disabled for REDIS_URL={url!r}")
        return 1

    q = "smoke: normal heart rate small dog"
    cache.set(q, {"answer": "smoke-ok", "intercepted": False}, "dog")
    hit = cache.get(q, "dog")
    if not hit or hit.get("answer") != "smoke-ok":
        print(f"FAIL: roundtrip miss backend={cache.backend} hit={hit}")
        return 1

    print(f"PASS: backend={cache.backend} url={url.split('@')[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
