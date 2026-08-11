#!/usr/bin/env python3
"""Build owner-complaint → clinical-term map (Task 0.3).

Primary open sources used here:
  1) HuggingFace `karenwky/pet-health-symptoms-dataset` (MIT)
     — 2000 rows pairing Owner Observation vs Clinical Notes by condition
  2) Curated bilingual lexicon (ZH/EN common owner phrases → clinical terms)
  3) Optional Kaggle `gracehephzibahm/animal-disease` when ~/.kaggle/kaggle.json exists

Outputs:
  - data/raw/pet_health_symptoms_hf.jsonl   (cached HF source)
  - data/raw/kaggle_animal_disease/…       (optional)
  - data/processed/complaint_clinical_map.csv
  - data/triage_tree/complaint_clinical_map.json

Usage:
  python scripts/11_build_complaint_map.py
  python scripts/11_build_complaint_map.py --seed-only
  python scripts/11_build_complaint_map.py --with-kaggle
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
TRIAGE_DIR = PROJECT_ROOT / "data" / "triage_tree"
HF_JSONL = RAW_DIR / "pet_health_symptoms_hf.jsonl"
CSV_OUT = PROCESSED_DIR / "complaint_clinical_map.csv"
JSON_OUT = TRIAGE_DIR / "complaint_clinical_map.json"
KAGGLE_DIR = RAW_DIR / "kaggle_animal_disease"
KAGGLE_DATASET = "gracehephzibahm/animal-disease"
# Public redistributions with the same AnimalName/symptoms1-5/Dangerous schema.
KAGGLE_MIRROR_URLS = (
    "https://raw.githubusercontent.com/IbrahimBagwan1/animal-health-prediction-ml/main/data.csv",
    "https://cdn.jsdelivr.net/gh/IbrahimBagwan1/animal-health-prediction-ml@main/data.csv",
)
PET_ANIMALS = {"dog", "cat", "dogs", "cats"}

# Clinical keyword mining from clinical-note text.
CLINICAL_TERM_RE = re.compile(
    r"\b("
    r"pruritus|alopecia|dermatitis|otitis|otorrhea|pyoderma|gastritis|"
    r"enteritis|gastroenteritis|diarrhea|diarrhoea|vomiting|emesis|"
    r"hematochezia|hematemesis|anorexia|lethargy|ataxia|lameness|"
    r"paresis|paralysis|dyspnea|tachypnea|tachycardia|bradycardia|"
    r"dehydration|obstruction|parasite|flea|tick|mite|mange|helminth|"
    r"roundworm|hookworm|whipworm|coccidia|giardia|anemia|anaemia|"
    r"seizure|epilepsy|pyrexia|fever|inflammation|infection|"
    r"mobility|arthritis|dysplasia|trauma|fracture|abscess"
    r")\b",
    re.I,
)

# Curated bilingual owner phrases → clinical retrieval terms.
CURATED_ENTRIES: List[Dict[str, Any]] = [
    {
        "complaint": "吐黄水",
        "aliases": ["吐黄色的水", "吐黄沫", "vomit yellow water", "yellow vomit", "bile vomit"],
        "clinical_terms": [
            "bilious vomiting",
            "bile",
            "gastroenteritis",
            "empty stomach vomiting",
        ],
        "condition": "Digestive Issues",
        "lang": "zh",
    },
    {
        "complaint": "拉肚子",
        "aliases": ["软便", "腹泻", "水便", "diarrhea", "loose stool", "runny poop"],
        "clinical_terms": ["diarrhea", "gastroenteritis", "enteritis", "dehydration"],
        "condition": "Digestive Issues",
        "lang": "zh",
    },
    {
        "complaint": "呕吐",
        "aliases": ["一直吐", "吐了好几次", "vomiting", "throwing up"],
        "clinical_terms": ["vomiting", "emesis", "gastroenteritis"],
        "condition": "Digestive Issues",
        "lang": "zh",
    },
    {
        "complaint": "便血",
        "aliases": ["拉血", "大便带血", "bloody stool", "blood in stool"],
        "clinical_terms": ["hematochezia", "gastrointestinal bleeding", "colitis"],
        "condition": "Digestive Issues",
        "lang": "zh",
    },
    {
        "complaint": "一直舔脚",
        "aliases": ["舔爪子", "咬脚", "lick paws", "chewing feet", "itchy paws"],
        "clinical_terms": [
            "pruritus",
            "pododermatitis",
            "allergy",
            "dermatitis",
            "yeast infection",
        ],
        "condition": "Skin Irritations",
        "lang": "zh",
    },
    {
        "complaint": "抓痒",
        "aliases": ["一直抓", "皮肤痒", "脱毛", "itchy", "scratching", "hair loss"],
        "clinical_terms": ["pruritus", "alopecia", "dermatitis", "allergy", "fleas"],
        "condition": "Skin Irritations",
        "lang": "zh",
    },
    {
        "complaint": "耳朵臭",
        "aliases": ["甩头", "抓耳朵", "耳垢多", "ear smell", "shaking head", "ear scratch"],
        "clinical_terms": ["otitis", "otorrhea", "ear infection", "yeast"],
        "condition": "Ear Infections",
        "lang": "zh",
    },
    {
        "complaint": "走路瘸",
        "aliases": ["跛行", "不敢踩", "腿痛", "limping", "lameness", "won't put weight"],
        "clinical_terms": ["lameness", "musculoskeletal pain", "arthritis", "trauma"],
        "condition": "Mobility Problems",
        "lang": "zh",
    },
    {
        "complaint": "有虫子",
        "aliases": ["绦虫", "蛔虫", "跳蚤", "worms", "fleas", "seeing worms in stool"],
        "clinical_terms": ["parasite", "helminth", "flea", "deworming"],
        "condition": "Parasites",
        "lang": "zh",
    },
    {
        "complaint": "不吃东西",
        "aliases": ["没食欲", "厌食", "not eating", "won't eat", "loss of appetite"],
        "clinical_terms": ["anorexia", "inappetence", "systemic illness"],
        "condition": "Digestive Issues",
        "lang": "zh",
    },
    {
        "complaint": "喘不过气",
        "aliases": ["呼吸困难", "喘气很重", "can't breathe", "labored breathing", "gasping"],
        "clinical_terms": ["dyspnea", "respiratory distress", "tachypnea"],
        "condition": "Respiratory",
        "lang": "zh",
    },
    {
        "complaint": "抽搐",
        "aliases": ["癫痫发作", "痉挛", "seizure", "convulsing", "fitting"],
        "clinical_terms": ["seizure", "epilepsy", "neurologic emergency"],
        "condition": "Neurologic",
        "lang": "zh",
    },
]


def ensure_hf_jsonl(force: bool = False) -> Path:
    if HF_JSONL.exists() and not force:
        logger.info("Using cached HF file: %s", HF_JSONL)
        return HF_JSONL
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading HuggingFace karenwky/pet-health-symptoms-dataset …")
    from datasets import load_dataset

    ds = load_dataset("karenwky/pet-health-symptoms-dataset", split="train")
    with HF_JSONL.open("w", encoding="utf-8") as fh:
        for row in ds:
            fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    logger.info("Wrote %s (%d rows)", HF_JSONL, len(ds))
    return HF_JSONL


def load_hf_rows(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def mine_clinical_terms(texts: Sequence[str], top_k: int = 12) -> List[str]:
    counts: Counter = Counter()
    for text in texts:
        for match in CLINICAL_TERM_RE.findall(text or ""):
            counts[match.lower()] += 1
    return [term for term, _ in counts.most_common(top_k)]


OWNER_FRAGMENT_RE = re.compile(
    r"\b("
    r"vomit(?:ing|s)?|diarrhea|diarrhoea|scratch(?:ing|es)?|itch(?:y|ing)?|"
    r"limp(?:ing)?|lame(?:ness)?|cough(?:ing)?|sneeze(?:ing)?|"
    r"hair\s*loss|not\s*eating|won't\s*eat|loss of appetite|"
    r"shaking\s*(?:its\s*)?head|ear\s*(?:smell|infection|discharge)|"
    r"bloody\s*stool|blood in (?:the )?stool|worms?|fleas?"
    r")\b",
    re.I,
)


def build_hf_entries(rows: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    by_condition: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: {"Owner Observation": [], "Clinical Notes": []}
    )
    for row in rows:
        condition = row.get("condition") or "Unknown"
        record_type = row.get("record_type") or ""
        text = (row.get("text") or "").strip()
        if text and record_type in by_condition[condition]:
            by_condition[condition][record_type].append(text)

    entries: List[Dict[str, Any]] = []
    for condition, parts in sorted(by_condition.items()):
        clinical_terms = mine_clinical_terms(parts["Clinical Notes"])
        if not clinical_terms:
            clinical_terms = [condition.lower()]

        # Condition-level aggregate (always useful for expansion).
        entries.append(
            {
                "complaint": condition,
                "aliases": [condition.lower()],
                "clinical_terms": clinical_terms,
                "condition": condition,
                "lang": "en",
                "source": "huggingface:karenwky/pet-health-symptoms-dataset",
            }
        )

        fragment_counts: Counter = Counter()
        for text in parts["Owner Observation"]:
            for match in OWNER_FRAGMENT_RE.findall(text):
                fragment_counts[match.lower()] += 1

        for fragment, _count in fragment_counts.most_common(25):
            entries.append(
                {
                    "complaint": fragment,
                    "aliases": [],
                    "clinical_terms": clinical_terms,
                    "condition": condition,
                    "lang": "en",
                    "source": "huggingface:karenwky/pet-health-symptoms-dataset",
                }
            )
    return entries


def try_download_kaggle() -> Optional[Path]:
    cred = Path.home() / ".kaggle" / "kaggle.json"
    if not cred.is_file():
        logger.warning(
            "No ~/.kaggle/kaggle.json — will try public mirror / local CSV. "
            "Official download: https://www.kaggle.com/datasets/%s",
            KAGGLE_DATASET,
        )
        return None
    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "kaggle",
        "datasets",
        "download",
        "-d",
        KAGGLE_DATASET,
        "-p",
        str(KAGGLE_DIR),
        "--unzip",
    ]
    logger.info("Running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error("Kaggle download failed: %s", exc)
        return None
    csv_files = list(KAGGLE_DIR.glob("*.csv"))
    if not csv_files:
        logger.error("No CSV found after Kaggle download in %s", KAGGLE_DIR)
        return None
    return csv_files[0]


def try_download_kaggle_mirror() -> Optional[Path]:
    """Fetch same-schema CSV from a public mirror when Kaggle API is unavailable."""
    import urllib.request

    KAGGLE_DIR.mkdir(parents=True, exist_ok=True)
    out = KAGGLE_DIR / "data.csv"
    for url in KAGGLE_MIRROR_URLS:
        try:
            logger.info("Trying Kaggle-schema mirror: %s", url)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as response:
                data = response.read()
            if len(data) < 1000:
                continue
            out.write_bytes(data)
            logger.info("Wrote mirror CSV → %s (%d bytes)", out, len(data))
            return out
        except Exception as exc:
            logger.warning("Mirror failed (%s): %s", url, exc)
    return None


def resolve_kaggle_csv(
    *,
    force_download: bool = False,
    csv_path: Optional[Path] = None,
) -> Optional[Path]:
    if csv_path and csv_path.is_file():
        return csv_path
    existing = sorted(KAGGLE_DIR.glob("*.csv")) if KAGGLE_DIR.is_dir() else []
    if existing and not force_download:
        logger.info("Using existing local Kaggle-schema CSV: %s", existing[0])
        return existing[0]
    downloaded = try_download_kaggle()
    if downloaded:
        return downloaded
    return try_download_kaggle_mirror()


def build_kaggle_entries(csv_path: Path) -> List[Dict[str, Any]]:
    """Map Animal Condition Classification rows into complaint→clinical entries.

    Prefer dog/cat rows for AnimaLink triage; still keep frequent cross-species
    symptom phrases. Dangerous=Yes symptoms get a triage_hint flag in metadata.
    """
    rows_raw: List[Dict[str, str]] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows_raw.append({k: (v or "").strip() for k, v in row.items()})

    # symptom -> related co-occurring clinical terms + danger counts
    related: Dict[str, Counter] = defaultdict(Counter)
    danger_hits: Counter = Counter()
    pet_hits: Counter = Counter()

    for row in rows_raw:
        animal = (row.get("AnimalName") or row.get("animalname") or "").strip()
        animal_l = animal.casefold()
        is_pet = animal_l in PET_ANIMALS
        symptoms = []
        for key, value in row.items():
            if key and key.lower().startswith("symptom") and value:
                symptoms.append(value)
        if len(symptoms) < 1:
            continue
        dangerous = (row.get("Dangerous") or row.get("dangerous") or "").strip().casefold()
        is_danger = dangerous in {"yes", "y", "true", "1"}
        weight = 3 if is_pet else 1
        for symptom in symptoms:
            key = symptom.casefold()
            pet_hits[key] += weight if is_pet else 0
            if is_danger:
                danger_hits[key] += weight
            for other in symptoms:
                if other.casefold() == key:
                    continue
                related[key][other.casefold()] += weight

    entries: List[Dict[str, Any]] = []
    # Keep symptoms that appear in pet rows, or are frequent overall.
    candidates = sorted(
        related.keys(),
        key=lambda s: (pet_hits[s], sum(related[s].values()), len(s)),
        reverse=True,
    )
    for symptom in candidates:
        if pet_hits[symptom] <= 0 and sum(related[symptom].values()) < 4:
            continue
        co_terms = [term for term, _ in related[symptom].most_common(8)]
        clinical = [symptom, *co_terms]
        # Deduplicate while preserving order
        seen: Set[str] = set()
        clinical_terms: List[str] = []
        for term in clinical:
            if term not in seen:
                seen.add(term)
                clinical_terms.append(term)
        entries.append(
            {
                "complaint": symptom,
                "aliases": [],
                "clinical_terms": clinical_terms,
                "condition": "KaggleAnimalDisease",
                "lang": "en",
                "source": f"kaggle:{KAGGLE_DATASET}",
                "dangerous": "Yes" if danger_hits[symptom] >= 2 else "No",
            }
        )
        if len(entries) >= 250:
            break

    logger.info(
        "Loaded %d Kaggle-derived symptom entries from %s (raw rows=%d)",
        len(entries),
        csv_path,
        len(rows_raw),
    )
    return entries


def curated_entries() -> List[Dict[str, Any]]:
    out = []
    for item in CURATED_ENTRIES:
        out.append({**item, "source": "curated_bilingual"})
    return out


def compile_index(entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    patterns: List[Dict[str, Any]] = []
    for entry in entries:
        phrases = [entry["complaint"], *entry.get("aliases", [])]
        for phrase in phrases:
            phrase = (phrase or "").strip()
            if len(phrase) < 2:
                continue
            patterns.append(
                {
                    "phrase": phrase,
                    "phrase_norm": phrase.casefold(),
                    "clinical_terms": entry.get("clinical_terms") or [],
                    "condition": entry.get("condition"),
                    "source": entry.get("source"),
                    "lang": entry.get("lang"),
                }
            )
    # Longer phrases first for matcher.
    patterns.sort(key=lambda p: len(p["phrase_norm"]), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Owner complaint → clinical term map for retrieval expansion "
            "(Task 0.3). Curated ZH/EN + HF pet-health-symptoms; optional Kaggle."
        ),
        "entry_count": len(entries),
        "pattern_count": len(patterns),
        "sources": sorted({e.get("source") or "" for e in entries}),
        "entries": list(entries),
        "patterns": patterns,
    }


def write_outputs(index: Dict[str, Any]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    TRIAGE_DIR.mkdir(parents=True, exist_ok=True)
    with JSON_OUT.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)

    with CSV_OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "complaint",
                "aliases",
                "clinical_terms",
                "condition",
                "lang",
                "source",
            ],
        )
        writer.writeheader()
        for entry in index["entries"]:
            writer.writerow(
                {
                    "complaint": entry.get("complaint", ""),
                    "aliases": " | ".join(entry.get("aliases") or []),
                    "clinical_terms": " | ".join(entry.get("clinical_terms") or []),
                    "condition": entry.get("condition", ""),
                    "lang": entry.get("lang", ""),
                    "source": entry.get("source", ""),
                }
            )
    logger.info(
        "Wrote %s (%d entries) and %s (%d patterns)",
        CSV_OUT,
        index["entry_count"],
        JSON_OUT,
        index["pattern_count"],
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build complaint→clinical map")
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Only curated bilingual lexicon (no HF/Kaggle download)",
    )
    parser.add_argument(
        "--with-kaggle",
        action="store_true",
        help="Include Kaggle animal-disease schema (API, local CSV, or public mirror)",
    )
    parser.add_argument(
        "--kaggle-csv",
        type=str,
        default="",
        help="Explicit path to animal-disease CSV (AnimalName/symptoms*/Dangerous)",
    )
    parser.add_argument(
        "--refresh-kaggle",
        action="store_true",
        help="Force re-download even if local CSV exists",
    )
    parser.add_argument(
        "--refresh-hf",
        action="store_true",
        help="Force re-download HuggingFace dataset",
    )
    args = parser.parse_args(argv)

    entries: List[Dict[str, Any]] = curated_entries()
    if not args.seed_only:
        path = ensure_hf_jsonl(force=args.refresh_hf)
        entries.extend(build_hf_entries(load_hf_rows(path)))
        # Default: include Kaggle-schema if already on disk; --with-kaggle forces resolve.
        want_kaggle = (
            args.with_kaggle
            or bool(args.kaggle_csv)
            or (KAGGLE_DIR.is_dir() and any(KAGGLE_DIR.glob("*.csv")))
        )
        if want_kaggle:
            kaggle_csv = resolve_kaggle_csv(
                force_download=args.refresh_kaggle or args.with_kaggle,
                csv_path=Path(args.kaggle_csv) if args.kaggle_csv else None,
            )
            if kaggle_csv:
                entries.extend(build_kaggle_entries(kaggle_csv))
            else:
                logger.error("Could not resolve Kaggle-schema CSV")

    index = compile_index(entries)
    write_outputs(index)
    print(
        json.dumps(
            {
                "entry_count": index["entry_count"],
                "pattern_count": index["pattern_count"],
                "sources": index["sources"],
                "csv": str(CSV_OUT),
                "json": str(JSON_OUT),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
