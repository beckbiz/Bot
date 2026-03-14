"""Telegram bot entry point with improved guided UX flows."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

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

        self.default_sources = list(dict.fromkeys(self.config.default_sources))
        self._bootstrap_default_sources()

        # lightweight guided interaction state: {telegram_user_id: action_name}
        self.pending_actions: Dict[int, str] = {}

        self._register_handlers()

    def _bootstrap_default_sources(self) -> None:
        for source in self.default_sources:
            source_type = "rss" if "rss" in source.lower() or "feed" in source.lower() else "website"
            self.db.add_source(None, source, source_type)

    def _get_all_sources(self) -> list[str]:
        merged = self.default_sources + self.db.get_all_sources()
        return list(dict.fromkeys(merged))

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

    async def _send_text(self, update: Update, text: str) -> None:
        if update.message:
            await update.message.reply_text(text)

    @staticmethod
    def _format_article(article: dict) -> str:
        return (
            f"📰 {article.get('category') or 'Allgemein'}\n"
            f"• {article.get('title', 'Untitled')}\n"
            f"{article.get('summary') or 'Keine Zusammenfassung verfügbar.'}\n"
            f"⭐ Importance: {article.get('importance') or 1}/10\n"
            f"🔗 {article.get('url', '')}"
        )

    async def start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user or not update.message:
            return
        self.user_manager.register_user(user.id)
        text = (
            "Willkommen beim AI News Assistant!\n\n"
            "Du kannst die Buttons nutzen oder Commands eingeben:\n"
            "/news  /add <url>  /sources  /category <...>  /search <begriff>  /top\n\n"
            "Tipp: Nutze 'Quelle hinzufügen' oder 'Kategorie wählen' für geführte Eingaben."
        )
        await update.message.reply_text(text, reply_markup=self.keyboard())

    async def help_cmd(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await self._send_text(
            update,
            "Verfügbare Aktionen:\n"
            "• News holen\n"
            "• Quelle hinzufügen\n"
            "• Quellen anzeigen\n"
            "• Kategorie wählen\n"
            "• Top News heute\n"
            "• Suche\n\n"
            "Oder per Commands:\n"
            "/news, /add <url>, /sources, /category AI Technology, /search AI, /top",
        )

    async def get_news(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return

        telegram_user_id = update.effective_user.id
        user_db_id = self.user_manager.register_user(telegram_user_id)
        candidates = self.db.get_user_digest_candidates(user_db_id, limit=8)

        if not candidates:
            await self._send_text(update, "Sammle neue News und erstelle Zusammenfassungen... ⏳")
            user_sources = self.user_manager.get_sources(telegram_user_id)
            effective_sources = list(dict.fromkeys(user_sources + self.default_sources))
            self.pipeline.collect_and_store(effective_sources)
            self.pipeline.summarize_pending()
            candidates = self.db.get_user_digest_candidates(user_db_id, limit=8)

        if not candidates:
            await self._send_text(update, "Noch keine News verfügbar. Bitte später erneut versuchen.")
            return

        ranked = self.ranker.rank(candidates)[:5]
        text = "\n\n".join(self._format_article(article) for article in ranked)
        await self._send_text(update, text)

    async def show_top(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        top = self.db.get_top_daily_articles(limit=5)
        if not top:
            await self._send_text(update, "Heute noch keine Top-News vorhanden.")
            return
        body = "\n\n".join(self._format_article(item) for item in top)
        await self._send_text(update, f"Top News heute\n\n{body}")

    async def add_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return

        if not context.args:
            self.pending_actions[update.effective_user.id] = "add_source"
            await self._send_text(update, "Bitte sende jetzt die URL der Quelle (RSS oder Website).")
            return

        success, msg = self.user_manager.add_source(update.effective_user.id, context.args[0])
        await self._send_text(update, msg)

    async def show_sources(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return
        items = self.user_manager.get_sources(update.effective_user.id)
        text = "\n".join(f"- {src}" for src in items) if items else "Keine Quellen gespeichert."
        await self._send_text(update, f"Deine Quellen:\n{text}")

    async def set_category(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return

        if not context.args:
            self.pending_actions[update.effective_user.id] = "set_category"
            await self._send_text(
                update,
                "Bitte sende Kategorien als Liste, z. B.:\nAI, Technology\n\n"
                f"Verfügbar: {', '.join(self.config.supported_categories)}",
            )
            return

        _, msg = self.user_manager.set_categories(update.effective_user.id, context.args)
        await self._send_text(update, msg)

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return

        if not context.args:
            self.pending_actions[update.effective_user.id] = "search"
            await self._send_text(update, "Bitte sende jetzt deinen Suchbegriff.")
            return

        results = self.db.search_articles(" ".join(context.args), limit=6)
        if not results:
            await self._send_text(update, "Keine Treffer gefunden.")
            return

        text = "\n\n".join(
            f"• {item['title']}\n{item.get('summary') or 'Keine Summary'}\n{item['url']}" for item in results
        )
        await self._send_text(update, text)

    async def _handle_pending_action(self, update: Update) -> bool:
        if not update.message or not update.effective_user:
            return False

        user_id = update.effective_user.id
        action = self.pending_actions.get(user_id)
        if not action:
            return False

        message_text = update.message.text.strip()

        if action == "add_source":
            success, msg = self.user_manager.add_source(user_id, message_text)
            await self._send_text(update, msg)
            if success:
                self.pending_actions.pop(user_id, None)
            return True

        if action == "set_category":
            raw_items = [item.strip() for item in message_text.replace(";", ",").split(",") if item.strip()]
            if not raw_items:
                await self._send_text(update, "Bitte mindestens eine Kategorie senden.")
                return True
            ok, msg = self.user_manager.set_categories(user_id, raw_items)
            await self._send_text(update, msg)
            if ok:
                self.pending_actions.pop(user_id, None)
            return True

        if action == "search":
            self.pending_actions.pop(user_id, None)
            results = self.db.search_articles(message_text, limit=6)
            if not results:
                await self._send_text(update, "Keine Treffer gefunden.")
                return True
            text = "\n\n".join(
                f"• {item['title']}\n{item.get('summary') or 'Keine Summary'}\n{item['url']}" for item in results
            )
            await self._send_text(update, text)
            return True

        return False

    async def handle_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        if await self._handle_pending_action(update):
            return

        text = update.message.text.strip()
        if text == "News holen":
            await self.get_news(update, context)
        elif text == "Top News heute":
            await self.show_top(update, context)
        elif text == "Quelle hinzufügen":
            self.pending_actions[update.effective_user.id] = "add_source"
            await self._send_text(update, "Bitte sende die URL der neuen Quelle.")
        elif text == "Quellen anzeigen":
            await self.show_sources(update, context)
        elif text == "Kategorie wählen":
            self.pending_actions[update.effective_user.id] = "set_category"
            await self._send_text(update, f"Verfügbare Kategorien: {', '.join(self.config.supported_categories)}")
        elif text == "Suche":
            self.pending_actions[update.effective_user.id] = "search"
            await self._send_text(update, "Bitte sende deinen Suchbegriff.")
        else:
            await self._send_text(update, "Unbekannte Eingabe. Nutze /help oder die Buttons.")

    async def _start_scheduler(self, _: Application) -> None:
        LOGGER.info("Starting background scheduler")
        asyncio.create_task(
            run_scheduler(
                pipeline=self.pipeline,
                digest_service=self.digest_service,
                source_provider=self._get_all_sources,
                every_minutes=self.config.scheduler.collection_interval_minutes,
                daily_digest_hour_utc=self.config.scheduler.daily_digest_hour_utc,
            )
        )

    def _register_handlers(self) -> None:
        self.app.post_init = self._start_scheduler

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help_cmd))
        self.app.add_handler(CommandHandler("news", self.get_news))
        self.app.add_handler(CommandHandler("add", self.add_source))
        self.app.add_handler(CommandHandler("sources", self.show_sources))
        self.app.add_handler(CommandHandler("category", self.set_category))
        self.app.add_handler(CommandHandler("search", self.search))
        self.app.add_handler(CommandHandler("top", self.show_top))

        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_buttons))

    def run(self) -> None:
        self.app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    NewsTelegramBot().run()

