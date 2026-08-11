"""Process raw Merck emergency data into triage-ready structured JSON."""

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


VITAL_TERMS = (
    "heart rate",
    "pulse",
    "respiratory",
    "temperature",
    "blood pressure",
    "capillary refill",
    "crt",
    "mucous membrane",
    "vital sign",
    "bpm",
    "mm hg",
    "rectal",
)

TOXICITY_TERMS = (
    "toxic",
    "toxin",
    "poison",
    "overdose",
    "antidote",
    "activated charcoal",
    "emesis",
    "decontamination",
    "mg/kg",
    "g/kg",
    "lethal",
)

TRIAGE_TERMS = (
    "emergency",
    "immediate",
    "urgent",
    "shock",
    "unconscious",
    "collapse",
    "seizure",
    "bleeding",
    "trouble breathing",
    "breathing difficulty",
    "respiratory distress",
    "cyanotic",
    "heat stroke",
    "hypothermia",
    "poisoning",
    "toxin",
    "bradycardia",
    "tachycardia",
    "hypotension",
    "cpr",
)

# Patterns used to pull numeric physiologic ranges for fast Red-Light checks.
NUMERIC_PATTERNS = (
    (
        "heart_rate_small_dog_normal_bpm",
        re.compile(
            r"70\s*[–-]\s*120\s*bpm[^\n.]{0,40}small dogs?",
            re.IGNORECASE,
        ),
        {"species": "dog", "size": "small", "metric": "heart_rate_bpm", "min": 70, "max": 120},
    ),
    (
        "heart_rate_large_dog_normal_bpm",
        re.compile(
            r"60\s*[–-]\s*120\s*bpm[^\n.]{0,40}large dogs?",
            re.IGNORECASE,
        ),
        {"species": "dog", "size": "large", "metric": "heart_rate_bpm", "min": 60, "max": 120},
    ),
    (
        "heart_rate_cat_normal_bpm",
        re.compile(
            r"150\s*[–-]\s*220\s*bpm[^\n.]{0,40}cats?",
            re.IGNORECASE,
        ),
        {"species": "cat", "metric": "heart_rate_bpm", "min": 150, "max": 220},
    ),
    (
        "heart_rate_dog_tachycardia_bpm",
        re.compile(
            r"tachycardia:\s*>\s*180\s*bpm\s*\(dogs?\)",
            re.IGNORECASE,
        ),
        {"species": "dog", "metric": "heart_rate_bpm", "severity": "tachycardia", "threshold": 180},
    ),
    (
        "heart_rate_cat_tachycardia_bpm",
        re.compile(
            r"tachycardia:\s*>\s*220\s*bpm\s*\(cats?\)",
            re.IGNORECASE,
        ),
        {"species": "cat", "metric": "heart_rate_bpm", "severity": "tachycardia", "threshold": 220},
    ),
    (
        "crt_normal_seconds",
        re.compile(r"1\s*[–-]\s*2\s*seconds", re.IGNORECASE),
        {"metric": "crt_seconds", "min": 1.0, "max": 2.0, "severity": "normal"},
    ),
    (
        "rectal_temp_dog_cat_f",
        re.compile(
            r"101\.5\s*[–-]\s*102\s*°?\s*F",
            re.IGNORECASE,
        ),
        {
            "species": "dog_cat",
            "metric": "rectal_temp_f",
            "min": 101.5,
            "max": 102.0,
            "severity": "normal",
        },
    ),
    (
        "map_low_normal_mmhg",
        re.compile(
            r"mean arterial pressure of\s*60\s*[–-]\s*80\s*mm\s*Hg",
            re.IGNORECASE,
        ),
        {"metric": "map_mmhg", "min": 60, "max": 80, "severity": "low_normal"},
    ),
    (
        "map_high_normal_mmhg",
        re.compile(
            r"mean arterial pressure of\s*80\s*[–-]\s*100\s*mm\s*Hg",
            re.IGNORECASE,
        ),
        {"metric": "map_mmhg", "min": 80, "max": 100, "severity": "high_normal"},
    ),
    (
        "hypothermia_rewarm_c",
        re.compile(
            r"rectal temperatures? are\s*>\s*36\.5\s*°?\s*C",
            re.IGNORECASE,
        ),
        {"metric": "rectal_temp_c", "threshold": 36.5, "severity": "rewarm_until_above"},
    ),
    (
        "cpr_compression_rate",
        re.compile(
            r"100\s*[–-]\s*120\s*compressions?\s*per\s*minute",
            re.IGNORECASE,
        ),
        {"metric": "cpr_compressions_per_min", "min": 100, "max": 120},
    ),
)


class MerckProcessor:
    """Clean and structure raw Merck articles for RAG + Red-Light triage."""

    def __init__(
        self,
        input_path: Optional[str] = None,
        output_path: Optional[str] = None,
        triage_path: Optional[str] = None,
    ) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.input_path = input_path or os.path.join(
            project_root, "data", "raw", "merck_emergencies_raw.json"
        )
        self.output_path = output_path or os.path.join(
            project_root, "data", "processed", "merck_emergencies_processed.json"
        )
        self.triage_path = triage_path or os.path.join(
            project_root, "data", "triage_tree", "merck_red_light_metrics.json"
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value)
        safe = "".join(
            ch
            for ch in normalized
            if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
        )
        return re.sub(r"\s+", " ", safe).strip()

    @staticmethod
    def _contains_any(text: str, terms: Tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(term in lowered for term in terms)

    def _clean_paragraphs(self, paragraphs: List[str]) -> Tuple[List[str], int]:
        cleaned: List[str] = []
        seen: Set[str] = set()
        duplicates = 0
        for paragraph in paragraphs:
            text = self._clean_text(paragraph)
            if not text:
                continue
            if text in seen:
                duplicates += 1
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned, duplicates

    def _clean_tables(self, tables: List[List[List[str]]]) -> List[List[List[str]]]:
        cleaned_tables: List[List[List[str]]] = []
        for table in tables:
            rows: List[List[str]] = []
            for row in table:
                cells = [self._clean_text(cell) for cell in row]
                if any(cells):
                    rows.append(cells)
            if rows:
                cleaned_tables.append(rows)
        return cleaned_tables

    def _table_blob(self, table: List[List[str]]) -> str:
        return " ".join(cell for row in table for cell in row)

    def _rows_as_records(self, table: List[List[str]]) -> List[Dict[str, str]]:
        if not table:
            return []
        header = table[0]
        if len(header) < 2:
            return [{"text": " | ".join(row)} for row in table]

        records: List[Dict[str, str]] = []
        for row in table[1:]:
            record: Dict[str, str] = {}
            for index, key in enumerate(header):
                value = row[index] if index < len(row) else ""
                if key:
                    record[key] = value
            if any(record.values()):
                records.append(record)
        return records

    def _extract_vital_signs(
        self, tables: List[List[List[str]]], paragraphs: List[str]
    ) -> List[Dict[str, Any]]:
        vital_signs: List[Dict[str, Any]] = []
        for index, table in enumerate(tables):
            blob = self._table_blob(table)
            if self._contains_any(blob, VITAL_TERMS):
                vital_signs.append(
                    {
                        "source": "table",
                        "table_index": index,
                        "records": self._rows_as_records(table),
                    }
                )
        for paragraph in paragraphs:
            if self._contains_any(paragraph, VITAL_TERMS):
                vital_signs.append({"source": "paragraph", "text": paragraph})
        return vital_signs

    def _extract_toxic_dosages(
        self, tables: List[List[List[str]]], paragraphs: List[str]
    ) -> List[Dict[str, Any]]:
        toxic_items: List[Dict[str, Any]] = []
        for index, table in enumerate(tables):
            blob = self._table_blob(table)
            if self._contains_any(blob, TOXICITY_TERMS):
                toxic_items.append(
                    {
                        "source": "table",
                        "table_index": index,
                        "records": self._rows_as_records(table),
                    }
                )
        for paragraph in paragraphs:
            if self._contains_any(paragraph, TOXICITY_TERMS):
                toxic_items.append({"source": "paragraph", "text": paragraph})
        return toxic_items

    def _extract_triage_indicators(self, paragraphs: List[str]) -> List[str]:
        indicators: List[str] = []
        seen: Set[str] = set()
        for paragraph in paragraphs:
            if self._contains_any(paragraph, TRIAGE_TERMS) and paragraph not in seen:
                seen.add(paragraph)
                indicators.append(paragraph)
        return indicators

    def _extract_numeric_metrics(
        self, paragraphs: List[str], tables: List[List[List[str]]]
    ) -> List[Dict[str, Any]]:
        corpus = "\n".join(paragraphs)
        for table in tables:
            corpus += "\n" + self._table_blob(table)

        metrics: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for metric_id, pattern, payload in NUMERIC_PATTERNS:
            if metric_id in seen_ids:
                continue
            if pattern.search(corpus):
                seen_ids.add(metric_id)
                metrics.append({"id": metric_id, **payload})
        return metrics

    def process_article(self, article: Dict[str, Any]) -> Dict[str, Any]:
        paragraphs, duplicates = self._clean_paragraphs(article.get("paragraphs") or [])
        tables = self._clean_tables(article.get("tables") or [])
        title = self._clean_text(article.get("title") or "")
        url = article.get("url") or ""

        vital_signs = self._extract_vital_signs(tables, paragraphs)
        toxic_dosages = self._extract_toxic_dosages(tables, paragraphs)
        triage_indicators = self._extract_triage_indicators(paragraphs)
        numeric_metrics = self._extract_numeric_metrics(paragraphs, tables)

        source_chars = sum(len(p) for p in (article.get("paragraphs") or []))
        retained_chars = sum(len(p) for p in paragraphs) + sum(
            len(cell) for table in tables for row in table for cell in row
        )

        return {
            "url": url,
            "title": title,
            "paragraphs": paragraphs,
            "tables": tables,
            "vital_signs": vital_signs,
            "toxic_dosages": toxic_dosages,
            "triage_indicators": triage_indicators,
            "numeric_metrics": numeric_metrics,
            "crawled_at": article.get("crawled_at"),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "source_note": article.get("source_note"),
            "token_saving_stats": {
                "source_characters": source_chars,
                "retained_characters": retained_chars,
                "duplicate_paragraphs_removed": duplicates,
                "estimated_retained_tokens": (retained_chars + 3) // 4,
                "vital_sign_blocks": len(vital_signs),
                "toxic_blocks": len(toxic_dosages),
                "triage_indicator_count": len(triage_indicators),
                "numeric_metric_count": len(numeric_metrics),
            },
        }

    def _build_red_light_index(
        self, processed_articles: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compact metric index for sub-500ms triage without LLM calls."""
        metrics_by_id: Dict[str, Dict[str, Any]] = {}
        red_flags: List[str] = []

        for article in processed_articles:
            for metric in article.get("numeric_metrics") or []:
                metric_id = metric.get("id")
                if metric_id and metric_id not in metrics_by_id:
                    metrics_by_id[metric_id] = {
                        **metric,
                        "source_title": article.get("title"),
                        "source_url": article.get("url"),
                    }
            for indicator in article.get("triage_indicators") or []:
                if indicator not in red_flags:
                    red_flags.append(indicator)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "purpose": "Red-Light Intercept physiologic checks without LLM",
            "metric_count": len(metrics_by_id),
            "metrics": list(metrics_by_id.values()),
            "red_flag_indicators": red_flags[:50],
        }

    def run(self) -> List[Dict[str, Any]]:
        logger.info("Loading raw articles from %s", self.input_path)
        with open(self.input_path, encoding="utf-8") as input_file:
            raw_articles = json.load(input_file)

        if not isinstance(raw_articles, list):
            raise ValueError("Raw Merck file must be a JSON list of articles")

        processed: List[Dict[str, Any]] = []
        for index, article in enumerate(raw_articles, start=1):
            title = article.get("title", f"article_{index}")
            logger.info("Processing %d/%d: %s", index, len(raw_articles), title)
            try:
                processed.append(self.process_article(article))
            except Exception:
                logger.exception("Failed to process article: %s", title)

        if not processed:
            raise RuntimeError("No articles were processed successfully")

        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as output_file:
            json.dump(processed, output_file, ensure_ascii=False, indent=2)
        logger.info("Saved %d processed articles to %s", len(processed), self.output_path)

        red_light = self._build_red_light_index(processed)
        os.makedirs(os.path.dirname(self.triage_path), exist_ok=True)
        with open(self.triage_path, "w", encoding="utf-8") as triage_file:
            json.dump(red_light, triage_file, ensure_ascii=False, indent=2)
        logger.info(
            "Saved Red-Light metrics (%d) to %s",
            red_light["metric_count"],
            self.triage_path,
        )
        return processed


if __name__ == "__main__":
    processor = MerckProcessor()
    processor.run()
