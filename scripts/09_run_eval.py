#!/usr/bin/env python3
"""Run fixed triage eval cases (deterministic extractive answers by default).

Usage:
  python scripts/09_run_eval.py
  python scripts/09_run_eval.py --cases evals/cases.json --json
  python scripts/09_run_eval.py --with-llm   # allow OpenAI if key is set
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CASES = os.path.join(PROJECT_ROOT, "evals", "cases.json")
DEFAULT_REPORT = os.path.join(PROJECT_ROOT, "evals", "last_report.json")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("anima_eval")


def _load_script(module_name: str, filename: str) -> Any:
    path = os.path.join(PROJECT_ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_cases(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"No cases found in {path}")
    return cases


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    hay = text or ""
    hay_l = hay.lower()
    for needle in needles:
        if not needle:
            continue
        if needle.lower() in hay_l or needle in hay:
            return True
    return False


def _request_kwargs(raw: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "question",
        "species",
        "size",
        "heart_rate_bpm",
        "crt_seconds",
        "rectal_temp_f",
        "rectal_temp_c",
        "map_mmhg",
        "symptoms",
        "chief_complaint",
        "top_k",
    }
    return {k: v for k, v in raw.items() if k in allowed and v is not None}


@dataclass
class CheckFailure:
    check: str
    detail: str


@dataclass
class CaseResult:
    id: str
    group: str
    passed: bool
    failures: List[CheckFailure] = field(default_factory=list)
    red_light_status: Optional[str] = None
    intercepted: Optional[bool] = None
    model_used: Optional[str] = None
    source_count: int = 0
    elapsed_ms: float = 0.0
    answer_zh_preview: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "group": self.group,
            "passed": self.passed,
            "failures": [asdict(f) for f in self.failures],
            "red_light_status": self.red_light_status,
            "intercepted": self.intercepted,
            "model_used": self.model_used,
            "source_count": self.source_count,
            "elapsed_ms": self.elapsed_ms,
            "answer_zh_preview": self.answer_zh_preview,
        }


def evaluate_case(pipeline: Any, rag_mod: Any, case: Dict[str, Any]) -> CaseResult:
    case_id = str(case.get("id") or "unnamed")
    group = str(case.get("group") or "")
    expect = case.get("expect") or {}
    request = rag_mod.RAGQueryRequest(**_request_kwargs(case.get("request") or {}))
    response = pipeline.query(request)

    answer_zh = response.answer_zh or response.answer or ""
    sources = response.sources or []
    source_blob = " ".join(
        (s.get("content") or "") + " " + str((s.get("metadata") or {}))
        for s in sources
    )

    failures: List[CheckFailure] = []

    expected_status = expect.get("red_light_status")
    if expected_status is not None:
        allowed = {str(s) for s in _as_list(expected_status)}
        actual = str(response.red_light_status)
        if actual not in allowed:
            failures.append(
                CheckFailure(
                    "red_light_status",
                    f"expected one of {sorted(allowed)}, got {actual}",
                )
            )

    if "intercepted" in expect and bool(response.intercepted) != bool(
        expect["intercepted"]
    ):
        failures.append(
            CheckFailure(
                "intercepted",
                f"expected {expect['intercepted']}, got {response.intercepted}",
            )
        )

    if "model_used" in expect and response.model_used != expect["model_used"]:
        failures.append(
            CheckFailure(
                "model_used",
                f"expected {expect['model_used']}, got {response.model_used}",
            )
        )

    min_sources = expect.get("min_sources")
    if min_sources is not None and len(sources) < int(min_sources):
        failures.append(
            CheckFailure(
                "min_sources",
                f"expected >= {min_sources}, got {len(sources)}",
            )
        )

    max_sources = expect.get("max_sources")
    if max_sources is not None and len(sources) > int(max_sources):
        failures.append(
            CheckFailure(
                "max_sources",
                f"expected <= {max_sources}, got {len(sources)}",
            )
        )

    must_any = _as_list(expect.get("answer_zh_must_contain_any"))
    if must_any and not _contains_any(answer_zh, must_any):
        failures.append(
            CheckFailure(
                "answer_zh_must_contain_any",
                f"none of {must_any} found in answer_zh",
            )
        )

    must_not = _as_list(expect.get("answer_zh_must_not_contain_any"))
    for needle in must_not:
        if _contains_any(answer_zh, [needle]):
            failures.append(
                CheckFailure(
                    "answer_zh_must_not_contain_any",
                    f"forbidden phrase found: {needle!r}",
                )
            )

    source_needles = _as_list(expect.get("sources_content_must_match_any"))
    if source_needles and not _contains_any(source_blob, source_needles):
        failures.append(
            CheckFailure(
                "sources_content_must_match_any",
                f"none of {source_needles} found in sources",
            )
        )

    meta_sources = [
        str((s.get("metadata") or {}).get("source") or "") for s in sources
    ]
    meta_modules = [
        str((s.get("metadata") or {}).get("module") or "") for s in sources
    ]

    must_src = _as_list(expect.get("sources_source_must_include_any"))
    if must_src and not any(
        any(needle.lower() == src.lower() for needle in must_src) for src in meta_sources
    ):
        failures.append(
            CheckFailure(
                "sources_source_must_include_any",
                f"expected one of {must_src} in source metadata, got {meta_sources}",
            )
        )

    must_mod = _as_list(expect.get("sources_module_must_include_any"))
    if must_mod and not any(
        any(needle.upper() == mod.upper() for needle in must_mod)
        for mod in meta_modules
    ):
        failures.append(
            CheckFailure(
                "sources_module_must_include_any",
                f"expected one of {must_mod} in module metadata, got {meta_modules}",
            )
        )

    extracted = list(getattr(response, "extracted_symptoms", None) or [])
    extracted_blob = " | ".join(extracted)

    must_sym = _as_list(expect.get("extracted_symptoms_must_contain_any"))
    if must_sym and not _contains_any(extracted_blob, must_sym):
        failures.append(
            CheckFailure(
                "extracted_symptoms_must_contain_any",
                f"none of {must_sym} found in extracted_symptoms={extracted!r}",
            )
        )

    forbid_sym = _as_list(expect.get("extracted_symptoms_must_not_contain_any"))
    for needle in forbid_sym:
        # Exact-tag ban (e.g. bare「吃了」) — substring ban would false-positive「吃了巧克力」.
        if any(tag == needle for tag in extracted):
            failures.append(
                CheckFailure(
                    "extracted_symptoms_must_not_contain_any",
                    f"forbidden exact tag {needle!r} in extracted_symptoms={extracted!r}",
                )
            )

    max_elapsed = expect.get("max_elapsed_ms")
    if max_elapsed is not None and float(response.elapsed_ms) > float(max_elapsed):
        failures.append(
            CheckFailure(
                "max_elapsed_ms",
                f"elapsed {response.elapsed_ms:.2f}ms > {max_elapsed}ms",
            )
        )

    preview = answer_zh.replace("\n", " ").strip()
    if len(preview) > 160:
        preview = preview[:157] + "..."

    return CaseResult(
        id=case_id,
        group=group,
        passed=not failures,
        failures=failures,
        red_light_status=response.red_light_status,
        intercepted=response.intercepted,
        model_used=response.model_used,
        source_count=len(sources),
        elapsed_ms=float(response.elapsed_ms),
        answer_zh_preview=preview,
    )


def build_pipeline(with_llm: bool = False) -> Tuple[Any, Any]:
    embed_mod = _load_script("eval_embed", "05_embed_merck.py")
    rag_mod = _load_script("eval_rag", "06_rag_query.py")
    store = embed_mod.MerckVectorStore()
    store.load()
    pipeline = rag_mod.AnimaRAGPipeline(vector_store=store)
    if not with_llm:
        pipeline.openai_api_key = ""
        pipeline.llm_enabled = False
        logger.info("Eval mode: extractive answers (LLM disabled)")
    elif pipeline.llm_enabled:
        logger.info("Eval mode: OpenAI enabled (%s)", pipeline.openai_model)
    else:
        logger.info("Eval mode: --with-llm requested but OPENAI_API_KEY missing")
    return pipeline, rag_mod


def run_eval(
    cases_path: str = DEFAULT_CASES,
    with_llm: bool = False,
    report_path: Optional[str] = DEFAULT_REPORT,
    group: Optional[str] = None,
) -> Dict[str, Any]:
    cases = load_cases(cases_path)
    if group:
        cases = [c for c in cases if str(c.get("group") or "") == group]
        if not cases:
            raise ValueError(f"No cases with group={group!r} in {cases_path}")
    pipeline, rag_mod = build_pipeline(with_llm=with_llm)
    results = [evaluate_case(pipeline, rag_mod, case) for case in cases]
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "cases_path": cases_path,
        "group_filter": group,
        "with_llm": with_llm,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "results": [r.to_dict() for r in results],
    }
    if report_path:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        logger.info("Wrote report → %s", report_path)
    return report


def _print_human(report: Dict[str, Any]) -> None:
    filt = report.get("group_filter")
    filt_note = f" group={filt}" if filt else ""
    print(
        f"\nEval{filt_note}: {report['passed']}/{report['total']} passed"
        f"  (LLM={'on' if report.get('with_llm') else 'off'})\n"
    )
    for item in report["results"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(
            f"  [{mark}] {item['id']:28s}  "
            f"status={item['red_light_status']}  "
            f"intercepted={item['intercepted']}  "
            f"sources={item['source_count']}  "
            f"{item['elapsed_ms']:.1f}ms"
        )
        for failure in item.get("failures") or []:
            print(f"         · {failure['check']}: {failure['detail']}")
    print()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run ANIMA triage eval suite")
    parser.add_argument("--cases", default=DEFAULT_CASES, help="Path to cases JSON")
    parser.add_argument(
        "--report",
        default=DEFAULT_REPORT,
        help="Write JSON report here (empty string to skip)",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Allow OpenAI answers when OPENAI_API_KEY is set",
    )
    parser.add_argument(
        "--group",
        default=None,
        help="Only run cases with this group (e.g. module_bc)",
    )
    parser.add_argument("--json", action="store_true", help="Print report JSON only")
    args = parser.parse_args(argv)

    report_path = args.report or None
    report = run_eval(
        cases_path=args.cases,
        with_llm=args.with_llm,
        report_path=report_path,
        group=args.group,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
