#!/usr/bin/env python3
"""Chunk Module B/C raw extracts into RAG-ready records (WBS 1.2).

Reads structured JSON already under data/raw/module_{b,c}_* — does NOT OCR PDFs.
Output: data/processed/module_bc_chunks.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(PROJECT_ROOT, "data", "raw")
OUT_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "module_bc_chunks.json")


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _chunk(
    *,
    chunk_id: str,
    content: str,
    module: str,
    source: str,
    chunk_type: str,
    title: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    content = re.sub(r"\s+", " ", (content or "").strip())
    meta: Dict[str, Any] = {
        "module": module,
        "source": source,
        "chunk_type": chunk_type,
        "article_title": title,
        "estimated_tokens": max(1, len(content.split())),
        "content_hash": _hash(content),
    }
    if extra:
        meta.update(extra)
    return {"chunk_id": chunk_id, "content": content, "metadata": meta}


def chunk_akc(path: str) -> List[Dict[str, Any]]:
    rows = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        name = (row.get("") or row.get("breed") or row.get("name") or f"breed_{i}").strip()
        if not name:
            continue
        parts = [
            f"AKC breed profile: {name}.",
            f"Group: {row.get('group') or 'unknown'}.",
            f"Temperament: {row.get('temperament') or 'n/a'}.",
            f"Height cm: {row.get('min_height')}–{row.get('max_height')}; "
            f"weight kg: {row.get('min_weight')}–{row.get('max_weight')}; "
            f"life expectancy yr: {row.get('min_expectancy')}–{row.get('max_expectancy')}.",
            f"Energy: {row.get('energy_level_category')}; "
            f"trainability: {row.get('trainability_category')}; "
            f"shedding: {row.get('shedding_category')}; "
            f"grooming: {row.get('grooming_frequency_category')}.",
        ]
        desc = (row.get("description") or "").strip()
        if desc:
            parts.append(desc[:1200])
        out.append(
            _chunk(
                chunk_id=f"akc_{i:04d}_{_hash(name)}",
                content=" ".join(parts),
                module="B",
                source="akc",
                chunk_type="breed_profile",
                title=name,
                extra={"breed": name, "group": row.get("group")},
            )
        )
    return out


def chunk_cbarq_norms(path: str) -> List[Dict[str, Any]]:
    data = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    cbarq = data.get("cbarq") or {}
    # short form
    short = cbarq.get("short_42") or {}
    for sub in short.get("subscales") or []:
        items = sub.get("items") or []
        text = (
            f"C-BARQ42 scoring: subscale {sub.get('label') or sub.get('id')} "
            f"= mean of items {items} (divisor {sub.get('divisor')}). "
            f"Notes: {sub.get('notes') or 'none'}."
        )
        out.append(
            _chunk(
                chunk_id=f"cbarq42_{sub.get('id')}",
                content=text,
                module="B",
                source="cbarq",
                chunk_type="scoring_rule",
                title=f"C-BARQ42 {sub.get('id')}",
            )
        )
    long101 = cbarq.get("long_101") or {}
    for sub in long101.get("subscales") or []:
        items = sub.get("items") or []
        rev = sub.get("reverse_items") or []
        text = (
            f"C-BARQ(101) scoring: subscale {sub.get('label') or sub.get('id')} "
            f"= mean of items {items} (divisor {sub.get('divisor')}). "
            f"Reverse-code items: {rev or 'none'}. "
            f"Source mapping: {sub.get('source') or 'n/a'}."
        )
        out.append(
            _chunk(
                chunk_id=f"cbarq101_{sub.get('id')}",
                content=text,
                module="B",
                source="cbarq",
                chunk_type="scoring_rule",
                title=f"C-BARQ101 {sub.get('id')}",
            )
        )
    mcpq = data.get("mcpq_r") or {}
    for dim in mcpq.get("dimensions") or []:
        adjs = dim.get("adjectives") or []
        text = (
            f"MCPQ-R dimension {dim.get('label') or dim.get('id')}: "
            f"adjectives {', '.join(adjs)}. "
            f"Score with POMP: 100 * sum / (n_items * 6). "
            f"n_items={dim.get('n_items')}, max_raw={dim.get('max_raw')}."
        )
        out.append(
            _chunk(
                chunk_id=f"mcpqr_{dim.get('id')}",
                content=text,
                module="B",
                source="mcpq_r",
                chunk_type="scoring_rule",
                title=f"MCPQ-R {dim.get('id')}",
            )
        )
    return out


def chunk_therapy_51q(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    data = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    for trend in data.get("therapy_dog_factor_trends") or []:
        text = (
            f"Therapy-dog C-BARQ factor trend (Sakurama 2023): "
            f"{trend.get('factor')} tends to be {trend.get('trend')} "
            f"(mean {trend.get('mean')}, SD {trend.get('sd')}, "
            f"Cronbach alpha {trend.get('cronbach_alpha')})."
        )
        out.append(
            _chunk(
                chunk_id=f"therapy51_{_hash(trend.get('factor') or '')}",
                content=text,
                module="B",
                source="therapy_cbarq_51q",
                chunk_type="norm_reference",
                title=trend.get("factor") or "factor",
            )
        )
    return out


def chunk_aaha(path: str) -> List[Dict[str, Any]]:
    data = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    for species_key, species_label in (("canine", "dog"), ("feline", "cat")):
        block = data.get(species_key) or {}
        stages = block.get("stages") or []
        focus = block.get("wellness_focus_areas") or []
        visit = block.get("visit_frequency_notes") or []
        stage_bits = []
        for st in stages:
            band = st.get("age_band") or st.get("definition") or ""
            stage_bits.append(f"{st.get('label')}: {band}")
        text = (
            f"AAHA {species_label} life stages ({block.get('guideline')}): "
            + "; ".join(stage_bits)
            + f". Wellness focus areas: {', '.join(focus)}."
        )
        if visit:
            text += " Visit frequency: " + "; ".join(visit) + "."
        out.append(
            _chunk(
                chunk_id=f"aaha_{species_key}_stages",
                content=text,
                module="C",
                source="aaha",
                chunk_type="life_stage",
                title=f"AAHA {species_label} life stages",
                extra={"species": species_label, "doi": block.get("doi")},
            )
        )
        for st in stages:
            band = st.get("age_band") or st.get("definition") or ""
            out.append(
                _chunk(
                    chunk_id=f"aaha_{species_key}_{st.get('id')}",
                    content=(
                        f"AAHA {species_label} life stage «{st.get('label')}»: {band}. "
                        f"Guideline: {block.get('guideline')}."
                    ),
                    module="C",
                    source="aaha",
                    chunk_type="life_stage",
                    title=f"AAHA {species_label} {st.get('label')}",
                    extra={"species": species_label, "stage_id": st.get("id")},
                )
            )
    return out


def chunk_pettalk(path: str) -> List[Dict[str, Any]]:
    data = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    for i, item in enumerate(data.get("items") or []):
        url = item.get("url") or ""
        topic = item.get("topic") or "edu"
        note = item.get("note") or ""
        text = (
            f"Asia / husbandry education URL ({topic}): {url}. {note}. "
            "Use as source pointer for climate-relevant pet care (ticks, fungus, "
            "allergy, vaccines, senior/puppy husbandry)."
        )
        out.append(
            _chunk(
                chunk_id=f"pettalk_{i:03d}_{_hash(url)}",
                content=text,
                module="C",
                source="pettalk_asia",
                chunk_type="url_pointer",
                title=note or topic or url,
                extra={"url": url, "topic": topic},
            )
        )
    return out


def chunk_pettalk_articles(path: str) -> List[Dict[str, Any]]:
    """Full article bodies from articles.jsonl (L1 scrape)."""
    out: List[Dict[str, Any]] = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            title = row.get("title") or "PetTalk article"
            content = (row.get("content") or "").strip()
            url = row.get("url") or ""
            if len(content) < 40:
                continue
            # Split long articles into ~900-char windows
            step = 800
            overlap = 100
            parts = []
            if len(content) <= 1000:
                parts = [content]
            else:
                start = 0
                while start < len(content):
                    parts.append(content[start : start + step + overlap])
                    start += step
            for j, part in enumerate(parts):
                out.append(
                    _chunk(
                        chunk_id=f"pettalk_art_{i:03d}_{j}_{_hash(url)}",
                        content=f"PetTalk article «{title}»: {part}",
                        module="C",
                        source="pettalk_asia",
                        chunk_type="article",
                        title=title,
                        extra={"url": url, "article_part": j},
                    )
                )
    return out


def chunk_mcpq_blank(path: str) -> List[Dict[str, Any]]:
    data = json.loads(open(path, encoding="utf-8").read())
    out: List[Dict[str, Any]] = []
    items = data.get("items") or []
    dims: Dict[str, List[str]] = {}
    for it in items:
        dims.setdefault(it.get("dimension") or "?", []).append(it.get("adjective") or "")
    overview = (
        f"MCPQ-R lab-derived blank form ({data.get('item_count')} adjectives, "
        f"scale 1-6). Scoring: {data.get('scoring')}. "
        "Not an official Monash PDF — reconstructed from Ley 2008/2009 adjective lists. "
        f"Instructions: {data.get('instructions_en')}"
    )
    out.append(
        _chunk(
            chunk_id="mcpqr_blank_overview",
            content=overview,
            module="B",
            source="mcpq_r",
            chunk_type="blank_form",
            title="MCPQ-R blank form overview",
        )
    )
    for dim, adjs in dims.items():
        out.append(
            _chunk(
                chunk_id=f"mcpqr_blank_{dim}",
                content=(
                    f"MCPQ-R blank dimension «{dim}»: rate each adjective 1-6 — "
                    + ", ".join(adjs)
                    + "."
                ),
                module="B",
                source="mcpq_r",
                chunk_type="blank_form",
                title=f"MCPQ-R blank {dim}",
                extra={"dimension": dim},
            )
        )
    return out


def main() -> None:
    chunks: List[Dict[str, Any]] = []
    akc = os.path.join(RAW, "module_b_behavior", "akc_breeds", "akc-data-latest.json")
    cbarq = os.path.join(RAW, "module_b_behavior", "cbarq_mcpq_r", "norms_and_scoring.json")
    therapy = os.path.join(RAW, "module_b_behavior", "cbarq_mcpq_r", "therapy_dog_51q_factors.json")
    mcpq_blank = os.path.join(
        RAW,
        "module_b_behavior",
        "cbarq_mcpq_r",
        "related_instruments",
        "mcpq_r_blank_form.json",
    )
    aaha = os.path.join(RAW, "module_c_husbandry", "aaha", "life_stages.json")
    pettalk = os.path.join(RAW, "module_c_husbandry", "pettalk_asia", "url_inventory.json")
    pettalk_arts = os.path.join(
        RAW, "module_c_husbandry", "pettalk_asia", "articles.jsonl"
    )

    for label, path, fn in [
        ("AKC", akc, chunk_akc),
        ("C-BARQ/MCPQ-R", cbarq, chunk_cbarq_norms),
        ("therapy 51Q", therapy, chunk_therapy_51q),
        ("MCPQ-R blank", mcpq_blank, chunk_mcpq_blank),
        ("AAHA", aaha, chunk_aaha),
        ("PetTalk URLs", pettalk, chunk_pettalk),
        ("PetTalk articles", pettalk_arts, chunk_pettalk_articles),
    ]:
        if not os.path.isfile(path):
            logger.warning("Skip missing %s: %s", label, path)
            continue
        part = fn(path)
        logger.info("%s → %d chunks", label, len(part))
        chunks.extend(part)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chunk_count": len(chunks),
        "modules": sorted({c["metadata"]["module"] for c in chunks}),
        "sources": sorted({c["metadata"]["source"] for c in chunks}),
        "chunks": chunks,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info("Wrote %d chunks → %s", len(chunks), OUT_PATH)
    print(json.dumps({"chunk_count": len(chunks), "sources": payload["sources"]}, indent=2))


if __name__ == "__main__":
    main()
