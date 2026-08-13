"""Semantic cache unit tests (memory backend; no Redis server required)."""

from conftest import load_script_module

semantic_cache = load_script_module("test_semantic_cache_mod", "semantic_cache.py")
SemanticCache = semantic_cache.SemanticCache


def test_memory_backend_roundtrip():
    cache = SemanticCache(redis_url="memory://local", ttl_seconds=60)
    assert cache.enabled is True
    assert cache.backend == "memory"
    assert cache.get("q1", "dog") is None

    payload = {"answer": "ok", "intercepted": False, "red_light_status": "GREEN"}
    cache.set("q1", payload, "dog")
    hit = cache.get("q1", "dog")
    assert hit == payload
    assert cache.get("q1", "cat") is None


def test_disabled_without_url():
    cache = SemanticCache(redis_url="")
    assert cache.enabled is False
    assert cache.backend == "off"
    assert cache.get("anything") is None
    cache.set("anything", {"x": 1})  # no-op


def test_key_normalization():
    cache = SemanticCache(redis_url="memory://local")
    cache.set("  Hello  ", {"a": 1}, "Dog")
    assert cache.get("hello", "dog") == {"a": 1}
