"""Module B: MCPQ-R personality scoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCPQ_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "module_b_behavior"
    / "cbarq_mcpq_r"
    / "related_instruments"
    / "mcpq_r_blank_form.json"
)
NORMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "module_b_behavior"
    / "cbarq_mcpq_r"
    / "norms_and_scoring.json"
)

DIM_COPY: Dict[str, Dict[str, str]] = {
    "extraversion": {
        "label_zh": "活力",
        "low_title_zh": "安静",
        "mid_title_zh": "收放还算稳",
        "high_title_zh": "精力旺、容易上头",
        "low_zh": "平常不太自己找事做，活动量需求没有那么高，节奏比较稳。",
        "mid_zh": "会玩也会停，出门和在家都还算收得回来。",
        "high_zh": "活动量大，情绪和身体都比较容易一起热起来，需要更明确的开始和结束。",
        "care_zh": "把运动拆成几段，先降温再释放。光靠一直跑，不一定会更稳。",
    },
    "motivation": {
        "label_zh": "主动性",
        "low_title_zh": "随和",
        "mid_title_zh": "有时会自己拿主意",
        "high_title_zh": "很有主见",
        "low_zh": "平常不太会强势争取资源或主导节奏，比较顺着环境走。",
        "mid_zh": "有自己的想法，但多数时候还能跟着你调整。",
        "high_zh": "会自己决定要不要做、怎么做，像是很有自己的计划。",
        "care_zh": "少硬碰，先把规则写清楚。让它知道配合有好处，比重复命令更有效。",
    },
    "training_focus": {
        "label_zh": "训练专注",
        "low_title_zh": "容易走神",
        "mid_title_zh": "简单环境还跟得上",
        "high_title_zh": "跟得上、学得快",
        "low_zh": "环境一复杂就容易飘，学得比较慢，或会了也不太稳。",
        "mid_zh": "在简单环境里还跟得上，难度一拉高就需要你帮它拆小一点。",
        "high_zh": "比较容易把注意力放回你身上，短课通常就能学到重点。",
        "care_zh": "主课放在它还做得到的难度上。先稳成功率，再慢慢加干扰。",
    },
    "amicability": {
        "label_zh": "亲和力",
        "low_title_zh": "有距离感",
        "mid_title_zh": "相处普通",
        "high_title_zh": "好相处",
        "low_zh": "不是坏，只是没那么爱靠近，也不一定喜欢每个对象都来互动。",
        "mid_zh": "熟了会放松，不熟时看对象，整体算中性。",
        "high_zh": "对人和环境通常比较放松，互动门槛低，容易让人觉得好带。",
        "care_zh": "不要因为看起来好相处，就忽略它也需要边界和休息。",
    },
    "neuroticism": {
        "label_zh": "敏感度",
        "low_title_zh": "稳定",
        "mid_title_zh": "有点谨慎",
        "high_title_zh": "敏感谨慎",
        "low_zh": "情绪起伏不大，面对变化通常还撑得住。",
        "mid_zh": "有些情境会紧一点，但多数时候还能恢复。",
        "high_zh": "对变化、压力或不确定感比较敏锐，容易先紧张起来。",
        "care_zh": "先给安全感和退路，再谈训练。太快、太多、太热闹都会让它更难处理。",
    },
}

BANDS = (
    ("0", 20.0, "很低"),
    ("1", 40.0, "偏低"),
    ("2", 60.0, "中间"),
    ("3", 80.0, "偏高"),
    ("4", 101.0, "很高"),
)


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_answers(raw: Mapping[Any, Any]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for key, val in raw.items():
        if val is None or val == "":
            continue
        token = str(key).strip().lower().replace("item_", "").replace("q", "")
        try:
            item = int(token)
            score = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Bad answer {key!r}={val!r}") from exc
        if item < 1 or item > 26:
            raise ValueError(f"MCPQ-R item must be 1–26, got {item}")
        if score < 1 or score > 6:
            raise ValueError(f"Item {item} score must be 1–6, got {score}")
        out[item] = score
    return out


def band_for(pct: float) -> Tuple[str, str]:
    for key, max_exclusive, label_zh in BANDS:
        if pct < max_exclusive:
            return key, label_zh
    return "4", "很高"


class MCPQRPersonality:
    def __init__(
        self,
        blank_form_path: Optional[Path] = None,
        norms_path: Optional[Path] = None,
    ) -> None:
        self.blank_path = Path(blank_form_path or MCPQ_PATH)
        self.norms_path = Path(norms_path or NORMS_PATH)
        self.blank = _load_json(self.blank_path)
        self.norms = _load_json(self.norms_path).get("mcpq_r") or {}
        self.items: List[Dict[str, Any]] = list(self.blank.get("items") or [])
        self.by_id = {int(it["item_no"]): it for it in self.items}
        self.dimensions: List[Dict[str, Any]] = list(self.norms.get("dimensions") or [])

    def required_items(self) -> List[int]:
        return sorted(self.by_id)

    def form_spec(self) -> Dict[str, Any]:
        dims = []
        for dim in self.dimensions:
            copy = DIM_COPY[dim["id"]]
            item_ids = [
                iid
                for iid, item in self.by_id.items()
                if item.get("dimension") == dim["id"]
            ]
            dims.append(
                {
                    "id": dim["id"],
                    "label_zh": copy["label_zh"],
                    "label_en": dim.get("label") or dim["id"],
                    "items": item_ids,
                    "adjectives": dim.get("adjectives") or [],
                    "low_title_zh": copy["low_title_zh"],
                    "mid_title_zh": copy["mid_title_zh"],
                    "high_title_zh": copy["high_title_zh"],
                }
            )
        items = []
        for item in self.items:
            copy = DIM_COPY[item["dimension"]]
            items.append(
                {
                    "id": int(item["item_no"]),
                    "adjective_en": item["adjective"],
                    "dimension": item["dimension"],
                    "dimension_zh": copy["label_zh"],
                    "prompt_zh": f"「{item['adjective']}」像不像这只狗？",
                    "scale_zh": [
                        "1 完全不像",
                        "2 比较不像",
                        "3 有一点像",
                        "4 有点像",
                        "5 很像",
                        "6 非常像",
                    ],
                }
            )
        return {
            "module": "B",
            "instrument": "MCPQ-R",
            "item_scale": {"min": 1, "max": 6},
            "required_items": self.required_items(),
            "instructions_zh": "请按直觉判断每个形容词像不像这只狗，1=完全不像，6=非常像。",
            "not_official_monash_pdf": bool(self.blank.get("not_official_monash_pdf")),
            "gap_note": self.blank.get("gap_note") or "",
            "dimensions": dims,
            "items": items,
        }

    def score(self, answers_raw: Mapping[Any, Any]) -> Dict[str, Any]:
        answers = parse_answers(answers_raw)
        scored_dims = []
        for dim in self.dimensions:
            dim_id = dim["id"]
            item_ids = [
                iid
                for iid, item in self.by_id.items()
                if item.get("dimension") == dim_id
            ]
            missing = [iid for iid in item_ids if iid not in answers]
            if missing:
                raise ValueError(f"MCPQ-R dimension {dim_id} missing items: {missing}")
            raw = sum(float(answers[i]) for i in item_ids)
            pct = 100.0 * raw / (len(item_ids) * 6.0)
            band, band_zh = band_for(pct)
            copy = DIM_COPY[dim_id]
            if pct < 40:
                title = copy["low_title_zh"]
                summary = copy["low_zh"]
            elif pct >= 60:
                title = copy["high_title_zh"]
                summary = copy["high_zh"]
            else:
                title = copy["mid_title_zh"]
                summary = copy["mid_zh"]
            scored_dims.append(
                {
                    "id": dim_id,
                    "label_zh": copy["label_zh"],
                    "label_en": dim.get("label") or dim_id,
                    "score_pct": round(pct, 1),
                    "score_raw": round(raw, 1),
                    "n_items": len(item_ids),
                    "band": band,
                    "band_zh": band_zh,
                    "title_zh": title,
                    "summary_zh": summary,
                    "care_zh": copy["care_zh"],
                    "adjectives": dim.get("adjectives") or [],
                    "items": item_ids,
                }
            )
        scored_dims.sort(key=lambda d: d["score_pct"], reverse=True)
        profile_zh = self._compose_profile(scored_dims)
        owner_report = self._compose_owner_report(scored_dims)
        return {
            "module": "B",
            "instrument": "MCPQ-R",
            "scoring_method": self.norms.get("scoring", {}).get("method", "POMP"),
            "dimensions": scored_dims,
            "profile_zh": profile_zh,
            "owner_report": owner_report,
            "disclaimer_zh": "MCPQ-R 是性格描述工具，不是医疗诊断。结果适合拿来理解相处与训练风格。",
        }

    def _compose_profile(self, dims: List[Dict[str, Any]]) -> str:
        top = sorted(dims, key=lambda d: abs(float(d["score_pct"]) - 50.0), reverse=True)[:3]
        bits = [f"{d['label_zh']}·{d['title_zh']}" for d in top]
        return "根据这份 MCPQ-R，它比较像：" + "、".join(bits) + "。"

    def _compose_owner_report(self, dims: List[Dict[str, Any]]) -> Dict[str, Any]:
        sections: List[Dict[str, Any]] = []
        bullets = [f"{d['label_zh']}：{d['title_zh']}。{d['summary_zh']}" for d in dims]
        sections.append({"id": "dimensions", "title_zh": "五个重点", "bullets_zh": bullets})
        care = [f"{d['label_zh']}：{d['care_zh']}" for d in dims]
        sections.append({"id": "care", "title_zh": "相处提醒", "bullets_zh": care})
        headline = "MCPQ-R 性格画像"
        summary = self._compose_profile(dims)
        full_parts: List[str] = [headline, summary]
        for sec in sections:
            full_parts.append(f"【{sec['title_zh']}】")
            for b in sec.get("bullets_zh") or []:
                full_parts.append(f"· {b}")
        return {
            "headline_zh": headline,
            "summary_zh": summary,
            "sections": sections,
            "full_zh": "\n\n".join(full_parts),
        }


def demo_answers() -> Dict[int, float]:
    out = {i: 3.0 for i in range(1, 27)}
    for i in range(12, 18):
        out[i] = 6.0
    for i in range(23, 27):
        out[i] = 2.0
    return out


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--form", action="store_true")
    p.add_argument("--demo", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    engine = MCPQRPersonality()
    if args.form:
        print(json.dumps(engine.form_spec(), ensure_ascii=False, indent=2))
    elif args.demo:
        print(json.dumps(engine.score(demo_answers()), ensure_ascii=False, indent=2))
    else:
        raise SystemExit("Pass --form or --demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
