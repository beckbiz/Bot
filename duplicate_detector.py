"""Duplicate detection via URL and title similarity."""
from __future__ import annotations

from difflib import SequenceMatcher


class DuplicateDetector:
    def __init__(self, threshold: float = 0.87) -> None:
        self.threshold = threshold

    @staticmethod
    def are_same_url(url_a: str, url_b: str) -> bool:
        return url_a.rstrip("/") == url_b.rstrip("/")

    def are_similar_titles(self, title_a: str, title_b: str) -> bool:
        ratio = SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()
        return ratio >= self.threshold

    def is_duplicate(self, candidate: dict[str, str], known: list[dict[str, str]]) -> bool:
        for article in known:
            if self.are_same_url(candidate.get("url", ""), article.get("url", "")):
                return True
            if self.are_similar_titles(candidate.get("title", ""), article.get("title", "")):
                return True
        return False
"""Duplicate detection via URL and title similarity."""
from __future__ import annotations

from difflib import SequenceMatcher


class DuplicateDetector:
    def __init__(self, threshold: float = 0.87) -> None:
        self.threshold = threshold

    @staticmethod
    def are_same_url(url_a: str, url_b: str) -> bool:
        return url_a.rstrip("/") == url_b.rstrip("/")

    def are_similar_titles(self, title_a: str, title_b: str) -> bool:
        ratio = SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()
        return ratio >= self.threshold

    def is_duplicate(self, candidate: dict[str, str], known: list[dict[str, str]]) -> bool:
        for article in known:
            if self.are_same_url(candidate.get("url", ""), article.get("url", "")):
                return True
            if self.are_similar_titles(candidate.get("title", ""), article.get("title", "")):
                return True
        return False
