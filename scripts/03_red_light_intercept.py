"""Red-Light Intercept: fast physiologic triage without LLM calls."""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TriageStatus(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"


# Symptom keywords that force immediate escalation (no LLM needed).
# Note: "heat stroke" alone is NOT here — heat is graded by vitals + severity signs.
CRITICAL_SYMPTOM_PATTERNS = (
    (re.compile(r"\b(unconscious|unresponsive|not breathing|stopped breathing)\b", re.I), "critical_consciousness"),
    (re.compile(r"(昏迷|无反应|没呼吸|停止呼吸)", re.I), "critical_consciousness"),
    (re.compile(r"\b(seizure|convuls)\w*\b", re.I), "seizure"),
    (re.compile(r"(抽搐|癫痫|癲癇)", re.I), "seizure"),
    (re.compile(r"\b(severe bleeding|uncontrolled bleeding|hemorrhag\w*)\b", re.I), "severe_bleeding"),
    (re.compile(r"(大出血|止不住血)", re.I), "severe_bleeding"),
    (re.compile(r"\b(chok\w*|can't breathe|cannot breathe|difficulty breathing|trouble breathing|respiratory distress)\b", re.I), "respiratory_distress"),
    (re.compile(r"(呼吸困难|呼吸困難|喘不过气)", re.I), "respiratory_distress"),
    (re.compile(r"\b(pois\w*|tox\w*|ingested poison|ate poison)\b", re.I), "poisoning"),
    (re.compile(r"(中毒|吃了毒药|误食毒物)", re.I), "poisoning"),
    (re.compile(r"\b(snake\s*bite|snakebite)\b", re.I), "snakebite"),
    (re.compile(r"(蛇咬)", re.I), "snakebite"),
)

# Collapse is severe when present, but heat-topic questions without collapse are graded below.
COLLAPSE_PATTERN = re.compile(
    r"\b(collapse|collapsed)\b|(虚脱|倒下|站不起来|瘫倒)",
    re.I,
)

HEAT_CONTEXT_PATTERN = re.compile(
    r"\b(heat\s*stroke|overheating|hypertherm\w*)\b|(中暑|过热|過熱|中暑怎么办|中暑怎麼辦)",
    re.I,
)

MILD_HEAT_SIGN_PATTERN = re.compile(
    r"\b(panting|drooling|hot skin|seek shade)\b|(喘气|流口水|热喘息|避暑)",
    re.I,
)

WARNING_SYMPTOM_PATTERNS = (
    (re.compile(r"\b(vomit\w*|letharg\w*|weakness|pale gums)\b", re.I), "general_warning"),
    (re.compile(r"(呕吐|嗜睡|乏力|苍白|蒼白)", re.I), "general_warning"),
    (re.compile(r"\b(shock|hypotherm\w*|cold to touch)\b", re.I), "circulatory_warning"),
)

INGESTION_CUE_PATTERN = re.compile(
    r"\b(ate|eaten|eat(?:ing)?|ingest\w*|chew\w*|swallow\w*|gnaw\w*)\b|"
    r"(吃了|误食|吞了|啃了|咬了|嚼了)",
    re.I,
)

# Capture "ate X" / "吃了X" as a whole phrase for UI chips (not bare "吃了").
INGESTION_OBJECT_PATTERN = re.compile(
    r"(?:吃了|误食|吞了|啃了|咬了|嚼了)\s*([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\-_]{0,19})"
    r"|"
    r"\b(?:ate|eaten|ingest(?:ed|ing)?|chewed|swallowed)\s+(?:some\s+|the\s+|a\s+|an\s+)?"
    r"([A-Za-z][A-Za-z\-]{1,30})",
    re.I,
)

# Common household toxins — escalate like poisoning when mentioned with intake context,
# or as a clear exposure phrase (chocolate/grape/xylitol are high-risk for pets).
TOXIC_FOOD_PATTERNS = (
    (
        re.compile(
            r"(吃了|误食|吞了|啃了).{0,8}(巧克力|可可)|"
            r"(巧克力|可可).{0,8}(吃|误食|吞)|"
            r"\b(ate|eaten|ingest\w*|chew\w*).{0,24}\b(chocolate|cocoa|theobromine)\b|"
            r"\b(chocolate|cocoa|theobromine)\b.{0,24}\b(ate|eaten|ingest\w*|chew\w*|poison)",
            re.I,
        ),
        "poisoning",
        "吃了巧克力",
    ),
    (
        re.compile(
            r"(吃了|误食|吞了|啃了).{0,8}(葡萄干|葡萄)|"
            r"(葡萄干|葡萄).{0,8}(吃|误食|吞)|"
            r"\b(ate|eaten|ingest\w*|chew\w*).{0,24}\b(grape|raisin)s?\b|"
            r"\b(grape|raisin)s?\b.{0,24}\b(ate|eaten|ingest\w*|chew\w*|poison)",
            re.I,
        ),
        "poisoning",
        "吃了葡萄/葡萄干",
    ),
    (
        re.compile(
            r"(吃了|误食|吞了|啃了).{0,8}(洋葱|蒜|大蒜)|"
            r"\b(ate|eaten|ingest\w*|chew\w*).{0,24}\b(onion|garlic)\b",
            re.I,
        ),
        "poisoning",
        "吃了洋葱/蒜",
    ),
    (
        re.compile(
            r"(吃了|误食|吞了|啃了).{0,8}(木糖醇|无糖口香糖)|"
            r"\b(ate|eaten|ingest\w*|chew\w*).{0,24}\b(xylitol)\b|"
            r"\bxylitol\b",
            re.I,
        ),
        "poisoning",
        "误食木糖醇",
    ),
)

# Owner-reported mentation / energy — important clinical judgment signals (not red flags alone).
# Prefer longer/more specific phrases first when matching.
MENTAL_STATUS_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"精神\s*(还行|還行|尚可|还可以|還可以|不错|不錯|很好|正常|OK|ok)"), "精神还行"),
    (re.compile(r"精神\s*(萎靡|很差|不好|差|差|不佳|不好)"), "精神差"),
    (re.compile(r"精神\s*(变差|變差|变差了|變差了)"), "精神变差"),
    (
        re.compile(
            r"\b(alert|responsive|still\s+ok|doing\s+ok|acting\s+normal|normal\s+energy)\b",
            re.I,
        ),
        "精神还行",
    ),
    (
        re.compile(
            r"\b(lethargic|lethargy|depressed|listless|weak\s+and\s+quiet|not\s+himself|not\s+herself)\b",
            re.I,
        ),
        "精神差",
    ),
)

# Patterns used to extract symptom keywords from free-text descriptions (no user keyword field).
# NOTE: bare ingestion cues like "吃了" are NOT listed — use INGESTION_OBJECT_PATTERN instead.
_EXTRACTION_PATTERNS = (
    *(pattern for pattern, _code in CRITICAL_SYMPTOM_PATTERNS),
    COLLAPSE_PATTERN,
    HEAT_CONTEXT_PATTERN,
    MILD_HEAT_SIGN_PATTERN,
    *(pattern for pattern, _code in WARNING_SYMPTOM_PATTERNS),
    *(pattern for pattern, _code, _label in TOXIC_FOOD_PATTERNS),
)


def extract_symptom_keywords(*texts: str) -> List[str]:
    """Pull known triage symptom phrases from free-text complaint / question."""
    blob = " ".join(part for part in texts if part).strip()
    if not blob:
        return []
    found: List[str] = []
    seen = set()

    def _add(phrase: str) -> None:
        phrase = (phrase or "").strip()
        if not phrase:
            return
        # Never surface bare ingestion verbs as the symptom chip.
        if INGESTION_CUE_PATTERN.fullmatch(phrase):
            return
        key = phrase.casefold()
        if key not in seen:
            seen.add(key)
            found.append(phrase)

    for pattern, _code, label in TOXIC_FOOD_PATTERNS:
        if pattern.search(blob):
            _add(label)

    for match in INGESTION_OBJECT_PATTERN.finditer(blob):
        obj = (match.group(1) or match.group(2) or "").strip()
        if not obj:
            continue
        # Prefer Chinese full phrase when match is CJK object.
        if match.group(1):
            _add(f"吃了{obj}")
        else:
            _add(f"ate {obj}")

    for pattern, label in MENTAL_STATUS_PATTERNS:
        if pattern.search(blob):
            _add(label)

    for pattern in _EXTRACTION_PATTERNS:
        for match in pattern.finditer(blob):
            _add(match.group(0).strip())

    return found



@dataclass
class PatientVitals:
    """Observed or owner-reported patient data for triage."""

    species: str
    size: Optional[str] = None  # small | large (dogs)
    heart_rate_bpm: Optional[float] = None
    crt_seconds: Optional[float] = None
    rectal_temp_f: Optional[float] = None
    rectal_temp_c: Optional[float] = None
    map_mmhg: Optional[float] = None
    symptoms: List[str] = field(default_factory=list)
    chief_complaint: str = ""


@dataclass
class TriageAlert:
    severity: TriageStatus
    code: str
    message: str
    metric_id: Optional[str] = None
    observed: Optional[Any] = None
    reference: Optional[Any] = None


@dataclass
class RedLightResult:
    status: TriageStatus
    intercept: bool
    alerts: List[TriageAlert]
    matched_red_flags: List[str]
    elapsed_ms: float
    recommendation: str
    llm_required: bool
    evaluated_at: str
    recommendation_zh: str = ""
    recommendation_en: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "intercept": self.intercept,
            "alerts": [
                {
                    "severity": alert.severity.value,
                    "code": alert.code,
                    "message": alert.message,
                    "metric_id": alert.metric_id,
                    "observed": alert.observed,
                    "reference": alert.reference,
                }
                for alert in self.alerts
            ],
            "matched_red_flags": self.matched_red_flags,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "recommendation": self.recommendation,
            "recommendation_zh": self.recommendation_zh or self.recommendation,
            "recommendation_en": self.recommendation_en or self.recommendation,
            "llm_required": self.llm_required,
            "evaluated_at": self.evaluated_at,
        }


class RedLightIntercept:
    """Evaluate vitals and symptoms against Merck reference metrics in <500ms."""

    MAX_ELAPSED_MS = 500.0

    def __init__(
        self,
        metrics_path: Optional[str] = None,
        toxic_plants_path: Optional[str] = None,
    ) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.metrics_path = metrics_path or os.path.join(
            project_root, "data", "triage_tree", "merck_red_light_metrics.json"
        )
        self.toxic_plants_path = toxic_plants_path or os.path.join(
            project_root, "data", "triage_tree", "aspca_toxic_plants.json"
        )
        self._index = self._load_index()
        self._toxic_aliases = self._load_toxic_aliases()

    def _load_index(self) -> Dict[str, Any]:
        with open(self.metrics_path, encoding="utf-8") as metrics_file:
            data = json.load(metrics_file)
        by_id = {metric["id"]: metric for metric in data.get("metrics", [])}
        return {
            "metrics_by_id": by_id,
            "red_flag_indicators": data.get("red_flag_indicators", []),
            "generated_at": data.get("generated_at"),
        }

    def _load_toxic_aliases(self) -> List[Dict[str, Any]]:
        """Load ASPCA toxic-plant aliases for absolute RED matching (Task 0.2)."""
        path = self.toxic_plants_path
        if not os.path.isfile(path):
            logger.warning(
                "ASPCA toxic plant index missing (%s). "
                "Run: python scripts/10_scrape_aspca_toxic.py",
                path,
            )
            return []
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load toxic plant index: %s", exc)
            return []

        compiled: List[Dict[str, Any]] = []
        for entry in payload.get("aliases") or []:
            alias = str(entry.get("alias") or "").strip()
            if len(alias) < 2:
                continue
            if any("\u4e00" <= ch <= "\u9fff" for ch in alias):
                pattern = re.compile(re.escape(alias))
            else:
                escaped = re.escape(alias.casefold()).replace(r"\ ", r"\s+")
                pattern = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.I)
            compiled.append(
                {
                    "alias": alias,
                    "ambiguous": bool(entry.get("ambiguous")),
                    "common_name": entry.get("common_name") or alias,
                    "toxic_to": entry.get("toxic_to") or [],
                    "url": entry.get("url"),
                    "pattern": pattern,
                }
            )
        logger.info("Loaded %d ASPCA toxic-plant aliases for Red-Light", len(compiled))
        return compiled

    def _match_toxic_plant(
        self, text: str, species: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not text or not self._toxic_aliases:
            return None
        has_ingestion = bool(INGESTION_CUE_PATTERN.search(text))
        species_norm = (species or "").strip().lower()
        for entry in self._toxic_aliases:
            toxic_to = [s.lower() for s in (entry.get("toxic_to") or [])]
            if species_norm in {"dog", "cat"} and toxic_to and species_norm not in toxic_to:
                continue
            match = entry["pattern"].search(text)
            if not match:
                continue
            if entry.get("ambiguous") and not has_ingestion:
                continue
            return {
                "alias": match.group(0),
                "common_name": entry["common_name"],
                "url": entry.get("url"),
            }
        return None

    @staticmethod
    def _normalize_species(species: str) -> str:
        value = species.strip().lower()
        if value in {"dog", "canine", "puppy"}:
            return "dog"
        if value in {"cat", "feline", "kitten"}:
            return "cat"
        return value

    @staticmethod
    def _normalize_size(size: Optional[str]) -> Optional[str]:
        if not size:
            return None
        value = size.strip().lower()
        if value in {"small", "sm", "toy", "mini"}:
            return "small"
        if value in {"large", "lg", "giant"}:
            return "large"
        return value

    def _select_hr_reference(
        self, patient: PatientVitals
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        metrics = self._index["metrics_by_id"]
        species = self._normalize_species(patient.species)
        size = self._normalize_size(patient.size)

        normal_key = None
        if species == "dog":
            if size == "small":
                normal_key = "heart_rate_small_dog_normal_bpm"
            elif size == "large":
                normal_key = "heart_rate_large_dog_normal_bpm"
            tach_key = "heart_rate_dog_tachycardia_bpm"
        elif species == "cat":
            normal_key = "heart_rate_cat_normal_bpm"
            tach_key = None
        else:
            normal_key = None
            tach_key = None

        normal = metrics.get(normal_key) if normal_key else None
        tach = metrics.get(tach_key) if tach_key else None
        if species == "cat":
            tach = metrics.get("heart_rate_cat_normal_bpm")
        return normal, tach

    def _check_range_violation(
        self,
        value: float,
        metric: Dict[str, Any],
        below_severity: TriageStatus = TriageStatus.YELLOW,
        above_severity: TriageStatus = TriageStatus.YELLOW,
    ) -> Optional[TriageAlert]:
        metric_id = metric.get("id")
        min_val = metric.get("min")
        max_val = metric.get("max")
        label = metric.get("metric", metric_id)

        if min_val is not None and value < min_val:
            return TriageAlert(
                severity=below_severity,
                code=f"{label}_below_normal",
                message=f"{label} {value} is below reference range ({min_val}-{max_val})",
                metric_id=metric_id,
                observed=value,
                reference={"min": min_val, "max": max_val},
            )
        if max_val is not None and value > max_val:
            return TriageAlert(
                severity=above_severity,
                code=f"{label}_above_normal",
                message=f"{label} {value} is above reference range ({min_val}-{max_val})",
                metric_id=metric_id,
                observed=value,
                reference={"min": min_val, "max": max_val},
            )
        return None

    def _evaluate_vitals(self, patient: PatientVitals) -> List[TriageAlert]:
        alerts: List[TriageAlert] = []
        metrics = self._index["metrics_by_id"]

        if patient.heart_rate_bpm is not None:
            hr = patient.heart_rate_bpm
            normal, tach = self._select_hr_reference(patient)
            species = self._normalize_species(patient.species)

            if species == "dog" and tach and tach.get("threshold") and hr > tach["threshold"]:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="heart_rate_tachycardia",
                        message=(
                            f"Heart rate {hr} bpm exceeds dog tachycardia threshold "
                            f"({tach['threshold']} bpm)"
                        ),
                        metric_id=tach.get("id"),
                        observed=hr,
                        reference={"threshold": tach["threshold"]},
                    )
                )
            elif species == "cat" and hr > 220:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="heart_rate_tachycardia",
                        message=f"Heart rate {hr} bpm exceeds cat tachycardia threshold (220 bpm)",
                        metric_id="heart_rate_cat_normal_bpm",
                        observed=hr,
                        reference={"threshold": 220},
                    )
                )
            elif species == "cat" and hr < 120:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="heart_rate_bradycardia_shock",
                        message=(
                            f"Heart rate {hr} bpm is bradycardic for a cat in possible shock "
                            "(< 120 bpm)"
                        ),
                        metric_id="heart_rate_cat_normal_bpm",
                        observed=hr,
                        reference={"threshold": 120},
                    )
                )
            elif species == "dog" and hr < 60:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="heart_rate_bradycardia",
                        message=f"Heart rate {hr} bpm is critically low for a dog (< 60 bpm)",
                        metric_id=normal.get("id") if normal else None,
                        observed=hr,
                        reference={"threshold": 60},
                    )
                )
            elif normal:
                violation = self._check_range_violation(
                    hr,
                    normal,
                    below_severity=TriageStatus.YELLOW,
                    above_severity=TriageStatus.YELLOW,
                )
                if violation:
                    alerts.append(violation)

        if patient.crt_seconds is not None:
            crt_metric = metrics.get("crt_normal_seconds")
            crt = patient.crt_seconds
            if crt > 2.0:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="crt_prolonged",
                        message=f"CRT {crt}s indicates poor perfusion (> 2s)",
                        metric_id=crt_metric.get("id") if crt_metric else None,
                        observed=crt,
                        reference={"max": 2.0},
                    )
                )
            elif crt < 1.0:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.YELLOW,
                        code="crt_hyperdynamic",
                        message=f"CRT {crt}s is hyperdynamic (< 1s)",
                        metric_id=crt_metric.get("id") if crt_metric else None,
                        observed=crt,
                        reference={"min": 1.0, "max": 2.0},
                    )
                )

        if patient.rectal_temp_f is not None:
            temp_metric = metrics.get("rectal_temp_dog_cat_f")
            temp_f = patient.rectal_temp_f
            if temp_f >= 104.0:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="hyperthermia_critical",
                        message=(
                            f"Rectal temperature {temp_f}°F indicates severe hyperthermia "
                            "(>= 104°F). Seek emergency care now."
                        ),
                        metric_id=temp_metric.get("id") if temp_metric else None,
                        observed=temp_f,
                        reference={"critical_threshold_f": 104.0},
                    )
                )
            elif temp_f >= 103.0:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.YELLOW,
                        code="hyperthermia_moderate",
                        message=(
                            f"Rectal temperature {temp_f}°F is elevated (103–104°F). "
                            "Begin cooling and reassess severity signs."
                        ),
                        metric_id=temp_metric.get("id") if temp_metric else None,
                        observed=temp_f,
                        reference={"moderate_threshold_f": 103.0},
                    )
                )
            elif temp_metric:
                violation = self._check_range_violation(
                    temp_f,
                    temp_metric,
                    below_severity=TriageStatus.YELLOW,
                    above_severity=TriageStatus.YELLOW,
                )
                if violation:
                    alerts.append(violation)

        if patient.rectal_temp_c is not None and patient.rectal_temp_f is None:
            temp_c = patient.rectal_temp_c
            if temp_c >= 40.0:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="hyperthermia_critical_c",
                        message=(
                            f"Rectal temperature {temp_c}°C indicates severe hyperthermia "
                            "(>= 40°C). Seek emergency care now."
                        ),
                        observed=temp_c,
                        reference={"critical_threshold_c": 40.0},
                    )
                )
            elif temp_c >= 39.5:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.YELLOW,
                        code="hyperthermia_moderate_c",
                        message=(
                            f"Rectal temperature {temp_c}°C is elevated. "
                            "Begin cooling and reassess severity signs."
                        ),
                        observed=temp_c,
                        reference={"moderate_threshold_c": 39.5},
                    )
                )

        if patient.rectal_temp_c is not None:
            rewarm_metric = metrics.get("hypothermia_rewarm_c")
            temp_c = patient.rectal_temp_c
            threshold = rewarm_metric.get("threshold") if rewarm_metric else 36.5
            if temp_c <= threshold:
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.YELLOW,
                        code="hypothermia_rewarm_needed",
                        message=(
                            f"Rectal temperature {temp_c}°C is at/below rewarming target "
                            f"(> {threshold}°C)"
                        ),
                        metric_id=rewarm_metric.get("id") if rewarm_metric else None,
                        observed=temp_c,
                        reference={"threshold": threshold},
                    )
                )

        if patient.map_mmhg is not None:
            map_value = patient.map_mmhg
            if map_value < 60:
                low_metric = metrics.get("map_low_normal_mmhg")
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code="map_hypotension",
                        message=f"Mean arterial pressure {map_value} mmHg indicates hypotension (< 60)",
                        metric_id=low_metric.get("id") if low_metric else None,
                        observed=map_value,
                        reference={"min": 60},
                    )
                )

        return alerts

    def _evaluate_symptoms(self, patient: PatientVitals) -> Tuple[List[TriageAlert], List[str]]:
        text = " ".join(
            [patient.chief_complaint, *patient.symptoms]
        ).strip()
        if not text:
            return [], []

        alerts: List[TriageAlert] = []
        matched_flags: List[str] = []

        for pattern, code in CRITICAL_SYMPTOM_PATTERNS:
            match = pattern.search(text)
            if match:
                phrase = match.group(0)
                matched_flags.append(phrase)
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.RED,
                        code=code,
                        message=f"Critical symptom detected: '{phrase}'",
                        observed=phrase,
                    )
                )

        for pattern, code, label in TOXIC_FOOD_PATTERNS:
            if pattern.search(text):
                if label not in matched_flags:
                    matched_flags.append(label)
                # Avoid duplicate poisoning alerts if already matched via CRITICAL.
                if not any(a.code == code and a.observed == label for a in alerts):
                    alerts.append(
                        TriageAlert(
                            severity=TriageStatus.RED,
                            code=code,
                            message=f"Critical toxin exposure detected: '{label}'",
                            observed=label,
                        )
                    )

        heat_alerts, heat_flags = self._grade_heat_severity(patient, text)
        alerts.extend(heat_alerts)
        for flag in heat_flags:
            if flag not in matched_flags:
                matched_flags.append(flag)

        # Collapse outside heat context remains RED (acute emergency).
        # Inside heat context, severity is already graded by _grade_heat_severity.
        collapse_match = COLLAPSE_PATTERN.search(text)
        if collapse_match and not HEAT_CONTEXT_PATTERN.search(text):
            phrase = collapse_match.group(0)
            if phrase not in matched_flags:
                matched_flags.append(phrase)
            alerts.append(
                TriageAlert(
                    severity=TriageStatus.RED,
                    code="collapse",
                    message=f"Critical symptom detected: '{phrase}'",
                    observed=phrase,
                )
            )

        for pattern, code in WARNING_SYMPTOM_PATTERNS:
            match = pattern.search(text)
            if match:
                phrase = match.group(0)
                if phrase not in matched_flags:
                    matched_flags.append(phrase)
                alerts.append(
                    TriageAlert(
                        severity=TriageStatus.YELLOW,
                        code=code,
                        message=f"Warning symptom detected: '{phrase}'",
                        observed=phrase,
                    )
                )

        toxic_hit = self._match_toxic_plant(text, patient.species)
        if toxic_hit:
            phrase = toxic_hit["alias"]
            if phrase not in matched_flags:
                matched_flags.append(phrase)
            plant_name = toxic_hit["common_name"]
            alerts.append(
                TriageAlert(
                    severity=TriageStatus.RED,
                    code="aspca_toxic_plant",
                    message=(
                        f"ASPCA toxic plant match: '{phrase}' "
                        f"(listed as {plant_name})"
                    ),
                    observed=phrase,
                    reference={
                        "common_name": plant_name,
                        "source": "ASPCA",
                        "url": toxic_hit.get("url"),
                    },
                )
            )

        return alerts, matched_flags

    def _grade_heat_severity(
        self, patient: PatientVitals, text: str
    ) -> Tuple[List[TriageAlert], List[str]]:
        """Self-check grading for heat/中暑: mild advice vs RED emergency.

        Severe (RED): temp >=104°F / >=40°C, or heat + collapse/unconscious/seizure/distress.
        Moderate (YELLOW): heat context with elevated temp or mild heat signs — allow RAG advice.
        Mild/ask-only (YELLOW guidance): "中暑怎么办" without severe signs — allow RAG, no intercept.
        """
        heat_match = HEAT_CONTEXT_PATTERN.search(text)
        if not heat_match:
            return [], []

        alerts: List[TriageAlert] = []
        flags: List[str] = [heat_match.group(0)]
        phrase = heat_match.group(0)

        temp_f = patient.rectal_temp_f
        temp_c = patient.rectal_temp_c
        if temp_f is None and temp_c is not None:
            temp_f = temp_c * 9.0 / 5.0 + 32.0

        has_collapse = bool(COLLAPSE_PATTERN.search(text))
        has_critical_neuro = bool(
            re.search(
                r"\b(unconscious|unresponsive|seizure|convuls)\w*\b|(昏迷|无反应|抽搐|癫痫)",
                text,
                re.I,
            )
        )
        has_resp = bool(
            re.search(
                r"\b(not breathing|difficulty breathing|respiratory distress)\b|(呼吸困难|没呼吸)",
                text,
                re.I,
            )
        )
        severe_vitals = (temp_f is not None and temp_f >= 104.0) or (
            temp_c is not None and temp_c >= 40.0
        )

        if severe_vitals or has_collapse or has_critical_neuro or has_resp:
            reasons = []
            if severe_vitals:
                reasons.append("critical temperature")
            if has_collapse:
                reasons.append("collapse")
            if has_critical_neuro:
                reasons.append("altered consciousness/seizure")
            if has_resp:
                reasons.append("respiratory distress")
            alerts.append(
                TriageAlert(
                    severity=TriageStatus.RED,
                    code="heat_stroke_severe",
                    message=(
                        f"Severe heat illness suspected ('{phrase}' + {', '.join(reasons)}). "
                        "Cool while transporting to emergency care now."
                    ),
                    observed={"temp_f": temp_f, "reasons": reasons},
                )
            )
            return alerts, flags

        mild_signs = MILD_HEAT_SIGN_PATTERN.search(text)
        moderate_temp = temp_f is not None and temp_f >= 102.5
        if mild_signs or moderate_temp:
            detail = []
            if mild_signs:
                detail.append(mild_signs.group(0))
                flags.append(mild_signs.group(0))
            if moderate_temp:
                detail.append(f"temp {temp_f}°F")
            alerts.append(
                TriageAlert(
                    severity=TriageStatus.YELLOW,
                    code="heat_stress_mild_moderate",
                    message=(
                        f"Possible mild/moderate heat stress ('{phrase}'; {', '.join(detail) or 'no severe signs'}). "
                        "Self-check: still responsive? walking? pink gums? temp <104°F? "
                        "If yes → cool, shade, water, monitor. If collapse/coma/temp≥104°F → emergency."
                    ),
                    observed={"temp_f": temp_f, "detail": detail},
                )
            )
            return alerts, flags

        # Asking about heat stroke without severe signs — guide self-assessment, allow RAG.
        alerts.append(
            TriageAlert(
                severity=TriageStatus.YELLOW,
                code="heat_self_assessment",
                message=(
                    f"Heat-related question ('{phrase}') without severe signs yet. "
                    "Confirm status: 1) rectal temp 2) consciousness 3) collapse/seizure "
                    "4) gum color/breathing. Mild panting only → cooling advice. "
                    "Temp≥104°F / collapse / unconscious → RED emergency."
                ),
                observed=phrase,
            )
        )
        return alerts, flags

    @staticmethod
    def _aggregate_status(alerts: List[TriageAlert]) -> TriageStatus:
        if any(alert.severity == TriageStatus.RED for alert in alerts):
            return TriageStatus.RED
        if any(alert.severity == TriageStatus.YELLOW for alert in alerts):
            return TriageStatus.YELLOW
        return TriageStatus.GREEN

    @staticmethod
    def _recommendation(status: TriageStatus, alerts: List[TriageAlert]) -> Tuple[str, str]:
        """Return (recommendation_zh, recommendation_en).

        Priority for RED copy: toxin/poison/snakebite > other critical symptoms >
        heat/hyperthermia > generic. Vital-only hyperthermia must not override an
        explicit poisoning complaint (common when the UI keeps prior heat vitals).
        """
        codes = {alert.code for alert in alerts}
        heat_codes = {
            "heat_stroke_severe",
            "heat_stress_mild_moderate",
            "heat_self_assessment",
            "hyperthermia_critical",
            "hyperthermia_critical_c",
            "hyperthermia_moderate",
            "hyperthermia_moderate_c",
        }
        poison_codes = {"poisoning", "aspca_toxic_plant", "snakebite"}
        heat_related = bool(codes & heat_codes)
        poison_related = bool(codes & poison_codes)
        toxic_plant = "aspca_toxic_plant" in codes
        seizure_related = "seizure" in codes or "critical_consciousness" in codes
        bleed_related = "severe_bleeding" in codes
        airway_related = "respiratory_distress" in codes

        if status == TriageStatus.RED:
            if toxic_plant:
                return (
                    "RED — 疑似 ASPCA 名录有毒植物暴露：立即送急诊，并尽量带上植物样本/照片。"
                    "可同时联系 ASPCA Animal Poison Control（888-426-4435）。不要等待 AI 建议。",
                    "RED — Suspected ASPCA-listed toxic plant exposure: seek emergency care now. "
                    "Bring a plant sample/photo if safe. You may also contact ASPCA Animal Poison "
                    "Control at (888) 426-4435. Do not wait for AI advice.",
                )
            if poison_related:
                return (
                    "RED — 疑似中毒/毒物暴露：立即送兽医急诊。尽量带上毒物包装、剩余物或呕吐物样本；"
                    "途中稳住气道、呼吸与循环。未经兽医指示不要自行催吐或乱用药。不要等待 AI 建议。",
                    "RED — Suspected poisoning/toxin exposure: seek emergency veterinary care now. "
                    "Bring packaging, remnants, or vomit sample if safe. Stabilize ABC in transit. "
                    "Do not induce vomiting or give remedies unless a veterinarian instructs. "
                    "Do not wait for AI advice.",
                )
            if airway_related:
                return (
                    "RED — 呼吸窘迫：立即送急诊，保持气道通畅，避免强行喂食喂水。不要等待 AI 建议。",
                    "RED — Respiratory distress: seek emergency care now. Keep the airway clear; "
                    "do not force food or water. Do not wait for AI advice.",
                )
            if bleed_related:
                return (
                    "RED — 严重出血：立即送急诊；可用干净敷料轻压止血，途中注意保温。不要等待 AI 建议。",
                    "RED — Severe bleeding: seek emergency care now. Apply gentle pressure with a "
                    "clean dressing and keep the animal warm in transit. Do not wait for AI advice.",
                )
            if seizure_related:
                return (
                    "RED — 抽搐/意识改变：立即送急诊。保护周围避免二次伤害，不要强塞物品入口。不要等待 AI 建议。",
                    "RED — Seizure / altered consciousness: seek emergency care now. Protect from "
                    "injury; do not put objects in the mouth. Do not wait for AI advice.",
                )
            if heat_related:
                return (
                    "RED — 重度中暑/严重过热：立即送急诊。途中移至阴凉、用室温水打湿身体、"
                    "加强通风；勿投冰水强灌。不要等待 AI 建议。",
                    "RED — Severe heat stroke / critical hyperthermia: seek emergency care now. "
                    "Move to shade, wet the coat with room-temperature water, increase airflow; "
                    "do not force ice water. Do not wait for AI advice.",
                )
            return (
                "RED — 紧急：请立即送兽医急诊。先稳住气道、呼吸、循环（ABC），不要等待 AI 分诊。",
                "RED LIGHT: Immediate emergency veterinary care. Do not wait for LLM triage. "
                "Stabilize ABC (airway, breathing, circulation) and transport to clinic now.",
            )
        if status == TriageStatus.YELLOW:
            if heat_related and not poison_related:
                return (
                    "YELLOW — 疑似轻/中度热应激：先自行确认（体温、神志、是否虚脱）。"
                    "仍清醒可走、牙龈粉红、体温 <104°F → 阴凉、室温水降温、少量饮水、持续观察。"
                    "若出现虚脱、昏迷、抽搐或体温 ≥104°F → 立即升级为 RED 送医。"
                    "可继续查看知识库降温建议。",
                    "YELLOW — Possible mild/moderate heat stress: self-check temperature, "
                    "consciousness, and collapse. If still responsive, pink gums, temp <104°F → "
                    "shade, room-temp water cooling, small sips of water, monitor closely. "
                    "If collapse, coma, seizure, or temp ≥104°F → escalate to RED emergency. "
                    "Knowledge-base cooling advice may follow.",
                )
            return (
                "YELLOW — 建议尽快就医评估，持续观察；可继续 AI 辅助分诊，但随时准备升级。",
                "YELLOW: Urgent veterinary evaluation recommended. Monitor closely; "
                "LLM-assisted triage may proceed but escalation should remain available.",
            )
        return (
            "GREEN — 依目前提供的体征/症状，未见立即红灯触发，可进行常规知识库分诊。",
            "GREEN: No immediate red-light triggers detected from supplied vitals/symptoms. "
            "Safe to proceed with standard LLM-assisted triage.",
        )

    def evaluate(self, patient: PatientVitals) -> RedLightResult:
        """Run Red-Light checks. Target runtime: well under 500ms."""
        start = time.perf_counter()

        vital_alerts = self._evaluate_vitals(patient)
        symptom_alerts, matched_flags = self._evaluate_symptoms(patient)
        alerts = vital_alerts + symptom_alerts
        status = self._aggregate_status(alerts)
        intercept = status == TriageStatus.RED
        elapsed_ms = (time.perf_counter() - start) * 1000
        rec_zh, rec_en = self._recommendation(status, alerts)

        if elapsed_ms > self.MAX_ELAPSED_MS:
            logger.warning(
                "Red-Light evaluation exceeded budget: %.2fms > %.0fms",
                elapsed_ms,
                self.MAX_ELAPSED_MS,
            )

        return RedLightResult(
            status=status,
            intercept=intercept,
            alerts=alerts,
            matched_red_flags=matched_flags,
            elapsed_ms=elapsed_ms,
            recommendation=rec_zh,
            recommendation_zh=rec_zh,
            recommendation_en=rec_en,
            llm_required=not intercept,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )


def _demo_cases() -> List[Tuple[str, PatientVitals]]:
    return [
        (
            "Normal small dog",
            PatientVitals(
                species="dog",
                size="small",
                heart_rate_bpm=90,
                crt_seconds=1.5,
                rectal_temp_f=101.8,
                chief_complaint="Mild limping after walk",
            ),
        ),
        (
            "Dog tachycardia + prolonged CRT",
            PatientVitals(
                species="dog",
                size="large",
                heart_rate_bpm=200,
                crt_seconds=3.0,
                symptoms=["pale gums", "weakness"],
                chief_complaint="Collapse after car ride",
            ),
        ),
        (
            "Cat bradycardia in shock",
            PatientVitals(
                species="cat",
                heart_rate_bpm=100,
                crt_seconds=2.5,
                chief_complaint="Found unresponsive, cold paws",
            ),
        ),
        (
            "Heat stroke dog — severe",
            PatientVitals(
                species="dog",
                heart_rate_bpm=170,
                rectal_temp_f=105.2,
                chief_complaint="Heat stroke after hiking, rapid panting and collapse",
            ),
        ),
        (
            "Heat stress — mild ask",
            PatientVitals(
                species="dog",
                heart_rate_bpm=120,
                rectal_temp_f=102.8,
                chief_complaint="中暑怎么办？散步后喘气、流口水，仍清醒能走",
                symptoms=["panting", "drooling"],
            ),
        ),
        (
            "Poisoning symptom only",
            PatientVitals(
                species="dog",
                chief_complaint="Ate rat poison 20 minutes ago, vomiting",
            ),
        ),
    ]


if __name__ == "__main__":
    intercept = RedLightIntercept()
    print(f"Loaded metrics from: {intercept.metrics_path}\n")

    for label, case in _demo_cases():
        result = intercept.evaluate(case)
        print(f"=== {label} ===")
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        print()
