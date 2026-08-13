# Eval suite

- `cases.json` — triage + Module B/C retrieval regression cases  
- `last_report.json` — latest run (gitignored)

```bash
# all cases
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py

# Module B/C only
HF_HUB_OFFLINE=1 python scripts/09_run_eval.py --group module_bc

# pytest
pytest tests/test_eval_suite.py -q
```

Module B/C groups expect `sources_module_must_include_any` / `sources_source_must_include_any`
(C-BARQ, AKC, AAHA, MCPQ-R, PetTalk).
