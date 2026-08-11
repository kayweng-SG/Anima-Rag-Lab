"""Scrape emergency and poisoning articles from the MSD/Merck Veterinary Manual."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# International MSD Vet Manual is the default entry point outside US/Canada.
# Content mirrors Merck Vet Manual and is typically reachable where
# merckvetmanual.com returns CloudFront 403.
DEFAULT_BASE_URL = "https://www.msdvetmanual.com"
ALLOWED_HOSTS = {
    "www.msdvetmanual.com",
    "msdvetmanual.com",
    "www.merckvetmanual.com",
    "merckvetmanual.com",
}

CATEGORY_PATHS = (
    # Emergency / poisoning (Task 0.1 core)
    "/emergency-medicine-and-critical-care",
    "/special-pet-topics/emergencies",
    "/special-pet-topics/poisoning",
    # Dog owners — clinical sections (triage-relevant)
    "/dog-owners/skin-disorders-of-dogs",
    "/dog-owners/digestive-disorders-of-dogs",
    "/dog-owners/ear-disorders-of-dogs",
    "/dog-owners/eye-disorders-of-dogs",
    "/dog-owners/lung-and-airway-disorders-of-dogs",
    "/dog-owners/bone-joint-and-muscle-disorders-of-dogs",
    "/dog-owners/hormonal-disorders-of-dogs",
    "/dog-owners/kidney-and-urinary-tract-disorders-of-dogs",
    "/dog-owners/heart-and-blood-vessel-disorders-of-dogs",
    "/dog-owners/blood-disorders-of-dogs",
    "/dog-owners/brain-spinal-cord-and-nerve-disorders-of-dogs",
    "/dog-owners/disorders-affecting-multiple-body-systems-of-dogs",
    "/dog-owners/immune-disorders-of-dogs",
    "/dog-owners/metabolic-disorders-of-dogs",
    "/dog-owners/reproductive-disorders-of-dogs",
    "/dog-owners/behavior-of-dogs",
    # Cat owners — clinical sections
    "/cat-owners/skin-disorders-of-cats",
    "/cat-owners/digestive-disorders-of-cats",
    "/cat-owners/ear-disorders-of-cats",
    "/cat-owners/eye-disorders-of-cats",
    "/cat-owners/lung-and-airway-disorders-of-cats",
    "/cat-owners/bone-joint-and-muscle-disorders-of-cats",
    "/cat-owners/hormonal-disorders-of-cats",
    "/cat-owners/kidney-and-urinary-tract-disorders-of-cats",
    "/cat-owners/heart-and-blood-vessel-disorders-of-cats",
    "/cat-owners/blood-disorders-of-cats",
    "/cat-owners/brain-spinal-cord-and-nerve-disorders-of-cats",
    "/cat-owners/disorders-affecting-multiple-body-systems-of-cats",
    "/cat-owners/immune-disorders-of-cats",
    "/cat-owners/metabolic-disorders-of-cats",
    "/cat-owners/reproductive-disorders-of-cats",
    "/cat-owners/behavior-of-cats",
)

ARTICLE_PATH_PREFIXES = tuple(f"{path.rstrip('/')}/" for path in CATEGORY_PATHS)


class MerckScraper:
    """Crawl MSD/Merck Veterinary Manual emergency and poisoning articles."""

    REQUEST_TIMEOUT = 30
    REQUEST_DELAY = 1.5

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (
            base_url
            or os.getenv("MERCK_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        self.category_urls = [
            urljoin(f"{self.base_url}/", path.lstrip("/")) for path in CATEGORY_PATHS
        ]

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
        )
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.output_path = os.path.join(
            project_root, "data", "raw", "merck_emergencies_raw.json"
        )
        self.seed_path = os.path.join(
            project_root, "data", "raw", "merck_emergencies_seed.json"
        )
        logger.info("Scraper base URL: %s", self.base_url)

    def _get_soup(self, url: str) -> BeautifulSoup:
        """Fetch a URL and return its parsed HTML document."""
        response = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
        if response.status_code == 403:
            cache_status = response.headers.get("X-Cache", "unknown")
            server = response.headers.get("Server", "unknown")
            raise requests.HTTPError(
                (
                    f"403 Access restricted for {url} "
                    f"(server={server}, x-cache={cache_status}). "
                    "Try https://www.msdvetmanual.com (international) or --seed."
                ),
                response=response,
            )
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def _is_valid_article_url(self, url: str) -> bool:
        """Return whether a URL belongs to a target emergency/poisoning section."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.netloc.lower() not in ALLOWED_HOSTS:
            return False
        path = parsed.path.rstrip("/")
        category_roots = {category_path.rstrip("/") for category_path in CATEGORY_PATHS}
        if path in category_roots:
            return False
        return any(parsed.path.startswith(prefix) for prefix in ARTICLE_PATH_PREFIXES)

    def get_article_links(self) -> List[str]:
        """Harvest unique emergency and poisoning article links."""
        links: Set[str] = set()
        blocked = False

        for category_url in self.category_urls:
            logger.info("Harvesting article links from %s", category_url)
            try:
                soup = self._get_soup(category_url)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 403:
                    blocked = True
                    logger.error("Could not fetch category page: %s", exc)
                    continue
                logger.error("Could not fetch category page: %s", exc)
                continue
            except requests.RequestException as exc:
                logger.error("Could not fetch category page: %s", exc)
                continue
            except Exception:
                logger.exception("Could not parse category page %s", category_url)
                continue

            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if not href:
                    continue
                absolute_url = urljoin(self.base_url, href)
                parsed = urlparse(absolute_url)
                # Normalize host to configured base when MSD/Merck mirrors share paths.
                if parsed.netloc.lower() in ALLOWED_HOSTS:
                    absolute_url = urljoin(
                        self.base_url,
                        parsed.path,
                    )
                    parsed = urlparse(absolute_url)
                normalized_url = (
                    parsed._replace(query="", fragment="").geturl().rstrip("/")
                )
                if self._is_valid_article_url(normalized_url):
                    links.add(normalized_url)

        article_links = sorted(links)
        logger.info("Found %d unique article links", len(article_links))
        if not article_links and blocked:
            logger.error(
                "Live access is blocked on this network. "
                "Confirm https://www.msdvetmanual.com loads, or use --seed."
            )
        return article_links

    def parse_article(self, url: str) -> Dict[str, object]:
        """Extract an article's title, paragraphs, and HTML tables."""
        soup = self._get_soup(url)
        content = soup.find("main") or soup.find("article")

        if content is None:
            logger.warning("No main article content found at %s", url)
            paragraphs: List[str] = []
            tables: List[List[List[str]]] = []
        else:
            paragraphs = [
                paragraph.get_text(" ", strip=True)
                for paragraph in content.find_all("p")
                if paragraph.get_text(" ", strip=True)
            ]

            tables = []
            for table in content.find_all("table"):
                rows = []
                for row in table.find_all("tr"):
                    cells = [
                        cell.get_text(" ", strip=True)
                        for cell in row.find_all(["th", "td"])
                    ]
                    if cells:
                        rows.append(cells)
                if rows:
                    tables.append(rows)

        heading = soup.find("h1")
        title_tag = soup.find("title")
        title = (
            heading.get_text(" ", strip=True)
            if heading
            else title_tag.get_text(" ", strip=True)
            if title_tag
            else ""
        )
        if not title:
            logger.warning("No title found at %s", url)

        return {
            "url": url,
            "title": title,
            "paragraphs": paragraphs,
            "tables": tables,
            "source_site": urlparse(self.base_url).netloc,
            "crawled_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save(self, articles: List[Dict[str, object]]) -> None:
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as output_file:
            json.dump(articles, output_file, ensure_ascii=False, indent=2)
        logger.info("Saved %d articles to %s", len(articles), self.output_path)

    def run_seed(self) -> List[Dict[str, object]]:
        """Copy curated offline seed data into the raw output path."""
        if not os.path.exists(self.seed_path):
            raise FileNotFoundError(
                f"Seed file not found: {self.seed_path}. "
                "Create it first or restore data/raw/merck_emergencies_seed.json."
            )
        with open(self.seed_path, encoding="utf-8") as seed_file:
            articles = json.load(seed_file)
        if not isinstance(articles, list) or not articles:
            raise ValueError(f"Seed file is empty or invalid: {self.seed_path}")
        self._save(articles)
        return articles

    def run(
        self,
        max_articles: Optional[int] = 10,
        merge_existing: bool = True,
    ) -> List[Dict[str, object]]:
        """Scrape articles, rate-limit requests, and save the collected data.

        When merge_existing is True (default), keep previously scraped articles and
        only fetch URLs that are not already present — used for corpus expansion.
        """
        existing: List[Dict[str, object]] = []
        existing_by_url: Dict[str, Dict[str, object]] = {}
        if merge_existing and os.path.isfile(self.output_path):
            try:
                with open(self.output_path, encoding="utf-8") as raw_file:
                    loaded = json.load(raw_file)
                if isinstance(loaded, list):
                    existing = loaded
                elif isinstance(loaded, dict) and isinstance(loaded.get("articles"), list):
                    existing = loaded["articles"]
                for article in existing:
                    url = str(article.get("url") or "").rstrip("/")
                    if url:
                        existing_by_url[url] = article
                logger.info(
                    "Merge mode: %d existing articles on disk", len(existing_by_url)
                )
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Could not load existing raw corpus for merge: %s", exc)

        links = self.get_article_links()
        if not links:
            logger.error(
                "No article links harvested. Aborting save to avoid overwriting "
                "existing data with an empty crawl result."
            )
            return existing

        new_links = [url for url in links if url.rstrip("/") not in existing_by_url]
        logger.info(
            "Links harvested=%d new=%d already_have=%d",
            len(links),
            len(new_links),
            len(links) - len(new_links),
        )

        if max_articles is not None:
            if max_articles < 0:
                raise ValueError("max_articles must be non-negative or None")
            new_links = new_links[:max_articles]

        fetched: List[Dict[str, object]] = []
        for index, url in enumerate(new_links, start=1):
            time.sleep(self.REQUEST_DELAY)
            logger.info("Scraping article %d/%d: %s", index, len(new_links), url)
            try:
                fetched.append(self.parse_article(url))
            except requests.RequestException as exc:
                logger.error("Network error while scraping %s: %s", url, exc)
            except Exception:
                logger.exception("Unexpected error while scraping %s", url)

        if not fetched and not existing_by_url:
            logger.error(
                "All article fetches failed. Aborting save to avoid writing empty JSON."
            )
            return []

        # Prefer freshly fetched copy when URL already existed (refresh path).
        merged_by_url = dict(existing_by_url)
        for article in fetched:
            merged_by_url[str(article.get("url") or "").rstrip("/")] = article
        articles = sorted(
            merged_by_url.values(),
            key=lambda item: str(item.get("url") or ""),
        )
        self._save(articles)
        logger.info(
            "Corpus now %d articles (+%d new this run)",
            len(articles),
            len(fetched),
        )
        return articles


if __name__ == "__main__":
    import sys

    scraper = MerckScraper()
    use_seed = "--seed" in sys.argv or os.getenv("MERCK_USE_SEED", "").lower() in {
        "1",
        "true",
        "yes",
    }
    full_crawl = "--full" in sys.argv
    replace = "--replace" in sys.argv

    if use_seed:
        logger.warning(
            "Using offline seed data because live access is unavailable "
            "or --seed was requested."
        )
        results = scraper.run_seed()
    else:
        max_articles = None if full_crawl else 10
        results = scraper.run(
            max_articles=max_articles,
            merge_existing=not replace,
        )
        if not results:
            raise SystemExit(
                "Scrape failed: site blocked or no articles found.\n"
                "Options:\n"
                "  1) Confirm https://www.msdvetmanual.com loads in a browser.\n"
                "  2) Set MERCK_BASE_URL if needed, then retry.\n"
                "  3) Offline fallback:\n"
                "       python scripts/01_scrape_merck.py --seed"
            )
        logger.info(
            "Live scrape complete: %d articles from %s",
            len(results),
            scraper.base_url,
        )
