"""Background scheduler to collect, process, and push digests."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from telegram import Bot

from ai_service import AIService
from article_scraper import ArticleScraper
from database import Database
from duplicate_detector import DuplicateDetector
from ranking import NewsRanker
from rss_collector import NewsCollector

LOGGER = logging.getLogger(__name__)


class NewsPipeline:
    def __init__(
        self,
        db: Database,
        collector: NewsCollector,
        scraper: ArticleScraper,
        duplicate_detector: DuplicateDetector,
        ai_service: AIService,
        ranker: NewsRanker,
    ) -> None:
        self.db = db
        self.collector = collector
        self.scraper = scraper
        self.duplicate_detector = duplicate_detector
        self.ai_service = ai_service
        self.ranker = ranker

    def collect_and_store(self, sources: list[str]) -> int:
        known = self.db.get_recent_article_meta(limit=300)
        inserted = 0

        for source in sources:
            articles = self.collector.collect_from_source(source)
            for article in articles:
                url = article.get("url")
                title = str(article.get("title", "Untitled"))
                if not url:
                    continue
                if self.db.article_exists(url) or self.duplicate_detector.is_duplicate(article, known):
                    continue

                text = self.scraper.extract_text(url)
                if len(text) < 180:
                    continue

                article_id = self.db.insert_article(
                    title=title,
                    url=url,
                    source=str(article.get("source", "unknown")),
                    published_at=article.get("published_at"),
                    text=text,
                )
                if article_id:
                    inserted += 1
                    known.append({"title": title, "url": url})

        LOGGER.info("Pipeline inserted %s new articles", inserted)
        return inserted

    def summarize_pending(self) -> int:
        pending = self.db.get_unsummarized_articles(limit=40)
        for article in pending:
            result = self.ai_service.summarize(article.get("text", ""))
            self.db.upsert_summary(
                article_id=article["id"],
                summary=result["summary"],
                category=result["category"],
                importance=result["importance"],
                ai_model=self.ai_service.model,
            )
        return len(pending)


class DigestService:
    def __init__(self, db: Database, ranker: NewsRanker, bot: Bot) -> None:
        self.db = db
        self.ranker = ranker
        self.bot = bot

    @staticmethod
    def _format_article(article: dict) -> str:
        return (
            f"• **{article.get('title', 'Untitled')}**\n"
            f"{article.get('summary', 'Keine Zusammenfassung verfügbar.')}\n"
            f"⭐ Importance: {article.get('importance', 1)}/10\n"
            f"Quelle: {article.get('source', 'N/A')}\n"
            f"🔗 {article.get('url', '')}\n"
        )

    async def send_digest(self) -> None:
        users = self.db.list_users()
        for user in users:
            candidates = self.db.get_user_digest_candidates(user_id=user["id"], limit=15)
            ranked = self.ranker.rank(candidates)
            clustered = self.ranker.cluster_articles(ranked)[:5]
            if not clustered:
                continue

            trending = self.ranker.trending_topics(candidates)
            body = "\n\n".join(self._format_article(article) for article in clustered)
            message = (
                "📰 **Top News**\n\n"
                f"{body}\n"
                f"🔥 Trending Topics Today:\n" + "\n".join(f"- {topic}" for topic in trending[:5])
            )
            await self.bot.send_message(chat_id=user["telegram_id"], text=message, parse_mode="Markdown")

            for article in clustered:
                if int(article.get("importance") or 0) >= 9:
                    await self.bot.send_message(
                        chat_id=user["telegram_id"],
                        text=f"🚨 **Breaking News**\n{self._format_article(article)}",
                        parse_mode="Markdown",
                    )

    async def send_daily_digest(self) -> None:
        users = self.db.list_users()
        top = self.db.get_top_daily_articles(limit=5)
        if not top:
            return
        body = "\n\n".join(self._format_article(article) for article in top)
        message = f"🌅 **Morning Briefing – Top 5**\n\n{body}"
        for user in users:
            await self.bot.send_message(chat_id=user["telegram_id"], text=message, parse_mode="Markdown")


async def run_scheduler(
    pipeline: NewsPipeline,
    digest_service: DigestService,
    source_provider: Callable[[], list[str]],
    every_minutes: int,
    daily_digest_hour_utc: int,
) -> None:
    """Simple asyncio scheduler loop."""
    last_daily_date: str | None = None

    while True:
        start = datetime.now(timezone.utc)
        try:
            sources = source_provider()
            pipeline.collect_and_store(sources)
            pipeline.summarize_pending()
            await digest_service.send_digest()

            today = start.strftime("%Y-%m-%d")
            if start.hour == daily_digest_hour_utc and last_daily_date != today:
                await digest_service.send_daily_digest()
                last_daily_date = today
        except Exception as exc:
            LOGGER.exception("Scheduler cycle failed: %s", exc)

        await asyncio.sleep(max(60, every_minutes * 60))
"""Background scheduler to collect, process, and push digests."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from telegram import Bot

from ai_service import AIService
from article_scraper import ArticleScraper
from database import Database
from duplicate_detector import DuplicateDetector
from ranking import NewsRanker
from rss_collector import NewsCollector

LOGGER = logging.getLogger(__name__)


class NewsPipeline:
    def __init__(
        self,
        db: Database,
        collector: NewsCollector,
        scraper: ArticleScraper,
        duplicate_detector: DuplicateDetector,
        ai_service: AIService,
        ranker: NewsRanker,
    ) -> None:
        self.db = db
        self.collector = collector
        self.scraper = scraper
        self.duplicate_detector = duplicate_detector
        self.ai_service = ai_service
        self.ranker = ranker

    def collect_and_store(self, sources: list[str]) -> int:
        known = self.db.get_recent_article_meta(limit=300)
        inserted = 0

        for source in sources:
            articles = self.collector.collect_from_source(source)
            for article in articles:
                url = article.get("url")
                title = str(article.get("title", "Untitled"))
                if not url:
                    continue
                if self.db.article_exists(url) or self.duplicate_detector.is_duplicate(article, known):
                    continue

                text = self.scraper.extract_text(url)
                if len(text) < 180:
                    continue

                article_id = self.db.insert_article(
                    title=title,
                    url=url,
                    source=str(article.get("source", "unknown")),
                    published_at=article.get("published_at"),
                    text=text,
                )
                if article_id:
                    inserted += 1
                    known.append({"title": title, "url": url})

        LOGGER.info("Pipeline inserted %s new articles", inserted)
        return inserted

    def summarize_pending(self) -> int:
        pending = self.db.get_unsummarized_articles(limit=40)
        for article in pending:
            result = self.ai_service.summarize(article.get("text", ""))
            self.db.upsert_summary(
                article_id=article["id"],
                summary=result["summary"],
                category=result["category"],
                importance=result["importance"],
                ai_model=self.ai_service.model,
            )
        return len(pending)


class DigestService:
    def __init__(self, db: Database, ranker: NewsRanker, bot: Bot) -> None:
        self.db = db
        self.ranker = ranker
        self.bot = bot

    @staticmethod
    def _format_article(article: dict) -> str:
        return (
            f"• **{article.get('title', 'Untitled')}**\n"
            f"{article.get('summary', 'Keine Zusammenfassung verfügbar.')}\n"
            f"⭐ Importance: {article.get('importance', 1)}/10\n"
            f"Quelle: {article.get('source', 'N/A')}\n"
            f"🔗 {article.get('url', '')}\n"
        )

    async def send_digest(self) -> None:
        users = self.db.list_users()
        for user in users:
            candidates = self.db.get_user_digest_candidates(user_id=user["id"], limit=15)
            ranked = self.ranker.rank(candidates)
            clustered = self.ranker.cluster_articles(ranked)[:5]
            if not clustered:
                continue

            trending = self.ranker.trending_topics(candidates)
            body = "\n\n".join(self._format_article(article) for article in clustered)
            message = (
                "📰 **Top News**\n\n"
                f"{body}\n"
                f"🔥 Trending Topics Today:\n" + "\n".join(f"- {topic}" for topic in trending[:5])
            )
            await self.bot.send_message(chat_id=user["telegram_id"], text=message, parse_mode="Markdown")

            for article in clustered:
                if int(article.get("importance") or 0) >= 9:
                    await self.bot.send_message(
                        chat_id=user["telegram_id"],
                        text=f"🚨 **Breaking News**\n{self._format_article(article)}",
                        parse_mode="Markdown",
                    )

    async def send_daily_digest(self) -> None:
        users = self.db.list_users()
        top = self.db.get_top_daily_articles(limit=5)
        if not top:
            return
        body = "\n\n".join(self._format_article(article) for article in top)
        message = f"🌅 **Morning Briefing – Top 5**\n\n{body}"
        for user in users:
            await self.bot.send_message(chat_id=user["telegram_id"], text=message, parse_mode="Markdown")


async def run_scheduler(
    pipeline: NewsPipeline,
    digest_service: DigestService,
    source_provider: Callable[[], list[str]],
    every_minutes: int,
    daily_digest_hour_utc: int,
) -> None:
    """Simple asyncio scheduler loop."""
    last_daily_date: str | None = None

    while True:
        start = datetime.now(timezone.utc)
        try:
            sources = source_provider()
            pipeline.collect_and_store(sources)
            pipeline.summarize_pending()
            await digest_service.send_digest()

            today = start.strftime("%Y-%m-%d")
            if start.hour == daily_digest_hour_utc and last_daily_date != today:
                await digest_service.send_daily_digest()
                last_daily_date = today
        except Exception as exc:
            LOGGER.exception("Scheduler cycle failed: %s", exc)

        await asyncio.sleep(max(60, every_minutes * 60))
