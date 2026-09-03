# Eval suite

- `cases.json` — triage + Module B/C retrieval regression cases  
- `last_report.json` — Lab extractive pipeline report (gitignored)  
- `animalink_retrieval_report.json` — AnimaLink pgvector retrieval report (gitignored)

```bash
# Lab local extractive pipeline (needs HF cache / sentence-transformers)
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py

# AnimaLink cloud retrieval after OpenAI re-embed (needs ANIMALINK_* + OPENAI_API_KEY)
python scripts/22_eval_animalink_retrieval.py

# Module B/C only (Lab pipeline)
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py --group module_bc

# pytest
pytest tests/test_eval_suite.py -q
```

Module B/C groups expect `sources_module_must_include_any` / `sources_source_must_include_any`
(C-BARQ, AKC, AAHA, MCPQ-R, PetTalk).
