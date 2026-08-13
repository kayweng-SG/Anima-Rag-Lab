"""Optional Redis semantic-cache helper (WBS 4.1).

When REDIS_URL is unset, all operations are no-ops so local/demo keeps working.

Backends:
  redis://… / rediss://…  — real Redis (Compose profile ``cache``)
  memory://local           — in-process TTL dict (smoke / no Docker)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class _MemoryRedis:
    """Minimal Redis subset (get / setex / ping) for local smoke without a server."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, str]] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> Optional[str]:
        row = self._store.get(key)
        if not row:
            return None
        expires_at, value = row
        if expires_at and expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def setex(self, key: str, ttl: int, value: str) -> bool:
        expires_at = time.time() + max(int(ttl), 1)
        self._store[key] = (expires_at, value)
        return True


class SemanticCache:
    def __init__(self, redis_url: Optional[str] = None, ttl_seconds: int = 3600) -> None:
        self.ttl = ttl_seconds
        self._client = None
        self.backend: str = "off"
        url = (redis_url or os.getenv("REDIS_URL") or "").strip()
        if not url:
            logger.info("SemanticCache disabled (REDIS_URL not set)")
            return

        lower = url.lower()
        if lower.startswith("memory:"):
            self._client = _MemoryRedis()
            self.backend = "memory"
            logger.info("SemanticCache connected (memory:// in-process)")
            return

        try:
            import redis  # type: ignore

            self._client = redis.Redis.from_url(url, decode_responses=True)
            self._client.ping()
            self.backend = "redis"
            logger.info("SemanticCache connected (%s)", url.split("@")[-1])
        except Exception as exc:  # noqa: BLE001 — cache must never break triage
            logger.warning("SemanticCache unavailable: %s", exc)
            self._client = None
            self.backend = "off"

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @staticmethod
    def _key(question: str, species: str = "") -> str:
        blob = f"{species.strip().lower()}::{question.strip().lower()}"
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
        return f"anima:triage:v1:{digest}"

    def get(self, question: str, species: str = "") -> Optional[dict[str, Any]]:
        if not self._client:
            return None
        try:
            raw = self._client.get(self._key(question, species))
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("SemanticCache get failed: %s", exc)
            return None

    def set(self, question: str, payload: dict[str, Any], species: str = "") -> None:
        if not self._client:
            return
        try:
            self._client.setex(
                self._key(question, species),
                self.ttl,
                json.dumps(payload, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SemanticCache set failed: %s", exc)
