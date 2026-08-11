"""Fixed eval-suite regression tests (extractive answers, no LLM)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES_PATH = os.path.join(PROJECT_ROOT, "evals", "cases.json")


def _load_eval_runner():
    path = os.path.join(PROJECT_ROOT, "scripts", "09_run_eval.py")
    spec = importlib.util.spec_from_file_location("anima_eval_runner", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["anima_eval_runner"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _load_cases():
    with open(CASES_PATH, encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload["cases"]


@pytest.fixture(scope="session")
def eval_runner():
    return _load_eval_runner()


@pytest.fixture(scope="session")
def eval_pipeline(rag_mod, vector_store, red_light):
    """Dedicated pipeline with LLM forced off for deterministic checks."""
    pipeline = rag_mod.AnimaRAGPipeline(vector_store=vector_store, red_light=red_light)
    pipeline.openai_api_key = ""
    pipeline.llm_enabled = False
    return pipeline


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_eval_case(eval_runner, eval_pipeline, rag_mod, case):
    result = eval_runner.evaluate_case(eval_pipeline, rag_mod, case)
    if not result.passed:
        details = "; ".join(f"{f.check}: {f.detail}" for f in result.failures)
        pytest.fail(f"{case['id']} failed — {details}")
