"""User profile and preference management."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from database import Database

LOGGER = logging.getLogger(__name__)


class UserManager:
    def __init__(self, db: Database, supported_categories: list[str]) -> None:
        self.db = db
        self.supported_categories = set(supported_categories)

    def register_user(self, telegram_id: int) -> int:
        user_id = self.db.upsert_user(telegram_id)
        LOGGER.info("User registered/updated: telegram_id=%s user_id=%s", telegram_id, user_id)
        return user_id

    def set_categories(self, telegram_id: int, categories: list[str]) -> tuple[bool, str]:
        invalid = [category for category in categories if category not in self.supported_categories]
        if invalid:
            return False, f"Ungültige Kategorien: {', '.join(invalid)}"

        user_id = self.db.get_user_id(telegram_id)
        if not user_id:
            user_id = self.register_user(telegram_id)

        self.db.set_user_categories(user_id, categories)
        return True, "Kategorien gespeichert."

    def get_categories(self, telegram_id: int) -> list[str]:
        user_id = self.db.get_user_id(telegram_id)
        if not user_id:
            return []
        return self.db.get_user_categories(user_id)

    @staticmethod
    def validate_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def add_source(self, telegram_id: int, url: str) -> tuple[bool, str]:
        if not self.validate_url(url):
            return False, "URL ist ungültig."

        source_type = "rss" if "rss" in url.lower() or "feed" in url.lower() else "website"
        user_id = self.db.get_user_id(telegram_id)
        if not user_id:
            user_id = self.register_user(telegram_id)

        inserted = self.db.add_source(user_id, url, source_type)
        if not inserted:
            return False, "Quelle existiert bereits."
        return True, "Quelle hinzugefügt."

    def get_sources(self, telegram_id: int) -> list[str]:
        user_id = self.db.get_user_id(telegram_id)
        if not user_id:
            return []
        return self.db.get_sources_for_user(user_id)
