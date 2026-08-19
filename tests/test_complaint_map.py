"""Complaint → clinical term map tests (Task 0.3)."""

import os

MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "triage_tree",
    "complaint_clinical_map.json",
)
CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "processed",
    "complaint_clinical_map.csv",
)


def test_complaint_map_files_exist():
    assert os.path.isfile(MAP_PATH), "Run: python scripts/11_build_complaint_map.py"
    assert os.path.isfile(CSV_PATH)


def test_complaint_map_includes_kaggle_source():
    import json

    with open(MAP_PATH, encoding="utf-8") as fh:
        payload = json.load(fh)
    sources = payload.get("sources") or []
    assert any(str(s).startswith("kaggle:") for s in sources), sources
    assert payload.get("entry_count", 0) >= 100


def test_expand_yellow_vomit_zh(rag_mod):
    terms = rag_mod.expand_complaint_to_clinical("小狗吐黄水了，怎么办？")
    joined = " ".join(terms).lower()
    assert terms
    assert "bile" in joined or "bilious" in joined or "gastro" in joined


def test_expand_scratching_en(rag_mod):
    terms = rag_mod.expand_complaint_to_clinical(
        "My dog keeps scratching and has hair loss"
    )
    joined = " ".join(terms).lower()
    assert "pruritus" in joined or "dermatitis" in joined or "alopecia" in joined


def test_retrieval_module_a_vs_b(rag_mod):
    assert rag_mod.retrieval_module_for("小狗正常心率是多少？") == "A"
    assert rag_mod.retrieval_module_for("狗吃了巧克力怎么办") == "A"
    assert rag_mod.retrieval_module_for("C-BARQ excitability 怎么计分？") == "B"
    assert rag_mod.retrieval_module_for("用问卷判断宠物性格") == "B"
    assert rag_mod.retrieval_module_for("AAHA senior cat life stage") == "C"
    assert rag_mod.retrieval_module_for("比熊犬常见疾病泪痕皮肤敏感怎么照顾？") == "C"


def test_pipeline_uses_clinical_expansion(rag_mod, rag_pipeline):
    RAGQueryRequest = rag_mod.RAGQueryRequest
    req = RAGQueryRequest(question="狗狗吐黄水怎么办？", species="dog")
    result = rag_pipeline.query(req)
    # Should not be forced RED solely by this digestive complaint.
    assert result.red_light_status in {"GREEN", "YELLOW"}
    q = (result.retrieval_query or "").lower()
    assert any(tok in q for tok in ("bile", "bilious", "gastro", "vomit"))
