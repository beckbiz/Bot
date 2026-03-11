# AI News Aggregator Telegram Bot

Production-ready AI-powered Telegram bot that collects news from RSS/web sources, extracts content, summarizes with Groq LLM, ranks importance, removes duplicates, and sends personalized user digests.

## Features

- Telegram bot with buttons and commands
- User management with SQLite
- Source management (RSS + websites)
- Article scraping via `newspaper3k` with BeautifulSoup fallback
- Duplicate detection (URL + title similarity)
- Groq AI summarization with retries and rate-limit handling
- Importance + recency ranking
- Category subscriptions
- Personalized digest, daily briefing, breaking-news alerts
- Trending topics extraction
- Article clustering for same event
- Background scheduler every 30 minutes
- Search across stored articles
- Token/request usage tracking
- Structured logging and secure secret handling with `.env`

## Project Structure

```
news-ai-bot/
├── bot.py
├── scheduler.py
├── ai_service.py
├── rss_collector.py
├── article_scraper.py
├── duplicate_detector.py
├── ranking.py
├── database.py
├── user_manager.py
├── config.py
├── data/
│   ├── users.db
│   ├── articles.db
├── config/
│   └── config.json
├── .env
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment variables in `.env`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
```

4. Optional: Edit `config/config.json` for sources, categories, and limits.

## Run

```bash
python bot.py
```

## Bot Commands

- `/start`
- `/news`
- `/add <url>`
- `/sources`
- `/category <cat1> <cat2> ...`
- `/search <query>`
- `/top`

Buttons:

- News holen
- Quelle hinzufügen
- Quellen anzeigen
- Kategorie wählen
- Top News heute
- Suche

## Production Notes

- For long-running production, run under `systemd`, Docker, or a process manager.
- Ensure outbound internet is available for RSS/web scraping and Groq API.
- Keep `.env` secrets private and rotate tokens periodically.
