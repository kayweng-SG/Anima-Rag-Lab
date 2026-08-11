"""Full RAG pipeline integration tests."""


def test_pipeline_green_with_sources(rag_mod, rag_pipeline):
    RAGQueryRequest = rag_mod.RAGQueryRequest
    result = rag_pipeline.query(
        RAGQueryRequest(
            question="What is normal heart rate for a small dog?",
            species="dog",
            size="small",
            heart_rate_bpm=95,
        )
    )
    assert result.intercepted is False
    assert result.red_light_status == "GREEN"
    assert len(result.sources) > 0
    assert result.answer_zh
    assert any("\u4e00" <= ch <= "\u9fff" for ch in result.answer_zh)
    assert "Numeric metric:" not in result.answer_zh


def test_pipeline_offtopic_not_heart_rate(rag_mod, rag_pipeline):
    RAGQueryRequest = rag_mod.RAGQueryRequest
    result = rag_pipeline.query(
        RAGQueryRequest(
            question="一直舔脚怎么办？",
            species="dog",
            size="small",
            heart_rate_bpm=95,
            rectal_temp_f=101.8,
        )
    )
    assert result.intercepted is False
    assert "70–120" not in result.answer_zh
    # Should stay on skin/itch topic — not dump vital-sign heart-rate tables.
    assert "心率参考范围" not in result.answer_zh


def test_pipeline_red_skips_retrieval(rag_mod, rag_pipeline):
    RAGQueryRequest = rag_mod.RAGQueryRequest
    result = rag_pipeline.query(
        RAGQueryRequest(
            question="Heat stroke first aid",
            species="dog",
            rectal_temp_f=105.2,
            chief_complaint="Heat stroke collapse",
        )
    )
    assert result.intercepted is True
    assert result.red_light_status == "RED"
    assert result.sources == []
    assert result.model_used == "red_light_intercept"


def test_format_status_line_break():
    import importlib.util
    import os
    import sys

    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "scripts", "06_rag_query.py"
    )
    spec = importlib.util.spec_from_file_location("rag_format_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rag_format_test"] = mod
    spec.loader.exec_module(mod)

    formatted = mod._format_bilingual_answer(
        "GREEN — 未见立即红灯触发，可进行常规知识库分诊。",
        "GREEN：小狗一直舔脚可能是过敏。建议观察。",
        lang="zh",
    )
    lines = formatted.splitlines()
    assert lines[0] == "分诊结论：GREEN"
    assert "\n\n" in formatted or len(lines) >= 3
    assert "可能是过敏" in formatted or "舔脚" in formatted or "未见立即红灯" in formatted


def test_pipeline_elapsed_reasonable(rag_mod, rag_pipeline):
    RAGQueryRequest = rag_mod.RAGQueryRequest
    result = rag_pipeline.query(
        RAGQueryRequest(
            question="How is poisoning treated?",
            species="dog",
            chief_complaint="Ate rat poison",
        )
    )
    assert result.elapsed_ms < 5000
