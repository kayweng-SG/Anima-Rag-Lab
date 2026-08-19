"""Module B: C-BARQ42 personality scoring."""


def test_all_mid_scores_typical(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    report = cbarq_engine.score(answers)
    assert report["skipped_subscales"] == []
    assert len(report["subscales"]) == 14
    assert all(row["band"] == "2" for row in report["subscales"])
    assert "性格" in report["disclaimer_zh"] or "教育" in report["disclaimer_zh"]
    assert report["care_needs_zh"]


def test_reverse_items_flip_training_difficulty(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    answers[27] = 4
    answers[28] = 4
    answers[29] = 0
    report = cbarq_engine.score(answers)
    training = next(r for r in report["subscales"] if r["id"] == "training_difficulty")
    assert training["score"] == 0.0
    assert training["band"] == "0"


def test_high_energy_gets_exercise_care(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    answers[39] = 4
    answers[40] = 4
    report = cbarq_engine.score(answers)
    energy = next(r for r in report["subscales"] if r["id"] == "energy")
    assert energy["band"] == "4"
    assert "精力很大" in energy["snapshot_zh"] or "拆家" in energy["snapshot_zh"]
    assert len(energy["care_zh"]) >= 50
    assert "狂奔" in energy["care_zh"] or "多段" in energy["care_zh"]


def test_missing_items_skip_subscale(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items() if i not in {1, 2}}
    report = cbarq_engine.score(answers)
    skipped_ids = {s["id"] for s in report["skipped_subscales"]}
    scored_ids = {s["id"] for s in report["subscales"]}
    assert "excitability" in skipped_ids
    assert "excitability" not in scored_ids


def test_form_has_colloquial_questions_and_band_contrast(cbarq_engine):
    spec = cbarq_engine.form_spec()
    assert spec["instrument"] == "C-BARQ42"
    excit = next(s for s in spec["subscales"] if s["id"] == "excitability")
    prompts = " ".join(q["prompt_zh"] for q in excit["questions"])
    assert "出门散步" in prompts
    assert "上车" in prompts
    bands = excit["bands_zh"]
    assert len(bands) == 5
    assert len(set(bands.values())) == 5
    assert "没反应" in bands["0"] or "躺" in bands["0"]
    assert "炸" in bands["4"]


def test_personality_endpoints(api_client, cbarq_engine):
    form = api_client.get("/v1/personality/cbarq")
    assert form.status_code == 200
    body = form.json()
    assert body["api_version"] == "v1"
    assert body["module"] == "B"
    assert body["subscales"][0]["questions"][0]["prompt_zh"]
    answers = {str(i): 2 for i in cbarq_engine.required_items()}
    scored = api_client.post(
        "/v1/personality/cbarq/score", json={"answers": answers}
    )
    assert scored.status_code == 200
    report = scored.json()
    assert len(report["subscales"]) == 14
    assert report["profile_zh"]
    mbti = report["mbti_like"]
    assert mbti["assigned"] is True
    assert mbti["balanced"] is True
    assert mbti["lean_code"] == "ISFJ"
    assert mbti["code"] == "BALANCED"
    assert "mbti_desc_zh" in mbti
    assert len(report["facets"]) == 4
    bad = api_client.post(
        "/v1/personality/cbarq/score", json={"answers": {"1": 9}}
    )
    assert bad.status_code == 422


def test_mid_scores_map_to_isfj(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    report = cbarq_engine.score(answers)
    mbti = report["mbti_like"]
    assert mbti["assigned"] is True
    assert mbti["balanced"] is True
    assert mbti["lean_code"] == "ISFJ"
    assert mbti["code"] == "BALANCED"
    assert mbti["title_zh"] == "均衡陪伴型"
    letters = {a["id"]: a["letter"] for a in mbti["axes"]}
    assert letters == {"EI": "I", "SN": "S", "TF": "F", "JP": "J"}
    facets = {f["facet_id"]: f for f in report["facets"]}
    assert set(facets) == {"social", "engine", "boundary", "cooperation"}
    assert all(f["score"] == 2.0 for f in report["facets"])
    assert all(f["borderline"] for f in report["facets"])


def test_demo_maps_to_enfj(cbarq_engine):
    answers = {i: 2.0 for i in range(1, 42)}
    answers[1] = answers[2] = 4.0
    answers[39] = answers[40] = 4.0
    answers[13] = answers[15] = 0.0
    answers[27] = answers[28] = 4.0
    answers[29] = 0.0
    mbti = cbarq_engine.score(answers)["mbti_like"]
    assert mbti["code"] == "ENFJ"
    assert "mbti_desc_zh" in mbti
    assert mbti["balanced"] is False
    assert mbti["title_zh"] == "领队暖犬"


def test_high_chase_and_train_hard_maps_to_enfp(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    answers[1] = answers[2] = 4  # excitability
    answers[39] = answers[40] = 4  # energy
    answers[13] = answers[15] = 0  # stranger fear
    answers[30] = answers[31] = 4  # chasing
    answers[27] = answers[28] = 0  # reverse → hard to train
    answers[29] = 4
    mbti = cbarq_engine.score(answers)["mbti_like"]
    assert mbti["code"] == "ENFP"
    assert mbti["title_zh"] == "阳光猎手"


def test_missing_subscale_skips_mbti_type(cbarq_engine):
    # Excitability only feeds engine (SN), not social (EI).
    answers = {i: 2 for i in cbarq_engine.required_items() if i not in {1, 2}}
    report = cbarq_engine.score(answers)
    assert report["mbti_like"]["assigned"] is False
    assert "SN" in report["mbti_like"]["missing_axes"]
    assert "EI" not in report["mbti_like"]["missing_axes"]
    skipped = {s["id"] for s in report["skipped_facets"]}
    scored = {f["facet_id"] for f in report["facets"]}
    assert "engine" in skipped
    assert "social" in scored
    assert "engine" not in scored


def test_scheme_a_energy_moves_n_not_e(cbarq_engine):
    answers = {i: 2 for i in cbarq_engine.required_items()}
    answers[39] = answers[40] = 4  # energy only
    report = cbarq_engine.score(answers)
    mbti = report["mbti_like"]
    letters = {a["id"]: a["letter"] for a in mbti["axes"]}
    assert letters["EI"] == "I"
    assert letters["SN"] == "N"
    assert mbti["code"] == "INFJ"
    assert mbti["balanced"] is False
    assert "mbti_desc_zh" in mbti
    facets = {f["facet_id"]: f for f in report["facets"]}
    assert facets["social"]["letter"] == "I"
    assert facets["engine"]["letter"] == "N"
    ei_terms = next(a for a in mbti["axes"] if a["id"] == "EI")["terms"]
    assert "energy" not in {t["subscale"] for t in ei_terms}
    assert "excitability" not in {t["subscale"] for t in ei_terms}


def test_scheme_a_axes_are_exclusive(cbarq_engine):
    spec = cbarq_engine.form_spec()["mbti_like"]
    seen = []
    for axis in spec["axes"]:
        for term in axis["terms"]:
            sid = term["subscale"]
            assert sid not in seen, f"{sid} appears on more than one axis"
            seen.append(sid)
    assert set(seen) == {
        "attachment_attention_seeking",
        "stranger_directed_fear",
        "dog_directed_fear",
        "nonsocial_fear",
        "chasing",
        "energy",
        "excitability",
        "stranger_directed_aggression",
        "owner_directed_aggression",
        "dog_directed_aggression",
        "familiar_dog_aggression",
        "training_difficulty",
        "touch_sensitivity",
    }


def test_fear_block_mirrors_aggression_block(cbarq_engine):
    """三种怕整块进 EI；四种攻击整块进 TF — 对称，不拆进 J/P。"""
    axes = {a["id"]: a for a in cbarq_engine.form_spec()["mbti_like"]["axes"]}
    ei = {t["subscale"] for t in axes["EI"]["terms"]}
    tf = {t["subscale"] for t in axes["TF"]["terms"]}
    jp = {t["subscale"] for t in axes["JP"]["terms"]}
    fears = {
        "stranger_directed_fear",
        "dog_directed_fear",
        "nonsocial_fear",
    }
    aggs = {
        "stranger_directed_aggression",
        "owner_directed_aggression",
        "dog_directed_aggression",
        "familiar_dog_aggression",
    }
    assert fears <= ei
    assert aggs == tf
    assert fears.isdisjoint(jp)
    assert all(
        t.get("invert")
        for t in axes["EI"]["terms"]
        if t["subscale"] in fears
    )


def test_form_lists_sixteen_mbti_types(cbarq_engine):
    spec = cbarq_engine.form_spec()
    codes = [t["code"] for t in spec["mbti_like"]["types"]]
    assert len(codes) == 16
    assert "ESFJ" in codes
    assert spec["mbti_like"]["analogical"] is True
    assert spec["layers"]["L2"] == "facets"
    assert spec["mbti_like"]["derived_from"] == "facets"
    facet_ids = [f["id"] for f in spec["facets"]]
    assert facet_ids == ["social", "engine", "boundary", "cooperation"]
    assert spec["mbti_like"]["balanced_type"]["title_zh"] == "均衡陪伴型"
    labels = [f["label_zh"] for f in spec["facets"]]
    assert "熟不熟得起来" in labels
    assert "精力" in labels
    for f in spec["facets"]:
        for word in ("外放", "扫描", "亲和", "有序", "示威"):
            assert word not in (f.get("pole_low_zh") or "")
            assert word not in (f.get("pole_high_zh") or "")
            assert word not in (f.get("label_zh") or "")


def test_owner_report_is_three_dimensional(cbarq_engine):
    answers = {i: 2.0 for i in range(1, 42)}
    answers[1] = answers[2] = 4.0
    answers[39] = answers[40] = 4.0
    answers[13] = answers[15] = 0.0
    answers[27] = answers[28] = 4.0
    answers[29] = 0.0
    report = cbarq_engine.score(answers)
    mbti = report["mbti_like"]
    assert len(mbti["personality_zh"]) >= 80
    assert len(mbti["traits_zh"]) >= 4
    assert mbti["with_people_zh"] and mbti["training_zh"] and mbti["dont_zh"]
    owner = report["owner_report"]
    ids = [s["id"] for s in owner["sections"]]
    for need in ("personality", "traits", "people", "dogs", "home", "walk", "training", "dont"):
        assert need in ids
    assert "领队暖犬" in owner["headline_zh"]
    assert "看我" in owner["full_zh"]
    facet_text = "\n".join(
        s.get("body_zh", "") + "\n".join(s.get("bullets_zh") or [])
        for s in owner["sections"]
        if s["id"] == "facets"
    )
    for bad in ("偏外放", "偏扫描", "偏亲和", "偏有序", "外放 / 内收", "眼前 / 扫描", "示威"):
        assert bad not in facet_text
    assert "熟不熟得起来" in facet_text
    assert "精力" in facet_text
    assert "见谁都热" in facet_text
    facets = report["facets"]
    jargon = ("外放", "内收", "扫描", "亲和", "有序", "随性", "示威", "引擎")
    for f in facets:
        assert f.get("owner_label_zh")
        blob = " ".join(
            str(f.get(k) or "")
            for k in (
                "label_zh",
                "facet_zh",
                "owner_label_zh",
                "owner_title_zh",
                "owner_summary_zh",
                "pole_short_zh",
            )
        )
        for word in jargon:
            assert word not in blob, (f["facet_id"], word, blob)
    portraits = cbarq_engine.mbti["types"]
    assert len(portraits) == 16
    for code, row in portraits.items():
        assert len(row["personality_zh"]) >= 80, code
        assert row["with_people_zh"] and row["home_zh"]
