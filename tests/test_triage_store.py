"""Triage result SQLite store tests."""

import importlib.util
import os
import sys


def _load_store(tmp_path):
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "scripts", "08_triage_store.py"
    )
    spec = importlib.util.spec_from_file_location("triage_store_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["triage_store_test"] = mod
    spec.loader.exec_module(mod)
    return mod.TriageResultStore(db_path=str(tmp_path / "triage_results.db"))


def test_store_saves_bilingual_answers(tmp_path):
    store = _load_store(tmp_path)
    record_id = store.save(
        request={
            "question": "中暑怎么办？喘气但仍清醒",
            "species": "dog",
            "rectal_temp_f": 102.8,
        },
        response={
            "answer_zh": "中文建议：阴凉降温",
            "answer_en": "English advice: cool in shade",
            "recommendation_zh": "YELLOW 中文",
            "recommendation_en": "YELLOW English",
            "red_light_status": "YELLOW",
            "intercepted": False,
            "extracted_symptoms": ["中暑", "喘气"],
            "sources": [{"rank": 1, "content": "cooling"}],
            "retrieval_query": "heat stroke",
            "model_used": "extractive_fallback",
            "elapsed_ms": 12.3,
            "red_light": {"status": "YELLOW"},
        },
    )
    assert record_id

    row = store.get(record_id)
    assert row is not None
    assert row["answer_zh"] == "中文建议：阴凉降温"
    assert row["answer_en"] == "English advice: cool in shade"
    assert row["recommendation_zh"] == "YELLOW 中文"
    assert row["recommendation_en"] == "YELLOW English"
    assert row["extracted_symptoms"] == ["中暑", "喘气"]
    assert row["red_light_status"] == "YELLOW"

    listed = store.list_recent(limit=5)
    assert len(listed) == 1
    assert listed[0]["id"] == record_id
