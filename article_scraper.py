"""Article text extraction with fallback parsing."""
from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup
from newspaper import Article

LOGGER = logging.getLogger(__name__)


class ArticleScraper:
    def __init__(self, timeout: int = 12) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AI-News-Bot/1.0"})

    def extract_text(self, url: str) -> str:
        text = self._extract_with_newspaper(url)
        if not text or len(text) < 200:
            text = self._extract_with_bs(url)
        return self._clean_text(text)

    def _extract_with_newspaper(self, url: str) -> str:
        try:
            article = Article(url)
            article.download()
            article.parse()
            return article.text or ""
        except Exception as exc:
            LOGGER.debug("newspaper extraction failed for %s: %s", url, exc)
            return ""

    def _extract_with_bs(self, url: str) -> str:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for selector in [
                "nav",
                "header",
                "footer",
                "aside",
                "script",
                "style",
                ".advertisement",
                ".ads",
                ".cookie",
                "#cookie",
            ]:
                for tag in soup.select(selector):
                    tag.decompose()

            main = soup.find("article") or soup.find("main") or soup.body
            return main.get_text(" ", strip=True) if main else ""
        except requests.RequestException as exc:
            LOGGER.warning("requests extraction failed for %s: %s", url, exc)
            return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text)
        cleaned = re.sub(r"(cookie policy|subscribe now|accept all cookies)", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

