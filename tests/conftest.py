"""Shared fixtures for ANIMA-RAG-Lab tests."""

import importlib.util
import os
import sys
from typing import Any

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

# Unit tests / eval must not hit cloud RPC even if .env has Supabase keys.
os.environ["ANIMA_RETRIEVAL"] = "local"
# Prefer local HF cache; avoid long proxy hangs when the model is missing.
# Warm cache once online: python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"
os.environ.setdefault("ANIMA_EMBED_OFFLINE", "1")
# Keep API tests open unless a test explicitly sets ANIMA_API_KEY.
os.environ["ANIMA_API_KEY"] = ""


def load_script_module(module_name: str, filename: str) -> Any:
    path = os.path.join(SCRIPTS_DIR, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def red_light_mod():
    return load_script_module("test_red_light", "03_red_light_intercept.py")


@pytest.fixture(scope="session")
def embed_mod():
    return load_script_module("test_embed", "05_embed_merck.py")


@pytest.fixture(scope="session")
def rag_mod():
    return load_script_module("test_rag", "06_rag_query.py")


@pytest.fixture(scope="session")
def api_mod():
    return load_script_module("test_api", "07_api_server.py")


@pytest.fixture(scope="session")
def upsert_mod():
    return load_script_module("test_upsert", "15_upsert_supabase.py")


@pytest.fixture(scope="session")
def red_light(red_light_mod):
    return red_light_mod.RedLightIntercept()


@pytest.fixture(scope="session")
def vector_store(embed_mod):
    store = embed_mod.MerckVectorStore(retrieval="local")
    store.load()
    return store


@pytest.fixture(scope="session")
def cbarq_engine():
    mod = load_script_module("test_cbarq", "19_cbarq_personality.py")
    return mod.CBarqPersonality()


@pytest.fixture(scope="session")
def mcpq_engine():
    mod = load_script_module("test_mcpq", "20_mcpq_personality.py")
    return mod.MCPQRPersonality()


@pytest.fixture(scope="session")
def rag_pipeline(rag_mod, vector_store, red_light):
    return rag_mod.AnimaRAGPipeline(vector_store=vector_store, red_light=red_light)


@pytest.fixture(scope="session")
def api_client(api_mod, tmp_path_factory):
    from fastapi.testclient import TestClient

    db_path = tmp_path_factory.mktemp("triage_db") / "triage_results.db"
    os.environ["ANIMA_TRIAGE_DB"] = str(db_path)
    # Recreate store bound to temp DB after env is set.
    api_mod._store = api_mod.TriageResultStore(db_path=str(db_path))

    with TestClient(api_mod.app) as client:
        # Lifespan may overwrite store; force temp path again.
        api_mod._store = api_mod.TriageResultStore(db_path=str(db_path))
        yield client
