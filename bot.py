"""Telegram bot entry point."""
from __future__ import annotations

import asyncio
import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_service import AIService
from article_scraper import ArticleScraper
from config import load_config, setup_logging
from database import Database
from duplicate_detector import DuplicateDetector
from ranking import NewsRanker
from rss_collector import NewsCollector
from scheduler import DigestService, NewsPipeline, run_scheduler
from user_manager import UserManager

LOGGER = logging.getLogger(__name__)


class NewsTelegramBot:
    def __init__(self) -> None:
        setup_logging()
        self.config = load_config()

        self.db = Database("data/users.db")
        self.user_manager = UserManager(self.db, self.config.supported_categories)

        self.collector = NewsCollector()
        self.scraper = ArticleScraper()
        self.duplicate_detector = DuplicateDetector()
        self.ai_service = AIService(
            db=self.db,
            api_key=self.config.groq_api_key,
            endpoint=self.config.groq_endpoint,
            model=self.config.groq_model,
            max_requests_per_minute=self.config.limits.max_requests_per_minute,
            max_tokens_per_day=self.config.limits.max_tokens_per_day,
        )
        self.ranker = NewsRanker()
        self.pipeline = NewsPipeline(
            db=self.db,
            collector=self.collector,
            scraper=self.scraper,
            duplicate_detector=self.duplicate_detector,
            ai_service=self.ai_service,
            ranker=self.ranker,
        )

        self.app = Application.builder().token(self.config.telegram_token).build()
        self.digest_service = DigestService(self.db, self.ranker, self.app.bot)

        self.sources = list(dict.fromkeys(self.config.default_sources))
        self._register_handlers()

    @staticmethod
    def keyboard() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton("News holen"), KeyboardButton("Top News heute")],
                [KeyboardButton("Quelle hinzufügen"), KeyboardButton("Quellen anzeigen")],
                [KeyboardButton("Kategorie wählen"), KeyboardButton("Suche")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False,
        )

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        self.user_manager.register_user(user.id)
        text = (
            "Willkommen beim AI News Assistant!\n"
            "Nutze die Buttons oder Commands wie /news, /add, /sources, /category, /search, /top"
        )
        await update.message.reply_text(text, reply_markup=self.keyboard())

    async def get_news(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        self.user_manager.register_user(user_id)
        candidates = self.db.get_user_digest_candidates(self.db.get_user_id(user_id), limit=8)
        if not candidates:
            await update.message.reply_text("Noch keine News verfügbar. Bitte später erneut versuchen.")
            return
        ranked = self.ranker.rank(candidates)[:5]
        lines = [
            f"📰 **{article['category'] or 'Allgemein'}**\n\n"
            f"• **{article['title']}**\n"
            f"{article['summary']}\n"
            f"⭐ Importance: {article['importance']}/10\n"
            f"Read more:\n{article['url']}"
            for article in ranked
        ]
        await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

    async def show_top(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        top = self.db.get_top_daily_articles(limit=5)
        if not top:
            await update.message.reply_text("Heute noch keine Top-News vorhanden.")
            return
        body = "\n\n".join(
            f"• **{item['title']}**\n{item['summary']}\n⭐ {item['importance']}/10\n{item['url']}"
            for item in top
        )
        await update.message.reply_text(f"📰 **Top News heute**\n\n{body}", parse_mode="Markdown")

    async def add_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        if not context.args:
            await update.message.reply_text("Bitte URL angeben: /add https://example.com/rss")
            return
        success, msg = self.user_manager.add_source(user.id, context.args[0])
        if success:
            self.sources.append(context.args[0])
            self.sources = list(dict.fromkeys(self.sources))
        await update.message.reply_text(msg)

    async def sources(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        items = self.user_manager.get_sources(user.id)
        text = "\n".join(f"- {src}" for src in items) if items else "Keine Quellen gespeichert."
        await update.message.reply_text(f"Deine Quellen:\n{text}")

    async def set_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not context.args:
            await update.message.reply_text(
                f"Bitte Kategorien angeben, z.B. /category AI Technology\nVerfügbar: {', '.join(self.config.supported_categories)}"
            )
            return
        ok, msg = self.user_manager.set_categories(user.id, context.args)
        await update.message.reply_text(msg)

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Bitte Suchbegriff angeben: /search AI")
            return
        results = self.db.search_articles(" ".join(context.args), limit=6)
        if not results:
            await update.message.reply_text("Keine Treffer gefunden.")
            return
        text = "\n\n".join(
            f"• **{item['title']}**\n{item.get('summary') or 'Keine Summary'}\n{item['url']}" for item in results
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def handle_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        text = update.message.text.strip()
        if text == "News holen":
            await self.get_news(update, context)
        elif text == "Top News heute":
            await self.show_top(update, context)
        elif text == "Quelle hinzufügen":
            await update.message.reply_text("Bitte nutze: /add <URL>")
        elif text == "Quellen anzeigen":
            await self.sources(update, context)
        elif text == "Kategorie wählen":
            await update.message.reply_text(
                f"Nutze /category mit Auswahl: {', '.join(self.config.supported_categories)}"
            )
        elif text == "Suche":
            await update.message.reply_text("Nutze /search <Begriff>")

    async def _start_scheduler(self, _: Application) -> None:
        LOGGER.info("Starting background scheduler")
        asyncio.create_task(
            run_scheduler(
                pipeline=self.pipeline,
                digest_service=self.digest_service,
                sources=self.sources,
                every_minutes=self.config.scheduler.collection_interval_minutes,
                daily_digest_hour_utc=self.config.scheduler.daily_digest_hour_utc,
            )
        )

    def _register_handlers(self) -> None:
        self.app.post_init = self._start_scheduler

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("news", self.get_news))
        self.app.add_handler(CommandHandler("add", self.add_source))
        self.app.add_handler(CommandHandler("sources", self.sources))
        self.app.add_handler(CommandHandler("category", self.set_category))
        self.app.add_handler(CommandHandler("search", self.search))
        self.app.add_handler(CommandHandler("top", self.show_top))

        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_buttons))

    def run(self) -> None:
        self.app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    NewsTelegramBot().run()
