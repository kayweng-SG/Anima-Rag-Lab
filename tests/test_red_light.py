"""Red-Light intercept triage tests."""

import pytest


@pytest.mark.parametrize(
    "label,patient,expected_status,expected_intercept",
    [
        (
            "normal_small_dog",
            {
                "species": "dog",
                "size": "small",
                "heart_rate_bpm": 90,
                "crt_seconds": 1.5,
                "rectal_temp_f": 101.8,
                "chief_complaint": "Mild limping after walk",
            },
            "GREEN",
            False,
        ),
        (
            "dog_tachycardia_crt",
            {
                "species": "dog",
                "size": "large",
                "heart_rate_bpm": 200,
                "crt_seconds": 3.0,
                "symptoms": ["pale gums"],
                "chief_complaint": "Collapse after car ride",
            },
            "RED",
            True,
        ),
        (
            "cat_shock_bradycardia",
            {
                "species": "cat",
                "heart_rate_bpm": 100,
                "crt_seconds": 2.5,
                "chief_complaint": "Found unresponsive, cold paws",
            },
            "RED",
            True,
        ),
        (
            "heat_stroke_severe",
            {
                "species": "dog",
                "heart_rate_bpm": 170,
                "rectal_temp_f": 105.2,
                "chief_complaint": "Heat stroke after hiking, collapse",
            },
            "RED",
            True,
        ),
        (
            "heat_ask_mild",
            {
                "species": "dog",
                "heart_rate_bpm": 120,
                "rectal_temp_f": 102.8,
                "symptoms": ["panting", "drooling"],
                "chief_complaint": "中暑怎么办？散步后喘气、流口水，仍清醒能走",
            },
            "YELLOW",
            False,
        ),
        (
            "heat_question_only",
            {
                "species": "dog",
                "chief_complaint": "中暑怎么办？",
            },
            "YELLOW",
            False,
        ),
        (
            "poisoning",
            {
                "species": "dog",
                "chief_complaint": "Ate rat poison 20 minutes ago, vomiting",
            },
            "RED",
            True,
        ),
        (
            "yellow_pale_gums",
            {
                "species": "dog",
                "heart_rate_bpm": 95,
                "symptoms": ["pale gums", "weakness"],
                "chief_complaint": "Lethargy since morning",
            },
            "YELLOW",
            False,
        ),
    ],
)
def test_red_light_status(
    red_light_mod, red_light, label, patient, expected_status, expected_intercept
):
    PatientVitals = red_light_mod.PatientVitals
    result = red_light.evaluate(PatientVitals(**patient))
    assert result.status.value == expected_status, label
    assert result.intercept is expected_intercept, label


def test_red_light_latency_budget(red_light_mod, red_light):
    PatientVitals = red_light_mod.PatientVitals
    patient = PatientVitals(
        species="dog",
        heart_rate_bpm=200,
        crt_seconds=3.0,
        chief_complaint="Collapse and severe bleeding",
    )
    result = red_light.evaluate(patient)
    assert result.elapsed_ms < red_light.MAX_ELAPSED_MS


def test_red_light_result_schema(red_light_mod, red_light):
    PatientVitals = red_light_mod.PatientVitals
    result = red_light.evaluate(
        PatientVitals(species="dog", heart_rate_bpm=90, chief_complaint="Routine check")
    )
    payload = result.to_dict()
    assert "status" in payload
    assert "alerts" in payload
    assert "elapsed_ms" in payload
    assert isinstance(payload["alerts"], list)


def test_extract_symptom_keywords_from_description(red_light_mod):
    extract = red_light_mod.extract_symptom_keywords
    mild = extract("中暑怎么办？", "散步后喘气、流口水，仍清醒能走")
    assert any("中暑" in item for item in mild)
    assert any("喘气" in item or "流口水" in item for item in mild)

    severe = extract("中暑怎么办？狗已经站不起来了", "Heat stroke after hiking, collapse")
    assert any("collapse" in item.lower() or "站不起来" in item for item in severe)
    assert any("heat" in item.lower() or "中暑" in item for item in severe)

    poison = extract("狗狗中毒怎么办？", "Ate rat poison, vomiting")
    assert any("poison" in item.lower() or "中毒" in item for item in poison)
    assert any("vomit" in item.lower() for item in poison)

    chocolate = extract("小狗吃了巧克力，怎么办？")
    assert any("巧克力" in item for item in chocolate)
    assert "吃了" not in chocolate  # bare ingestion verb must not be the chip

    chocolate_ok = extract("小狗吃了巧克力，精神还行，有点担心。")
    assert any("巧克力" in item for item in chocolate_ok)
    assert any("精神还行" in item for item in chocolate_ok)

def test_chocolate_ingestion_is_red(red_light_mod, red_light):
    PatientVitals = red_light_mod.PatientVitals
    result = red_light.evaluate(
        PatientVitals(
            species="dog",
            size="small",
            chief_complaint="小狗吃了巧克力，精神还行，有点担心。",
        )
    )
    assert result.status.value == "RED"
    assert result.intercept is True
    assert any(a.code == "poisoning" for a in result.alerts)
    assert "中毒" in result.recommendation_zh or "毒物" in result.recommendation_zh


def test_aspca_toxic_plant_red(red_light_mod, red_light):
    PatientVitals = red_light_mod.PatientVitals
    assert len(red_light._toxic_aliases) > 0

    lily = red_light.evaluate(
        PatientVitals(
            species="cat",
            chief_complaint="猫吃了百合叶子，现在在吐",
        )
    )
    assert lily.status.value == "RED"
    assert lily.intercept is True
    assert any(a.code == "aspca_toxic_plant" for a in lily.alerts)

    sago = red_light.evaluate(
        PatientVitals(
            species="dog",
            chief_complaint="Dog chewed sago palm seeds this morning",
        )
    )
    assert sago.status.value == "RED"
    assert any(a.code == "aspca_toxic_plant" for a in sago.alerts)


def test_poison_recommendation_not_overridden_by_hot_vitals(red_light_mod, red_light):
    """UI often keeps prior heatstroke vitals; poison complaint must win the copy."""
    PatientVitals = red_light_mod.PatientVitals
    result = red_light.evaluate(
        PatientVitals(
            species="dog",
            size="large",
            heart_rate_bpm=170,
            rectal_temp_f=105.2,
            chief_complaint="狗狗中毒怎么办？刚才吃了老鼠药，还在呕吐。",
        )
    )
    assert result.status.value == "RED"
    assert any(a.code == "poisoning" for a in result.alerts)
    assert "中毒" in result.recommendation_zh
    assert "中暑" not in result.recommendation_zh
    assert "poison" in result.recommendation_en.lower()
    assert "heat stroke" not in result.recommendation_en.lower()


def test_aspca_ambiguous_plant_needs_ingestion(red_light_mod, red_light):
    PatientVitals = red_light_mod.PatientVitals
    result = red_light.evaluate(
        PatientVitals(
            species="dog",
            heart_rate_bpm=90,
            chief_complaint="We have an apple tree in the backyard",
        )
    )
    assert not any(a.code == "aspca_toxic_plant" for a in result.alerts)
