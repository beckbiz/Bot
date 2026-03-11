"""Collect articles from RSS feeds and websites."""
from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)


class NewsCollector:
    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AI-News-Bot/1.0",
            }
        )

    def collect_from_source(self, source_url: str) -> list[dict[str, str | None]]:
        if any(token in source_url.lower() for token in ["rss", "feed", ".xml"]):
            return self.collect_from_rss(source_url)
        return self.collect_from_website(source_url)

    def collect_from_rss(self, feed_url: str) -> list[dict[str, str | None]]:
        articles: list[dict[str, str | None]] = []
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:30]:
                published = getattr(entry, "published", None)
                articles.append(
                    {
                        "title": getattr(entry, "title", "Untitled"),
                        "url": getattr(entry, "link", ""),
                        "source": urlparse(feed_url).netloc,
                        "published_at": published,
                    }
                )
            LOGGER.info("Collected %s RSS entries from %s", len(articles), feed_url)
        except Exception as exc:
            LOGGER.exception("RSS collection failed for %s: %s", feed_url, exc)
        return articles

    def collect_from_website(self, website_url: str) -> list[dict[str, str | None]]:
        articles: list[dict[str, str | None]] = []
        try:
            response = self.session.get(website_url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for link in soup.select("a[href]"):
                href = link.get("href", "")
                title = (link.get_text() or "").strip()
                if len(title) < 20:
                    continue
                absolute_url = urljoin(website_url, href)
                if not absolute_url.startswith("http"):
                    continue
                articles.append(
                    {
                        "title": title[:300],
                        "url": absolute_url,
                        "source": urlparse(website_url).netloc,
                        "published_at": datetime.utcnow().isoformat(),
                    }
                )
                if len(articles) >= 40:
                    break
            LOGGER.info("Collected %s website links from %s", len(articles), website_url)
        except requests.RequestException as exc:
            LOGGER.warning("Website collection failed for %s: %s", website_url, exc)
        return articles
