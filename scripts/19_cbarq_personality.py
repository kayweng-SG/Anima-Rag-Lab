#!/usr/bin/env python3
"""C-BARQ42 personality scoring (Module B).

Questionnaire answers → 14 subscale means → banded personality + care needs
→ analogical 16-type (MBTI-like) layer for product UX.
Colloquial Chinese prompts are paraphrases of the 2018 short form situations.

Usage:
  python scripts/19_cbarq_personality.py --demo
  python scripts/19_cbarq_personality.py --answers path/to/answers.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cbarq_personality")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NORMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "module_b_behavior"
    / "cbarq_mcpq_r"
    / "norms_and_scoring.json"
)
COPY_PATH = (
    PROJECT_ROOT / "data" / "processed" / "module_b" / "cbarq42_profile_copy.json"
)
ITEMS_PATH = PROJECT_ROOT / "data" / "processed" / "module_b" / "cbarq42_items.json"
MBTI_PATH = PROJECT_ROOT / "data" / "processed" / "module_b" / "cbarq42_mbti_types.json"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_answers(raw: Mapping[Any, Any]) -> Dict[int, float]:
    """Accept {1: 2}, {"1": 2}, {"item_1": 2}."""
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
        if item < 1 or item > 42:
            raise ValueError(f"C-BARQ42 item must be 1–42, got {item}")
        if score < 0 or score > 4:
            raise ValueError(f"Item {item} score must be 0–4, got {score}")
        out[item] = score
    return out


TYPE_COPY_KEYS = (
    "summary_zh",
    "personality_zh",
    "care_zh",
    "traits_zh",
    "with_people_zh",
    "with_dogs_zh",
    "home_zh",
    "walk_zh",
    "training_zh",
    "dont_zh",
    "watch_zh",
)


def band_for(score: float, bands: Mapping[str, Any]) -> str:
    """Map 0–4 mean onto five questionnaire grades 0..4."""
    ordered = sorted(bands.keys(), key=lambda k: float(bands[k]["max_exclusive"]))
    for key in ordered:
        if score < float(bands[key]["max_exclusive"]):
            return str(key)
    return str(ordered[-1])


class CBarqPersonality:
    """Score C-BARQ42 and attach Lab personality / care copy."""

    def __init__(
        self,
        norms_path: Optional[Path] = None,
        copy_path: Optional[Path] = None,
        items_path: Optional[Path] = None,
        mbti_path: Optional[Path] = None,
    ) -> None:
        self.norms_path = Path(norms_path or NORMS_PATH)
        self.copy_path = Path(copy_path or COPY_PATH)
        self.items_path = Path(items_path or ITEMS_PATH)
        self.mbti_path = Path(mbti_path or MBTI_PATH)
        self.norms = _load_json(self.norms_path)
        self.copy = _load_json(self.copy_path)
        self.items_doc = _load_json(self.items_path)
        self.mbti = _load_json(self.mbti_path)
        short = (self.norms.get("cbarq") or {}).get("short_42") or {}
        self.subscales: List[Dict[str, Any]] = list(short.get("subscales") or [])
        self.reverse_items = {int(x) for x in (short.get("reverse_code_items") or [])}

    def required_items(self) -> List[int]:
        items: set[int] = set()
        for sub in self.subscales:
            items.update(int(i) for i in (sub.get("items") or []))
        return sorted(items)

    def form_spec(self) -> Dict[str, Any]:
        copy_subs = self.copy.get("subscales") or {}
        anchors = self.items_doc.get("anchors") or {}
        item_by_id = {int(it["id"]): it for it in (self.items_doc.get("items") or [])}
        groups = []
        for sub in self.subscales:
            sid = sub["id"]
            meta = copy_subs.get(sid) or {}
            item_ids = [int(i) for i in (sub.get("items") or [])]
            questions = []
            for iid in item_ids:
                it = item_by_id.get(iid) or {}
                anchor = anchors.get(it.get("anchor") or "") or {}
                questions.append(
                    {
                        "id": iid,
                        "prompt_zh": it.get("prompt_zh") or f"第 {iid} 题",
                        "scale_zh": anchor.get("zh") or [],
                        "hint_zh": anchor.get("prompt_zh") or "",
                        "reverse": bool(it.get("reverse") or iid in self.reverse_items),
                    }
                )
            groups.append(
                {
                    "id": sid,
                    "label_zh": meta.get("label_zh") or sid,
                    "label_en": meta.get("label_en") or sub.get("label") or sid,
                    "ask_zh": meta.get("ask_zh") or "",
                    "items": item_ids,
                    "questions": questions,
                    "reverse_items": sorted(i for i in item_ids if i in self.reverse_items),
                    "bands_zh": {
                        key: (meta.get(key) or {}).get("snapshot_zh")
                        for key in ("0", "1", "2", "3", "4")
                    },
                }
            )
        misc = [
            {
                "id": int(it["id"]),
                "prompt_zh": it.get("prompt_zh"),
                "scale_zh": (anchors.get(it.get("anchor") or "") or {}).get("zh") or [],
            }
            for it in (self.items_doc.get("items") or [])
            if it.get("section") == "misc"
        ]
        return {
            "module": "B",
            "instrument": "C-BARQ42",
            "item_scale": {"min": 0, "max": 4},
            "anchors": anchors,
            "required_items": self.required_items(),
            "reverse_code_items": sorted(self.reverse_items),
            "subscales": groups,
            "misc_questions": misc,
            "layers": {
                "L1": "subscales",
                "L2": "facets",
                "L3": "mbti_like",
                "L1_zh": "14 维分量表（主报告）",
                "L2_zh": "日常四个重点（摘要）",
                "L3_zh": "16 型贴纸（可选；由面向二分派生）",
            },
            "facets": self._facet_form_spec(),
            "disclaimer_zh": self.copy.get("disclaimer_zh"),
            "disclaimer_en": self.copy.get("disclaimer_en"),
            "note": self.items_doc.get("note"),
            "mbti_like": self._mbti_form_spec(),
        }

    def _item_value(self, item: int, answers: Mapping[int, float]) -> float:
        raw = float(answers[item])
        if item in self.reverse_items:
            return 4.0 - raw
        return raw

    def score(self, answers_raw: Mapping[Any, Any]) -> Dict[str, Any]:
        answers = parse_answers(answers_raw)
        bands = self.copy["bands"]
        copy_subs = self.copy.get("subscales") or {}
        scored: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        care_zh: List[str] = []
        care_en: List[str] = []

        for sub in self.subscales:
            sid = sub["id"]
            items = [int(i) for i in (sub.get("items") or [])]
            missing = [i for i in items if i not in answers]
            meta = copy_subs.get(sid) or {}
            label_zh = meta.get("label_zh") or sid
            label_en = meta.get("label_en") or sid
            if missing:
                skipped.append(
                    {
                        "id": sid,
                        "label_zh": label_zh,
                        "label_en": label_en,
                        "missing_items": missing,
                    }
                )
                continue
            values = [self._item_value(i, answers) for i in items]
            mean = sum(values) / len(values)
            band = band_for(mean, bands)
            band_copy = (meta.get(band) or {}) if isinstance(meta.get(band), dict) else {}
            row = {
                "id": sid,
                "label_zh": label_zh,
                "label_en": label_en,
                "score": round(mean, 3),
                "band": band,
                "band_zh": bands[band]["label_zh"],
                "band_en": bands[band]["label_en"],
                "n_items": len(items),
                "snapshot_zh": band_copy.get("snapshot_zh") or "",
                "personality_zh": band_copy.get("personality_zh") or "",
                "personality_en": band_copy.get("personality_en") or "",
                "care_zh": band_copy.get("care_zh") or "",
                "care_en": band_copy.get("care_en") or "",
            }
            scored.append(row)
            if row["care_zh"]:
                care_zh.append(f"{label_zh}·{row['band_zh']}：{row['care_zh']}")
            if row["care_en"]:
                care_en.append(f"{label_en} ({row['band_en']}): {row['care_en']}")

        profile_zh, profile_en = self._compose_profile(scored)
        facets, skipped_facets = self.score_facets(scored)
        mbti_like = self.assign_mbti(facets, skipped_facets)
        owner_report = self.compose_owner_report(scored, facets, mbti_like)
        return {
            "module": "B",
            "instrument": "C-BARQ42",
            "answered_items": len(answers),
            "required_items": len(self.required_items()),
            "subscales": scored,
            "skipped_subscales": skipped,
            "profile_zh": profile_zh,
            "profile_en": profile_en,
            "owner_report": owner_report,
            "care_needs_zh": care_zh,
            "care_needs_en": care_en,
            "facets": facets,
            "skipped_facets": skipped_facets,
            "mbti_like": mbti_like,
            "disclaimer_zh": self.copy.get("disclaimer_zh"),
            "disclaimer_en": self.copy.get("disclaimer_en"),
        }

    def _compose_profile(self, scored: List[Dict[str, Any]]) -> Tuple[str, str]:
        if not scored:
            return (
                "作答不足，无法生成性格画像。请补齐分量表题目后重试。",
                "Not enough answers to build a profile. Fill remaining subscale items.",
            )
        salient: List[Dict[str, Any]] = []
        for row in scored:
            if row["band"] == "2":
                continue
            # training_difficulty high = harder; low = easy — both informative
            salient.append(row)
        salient.sort(key=lambda r: abs(r["score"] - 2.0), reverse=True)
        top = salient[:3] or scored[:2]
        bits_zh = [
            f"{r['label_zh']}·{r['band_zh']}——{r.get('snapshot_zh') or r['personality_zh']}"
            for r in top
        ]
        bits_en = [f"{r['label_en']} {r['band_en']}: {r['personality_en']}" for r in top]
        intro_zh = "根据你填的问卷，它现在比较像："
        intro_en = "From your answers, the clearest traits are:"
        return intro_zh + "".join(f"\n- {b}" for b in bits_zh), intro_en + "".join(
            f"\n- {b}" for b in bits_en
        )

    def _type_fields(self, type_copy: Mapping[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key in TYPE_COPY_KEYS:
            if key in type_copy:
                out[key] = type_copy[key]
        return out

    def compose_owner_report(
        self,
        scored: List[Dict[str, Any]],
        facets: List[Dict[str, Any]],
        mbti: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Owner-facing 3D portrait: personality, traits, living, training."""
        title = str(mbti.get("title_zh") or "这份问卷")
        code = str(mbti.get("code") or "")
        headline = f"{title} · {code}".strip(" ·") if mbti.get("assigned") else "四个重点已出（角色贴纸未出）"
        sections: List[Dict[str, Any]] = []

        def add(sid: str, title_zh: str, body: str = "", bullets: Optional[List[str]] = None) -> None:
            if not (body or bullets):
                return
            item: Dict[str, Any] = {"id": sid, "title_zh": title_zh}
            if body:
                item["body_zh"] = body
            if bullets:
                item["bullets_zh"] = bullets
            sections.append(item)

        add("personality", "个性", str(mbti.get("personality_zh") or ""))
        traits = mbti.get("traits_zh")
        if isinstance(traits, list) and traits:
            add("traits", "特色", bullets=[str(x) for x in traits])

        facet_bits = []
        for f in facets:
            label = f.get("owner_label_zh") or f.get("facet_zh") or f.get("label_zh")
            if f.get("borderline"):
                mid = f.get("owner_mid_zh") or "分数靠近中间，多数情况普通。"
                line = f"{label}：{mid}"
            else:
                title = f.get("owner_title_zh") or ""
                detail = f.get("owner_summary_zh") or ""
                if title and detail:
                    line = f"{label}：{title}。{detail}"
                elif title:
                    line = f"{label}：{title}"
                else:
                    line = f"{label}：{detail}"
            facet_bits.append(line)
        add("facets", "日常里的四个重点", bullets=facet_bits)

        add("people", "和人相处", str(mbti.get("with_people_zh") or ""))
        add("dogs", "和狗相处", str(mbti.get("with_dogs_zh") or ""))
        add("home", "在家日常", str(mbti.get("home_zh") or ""))
        add("walk", "出门与运动", str(mbti.get("walk_zh") or ""))
        add("training", "怎么教", str(mbti.get("training_zh") or ""))
        add("dont", "建议不要", str(mbti.get("dont_zh") or ""))

        watch_bits = []
        if mbti.get("watch_zh"):
            watch_bits.append(str(mbti["watch_zh"]))
        for row in scored:
            if row.get("id") == "separation_related_problems" and row.get("band") in {"3", "4"}:
                watch_bits.append(
                    f"问卷里「你不在时会不会慌」已经到{row.get('band_zh')}。"
                    f"{row.get('care_zh') or row.get('personality_zh') or ''}"
                )
            if "aggression" in str(row.get("id")) and row.get("band") in {"3", "4"}:
                watch_bits.append(
                    f"{row.get('label_zh')}已经到{row.get('band_zh')}。先把距离管好，类型名称不能代替安全。"
                    f"{row.get('care_zh') or ''}"
                )
        add("watch", "什么时候该找专业帮忙", "\n".join(watch_bits))

        salient = []
        ranked = sorted(scored, key=lambda r: abs(float(r.get("score") or 2) - 2.0), reverse=True)
        for row in ranked:
            if row.get("band") == "2":
                continue
            snap = row.get("snapshot_zh") or row.get("personality_zh") or ""
            salient.append(f"{row.get('label_zh')}·{row.get('band_zh')}——{snap}")
            if len(salient) >= 4:
                break
        add("salient", "问卷里最明显的几条", bullets=salient)

        full_parts = [headline]
        if mbti.get("summary_zh"):
            full_parts.append(str(mbti["summary_zh"]))
        for sec in sections:
            full_parts.append(f"【{sec['title_zh']}】")
            if sec.get("body_zh"):
                full_parts.append(sec["body_zh"])
            for b in sec.get("bullets_zh") or []:
                full_parts.append(f"· {b}")
        return {
            "headline_zh": headline,
            "summary_zh": mbti.get("summary_zh") or "",
            "sections": sections,
            "full_zh": "\n\n".join(full_parts),
        }

    def _facet_form_spec(self) -> List[Dict[str, Any]]:
        out = []
        for axis in self.mbti.get("axes") or []:
            out.append(
                {
                    "id": axis.get("facet_id") or axis["id"],
                    "axis_id": axis["id"],
                    "label_zh": axis.get("owner_label_zh") or axis.get("facet_zh") or axis.get("label_zh"),
                    "label_en": axis.get("facet_en") or axis.get("label_en"),
                    "pole_low_zh": axis.get("owner_low_title_zh") or axis.get("pole_low_zh") or axis.get("letter_low"),
                    "pole_high_zh": axis.get("owner_high_title_zh") or axis.get("pole_high_zh") or axis.get("letter_high"),
                    "letter_low": axis.get("letter_low"),
                    "letter_high": axis.get("letter_high"),
                    "dog_meaning_zh": axis.get("dog_meaning_zh"),
                    "owner_label_zh": axis.get("owner_label_zh"),
                    "owner_low_title_zh": axis.get("owner_low_title_zh"),
                    "owner_high_title_zh": axis.get("owner_high_title_zh"),
                    "owner_mid_zh": axis.get("owner_mid_zh"),
                    "terms": axis.get("terms") or [],
                }
            )
        return out

    def _mbti_form_spec(self) -> Dict[str, Any]:
        spec = self.mbti
        axes = []
        for axis in spec.get("axes") or []:
            axes.append(
                {
                    "id": axis["id"],
                    "facet_id": axis.get("facet_id") or axis["id"],
                    "facet_zh": axis.get("owner_label_zh") or axis.get("facet_zh"),
                    "label_zh": axis.get("owner_label_zh") or axis.get("label_zh"),
                    "letter_low": axis.get("letter_low"),
                    "letter_high": axis.get("letter_high"),
                    "low_zh": axis.get("low_zh"),
                    "high_zh": axis.get("high_zh"),
                    "dog_meaning_zh": axis.get("dog_meaning_zh"),
                    "owner_label_zh": axis.get("owner_label_zh"),
                    "owner_low_title_zh": axis.get("owner_low_title_zh"),
                    "owner_high_title_zh": axis.get("owner_high_title_zh"),
                    "owner_mid_zh": axis.get("owner_mid_zh"),
                    "terms": axis.get("terms") or [],
                }
            )
        types = spec.get("types") or {}
        catalog = [
            {
                "code": t["code"],
                "title_zh": t.get("title_zh"),
                "summary_zh": t.get("summary_zh"),
            }
            for t in types.values()
        ]
        catalog.sort(key=lambda x: x["code"])
        balanced = spec.get("balanced_type") or {}
        return {
            "analogical": True,
            "derived_from": "facets",
            "threshold": (spec.get("scale") or {}).get("threshold", 2.0),
            "rule_zh": (spec.get("scale") or {}).get("rule"),
            "disclaimer_zh": spec.get("disclaimer_zh"),
            "overlap_note_zh": spec.get("overlap_note_zh"),
            "axes": axes,
            "types": catalog,
            "balanced_type": {
                "code": balanced.get("code") or "BALANCED",
                "title_zh": balanced.get("title_zh") or "均衡陪伴型",
                "summary_zh": balanced.get("summary_zh") or "",
            },
        }

    def score_facets(
        self, scored: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """L2: 14 subscale means → 4 exclusive facet scores."""
        scale = self.mbti.get("scale") or {}
        threshold = float(scale.get("threshold", 2.0))
        margin = float(scale.get("borderline_margin", 0.25))
        scored_by_id = {row["id"]: row for row in scored}
        facets: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for axis in self.mbti.get("axes") or []:
            row = self._axis_score(axis, scored_by_id, threshold, margin)
            if row is None:
                skipped.append(
                    {
                        "id": axis.get("facet_id") or axis["id"],
                        "axis_id": axis["id"],
                        "label_zh": axis.get("owner_label_zh") or axis.get("facet_zh") or axis.get("label_zh"),
                    }
                )
                continue
            facets.append(row)
        return facets, skipped

    def assign_mbti(
        self,
        facets: List[Dict[str, Any]],
        skipped_facets: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """L3 sticker: four facet poles → 16-letter type (or balanced)."""
        spec = self.mbti
        skipped_facets = skipped_facets or []
        axes_out = list(facets)
        if skipped_facets or len(facets) != 4:
            return {
                "assigned": False,
                "derived_from": "facets",
                "reason_zh": "四个重点作答不足，无法给出角色贴纸。14 维报告与已算出的重点仍可用。",
                "missing_axes": [s.get("axis_id") or s.get("id") for s in skipped_facets],
                "missing_facets": [s.get("id") for s in skipped_facets],
                "axes": axes_out,
                "disclaimer_zh": spec.get("disclaimer_zh"),
            }

        letters = [f["letter"] for f in facets]
        lean_code = "".join(letters)
        balanced = all(f.get("borderline") for f in facets)
        type_copy = (spec.get("types") or {}).get(lean_code) or {}
        if balanced:
            type_copy = spec.get("balanced_type") or type_copy
        borderline = [a["id"] for a in axes_out if a.get("borderline")]
        payload = {
            "assigned": True,
            "derived_from": "facets",
            "balanced": balanced,
            "code": "BALANCED" if balanced else lean_code,
            "lean_code": lean_code,
            "title_zh": type_copy.get("title_zh") or lean_code,
            "title_en": type_copy.get("title_en") or lean_code,
            "axes": axes_out,
            "borderline_axes": borderline,
            "analogical": True,
            "disclaimer_zh": spec.get("disclaimer_zh"),
            "disclaimer_en": spec.get("disclaimer_en"),
        }
        payload.update(self._type_fields(type_copy))
        payload["mbti_desc_zh"] = self._compose_mbti_desc_zh(payload["code"])
        return payload

    def _compose_mbti_desc_zh(self, code: str) -> str:
        """
        MBTI 风格一句话描述（给 App 展示用）。

        注意：这是类比层文案，不宣称医学或心理学意义。
        """
        if code == "BALANCED":
            return "四个重点都贴中线：不极端、不容易被单一因素带走。相处用可预期的节奏和短训练就够；稍微偏高就按偏高那一条重点调整。"

        if not code or len(code) != 4:
            return ""

        ei, sn, tf, jp = code[0], code[1], code[2], code[3]

        ei_word = {"I": "慢热", "E": "见谁都热"}[ei]
        sn_word = {"S": "安静", "N": "嗨得停不下"}[sn]
        tf_word = {"F": "好说话", "T": "会看家、容易炸"}[tf]
        jp_word = {"J": "听话", "P": "有主见、不太听话"}[jp]

        ei_guide = {
            "I": "先给缓冲与时间，让它自己靠近",
            "E": "先坐定再招呼，热情要有开关",
        }[ei]
        sn_guide = {
            "S": "用闻味道与日常节奏就够",
            "N": "运动要拆段：先降温再释放",
        }[sn]
        tf_guide = {
            "F": "沟通更容易：用短句交换成功",
            "T": "边界先稳：门口/资源先有结束与回收",
        }[tf]
        jp_guide = {
            "J": "口令一次一件，短课就见效",
            "P": "少重复、给选择与退路，成功从小开始",
        }[jp]

        return (
            f"它的组合是「{ei_word} / {sn_word} / {tf_word} / {jp_word}」。"
            f"相处省力做法：{ei_guide}；再{sn_guide}；边界先{tf_guide}，"
            f"合作用{jp_guide}。"
        )

    def _axis_score(
        self,
        axis: Mapping[str, Any],
        scored_by_id: Mapping[str, Dict[str, Any]],
        threshold: float,
        margin: float,
    ) -> Optional[Dict[str, Any]]:
        terms = list(axis.get("terms") or [])
        if not terms:
            return None
        num = 0.0
        den = 0.0
        parts: List[Dict[str, Any]] = []
        for term in terms:
            sid = str(term["subscale"])
            row = scored_by_id.get(sid)
            if row is None:
                return None
            raw = float(row["score"])
            invert = bool(term.get("invert"))
            value = 4.0 - raw if invert else raw
            weight = float(term.get("weight", 1.0))
            num += value * weight
            den += weight
            parts.append(
                {
                    "subscale": sid,
                    "raw": round(raw, 3),
                    "value": round(value, 3),
                    "invert": invert,
                    "weight": weight,
                }
            )
        if den <= 0:
            return None
        score = num / den
        high = score > threshold
        letter = axis["letter_high"] if high else axis["letter_low"]
        pole = "high" if high else "low"
        borderline = abs(score - threshold) < margin
        pole_zh = axis.get("high_zh") if high else axis.get("low_zh")
        facet_id = axis.get("facet_id") or axis["id"]
        if borderline:
            owner_title = ""
            owner_summary = axis.get("owner_mid_zh") or ""
            pole_short = "大多数情况普通"
        else:
            owner_title = (
                axis.get("owner_high_title_zh")
                if high
                else axis.get("owner_low_title_zh")
            ) or ""
            owner_summary = pole_zh or ""
            pole_short = owner_title or (
                axis.get("pole_high_zh") if high else axis.get("pole_low_zh")
            ) or letter
        return {
            "id": axis["id"],
            "facet_id": facet_id,
            "facet_zh": axis.get("facet_zh") or axis.get("label_zh"),
            "owner_label_zh": axis.get("owner_label_zh") or axis.get("facet_zh"),
            "owner_title_zh": owner_title,
            "owner_summary_zh": owner_summary,
            "owner_mid_zh": axis.get("owner_mid_zh") or "",
            "label_zh": axis.get("owner_label_zh") or axis.get("facet_zh") or axis.get("label_zh"),
            "axis_label_zh": axis.get("label_zh"),
            "score": round(score, 3),
            "pole": pole,
            "pole_short_zh": pole_short,
            "letter": letter,
            "pole_zh": pole_zh,
            "borderline": borderline,
            "dims": [p["subscale"] for p in parts],
            "terms": parts,
        }


def demo_answers() -> Dict[int, float]:
    """High energy/excitability, low fear — for CLI smoke."""
    answers = {i: 2.0 for i in range(1, 42)}
    answers[1] = answers[2] = 4.0  # excitability
    answers[39] = answers[40] = 4.0  # energy
    answers[13] = answers[15] = 0.0  # stranger fear
    answers[27] = answers[28] = 4.0  # reverse → low training difficulty
    answers[29] = 0.0
    return answers


def main(argv: Optional[Iterable[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--answers", type=Path, default=None)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--form", action="store_true", help="Print form spec JSON")
    args = p.parse_args(list(argv) if argv is not None else None)
    engine = CBarqPersonality()
    if args.form:
        print(json.dumps(engine.form_spec(), ensure_ascii=False, indent=2))
        return 0
    if args.demo:
        payload = engine.score(demo_answers())
    elif args.answers:
        payload = engine.score(_load_json(args.answers))
    else:
        raise SystemExit("Pass --demo, --form, or --answers JSON")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
