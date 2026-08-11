"""Vector retrieval smoke tests."""

import warnings

import numpy as np


def test_vector_store_loaded(vector_store):
    assert vector_store.vectors is not None
    assert len(vector_store.records) > 0
    assert vector_store.vectors.dtype == np.float32
    assert np.isfinite(vector_store.vectors).all()


def test_search_no_matmul_runtime_warnings(vector_store):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        hits = vector_store.search(
            "dog heart rate bpm normal reference range", top_k=5
        )
    matmul_warns = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "matmul" in str(w.message).lower()
    ]
    assert matmul_warns == [], [str(w.message) for w in matmul_warns]
    assert len(hits) >= 1
    assert all(-1.0 - 1e-5 <= h["score"] <= 1.0 + 1e-5 for h in hits)


def test_heart_rate_query_returns_metric(vector_store):
    hits = vector_store.search(
        "dog heart rate bpm normal reference range tachycardia", top_k=15
    )
    assert len(hits) >= 3
    chunk_types = {hit["metadata"].get("chunk_type") for hit in hits}
    assert "numeric_metric" in chunk_types
    assert any("heart_rate" in hit["content"] for hit in hits)


def test_poisoning_query_returns_toxic_chunk(vector_store):
    hits = vector_store.search("poisoning activated charcoal treatment", top_k=3)
    assert len(hits) >= 1
    combined = " ".join(hit["content"].lower() for hit in hits)
    assert "poison" in combined or "charcoal" in combined or "toxic" in combined


def test_heat_stroke_query_returns_relevant_chunk(vector_store):
    hits = vector_store.search("heat stroke cooling first aid", top_k=3)
    assert len(hits) >= 1
    combined = " ".join(hit["content"].lower() for hit in hits)
    assert "heat" in combined or "cool" in combined
