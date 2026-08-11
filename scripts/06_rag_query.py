"""ANIMA RAG query pipeline: Red-Light intercept -> retrieval -> answer generation."""

import importlib.util
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)


def _load_dotenv(path: Optional[str] = None) -> None:
    """Load KEY=VALUE pairs from .env without requiring python-dotenv."""
    env_path = path or os.path.join(PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for raw in env_file:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning("Could not read .env: %s", exc)


_load_dotenv()


def _load_script_module(module_name: str, filename: str):
    path = os.path.join(SCRIPTS_DIR, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_red_light_mod = _load_script_module("anima_red_light", "03_red_light_intercept.py")
_embed_mod = _load_script_module("anima_embed", "05_embed_merck.py")

RedLightIntercept = _red_light_mod.RedLightIntercept
PatientVitals = _red_light_mod.PatientVitals
extract_symptom_keywords = _red_light_mod.extract_symptom_keywords
MerckVectorStore = _embed_mod.MerckVectorStore


SYSTEM_PROMPT = (
    "You are AnimaLink, a veterinary emergency triage assistant. "
    "Answer using the provided Merck Veterinary Manual context when present. "
    "If context is empty or thin, still give structured self-check guidance for pet owners, "
    "but clearly say it is not a diagnosis. "
    "Safety-first. Never invent unrelated vital-sign numbers. "
    "Always return both Simplified Chinese (answer_zh) and English (answer_en)."
)

# Topic-level Chinese guidance when Merck snippets match emergency themes.
TOPIC_GUIDANCE_ZH: Tuple[Tuple[re.Pattern, Tuple[str, ...]], ...] = (
    (
        re.compile(r"heat\s*stroke|hypertherm|overheat|中暑|过热", re.I),
        (
            "中暑常见表现：皮肤发烫、呕吐、流口水、急促喘气、痛苦表现、步态不稳、虚脱或意识改变。",
            "轻度处理：立即移至阴凉通风处，用室温水打湿被毛并加强通风，少量补水，持续观察体温与神志。",
            "若出现虚脱、昏迷、抽搐，或直肠体温 ≥40°C（104°F），请立即送急诊。",
        ),
    ),
    (
        re.compile(r"poison|tox|中毒|毒物", re.I),
        (
            "疑似中毒：请立即联系兽医或动物中毒控制中心，不要自行催吐（除非兽医明确指示）。",
            "就医时尽量带上毒物包装、呕吐物样本与接触时间，便于对症处理。",
            "部分案例可考虑活性炭、洗胃或支持疗法，须由兽医评估后决定。",
        ),
    ),
    (
        re.compile(r"heart\s*rate|心率|心跳|脉搏", re.I),
        (
            "心率会随体型、年龄、紧张与活动状态变化；单次测量需结合整体状态判断。",
            "若伴虚脱、苍白牙龈、呼吸困难或持续异常，请尽快就医。",
        ),
    ),
    (
        re.compile(
            r"舔脚|舔爪|抓痒|瘙痒|皮肤|dermatitis|pruritus|itch|lick(?:ing)?\s*(?:paw|feet)|skin\s*disorder",
            re.I,
        ),
        (
            "可能原因拆解：①寄生虫（跳蚤/螨）②过敏（环境/食物）③细菌或酵母继发感染④趾间异物/创伤⑤潮湿闷热或接触刺激物。",
            "请先观察并记录：舔的是单脚还是多脚？趾间是否红肿、破皮、渗液、异味？有无脱毛、结痂、跛行？是否季节性或雨天加重？",
            "非侵入性居家行动：趾间用干净温湿软布/宠物湿巾轻柔擦干擦净；保持足垫干爽（外出潮湿后立即擦干）；室内通风或适度开空调降湿；减少继续舔咬（必要时伊丽莎白圈）；暂时避免刺激性洗澡/新香氛地板清洁剂。",
            "暂勿自行：不要乱涂人用药膏、激素霜、双氧水或酒精；不要长期泡药液。",
            "尽快就医：持续加重、破皮出血、明显疼痛/跛行、全身抓痒、精神变差，或居家护理 24–48 小时无改善。",
        ),
    ),
    (
        re.compile(r"呕吐|腹泻|digestive|vomit|diarrhea|软便|拉肚子|吐黄水|吐黄", re.I),
        (
            "可能原因：饮食不当、感染、寄生虫、异物、胰腺炎或其他系统疾病。",
            "请先观察：次数、是否混血/胆汁、精神与饮水、是否脱水（牙龈干燥、皮肤回弹慢）。",
            "短暂轻度可先禁食数小时并观察；持续呕吐、血便、腹胀、精神萎靡或幼龄/老年动物请尽快就医。",
        ),
    ),
)

# Best-effort phrase map for short English emergency snippets.
PHRASE_MAP_ZH: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"activated charcoal", re.I), "活性炭（须遵医嘱）"),
    (re.compile(r"milk of magnesia", re.I), "镁乳（部分中毒可用，须遵医嘱）"),
    (re.compile(r"rapid panting", re.I), "急促喘气"),
    (re.compile(r"hot skin", re.I), "皮肤发烫"),
    (re.compile(r"uncoordinated movement", re.I), "步态不稳"),
    (re.compile(r"unconsciousness", re.I), "意识丧失"),
    (re.compile(r"heat stroke", re.I), "中暑"),
    (re.compile(r"vomiting", re.I), "呕吐"),
    (re.compile(r"drooling", re.I), "流口水"),
    (re.compile(r"collapse", re.I), "虚脱/倒下"),
    (re.compile(r"distress", re.I), "痛苦表现"),
    (re.compile(r"flush out stomach contents", re.I), "冲洗胃内容物"),
    (re.compile(r"saline cathartics", re.I), "生理盐水泻剂"),
    (re.compile(r"supportive", re.I), "支持疗法"),
    (re.compile(r"Vital sign reference\s*[—\-]\s*", re.I), "体征参考 — "),
    (re.compile(r"Heart rate,?\s*bpm", re.I), "心率（次/分钟）"),
    (re.compile(r"\bheart rate\b", re.I), "心率"),
    (re.compile(r"\bbpm\b", re.I), "次/分钟"),
    (re.compile(r"rectal temperature", re.I), "直肠体温"),
    (re.compile(r"Triage indicator:\s*", re.I), "分诊指标："),
    (re.compile(r"Toxicology / poisoning guidance\s*[—\-]\s*", re.I), "中毒处理指引 — "),
)

CHUNK_TYPE_ZH = {
    "numeric_metric": "数值指标",
    "vital_sign": "体征参考",
    "triage_indicator": "分诊指标",
    "toxic_dosage": "毒物剂量",
    "paragraph": "段落摘录",
    "chunk": "知识片段",
}


def _localize_source_content(
    content: str,
    chunk_type: str,
    request: Optional["RAGQueryRequest"] = None,
) -> str:
    text = (content or "").strip()
    if not text:
        return ""

    if chunk_type == "numeric_metric" or text.startswith("Numeric metric:"):
        fields = _parse_metric_fields(text)
        # Also parse metric id from "Numeric metric: id; ..."
        if "id" not in fields and "Numeric metric:" in text:
            head = text.split(";", 1)[0]
            fields.setdefault("id", head.replace("Numeric metric:", "").strip())
        formatted = _format_numeric_metric_zh(fields, request or RAGQueryRequest(question=""))
        if formatted:
            return formatted

    translated = _snippet_to_zh(text)
    if _is_chinese_enough(translated) and not _has_english_sentence_fragments(translated):
        return translated
    if translated != text:
        return translated
    return text


def _enrich_sources_zh(
    sources: List[Dict[str, Any]],
    request: Optional["RAGQueryRequest"] = None,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for source in sources:
        item = dict(source)
        meta = dict(item.get("metadata") or {})
        chunk_type = meta.get("chunk_type", "chunk")
        content = item.get("content") or ""
        content_zh = _localize_source_content(content, chunk_type, request)
        type_zh = CHUNK_TYPE_ZH.get(chunk_type, "知识片段")
        meta["chunk_type_zh"] = type_zh
        item["metadata"] = meta
        item["content_zh"] = content_zh
        item["chunk_type_zh"] = type_zh
        enriched.append(item)
    return enriched


def _split_status_and_body(text: str) -> Tuple[str, str]:
    """Split leading RED/YELLOW/GREEN judgment line from the rest of the answer."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "", ""
    match = re.match(
        r"^(?:分诊结论|Triage status)\s*[：:]\s*(GREEN|YELLOW|RED)\s*(?:\n+|[：:\-—–]\s*)?(.*)$",
        cleaned,
        flags=re.I | re.S,
    )
    if not match:
        match = re.match(
            r"^(GREEN|YELLOW|RED)\s*[：:\-—–]\s*(.*)$",
            cleaned,
            flags=re.I | re.S,
        )
    if not match:
        return "", cleaned
    status = match.group(1).upper()
    rest = (match.group(2) or "").strip()
    return status, rest


def _format_bilingual_answer(
    note: str,
    body: str,
    *,
    lang: str,
) -> str:
    """Put triage judgment on its own line, then structured content."""
    note = (note or "").strip()
    body = (body or "").strip()
    status_from_note, note_body = _split_status_and_body(note)
    status_from_body, body_rest = _split_status_and_body(body)

    status = status_from_body or status_from_note
    if status_from_body:
        body = body_rest

    # Avoid duplicating the red-light sentence inside the body.
    if note_body and body:
        if body.startswith(note_body):
            body = body[len(note_body) :].lstrip(" \n：:")

    label = {"zh": "分诊结论", "en": "Triage status"}.get(lang, "Triage status")
    lines: List[str] = []
    if status:
        lines.append(f"{label}：{status}")
        if note_body and not body.startswith(note_body[:12] if len(note_body) > 12 else note_body):
            # Keep short judgment under status only when body doesn't already explain it.
            if "可能原因" not in body and "Possible causes" not in body:
                lines.append(note_body)
    elif note:
        lines.append(note)

    if body:
        if lines:
            lines.append("")
        lines.append(body)
    return "\n".join(lines).strip()


def _parse_metric_fields(content: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for part in content.split(";"):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()
    return fields


def _format_numeric_metric_zh(fields: Dict[str, str], request: "RAGQueryRequest") -> Optional[str]:
    metric = fields.get("metric", "")
    species = fields.get("species") or request.species or "dog"
    size = fields.get("size") or request.size or ""

    if metric == "heart_rate_bpm":
        if "min" in fields and "max" in fields:
            if species == "cat":
                label = "猫"
            elif size == "small":
                label = "小型犬"
            elif size == "large":
                label = "大型犬"
            else:
                label = "犬"
            return f"{label}正常心率参考范围：{fields['min']}–{fields['max']} 次/分钟"
        if "threshold" in fields:
            return f"犬心动过速参考阈值：≥ {fields['threshold']} 次/分钟"

    if metric in {"rectal_temp_f", "rectal_temp_dog_cat_f"}:
        if "min" in fields and "max" in fields:
            return f"犬猫正常直肠体温参考：{fields['min']}–{fields['max']} °F"
        if fields.get("critical_threshold_f"):
            return f"严重过热警戒体温：≥ {fields['critical_threshold_f']} °F"

    if metric == "crt_normal_seconds" and "max" in fields:
        return f"正常 CRT（毛细血管再充盈时间）：约 1–{fields['max']} 秒"

    metric_id = fields.get("id") or ""
    if "min" in fields and "max" in fields:
        return f"参考指标 {metric_id or metric}：{fields['min']}–{fields['max']}"
    if "threshold" in fields:
        return f"参考阈值 {metric_id or metric}：{fields['threshold']}"
    return None


def _snippet_to_zh(text: str) -> str:
    cleaned = text.strip()
    for prefix in ("Triage indicator: ", "Toxicology / poisoning guidance — ", "Numeric metric: "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    result = cleaned
    for pattern, zh in PHRASE_MAP_ZH:
        result = pattern.sub(zh, result)
    return result


def _question_wants_heart_rate(text: str) -> bool:
    return bool(re.search(r"心率|心跳|脉搏|heart\s*rate|\bbpm\b", text, re.I))


def _question_wants_temperature(text: str) -> bool:
    return bool(
        re.search(r"体温|溫度|温度|rectal\s*temp|temperature|发热|發燒", text, re.I)
    )


def _metric_relevant_to_question(metric: str, question: str) -> bool:
    if metric == "heart_rate_bpm":
        return _question_wants_heart_rate(question)
    if metric in {"rectal_temp_f", "rectal_temp_dog_cat_f", "hypothermia_rewarm_c"}:
        return _question_wants_temperature(question) or bool(
            re.search(r"中暑|heat\s*stroke|过热", question, re.I)
        )
    if metric == "crt_normal_seconds":
        return bool(re.search(r"\bcrt\b|毛细血管|灌注", question, re.I))
    # Unknown metrics: only keep if question mentions the metric id-ish token.
    return bool(metric and metric.lower() in question.lower())


def _source_relevant_to_question(
    request: "RAGQueryRequest", source: Dict[str, Any]
) -> bool:
    content = (source.get("content") or "").strip()
    if not content:
        return False
    if _species_mismatch(content, request.species):
        return False

    meta = source.get("metadata") or {}
    chunk_type = meta.get("chunk_type", "paragraph")
    question = request.question or ""
    content_l = content.lower()

    if chunk_type == "numeric_metric":
        fields = _parse_metric_fields(content)
        return _metric_relevant_to_question(fields.get("metric", ""), question)

    # Prefer question-topic match; otherwise require lexical overlap with content.
    for pattern, _items in TOPIC_GUIDANCE_ZH:
        if pattern.search(question) and pattern.search(content):
            return True
        if pattern.search(question) and not pattern.search(content):
            # Question is about a known topic; skip off-topic snippets.
            return False

    # Cross-lingual bridge: Chinese questions vs English Merck chunks.
    # Use QUERY_EXPANSIONS that carry typed chunk hints (skip species-only expansions).
    for pattern, expansion, types in QUERY_EXPANSIONS:
        if not types:
            continue
        if not pattern.search(question):
            continue
        keywords = [w for w in expansion.lower().split() if len(w) >= 4]
        if any(kw in content_l for kw in keywords):
            return True

    # Task 0.3: owner-complaint map clinical terms also count as relevance evidence.
    for term in expand_complaint_to_clinical(question):
        token = term.casefold().strip()
        if len(token) >= 4 and token in content_l:
            return True

    # Generic overlap check for non-topic questions (e.g. paw licking).
    tokens = re.findall(r"[A-Za-z]{3,}|\d+|[\u4e00-\u9fff]{2,}", question.lower())
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in content_l)
    return hits >= 1


def _topic_bullets_zh(question: str, content: str) -> List[str]:
    """Only emit topic bullets when the *question* matches that topic."""
    bullets: List[str] = []
    seen = set()
    for pattern, items in TOPIC_GUIDANCE_ZH:
        if pattern.search(question):
            for item in items:
                if item not in seen:
                    seen.add(item)
                    bullets.append(item)
    return bullets


def _species_mismatch(content: str, species: Optional[str]) -> bool:
    if species not in {"dog", "cat"}:
        return False
    return bool(re.search(r"\b(horse|equine|foal|mare|stallion)\b", content, re.I))


def _is_chinese_enough(text: str) -> bool:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk >= 10:
        return True
    return cjk / max(len(text), 1) >= 0.3


def _has_english_sentence_fragments(text: str) -> bool:
    return bool(
        re.search(
            r"\b(Signs of|include|The first|might be|should be|above|below|indicates|vulnerable)\b",
            text,
            re.I,
        )
    )


def _build_chinese_guidance(
    request: "RAGQueryRequest", sources: List[Dict[str, Any]]
) -> List[str]:
    lines: List[str] = []
    seen = set()
    relevant = [s for s in sources if _source_relevant_to_question(request, s)]

    for source in relevant[:5]:
        content = (source.get("content") or "").strip()
        meta = source.get("metadata") or {}
        chunk_type = meta.get("chunk_type", "paragraph")

        if chunk_type == "numeric_metric":
            fields = _parse_metric_fields(content)
            line = _format_numeric_metric_zh(fields, request)
            if line and line not in seen:
                seen.add(line)
                lines.append(f"· {line}")
            continue

        if len(content) < 28 and chunk_type == "paragraph":
            continue

        topic_from_question = _topic_bullets_zh(request.question, content)
        for bullet in topic_from_question:
            if bullet not in seen:
                seen.add(bullet)
                lines.append(f"· {bullet}")

        if topic_from_question:
            continue

        translated = _snippet_to_zh(content)
        if (
            len(translated) >= 28
            and translated not in seen
            and _is_chinese_enough(translated)
            and not _has_english_sentence_fragments(translated)
        ):
            seen.add(translated)
            lines.append(f"· {translated}")

    if not lines:
        for pattern, items in TOPIC_GUIDANCE_ZH:
            if pattern.search(request.question):
                for item in items[:3]:
                    if item not in seen:
                        seen.add(item)
                        lines.append(f"· {item}")
                break

    return lines[:6]

QUERY_EXPANSIONS = (
    (
        re.compile(r"心率|心跳|脉搏|heart\s*rate|\bbpm\b", re.I),
        "heart rate bpm vital signs normal reference range tachycardia bradycardia",
        ("numeric_metric", "vital_sign"),
    ),
    (
        re.compile(r"体温|溫度|温度|rectal\s*temp|temperature|发热|發燒", re.I),
        "rectal temperature fever hypothermia heat stroke",
        ("numeric_metric", "vital_sign"),
    ),
    (
        re.compile(r"中暑|heat\s*stroke|过热|過熱", re.I),
        "heat stroke cooling first aid hyperthermia",
        ("vital_sign", "triage_indicator", "paragraph"),
    ),
    (
        re.compile(r"中毒|毒物|poison|toxin|toxic", re.I),
        "poisoning toxicology antidote activated charcoal decontamination",
        ("toxic_dosage", "paragraph"),
    ),
    (
        re.compile(
            r"舔脚|舔爪|抓痒|瘙痒|皮肤|过敏|itch|pruritus|dermatitis|lick(?:ing)?\s*(?:paw|feet)|skin",
            re.I,
        ),
        "itching pruritus dermatitis skin allergy lick paws yeast infection fleas",
        ("paragraph", "triage_indicator"),
    ),
    (
        re.compile(r"呕吐|腹泻|digestive|vomit|diarrhea|软便|拉肚子|吐黄水|吐黄", re.I),
        "vomiting diarrhea digestive gastroenteritis dehydration bilious bile",
        ("paragraph",),
    ),
    (
        re.compile(
            r"尿血|血尿|尿频|排尿|泌尿|尿闭|bladder|urinary|cystitis|hematuria|尿不出",
            re.I,
        ),
        "urinary tract bladder kidney cystitis hematuria dysuria obstruction",
        ("paragraph", "triage_indicator"),
    ),
    (
        re.compile(r"抽搐|癫痫|痉挛|seizure|epilep|convulsion|tremor", re.I),
        "seizure epilepsy neurologic brain spinal cord nerve disorders",
        ("paragraph", "triage_indicator"),
    ),
    (
        re.compile(r"咳嗽|咳嗽|喘气|呼吸困难|哮喘|asthma|dyspnea|panting", re.I),
        "cough dyspnea asthma lung airway respiratory distress",
        ("paragraph", "vital_sign"),
    ),
    (
        re.compile(r"小狗|犬|狗|\bdog\b|canine", re.I),
        "dog canine",
        (),
    ),
    (
        re.compile(r"猫|貓|\bcat\b|feline", re.I),
        "cat feline",
        (),
    ),
    (
        re.compile(r"正常|参考|參考|范围|範圍|normal|reference", re.I),
        "normal reference range",
        ("numeric_metric", "vital_sign"),
    ),
)


def _load_complaint_clinical_map(
    path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load Task 0.3 owner-complaint → clinical-term patterns."""
    map_path = path or os.path.join(
        PROJECT_ROOT, "data", "triage_tree", "complaint_clinical_map.json"
    )
    if not os.path.isfile(map_path):
        logger.warning(
            "Complaint map missing (%s). Run: python scripts/11_build_complaint_map.py",
            map_path,
        )
        return []
    try:
        with open(map_path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load complaint map: %s", exc)
        return []
    patterns = payload.get("patterns") or []
    logger.info("Loaded %d complaint→clinical patterns", len(patterns))
    return patterns


_COMPLAINT_PATTERNS = _load_complaint_clinical_map()


def expand_complaint_to_clinical(text: str, limit: int = 8) -> List[str]:
    """Map owner free-text phrases to clinical retrieval terms."""
    blob = (text or "").strip()
    if not blob or not _COMPLAINT_PATTERNS:
        return []
    blob_l = blob.casefold()
    terms: List[str] = []
    seen: set = set()
    for entry in _COMPLAINT_PATTERNS:
        phrase = entry.get("phrase") or ""
        phrase_norm = entry.get("phrase_norm") or phrase.casefold()
        if len(phrase_norm) < 2:
            continue
        # CJK / multiword: substring; short ASCII: word-ish boundary.
        matched = False
        if any("\u4e00" <= ch <= "\u9fff" for ch in phrase):
            matched = phrase in blob or phrase_norm in blob_l
        elif " " in phrase_norm or len(phrase_norm) >= 6:
            matched = phrase_norm in blob_l
        else:
            matched = bool(
                re.search(rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])", blob_l)
            )
        if not matched:
            continue
        for term in entry.get("clinical_terms") or []:
            key = term.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                terms.append(term.strip())
                if len(terms) >= limit:
                    return terms
    return terms


@dataclass
class RAGQueryRequest:
    question: str
    species: Optional[str] = None
    size: Optional[str] = None
    heart_rate_bpm: Optional[float] = None
    crt_seconds: Optional[float] = None
    rectal_temp_f: Optional[float] = None
    rectal_temp_c: Optional[float] = None
    map_mmhg: Optional[float] = None
    symptoms: List[str] = field(default_factory=list)
    chief_complaint: str = ""
    top_k: int = 5


@dataclass
class RAGQueryResponse:
    answer: str
    intercepted: bool
    red_light_status: Optional[str]
    red_light: Optional[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    retrieval_query: str
    model_used: str
    elapsed_ms: float
    evaluated_at: str
    extracted_symptoms: List[str] = field(default_factory=list)
    answer_zh: str = ""
    answer_en: str = ""
    recommendation_zh: str = ""
    recommendation_en: str = ""
    record_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        answer_zh = self.answer_zh or self.answer
        answer_en = self.answer_en or self.answer
        return {
            "answer": answer_zh,
            "answer_zh": answer_zh,
            "answer_en": answer_en,
            "recommendation_zh": self.recommendation_zh,
            "recommendation_en": self.recommendation_en,
            "intercepted": self.intercepted,
            "red_light_status": self.red_light_status,
            "red_light": self.red_light,
            "sources": self.sources,
            "retrieval_query": self.retrieval_query,
            "model_used": self.model_used,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "evaluated_at": self.evaluated_at,
            "extracted_symptoms": self.extracted_symptoms,
            "record_id": self.record_id,
        }


class AnimaRAGPipeline:
    """End-to-end emergency RAG with Red-Light safety gate."""

    def __init__(
        self,
        vector_store: Optional[MerckVectorStore] = None,
        red_light: Optional[RedLightIntercept] = None,
    ) -> None:
        self.vector_store = vector_store or MerckVectorStore()
        self.red_light = red_light or RedLightIntercept()
        self.openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.openai_model = os.getenv("ANIMA_LLM_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        self.llm_enabled = bool(self.openai_api_key)
        if self.llm_enabled:
            logger.info("OpenAI answers enabled (model=%s)", self.openai_model)
        else:
            logger.info("OpenAI key not set — using extractive Chinese/English fallback")

    def _enrich_symptoms_from_description(self, request: RAGQueryRequest) -> List[str]:
        """Extract symptom keywords from question + chief complaint (no separate keyword field)."""
        extracted = extract_symptom_keywords(request.question, request.chief_complaint)
        clinical = expand_complaint_to_clinical(
            " ".join(
                part
                for part in [request.question, request.chief_complaint]
                if part
            )
        )
        # Keep any API-supplied symptoms for backward compatibility, then dedupe.
        merged: List[str] = []
        seen = set()
        for phrase in [*extracted, *clinical, *request.symptoms]:
            key = phrase.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(phrase.strip())
        request.symptoms = merged
        return merged

    def _build_patient(self, request: RAGQueryRequest) -> Optional[PatientVitals]:
        if not any(
            [
                request.species,
                request.chief_complaint,
                request.symptoms,
                request.question,
                request.heart_rate_bpm is not None,
                request.crt_seconds is not None,
                request.rectal_temp_f is not None,
                request.rectal_temp_c is not None,
                request.map_mmhg is not None,
            ]
        ):
            return None
        if not request.species:
            request.species = "unknown"
        return PatientVitals(
            species=request.species,
            size=request.size,
            heart_rate_bpm=request.heart_rate_bpm,
            crt_seconds=request.crt_seconds,
            rectal_temp_f=request.rectal_temp_f,
            rectal_temp_c=request.rectal_temp_c,
            map_mmhg=request.map_mmhg,
            symptoms=request.symptoms,
            chief_complaint=request.chief_complaint or request.question,
        )

    def _detect_preferred_types(self, text: str) -> Tuple[str, ...]:
        preferred: List[str] = []
        for pattern, _expansion, types in QUERY_EXPANSIONS:
            if types and pattern.search(text):
                for chunk_type in types:
                    if chunk_type not in preferred:
                        preferred.append(chunk_type)
        return tuple(preferred)

    def _build_retrieval_query(self, request: RAGQueryRequest) -> str:
        raw_parts = [request.question]
        if request.chief_complaint:
            raw_parts.append(request.chief_complaint)
        if request.symptoms:
            raw_parts.extend(request.symptoms)
        if request.species:
            raw_parts.append(request.species)
        if request.size:
            raw_parts.append(request.size)
        blob = " ".join(raw_parts)

        expansions: List[str] = []
        for pattern, expansion, _types in QUERY_EXPANSIONS:
            if pattern.search(blob):
                expansions.append(expansion)

        clinical_from_complaints = expand_complaint_to_clinical(blob)
        if clinical_from_complaints:
            expansions.append(" ".join(clinical_from_complaints))

        # Only inject vital-sign retrieval terms when the question asks for them.
        # Filling HR/temp form fields must NOT force heart-rate answers for
        # unrelated complaints like paw licking.
        if request.heart_rate_bpm is not None and _question_wants_heart_rate(blob):
            expansions.append("heart rate bpm vital signs")
        if request.rectal_temp_f is not None and (
            _question_wants_temperature(blob)
            or re.search(r"中暑|heat\s*stroke|过热", blob, re.I)
        ):
            expansions.append("rectal temperature heat stroke")

        parts = expansions + raw_parts
        if (
            request.species == "dog"
            and request.size
            and _question_wants_heart_rate(blob)
        ):
            parts.append(f"{request.size} dog heart rate")
        return " ".join(parts)

    def _rerank_sources(
        self,
        sources: List[Dict[str, Any]],
        preferred_types: Sequence[str],
        top_k: int,
        question: str = "",
    ) -> List[Dict[str, Any]]:
        ranked: List[Tuple[float, Dict[str, Any]]] = []
        wants_hr = _question_wants_heart_rate(question)
        for source in sources:
            content = (source.get("content") or "").strip()
            meta = source.get("metadata") or {}
            chunk_type = meta.get("chunk_type", "paragraph")
            score = float(source.get("score") or 0.0)

            # Drop near-empty / title-only junk that TF-IDF over-ranks.
            if len(content) < 24 and chunk_type != "numeric_metric":
                continue
            if score <= 0:
                continue

            # Suppress heart-rate metrics for unrelated questions.
            if chunk_type == "numeric_metric" and not wants_hr:
                fields = _parse_metric_fields(content)
                if fields.get("metric") == "heart_rate_bpm":
                    continue

            boost = 0.0
            if preferred_types and chunk_type in preferred_types:
                boost += 0.35 * (
                    1.0
                    + 0.15
                    * (len(preferred_types) - preferred_types.index(chunk_type))
                )
            if chunk_type == "numeric_metric" and wants_hr:
                boost += 0.25
            if len(content) < 40 and chunk_type == "paragraph":
                boost -= 0.2

            ranked.append((score + boost, source))

        ranked.sort(key=lambda item: item[0], reverse=True)
        results: List[Dict[str, Any]] = []
        for index, (_adjusted, source) in enumerate(ranked[:top_k], start=1):
            item = dict(source)
            item["rank"] = index
            results.append(item)
        return results
    @staticmethod
    def _format_context(sources: List[Dict[str, Any]]) -> str:
        blocks = []
        for source in sources:
            meta = source.get("metadata", {})
            title = meta.get("article_title", "Merck article")
            chunk_type = meta.get("chunk_type", "chunk")
            blocks.append(
                f"[{chunk_type}] {title}\n{source['content']}"
            )
        return "\n\n".join(blocks)

    def _extractive_answers(
        self,
        request: RAGQueryRequest,
        sources: List[Dict[str, Any]],
        note_zh: str,
        note_en: str,
    ) -> Tuple[str, str]:
        topic_lines = []
        for pattern, items in TOPIC_GUIDANCE_ZH:
            if pattern.search(request.question or ""):
                topic_lines = [f"· {item}" for item in items]
                break

        if not sources and not topic_lines:
            answer_zh = _format_bilingual_answer(
                note_zh,
                "未检索到足够相关的 Merck 参考内容。若症状加重请立即就医。\n"
                "以上仅为信息参考，不能替代执业兽医诊断与治疗。",
                lang="zh",
            )
            answer_en = _format_bilingual_answer(
                note_en,
                "No matching Merck references were retrieved. "
                "Seek veterinary care if symptoms are worsening.\n"
                "This is informational guidance only — not a veterinary diagnosis.",
                lang="en",
            )
            return answer_zh, answer_en

        zh_lines = _build_chinese_guidance(request, sources) if sources else []
        if topic_lines:
            # Prefer structured topic guidance; keep metric lines if present.
            metric_lines = [line for line in zh_lines if "参考" in line or "心率" in line or "体温" in line]
            zh_lines = topic_lines + [line for line in metric_lines if line not in topic_lines]

        if not zh_lines:
            zh_lines = topic_lines or [
                "· 请补充更具体症状（部位、持续时间、是否红肿/破皮/跛行）以便进一步分诊。",
                "· 若持续加重或精神变差，请尽快就医。",
            ]

        zh_body = (
            f"针对「{request.question}」，建议按下面步骤自我核对：\n"
            + "\n".join(zh_lines)
            + "\n\n以上仅为信息参考，不能替代执业兽医诊断与治疗。"
        )
        answer_zh = _format_bilingual_answer(note_zh, zh_body, lang="zh")

        relevant = [s for s in sources if _source_relevant_to_question(request, s)]
        bullets = [f"- {source['content']}" for source in (relevant or sources)[:3]]
        en_body = (
            f"For \"{request.question}\", review the following guidance:\n"
            + ("\n".join(bullets) if bullets else "- Monitor closely and seek veterinary care if worsening.")
            + "\n\nThis is informational guidance only — not a veterinary diagnosis."
        )
        answer_en = _format_bilingual_answer(note_en, en_body, lang="en")
        return answer_zh, answer_en

    def _openai_answers(
        self,
        request: RAGQueryRequest,
        sources: List[Dict[str, Any]],
        note_zh: str,
        note_en: str,
    ) -> Tuple[str, str]:
        context = self._format_context(sources) if sources else "(no matching Merck chunks)"
        topic_hint = ""
        for pattern, items in TOPIC_GUIDANCE_ZH:
            if pattern.search(request.question or ""):
                topic_hint = "\n".join(f"- {item}" for item in items)
                break

        user_prompt = (
            f"Patient question: {request.question}\n"
            f"Chief complaint: {request.chief_complaint or 'N/A'}\n"
            f"Species: {request.species or 'unknown'}\n"
            f"Size: {request.size or 'N/A'}\n"
            f"Extracted symptoms: {', '.join(request.symptoms) or 'N/A'}\n"
            f"Red-Light note (ZH): {note_zh}\n"
            f"Red-Light note (EN): {note_en}\n\n"
            f"Topic checklist hint:\n{topic_hint or '(none)'}\n\n"
            f"Merck context:\n{context}\n\n"
            "Return JSON only with keys answer_zh and answer_en.\n"
            "Format BOTH answers exactly like this (use real newlines):\n"
            "分诊结论：GREEN|YELLOW|RED\n"
            "<one short judgment sentence>\n"
            "\n"
            "可能原因：\n"
            "1) ...\n"
            "2) ...\n"
            "3) ...\n"
            "\n"
            "请先观察：\n"
            "- ...\n"
            "- ...\n"
            "\n"
            "建议行动：\n"
            "- <至少 3–5 条可立刻做的非侵入性居家护理，例如：擦干趾间、保持干爽、通风/除湿或开空调、减少舔咬、更换刺激清洁剂等>\n"
            "- <明确写出暂勿做什么：人用药膏、酒精、双氧水等>\n"
            "\n"
            "何时就医：\n"
            "- ...\n"
            "\n"
            "免责声明：以上仅为信息参考，不能替代执业兽医诊断与治疗。\n"
            "English answer_en should mirror the same section structure "
            "(Triage status / Possible causes / Check first / What to do / Seek care when / Disclaimer).\n"
            "Rules:\n"
            "1) Do NOT write a vague one-liner like 'maybe allergy or other reasons'. "
            "Always break down at least 3 plausible causes and concrete observation points.\n"
            "2) '建议行动 / What to do' MUST include concrete non-invasive home care "
            "(keep paws dry, gently wipe clean, improve ventilation/AC to reduce humidity, "
            "e-collar to stop licking, avoid irritants). "
            "Do NOT only say 'observe' or 'see a vet'.\n"
            "3) Use Merck context when relevant; if thin, still give the structured checklist.\n"
            "4) Do NOT invent unrelated heart-rate/temp numbers; do NOT recommend human meds.\n"
            "5) Keep owner-friendly Simplified Chinese in answer_zh."
        )
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.openai_model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
        answer_zh = str(parsed.get("answer_zh") or "").strip()
        answer_en = str(parsed.get("answer_en") or "").strip()
        if not answer_zh or not answer_en:
            raise ValueError("OpenAI bilingual response missing answer_zh/answer_en")
        # Normalize: ensure judgment line and body are separated even if model compacted.
        answer_zh = _format_bilingual_answer(note_zh, answer_zh, lang="zh")
        answer_en = _format_bilingual_answer(note_en, answer_en, lang="en")
        return answer_zh, answer_en

    def _generate_answers(
        self,
        request: RAGQueryRequest,
        sources: List[Dict[str, Any]],
        note_zh: str,
        note_en: str,
    ) -> Tuple[str, str, str]:
        """Return (answer_zh, answer_en, model_used)."""
        if self.llm_enabled:
            try:
                answer_zh, answer_en = self._openai_answers(
                    request, sources, note_zh, note_en
                )
                return answer_zh, answer_en, self.openai_model
            except (requests.RequestException, ValueError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("OpenAI bilingual call failed, falling back: %s", exc)
        answer_zh, answer_en = self._extractive_answers(
            request, sources, note_zh, note_en
        )
        return answer_zh, answer_en, "extractive_fallback"

    def query(self, request: RAGQueryRequest) -> RAGQueryResponse:
        """Run Red-Light -> retrieval -> bilingual answer generation."""
        start = time.perf_counter()
        extracted_symptoms = self._enrich_symptoms_from_description(request)
        patient = self._build_patient(request)
        red_light_result = None
        note_zh = "Red-Light：未评估（未提供体征/症状）。"
        note_en = "Red-Light: not evaluated (no patient vitals/symptoms supplied)."
        recommendation_zh = ""
        recommendation_en = ""

        if patient is not None:
            red_light_result = self.red_light.evaluate(patient)
            note_zh = red_light_result.recommendation_zh or red_light_result.recommendation
            note_en = red_light_result.recommendation_en or red_light_result.recommendation
            recommendation_zh = note_zh
            recommendation_en = note_en
            if red_light_result.intercept:
                elapsed_ms = (time.perf_counter() - start) * 1000
                answer_zh = _format_bilingual_answer(
                    note_zh,
                    "请立即送兽医急诊，途中注意稳住气道、呼吸与循环。不要等待 AI 建议。",
                    lang="zh",
                )
                answer_en = _format_bilingual_answer(
                    note_en,
                    "Seek emergency veterinary care now. Stabilize ABC while transporting. "
                    "Do not wait for AI advice.",
                    lang="en",
                )
                return RAGQueryResponse(
                    answer=answer_zh,
                    answer_zh=answer_zh,
                    answer_en=answer_en,
                    recommendation_zh=recommendation_zh,
                    recommendation_en=recommendation_en,
                    intercepted=True,
                    red_light_status=red_light_result.status.value,
                    red_light=red_light_result.to_dict(),
                    sources=[],
                    retrieval_query=self._build_retrieval_query(request),
                    model_used="red_light_intercept",
                    elapsed_ms=elapsed_ms,
                    evaluated_at=datetime.now(timezone.utc).isoformat(),
                    extracted_symptoms=extracted_symptoms,
                )

        retrieval_query = self._build_retrieval_query(request)
        preferred_types = self._detect_preferred_types(retrieval_query)
        candidates = self.vector_store.search(
            retrieval_query, top_k=max(request.top_k * 8, 20)
        )
        sources = self._rerank_sources(
            candidates,
            preferred_types,
            request.top_k,
            question=request.question or "",
        )
        # Keep only sources that actually relate to the question for the response payload.
        relevant_sources = [
            s for s in sources if _source_relevant_to_question(request, s)
        ]
        display_sources = _enrich_sources_zh(relevant_sources, request)
        answer_zh, answer_en, model_used = self._generate_answers(
            request, relevant_sources, note_zh, note_en
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        return RAGQueryResponse(
            answer=answer_zh,
            answer_zh=answer_zh,
            answer_en=answer_en,
            recommendation_zh=recommendation_zh,
            recommendation_en=recommendation_en,
            intercepted=False,
            red_light_status=(
                red_light_result.status.value if red_light_result else None
            ),
            red_light=(
                red_light_result.to_dict() if red_light_result else None
            ),
            sources=display_sources,
            retrieval_query=retrieval_query,
            model_used=model_used,
            elapsed_ms=elapsed_ms,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            extracted_symptoms=extracted_symptoms,
        )


def _demo_requests() -> List[RAGQueryRequest]:
    return [
        RAGQueryRequest(
            question="What is normal heart rate for a small dog?",
            species="dog",
            size="small",
            heart_rate_bpm=95,
            chief_complaint="Owner worried about fast breathing after exercise",
        ),
        RAGQueryRequest(
            question="中暑怎么办？",
            species="dog",
            heart_rate_bpm=120,
            rectal_temp_f=102.8,
            chief_complaint="散步后喘气、流口水，仍清醒能走",
        ),
        RAGQueryRequest(
            question="中暑怎么办？狗已经站不起来了",
            species="dog",
            heart_rate_bpm=170,
            rectal_temp_f=105.2,
            chief_complaint="Heat stroke after hiking, collapse",
        ),
        RAGQueryRequest(
            question="How is poisoning treated?",
            species="dog",
            chief_complaint="Ate rat poison 20 minutes ago, vomiting",
        ),
    ]


if __name__ == "__main__":
    pipeline = AnimaRAGPipeline()

    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        payload = json.load(sys.stdin)
        request = RAGQueryRequest(**payload)
        result = pipeline.query(request)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        for index, demo in enumerate(_demo_requests(), start=1):
            result = pipeline.query(demo)
            print(f"=== Demo {index}: {demo.question} ===")
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            print()
