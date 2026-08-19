"""Module B: MCPQ-R personality scoring."""


def test_mcpq_form_spec(mcpq_engine):
    spec = mcpq_engine.form_spec()
    assert spec["instrument"] == "MCPQ-R"
    assert len(spec["required_items"]) == 26
    assert len(spec["dimensions"]) == 5
    assert spec["items"][0]["prompt_zh"]


def test_mcpq_mid_scores(mcpq_engine):
    answers = {i: 3 for i in mcpq_engine.required_items()}
    report = mcpq_engine.score(answers)
    assert report["instrument"] == "MCPQ-R"
    assert len(report["dimensions"]) == 5
    labels = {d["label_zh"] for d in report["dimensions"]}
    assert labels == {"活力", "主动性", "训练专注", "亲和力", "敏感度"}
    assert report["owner_report"]["headline_zh"] == "MCPQ-R 性格画像"
    assert "MCPQ-R" in report["owner_report"]["full_zh"]


def test_mcpq_high_training_focus(mcpq_engine):
    answers = {i: 3 for i in mcpq_engine.required_items()}
    for i in range(12, 18):
        answers[i] = 6
    report = mcpq_engine.score(answers)
    training = next(d for d in report["dimensions"] if d["id"] == "training_focus")
    assert training["score_pct"] >= 90
    assert training["title_zh"] == "跟得上、学得快"


def test_mcpq_endpoint(api_client):
    form = api_client.get("/v1/personality/mcpq")
    assert form.status_code == 200
    body = form.json()
    assert body["instrument"] == "MCPQ-R"
    answers = {str(i): 3 for i in range(1, 27)}
    scored = api_client.post("/v1/personality/mcpq/score", json={"answers": answers})
    assert scored.status_code == 200
    report = scored.json()
    assert report["instrument"] == "MCPQ-R"
    assert len(report["dimensions"]) == 5
    assert report["owner_report"]["sections"]
    bad = api_client.post("/v1/personality/mcpq/score", json={"answers": {"1": 9}})
    assert bad.status_code == 422
