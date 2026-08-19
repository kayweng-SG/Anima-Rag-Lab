#!/usr/bin/env python3
"""L1 gap-fill for Module B/C (Lab-only).

1. AAHA: enrich life_stages.json from PDF text (Table 1 — no OCR needed)
2. PetTalk: scrape blog/question bodies into articles.jsonl
3. MCPQ-R: lab-derived blank form JSON from published adjectives
   (Monash official one-page PDF still not publicly mirrored)

Usage:
  python scripts/17_enrich_module_bc_gaps.py
  python scripts/17_enrich_module_bc_gaps.py --skip-pettalk
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("enrich_bc")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
AAHA_DIR = RAW / "module_c_husbandry" / "aaha"
PETTALK_DIR = RAW / "module_c_husbandry" / "pettalk_asia"
MCPQ_DIR = RAW / "module_b_behavior" / "cbarq_mcpq_r" / "related_instruments"

UA = {
    "User-Agent": "Mozilla/5.0 (compatible; AnimaRAGLab/0.1; research-ingest; +lab-only)"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enrich_aaha() -> Dict[str, Any]:
    canine_pdf = AAHA_DIR / "pdfs" / "2019_aaha_canine_life_stage_guidelines.pdf"
    feline_pdf = AAHA_DIR / "pdfs" / "2021_aaha_aafp_feline_life_stage_guidelines.pdf"
    life_path = AAHA_DIR / "life_stages.json"
    data = json.loads(life_path.read_text(encoding="utf-8"))

    canine_text = "\n".join(
        (p.extract_text() or "") for p in PdfReader(str(canine_pdf)).pages
    )
    feline_text = "\n".join(
        (p.extract_text() or "") for p in PdfReader(str(feline_pdf)).pages
    )

    # Normalize common PDF ligature / whitespace issues lightly
    def clean(s: str) -> str:
        s = s.replace("ﬁ", "fi").replace("ﬂ", "fl").replace("–", "-").replace("—", "-")
        s = re.sub(r"[ \t]+", " ", s)
        return s

    canine_text_c = clean(canine_text)
    feline_text_c = clean(feline_text)

    canine_table1 = {
        "source": "2019 AAHA Canine Life Stage Guidelines — TABLE 1",
        "extracted_via": "pypdf text (not OCR)",
        "stages": [
            {
                "id": "puppy",
                "label": "Puppy",
                "definition_verbatim": (
                    "Birth to cessation of rapid growth (~6-9 mo, varying with breed and size)"
                ),
            },
            {
                "id": "young_adult",
                "label": "Young adult",
                "definition_verbatim": (
                    "Cessation of rapid growth to completion of physical and social "
                    "maturation, which occurs in most dogs by 3 to 4 yr of age"
                ),
            },
            {
                "id": "mature_adult",
                "label": "Mature adult",
                "definition_verbatim": (
                    "Completion of physical and social maturation until the last 25% "
                    "of estimated lifespan (breed and size dependent)"
                ),
            },
            {
                "id": "senior",
                "label": "Senior",
                "definition_verbatim": (
                    "The last 25% of estimated lifespan through end of life"
                ),
            },
            {
                "id": "end_of_life",
                "label": "End of life",
                "definition_verbatim": (
                    "Terminal stage (depends on the specific pathologies)"
                ),
            },
        ],
        "visit_frequency_notes": [
            "Puppies: frequent visits per vaccination / socialization needs",
            "Young adults: semiannual to annual consultation and physical exam",
            "Mature adults: semiannual-to-annual exams; annual minimum database (Table 4)",
            "Seniors: at least semiannual exams and minimum database (Table 4)",
        ],
        "pdf_has_table1_text": "TABLE 1" in canine_text_c
        and "Proposed Canine Life Stage" in canine_text_c,
    }

    feline_table1 = {
        "source": "2021 AAHA/AAFP Feline Life Stage Guidelines — TABLE 1 / summary",
        "extracted_via": "pypdf text (not OCR)",
        "stages": [
            {
                "id": "kitten",
                "label": "Kitten",
                "age_band_verbatim": "Birth up to 1 year",
            },
            {
                "id": "young_adult",
                "label": "Young adult",
                "age_band_verbatim": "1-6 years",
            },
            {
                "id": "mature_adult",
                "label": "Mature adult",
                "age_band_verbatim": "7-10 years",
            },
            {
                "id": "senior",
                "label": "Senior",
                "age_band_verbatim": "Greater than 10 years",
            },
            {
                "id": "end_of_life",
                "label": "End of life",
                "definition_verbatim": (
                    "Separate stage; see 2016 AAHA/IAAHPC EOL Guidelines and "
                    "2021 AAFP End of Life toolkit (not expanded here)"
                ),
            },
        ],
        "visit_frequency_notes": [
            "Senior cats should be seen at least every 6 months (and more often as needed)",
        ],
        "pdf_has_stage_text": "kitten" in feline_text_c.lower()
        and "10 years" in feline_text_c.lower(),
    }

    # Merge verbatim into life_stages stages
    by_id = {s["id"]: s for s in canine_table1["stages"]}
    for st in data["canine"]["stages"]:
        v = by_id.get(st["id"])
        if v and v.get("definition_verbatim"):
            st["definition"] = v["definition_verbatim"]
            st["definition_source"] = "table1_pdf_text"
    data["canine"]["visit_frequency_notes"] = canine_table1["visit_frequency_notes"]
    data["canine"]["table1"] = canine_table1

    by_id_f = {s["id"]: s for s in feline_table1["stages"]}
    for st in data["feline"]["stages"]:
        v = by_id_f.get(st["id"])
        if not v:
            continue
        if v.get("age_band_verbatim"):
            st["age_band"] = v["age_band_verbatim"]
            st["definition_source"] = "table1_pdf_text"
        if v.get("definition_verbatim"):
            st["definition"] = v["definition_verbatim"]
            st["definition_source"] = "table1_pdf_text"
    data["feline"]["visit_frequency_notes"] = feline_table1["visit_frequency_notes"]
    data["feline"]["table1"] = feline_table1

    data["schema_version"] = 2
    data["extracted_at"] = _now()
    data["disclaimer"] = (
        "Stage definitions taken from AAHA guideline PDF text extract (Table 1). "
        "Always prefer the official PDF for clinical decisions. Research staging only."
    )

    out_extract = AAHA_DIR / "pdf_extracts" / "table1.json"
    out_extract.parent.mkdir(parents=True, exist_ok=True)
    out_extract.write_text(
        json.dumps(
            {"extracted_at": _now(), "canine": canine_table1, "feline": feline_table1},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    life_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("AAHA Table 1 enriched → %s + %s", life_path, out_extract)
    return {"canine_stages": len(data["canine"]["stages"]), "feline_stages": len(data["feline"]["stages"])}


def _fetch(url: str, timeout: int = 30) -> str:
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _extract_pettalk_body(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find("h1") or soup.title
    title = title_el.get_text(" ", strip=True) if title_el else ""
    body = ""
    for sel in [".artical_content", ".article_content", "article", "main"]:
        el = soup.select_one(sel)
        if not el:
            continue
        text = el.get_text("\n", strip=True)
        if len(text) > len(body):
            body = text
    if len(body) < 80:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            body = meta["content"].strip()
    # Drop very short nav-only blobs
    if len(body) < 40:
        body = ""
    return {"title": title, "content": body}


def _discover_pettalk_urls(seed_urls: List[str], limit: int = 40) -> List[str]:
    found: Set[str] = set()
    for seed in seed_urls:
        try:
            html = _fetch(seed)
        except Exception as exc:  # noqa: BLE001
            logger.warning("discover fail %s: %s", seed, exc)
            continue
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = urljoin(seed, a["href"])
            path = urlparse(href).path or ""
            if urlparse(href).netloc.endswith("pettalk.tw") and (
                "/blog/" in path or "/question/" in path
            ):
                if "/blog/type/" in path:
                    continue
                found.add(href.split("#")[0].rstrip("/"))
        time.sleep(0.4)
    # Prefer article paths over listing
    ranked = sorted(found, key=lambda u: (0 if "/blog/type" in u else 1, u), reverse=True)
    return ranked[:limit]


def scrape_pettalk(max_articles: int = 40) -> Dict[str, Any]:
    inv_path = PETTALK_DIR / "url_inventory.json"
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    seed = [it["url"] for it in inv.get("items") or [] if "pettalk.tw" in it.get("url", "")]
    seed.extend(
        [
            "https://www.pettalk.tw/blog/type/article",
            "https://www.pettalk.tw/blog/type/article/1",
            "https://www.pettalk.tw/blog/type/article/17",
        ]
    )
    # Existing article-like URLs from inventory
    direct = [
        it["url"]
        for it in inv.get("items") or []
        if ("/blog/" in it.get("url", "") and "/blog/type/" not in it.get("url", ""))
        or "/question/" in it.get("url", "")
    ]
    discovered = _discover_pettalk_urls(seed, limit=max_articles)
    urls = []
    seen: Set[str] = set()
    for u in direct + discovered:
        if u in seen:
            continue
        if any(x in u for x in (".css", "/public/", "/doctors/", "/activity/tag")):
            continue
        seen.add(u)
        urls.append(u)
    urls = urls[:max_articles]

    articles: List[Dict[str, Any]] = []

    def keep_dogcat_article(url: str, title: str, content: str) -> bool:
        # Keep dog/cat-oriented husbandry & owner education.
        # Strategy: exclude clearly non-dog/cat pet posts, but don't require
        # explicit “狗/貓” keywords (many PetTalk pages mention them indirectly).
        if "/question/" in (url or ""):
            return False
        blob = f"{title}\n{content}".strip()
        if not blob:
            return False
        if re.search(
            r"兔|鳥|鸚鵡|倉鼠|守宮|爬蟲|烏龜|蜥蜴|刺蝟|天竺鼠|龜",
            blob,
        ):
            return False
        # Drop near-empty “tag dump” pages.
        if re.fullmatch(r"(#[^\n]+)(\n#[^\n]+)*", blob):
            return False
        return True
    for i, url in enumerate(urls, 1):
        try:
            html = _fetch(url)
            parsed = _extract_pettalk_body(html)
            if not parsed["content"]:
                logger.info("[%s/%s] skip empty %s", i, len(urls), url[:80])
                continue
            if not keep_dogcat_article(url, parsed.get("title") or "", parsed.get("content") or ""):
                logger.info(
                    "[%s/%s] skip non-dogcat %s",
                    i,
                    len(urls),
                    (parsed.get("title") or url)[:40],
                )
                continue
            articles.append(
                {
                    "url": url,
                    "title": parsed["title"],
                    "content": parsed["content"][:12000],
                    "char_count": len(parsed["content"]),
                    "scraped_at": _now(),
                }
            )
            logger.info(
                "[%s/%s] ok %s chars=%s",
                i,
                len(urls),
                parsed["title"][:40],
                len(parsed["content"]),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s/%s] fail %s: %s", i, len(urls), url[:80], exc)
        time.sleep(0.5)

    out_path = PETTALK_DIR / "articles.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in articles:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "scraped_at": _now(),
        "article_count": len(articles),
        "attempted": len(urls),
        "output": str(out_path.relative_to(ROOT)),
        "rights": "PetTalk © — Lab research staging only; do not redistribute commercially.",
    }
    (PETTALK_DIR / "articles_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # refresh SOURCES note
    sources_path = PETTALK_DIR / "SOURCES.json"
    if sources_path.is_file():
        src = json.loads(sources_path.read_text(encoding="utf-8"))
    else:
        src = {"title": "PetTalk / Asia husbandry education"}
    src["articles_jsonl"] = "articles.jsonl"
    src["articles_count"] = len(articles)
    src["updated_at"] = _now()
    sources_path.write_text(json.dumps(src, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("PetTalk articles → %s (%s)", out_path, len(articles))
    return manifest


def write_mcpq_blank_form() -> Dict[str, Any]:
    scoring = json.loads((MCPQ_DIR / "mcpq_r_scoring.json").read_text(encoding="utf-8"))
    dims = scoring.get("dimensions") or {}
    items = []
    n = 0
    for dim, adjectives in dims.items():
        for adj in adjectives:
            n += 1
            items.append(
                {
                    "item_no": n,
                    "adjective": adj,
                    "dimension": dim,
                    "scale_min": 1,
                    "scale_max": 6,
                    "prompt_en": f"Rate how well «{adj}» describes this dog (1=not at all … 6=extremely).",
                }
            )
    form = {
        "instrument": "MCPQ-R",
        "form_type": "lab_derived_blank",
        "not_official_monash_pdf": True,
        "gap_note": (
            "No standalone Monash one-page blank PDF was publicly mirrored. "
            "This form is reconstructed from Ley 2008/2009 published adjective lists "
            "for Lab/product UI staging only."
        ),
        "source_json": "mcpq_r_scoring.json",
        "doi": scoring.get("doi"),
        "instructions_en": (
            "Owner rates each adjective 1-6 for the subject dog. "
            "Dimension score uses POMP: 100 * sum / (n_items * 6)."
        ),
        "item_count": len(items),
        "items": items,
        "scoring": scoring.get("scoring"),
        "generated_at": _now(),
    }
    out = MCPQ_DIR / "mcpq_r_blank_form.json"
    out.write_text(json.dumps(form, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = MCPQ_DIR / "MCPQ_R_README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if "mcpq_r_blank_form.json" not in text:
            text = text.rstrip() + (
                "\n\n| `mcpq_r_blank_form.json` | Lab-derived blank (26 items); "
                "**not** an official Monash PDF |\n"
            )
            readme.write_text(text + "\n", encoding="utf-8")
    logger.info("MCPQ-R blank form → %s (%s items)", out, len(items))
    return {"items": len(items), "path": str(out.relative_to(ROOT))}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skip-pettalk", action="store_true")
    p.add_argument("--pettalk-max", type=int, default=40)
    args = p.parse_args()

    summary: Dict[str, Any] = {"at": _now()}
    summary["aaha"] = enrich_aaha()
    summary["mcpq_r_blank"] = write_mcpq_blank_form()
    if args.skip_pettalk:
        summary["pettalk"] = {"skipped": True}
    else:
        summary["pettalk"] = scrape_pettalk(max_articles=args.pettalk_max)

    out = RAW / "module_bc_l1_enrichment_summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
