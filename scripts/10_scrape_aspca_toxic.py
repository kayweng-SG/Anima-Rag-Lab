#!/usr/bin/env python3
"""Scrape ASPCA toxic plant lists for absolute Red-Light matching (Task 0.2).

Sources:
  - https://www.aspca.org/pet-care/animal-poison-control/dogs-plant-list
  - https://www.aspca.org/pet-care/animal-poison-control/cats-plant-list

Writes:
  - data/raw/aspca_toxic_plants_raw.json
  - data/triage_tree/aspca_toxic_plants.json  (normalized aliases for matching)

Offline fallback:
  python scripts/10_scrape_aspca_toxic.py --seed
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASE = "https://www.aspca.org"
LIST_URLS = {
    "dog": f"{DEFAULT_BASE}/pet-care/animal-poison-control/dogs-plant-list",
    "cat": f"{DEFAULT_BASE}/pet-care/animal-poison-control/cats-plant-list",
}

# Extra Chinese / local aliases for high-risk plants (owner free-text).
ZH_ALIAS_OVERLAY: Dict[str, Tuple[str, ...]] = {
    "lily": ("百合", "香水百合", "复活节百合"),
    "lilies": ("百合",),
    "sago palm": ("苏铁", "铁树"),
    "cycads": ("苏铁",),
    "oleander": ("夹竹桃",),
    "azalea": ("杜鹃", "映山红"),
    "rhododendron": ("杜鹃", "石南"),
    "yew": ("红豆杉", "紫杉"),
    "castor bean": ("蓖麻",),
    "african wonder tree": ("蓖麻",),
    "tulip": ("郁金香",),
    "narcissus": ("水仙",),
    "daffodil": ("水仙",),
    "autumn crocus": ("秋水仙",),
    "foxglove": ("毛地黄", "洋地黄"),
    "dieffenbachia": ("花叶万年青", "哑蔗"),
    "philodendron": ("喜林芋",),
    "pothos": ("绿萝",),
    "jade plant": ("玉树",),
    "aloe": ("芦荟",),
}

# Single-word food/common names that need an ingestion cue to avoid false RED.
AMBIGUOUS_ALIASES = {
    "apple",
    "apricot",
    "peach",
    "plum",
    "cherry",
    "tomato",
    "potato",
    "onion",
    "garlic",
    "grape",
    "raisin",
    "avocado",
    "aloe",
    "bay",
    "basil",
    "mint",
    "parsley",
}


def _load_dotenv(path: Optional[str] = None) -> None:
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
    except OSError:
        pass


_load_dotenv()


def _split_aliases(blob: str) -> List[str]:
    parts: List[str] = []
    for chunk in re.split(r"[,;/]| and | including:| Includes ", blob, flags=re.I):
        item = chunk.strip(" ()")
        item = re.sub(r"\s+", " ", item)
        if item and item.lower() not in {"many", "group also includes", "over"}:
            parts.append(item)
    return parts


def parse_plant_row(text: str, href: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Parse ASPCA list row text into structured plant record."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw or "Scientific Names" not in raw:
        return None

    scientific = ""
    family = ""
    head = raw
    sci_match = re.search(
        r"\|\s*Scientific Names:\s*(.*?)\s*(?:\||$)", raw, flags=re.I
    )
    if sci_match:
        scientific = sci_match.group(1).strip(" .")
        head = raw[: sci_match.start()].strip(" |")
    fam_match = re.search(r"\|\s*Family:\s*(.*?)\s*(?:\||$)", raw, flags=re.I)
    if fam_match:
        family = fam_match.group(1).strip(" .")

    common = head
    alias_blob = ""
    paren = re.match(r"^(.*?)\((.*)\)\s*$", head)
    if paren:
        common = paren.group(1).strip()
        alias_blob = paren.group(2).strip()

    aliases: List[str] = []
    seen: Set[str] = set()

    def add(name: str) -> None:
        cleaned = re.sub(r"\s+", " ", (name or "").strip(" ."))
        if not cleaned or len(cleaned) < 2:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        aliases.append(cleaned)

    add(common)
    for alias in _split_aliases(alias_blob):
        add(alias)
    for sci in _split_aliases(scientific.replace(" spp", "").replace(" spp.", "")):
        add(sci)
        # Also add genus alone for "Genus spp." style names when long enough.
        genus = sci.split()[0] if sci.split() else ""
        if genus and genus[0].isupper() and len(genus) >= 5 and not genus.endswith("."):
            add(genus)

    for key, zh_names in ZH_ALIAS_OVERLAY.items():
        if key in common.casefold() or any(key in a.casefold() for a in aliases):
            for zh in zh_names:
                add(zh)

    return {
        "common_name": common,
        "scientific_names": scientific,
        "family": family,
        "aliases": aliases,
        "url": href,
        "raw": raw,
    }


def extract_toxic_section(soup: BeautifulSoup, species: str) -> List[Dict[str, Any]]:
    label = "Dogs" if species == "dog" else "Cats"
    start_title = f"Plants Toxic to {label}"
    stop_title = f"Plants Non-Toxic to {label}"
    started = False
    plants: List[Dict[str, Any]] = []
    for el in soup.find_all(["h2", "div"]):
        if el.name == "h2":
            title = el.get_text(" ", strip=True)
            if title == start_title:
                started = True
                continue
            if started and stop_title in title:
                break
            continue
        if not started:
            continue
        classes = el.get("class") or []
        if "views-row" not in classes:
            continue
        link = el.find("a", href=True)
        href = urljoin(DEFAULT_BASE, link["href"]) if link else None
        parsed = parse_plant_row(el.get_text(" ", strip=True), href=href)
        if parsed:
            parsed["toxic_to"] = [species]
            plants.append(parsed)
    return plants


class AspcaToxicScraper:
    REQUEST_TIMEOUT = 45
    REQUEST_DELAY = 1.0

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.raw_path = os.path.join(
            PROJECT_ROOT, "data", "raw", "aspca_toxic_plants_raw.json"
        )
        self.processed_path = os.path.join(
            PROJECT_ROOT, "data", "triage_tree", "aspca_toxic_plants.json"
        )
        self.seed_path = os.path.join(
            PROJECT_ROOT, "data", "raw", "aspca_toxic_plants_seed.json"
        )

    def fetch_list(self, species: str) -> List[Dict[str, Any]]:
        url = LIST_URLS[species]
        logger.info("Fetching ASPCA %s toxic plant list: %s", species, url)
        response = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")
        plants = extract_toxic_section(soup, species)
        logger.info("Parsed %d toxic plants for %s", len(plants), species)
        return plants

    @staticmethod
    def merge_by_common_name(
        dog_plants: Iterable[Dict[str, Any]],
        cat_plants: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for plant in [*dog_plants, *cat_plants]:
            key = (plant.get("common_name") or "").casefold().strip()
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    **plant,
                    "toxic_to": list(plant.get("toxic_to") or []),
                    "aliases": list(plant.get("aliases") or []),
                }
                continue
            existing = merged[key]
            for species in plant.get("toxic_to") or []:
                if species not in existing["toxic_to"]:
                    existing["toxic_to"].append(species)
            alias_seen = {a.casefold() for a in existing["aliases"]}
            for alias in plant.get("aliases") or []:
                if alias.casefold() not in alias_seen:
                    existing["aliases"].append(alias)
                    alias_seen.add(alias.casefold())
            if not existing.get("url") and plant.get("url"):
                existing["url"] = plant["url"]
            if not existing.get("scientific_names") and plant.get("scientific_names"):
                existing["scientific_names"] = plant["scientific_names"]
        return sorted(merged.values(), key=lambda p: p["common_name"].casefold())

    def build_index(self, plants: List[Dict[str, Any]]) -> Dict[str, Any]:
        alias_entries: List[Dict[str, Any]] = []
        seen_alias: Set[str] = set()
        for plant in plants:
            for alias in plant.get("aliases") or []:
                key = alias.casefold().strip()
                if not key or key in seen_alias:
                    continue
                seen_alias.add(key)
                alias_entries.append(
                    {
                        "alias": alias,
                        "alias_norm": key,
                        "common_name": plant["common_name"],
                        "scientific_names": plant.get("scientific_names") or "",
                        "toxic_to": plant.get("toxic_to") or [],
                        "ambiguous": key in AMBIGUOUS_ALIASES or (
                            " " not in key and len(key) < 6 and key.isascii()
                        ),
                        "url": plant.get("url"),
                    }
                )
        # Longest first helps matcher prefer specific names.
        alias_entries.sort(key=lambda item: len(item["alias_norm"]), reverse=True)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "ASPCA Animal Poison Control — Toxic Plant Lists",
            "source_urls": LIST_URLS,
            "disclaimer": (
                "ASPCA plant toxicity data for educational triage matching. "
                "Not a substitute for veterinary care. "
                "Hotline: (888) 426-4435"
            ),
            "plant_count": len(plants),
            "alias_count": len(alias_entries),
            "plants": plants,
            "aliases": alias_entries,
            "ambiguous_aliases": sorted(AMBIGUOUS_ALIASES),
        }

    def save(self, raw_plants: List[Dict[str, Any]], index: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.raw_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.processed_path), exist_ok=True)
        with open(self.raw_path, "w", encoding="utf-8") as fh:
            json.dump(raw_plants, fh, ensure_ascii=False, indent=2)
        with open(self.processed_path, "w", encoding="utf-8") as fh:
            json.dump(index, fh, ensure_ascii=False, indent=2)
        logger.info(
            "Saved raw=%s (%d) index=%s (plants=%d aliases=%d)",
            self.raw_path,
            len(raw_plants),
            self.processed_path,
            index.get("plant_count"),
            index.get("alias_count"),
        )

    def run_seed(self) -> Dict[str, Any]:
        if not os.path.isfile(self.seed_path):
            raise FileNotFoundError(
                f"Seed missing: {self.seed_path}. Run a live scrape once to create data, "
                "or restore the seed file."
            )
        with open(self.seed_path, encoding="utf-8") as fh:
            plants = json.load(fh)
        if not isinstance(plants, list) or not plants:
            raise ValueError(f"Invalid seed: {self.seed_path}")
        index = self.build_index(plants)
        self.save(plants, index)
        return index

    def run(self) -> Dict[str, Any]:
        dog_plants = self.fetch_list("dog")
        time.sleep(self.REQUEST_DELAY)
        cat_plants = self.fetch_list("cat")
        plants = self.merge_by_common_name(dog_plants, cat_plants)
        if not plants:
            raise RuntimeError("ASPCA scrape returned 0 toxic plants")
        index = self.build_index(plants)
        self.save(plants, index)
        # Keep seed in sync with a compact high-signal subset for offline demos.
        high_risk = [
            p
            for p in plants
            if any(
                key in (p.get("common_name") or "").casefold()
                for key in (
                    "lily",
                    "sago",
                    "oleander",
                    "azalea",
                    "yew",
                    "castor",
                    "african wonder",
                    "tulip",
                    "narcissus",
                    "daffodil",
                    "foxglove",
                    "dieffenbachia",
                    "philodendron",
                    "autumn crocus",
                )
            )
        ]
        if high_risk:
            with open(self.seed_path, "w", encoding="utf-8") as fh:
                json.dump(high_risk, fh, ensure_ascii=False, indent=2)
            logger.info("Updated offline seed with %d high-risk plants", len(high_risk))
        return index


def main() -> int:
    import sys

    scraper = AspcaToxicScraper()
    use_seed = "--seed" in sys.argv
    try:
        index = scraper.run_seed() if use_seed else scraper.run()
    except Exception as exc:
        logger.error("ASPCA scrape failed: %s", exc)
        if not use_seed and os.path.isfile(scraper.seed_path):
            logger.warning("Falling back to --seed")
            index = scraper.run_seed()
        else:
            raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "plant_count": index["plant_count"],
                "alias_count": index["alias_count"],
                "processed_path": scraper.processed_path,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
