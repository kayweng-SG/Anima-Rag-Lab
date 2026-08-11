"""Chunk processed Merck data into compact RAG-ready records."""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


DEFAULT_MAX_TOKENS = 300
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class MerckChunker:
    """Build dense, deduplicated chunks for embedding and retrieval."""

    def __init__(
        self,
        input_path: Optional[str] = None,
        output_path: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.input_path = input_path or os.path.join(
            project_root, "data", "processed", "merck_emergencies_processed.json"
        )
        self.output_path = output_path or os.path.join(
            project_root, "data", "processed", "merck_emergencies_chunks.json"
        )
        self.max_tokens = max_tokens

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return (len(text) + 3) // 4

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]

    def _split_long_text(self, text: str) -> List[str]:
        if self._estimate_tokens(text) <= self.max_tokens:
            return [text]

        parts: List[str] = []
        current = ""
        for sentence in SENTENCE_SPLIT.split(text):
            candidate = f"{current} {sentence}".strip() if current else sentence
            if self._estimate_tokens(candidate) <= self.max_tokens:
                current = candidate
            else:
                if current:
                    parts.append(current)
                current = sentence
        if current:
            parts.append(current)
        return parts or [text]

    def _make_chunk(
        self,
        *,
        chunk_id: str,
        article_index: int,
        article_title: str,
        article_url: str,
        chunk_type: str,
        content: str,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = {
            "article_index": article_index,
            "article_title": article_title,
            "article_url": article_url,
            "chunk_type": chunk_type,
            "estimated_tokens": self._estimate_tokens(content),
            "content_hash": self._content_hash(content),
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return {
            "chunk_id": chunk_id,
            "content": content,
            "metadata": metadata,
        }

    def _record_to_text(self, record: Dict[str, str]) -> str:
        return "; ".join(f"{key}: {value}" for key, value in record.items() if value)

    def _chunk_article(
        self, article: Dict[str, Any], article_index: int
    ) -> List[Dict[str, Any]]:
        title = article.get("title") or f"article_{article_index}"
        url = article.get("url") or ""
        chunks: List[Dict[str, Any]] = []
        seen_hashes: Set[str] = set()

        def add_chunk(
            chunk_id: str,
            chunk_type: str,
            content: str,
            extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            content = content.strip()
            if not content:
                return
            content_hash = self._content_hash(content)
            if content_hash in seen_hashes:
                return
            seen_hashes.add(content_hash)
            for part_index, part in enumerate(self._split_long_text(content)):
                suffix = f"_{part_index}" if part_index else ""
                chunks.append(
                    self._make_chunk(
                        chunk_id=f"{chunk_id}{suffix}",
                        article_index=article_index,
                        article_title=title,
                        article_url=url,
                        chunk_type=chunk_type,
                        content=part,
                        extra_metadata=extra,
                    )
                )

        for para_index, paragraph in enumerate(article.get("paragraphs") or []):
            add_chunk(
                f"a{article_index}_para_{para_index}",
                "paragraph",
                paragraph,
            )

        for triage_index, indicator in enumerate(article.get("triage_indicators") or []):
            add_chunk(
                f"a{article_index}_triage_{triage_index}",
                "triage_indicator",
                f"Triage indicator: {indicator}",
                {"priority": "high"},
            )

        for vital_index, vital in enumerate(article.get("vital_signs") or []):
            if vital.get("source") == "table":
                for row_index, record in enumerate(vital.get("records") or []):
                    text = self._record_to_text(record)
                    add_chunk(
                        f"a{article_index}_vital_{vital_index}_row_{row_index}",
                        "vital_sign",
                        f"Vital sign reference — {text}",
                        {"table_index": vital.get("table_index")},
                    )
            elif vital.get("text"):
                add_chunk(
                    f"a{article_index}_vital_{vital_index}",
                    "vital_sign",
                    f"Vital sign reference — {vital['text']}",
                )

        for toxic_index, toxic in enumerate(article.get("toxic_dosages") or []):
            if toxic.get("source") == "table":
                for row_index, record in enumerate(toxic.get("records") or []):
                    text = self._record_to_text(record)
                    add_chunk(
                        f"a{article_index}_toxic_{toxic_index}_row_{row_index}",
                        "toxic_dosage",
                        f"Toxicology / poisoning guidance — {text}",
                        {"table_index": toxic.get("table_index")},
                    )
            elif toxic.get("text"):
                add_chunk(
                    f"a{article_index}_toxic_{toxic_index}",
                    "toxic_dosage",
                    f"Toxicology / poisoning guidance — {toxic['text']}",
                )

        for metric_index, metric in enumerate(article.get("numeric_metrics") or []):
            metric_id = metric.get("id", f"metric_{metric_index}")
            parts = [
                f"Numeric metric: {metric_id}",
                f"metric={metric.get('metric')}",
            ]
            for key in ("species", "size", "min", "max", "threshold", "severity"):
                if key in metric:
                    parts.append(f"{key}={metric[key]}")
            add_chunk(
                f"a{article_index}_metric_{metric_index}",
                "numeric_metric",
                "; ".join(parts),
                {"metric_id": metric_id},
            )

        return chunks

    def run(self) -> Dict[str, Any]:
        logger.info("Loading processed articles from %s", self.input_path)
        with open(self.input_path, encoding="utf-8") as input_file:
            articles = json.load(input_file)

        if not isinstance(articles, list):
            raise ValueError("Processed Merck file must be a JSON list")

        all_chunks: List[Dict[str, Any]] = []
        for index, article in enumerate(articles):
            title = article.get("title", f"article_{index}")
            logger.info("Chunking %d/%d: %s", index + 1, len(articles), title)
            all_chunks.extend(self._chunk_article(article, index))

        if not all_chunks:
            raise RuntimeError("No chunks were generated")

        type_counts: Dict[str, int] = {}
        total_tokens = 0
        for chunk in all_chunks:
            chunk_type = chunk["metadata"]["chunk_type"]
            type_counts[chunk_type] = type_counts.get(chunk_type, 0) + 1
            total_tokens += chunk["metadata"]["estimated_tokens"]

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_file": os.path.basename(self.input_path),
            "chunk_count": len(all_chunks),
            "estimated_total_tokens": total_tokens,
            "max_tokens_per_chunk": self.max_tokens,
            "chunk_type_counts": type_counts,
            "chunks": all_chunks,
        }

        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)

        logger.info(
            "Saved %d chunks (~%d tokens) to %s",
            len(all_chunks),
            total_tokens,
            self.output_path,
        )
        logger.info("Chunk breakdown: %s", type_counts)
        return payload


if __name__ == "__main__":
    MerckChunker().run()
