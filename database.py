"""SQLite storage layer for users, sources, articles, summaries, and usage."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOGGER = logging.getLogger(__name__)


@dataclass
class Article:
    id: int
    title: str
    url: str
    source: str
    published_at: str
    text: str
    category: str | None = None
    importance: int | None = None
    summary: str | None = None


class Database:
    """Thin repository wrapper around SQLite operations."""

    def __init__(self, db_path: str | Path = "data/news.db") -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    last_active TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_categories (
                    user_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    UNIQUE(user_id, category),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    UNIQUE(user_id, url),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    source TEXT NOT NULL,
                    published_at TEXT,
                    text TEXT,
                    inserted_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS summaries (
                    article_id INTEGER UNIQUE NOT NULL,
                    summary TEXT NOT NULL,
                    category TEXT,
                    importance INTEGER,
                    ai_model TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(article_id) REFERENCES articles(id)
                );

                CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date_key TEXT NOT NULL,
                    minute_key TEXT NOT NULL,
                    tokens_used INTEGER NOT NULL,
                    requests_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_articles_inserted_at ON articles(inserted_at);
                CREATE INDEX IF NOT EXISTS idx_summaries_category ON summaries(category);
                CREATE INDEX IF NOT EXISTS idx_usage_date ON usage(date_key);
                """
            )
        LOGGER.info("Database initialized: %s", self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_user(self, telegram_id: int) -> int:
        now = self._now()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET last_active = ? WHERE id = ?", (now, row["id"])
                )
                return int(row["id"])
            cursor = conn.execute(
                "INSERT INTO users (telegram_id, created_at, last_active) VALUES (?, ?, ?)",
                (telegram_id, now, now),
            )
            return int(cursor.lastrowid)

    def get_user_id(self, telegram_id: int) -> int | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return int(row["id"]) if row else None

    def set_user_categories(self, user_id: int, categories: list[str]) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM user_categories WHERE user_id = ?", (user_id,))
            for category in categories:
                conn.execute(
                    "INSERT OR IGNORE INTO user_categories (user_id, category) VALUES (?, ?)",
                    (user_id, category),
                )

    def get_user_categories(self, user_id: int) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT category FROM user_categories WHERE user_id = ?", (user_id,)
            ).fetchall()
            return [row["category"] for row in rows]

    def add_source(self, user_id: int | None, url: str, source_type: str) -> bool:
        with self.connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO sources (user_id, url, source_type, added_at) VALUES (?, ?, ?, ?)",
                    (user_id, url, source_type, self._now()),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_sources_for_user(self, user_id: int | None) -> list[str]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT url FROM sources WHERE user_id = ? OR user_id IS NULL",
                (user_id,),
            ).fetchall()
            return [row["url"] for row in rows]

    def article_exists(self, url: str) -> bool:
        with self.connection() as conn:
            return (
                conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone()
                is not None
            )

    def insert_article(
        self,
        title: str,
        url: str,
        source: str,
        published_at: str | None,
        text: str,
    ) -> int | None:
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO articles (title, url, source, published_at, text, inserted_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (title, url, source, published_at, text, self._now()),
                )
                return int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def upsert_summary(
        self,
        article_id: int,
        summary: str,
        category: str,
        importance: int,
        ai_model: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO summaries (article_id, summary, category, importance, ai_model, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id)
                DO UPDATE SET summary=excluded.summary, category=excluded.category,
                importance=excluded.importance, ai_model=excluded.ai_model, updated_at=excluded.updated_at
                """,
                (article_id, summary, category, importance, ai_model, self._now()),
            )

    def get_unsummarized_articles(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT a.* FROM articles a
                LEFT JOIN summaries s ON s.article_id = a.id
                WHERE s.article_id IS NULL
                ORDER BY a.inserted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_rankable_articles(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.title, a.url, a.source, a.published_at, a.inserted_at,
                       s.summary, s.category, s.importance
                FROM articles a
                JOIN summaries s ON s.article_id = a.id
                ORDER BY a.inserted_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def search_articles(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = f"%{query}%"
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT a.title, a.url, a.source, s.summary, s.importance, s.category
                FROM articles a
                LEFT JOIN summaries s ON s.article_id = a.id
                WHERE a.title LIKE ? OR a.text LIKE ? OR s.summary LIKE ?
                ORDER BY a.inserted_at DESC
                LIMIT ?
                """,
                (q, q, q, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def log_usage(self, tokens_used: int, requests_count: int) -> None:
        now = datetime.now(timezone.utc)
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO usage (date_key, minute_key, tokens_used, requests_count, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%Y-%m-%d %H:%M"),
                    tokens_used,
                    requests_count,
                    now.isoformat(),
                ),
            )

    def get_usage(self) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        date_key = now.strftime("%Y-%m-%d")
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        with self.connection() as conn:
            day = conn.execute(
                "SELECT COALESCE(SUM(tokens_used),0) AS tokens FROM usage WHERE date_key = ?",
                (date_key,),
            ).fetchone()
            rpm = conn.execute(
                "SELECT COALESCE(SUM(requests_count),0) AS requests FROM usage WHERE minute_key = ?",
                (minute_key,),
            ).fetchone()
            return {"tokens_today": int(day["tokens"]), "requests_this_minute": int(rpm["requests"])}

    def list_users(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            return [dict(row) for row in rows]

    def get_user_digest_candidates(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        categories = self.get_user_categories(user_id)
        with self.connection() as conn:
            if categories:
                placeholders = ",".join("?" * len(categories))
                rows = conn.execute(
                    f"""
                    SELECT a.title, a.url, a.source, a.published_at, s.summary, s.importance, s.category
                    FROM articles a
                    JOIN summaries s ON s.article_id = a.id
                    WHERE s.category IN ({placeholders})
                    ORDER BY s.importance DESC, a.inserted_at DESC
                    LIMIT ?
                    """,
                    (*categories, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT a.title, a.url, a.source, a.published_at, s.summary, s.importance, s.category
                    FROM articles a
                    JOIN summaries s ON s.article_id = a.id
                    ORDER BY s.importance DESC, a.inserted_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]

    def get_top_daily_articles(self, limit: int = 5) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT a.title, a.url, a.source, s.summary, s.importance, s.category
                FROM articles a
                JOIN summaries s ON s.article_id = a.id
                WHERE a.inserted_at LIKE ?
                ORDER BY s.importance DESC, a.inserted_at DESC
                LIMIT ?
                """,
                (f"{today}%", limit),
            ).fetchall()
            return [dict(row) for row in rows]
