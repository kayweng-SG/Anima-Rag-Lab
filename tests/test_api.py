"""FastAPI triage endpoint tests (incl. /v1 App contract)."""

import os


def test_root_serves_frontend(api_client):
    response = api_client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "AnimaLink" in response.text


def test_api_info(api_client):
    response = api_client.get("/api")
    assert response.status_code == 200
    body = response.json()
    assert body["query_endpoint"] == "POST /v1/triage/query"
    assert body["api_version"] == "v1"

    v1 = api_client.get("/v1")
    assert v1.status_code == 200
    assert v1.json()["api_version"] == "v1"


def test_health(api_client):
    response = api_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["api_version"] == "v1"
    assert body["vector_store_loaded"] is True
    assert body["vector_count"] >= 100
    assert "llm_enabled" in body
    assert "auth_required" in body
    assert "toxic_plants_loaded" in body
    assert "complaint_map_loaded" in body
    assert "cache_enabled" in body
    assert "cache_backend" in body
    assert "retrieval" in body
    assert "retrieval_last" in body
    assert body["retrieval_fallbacks"] == 0


def test_health_reports_backend_actually_used(api_client):
    """`retrieval` is the intent; `retrieval_last` is what really served."""
    assert api_client.get("/health").json()["retrieval_last"] is None
    api_client.post(
        "/triage/query",
        json={"question": "What is normal heart rate for a small dog?"},
    )
    body = api_client.get("/health").json()
    assert body["retrieval_last"] == "local"


def test_triage_query_green(api_client):
    response = api_client.post(
        "/triage/query",
        json={
            "question": "What is normal heart rate for a small dog?",
            "species": "dog",
            "size": "small",
            "heart_rate_bpm": 95,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "v1"
    assert body["request_id"]
    assert body["red_light_status"] == "GREEN"
    assert body["intercepted"] is False
    assert body["sources"]
    assert body["answer_zh"]
    assert body["answer_en"]
    assert body["record_id"]
    assert response.headers.get("X-API-Version") == "v1"
    assert response.headers.get("X-Request-Id")

    saved = api_client.get(f"/triage/results/{body['record_id']}")
    assert saved.status_code == 200
    row = saved.json()
    assert row["answer_zh"] == body["answer_zh"]
    assert row["answer_en"] == body["answer_en"]


def test_v1_triage_query_with_client_request_id(api_client):
    response = api_client.post(
        "/v1/triage/query",
        headers={"X-Request-Id": "hdr-req-1"},
        json={
            "question": "小狗正常心率是多少？",
            "species": "dog",
            "size": "small",
            "heart_rate_bpm": 95,
            "client_request_id": "client-req-9",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "client-req-9"
    assert body["api_version"] == "v1"


def test_triage_query_red_intercept(api_client):
    response = api_client.post(
        "/v1/triage/query",
        json={
            "question": "Poisoning treatment",
            "species": "dog",
            "chief_complaint": "Ate rat poison, vomiting",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["red_light_status"] == "RED"
    assert body["intercepted"] is True
    assert body["sources"] == []
    assert "立即" in body["answer_zh"] or "紧急" in body["answer_zh"]
    assert "emergency" in body["answer_en"].lower()
    assert body["record_id"]


def test_triage_results_list(api_client):
    response = api_client.get("/v1/triage/results?limit=5")
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert body["count"] == len(body["results"])
    assert body["api_version"] == "v1"


def test_triage_query_validation_error(api_client):
    response = api_client.post("/v1/triage/query", json={"question": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"]


def test_api_key_required_when_configured(api_client, monkeypatch):
    monkeypatch.setenv("ANIMA_API_KEY", "test-secret-key")
    # Hit endpoint without key.
    denied = api_client.post(
        "/v1/triage/query",
        json={"question": "小狗正常心率是多少？", "species": "dog"},
    )
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"

    ok = api_client.post(
        "/v1/triage/query",
        headers={"X-API-Key": "test-secret-key"},
        json={
            "question": "小狗正常心率是多少？",
            "species": "dog",
            "size": "small",
            "heart_rate_bpm": 95,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["api_version"] == "v1"

    # Cleanup for other tests in same process.
    monkeypatch.delenv("ANIMA_API_KEY", raising=False)
