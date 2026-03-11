"""Application configuration loader."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "config" / "config.json"


@dataclass(frozen=True)
class Limits:
    max_requests_per_minute: int
    max_tokens_per_day: int


@dataclass(frozen=True)
class SchedulerConfig:
    collection_interval_minutes: int
    daily_digest_hour_utc: int


@dataclass(frozen=True)
class AppConfig:
    telegram_token: str
    groq_api_key: str
    groq_endpoint: str
    groq_model: str
    default_sources: list[str]
    supported_categories: list[str]
    scheduler: SchedulerConfig
    limits: Limits


def setup_logging() -> None:
    """Configure app-wide logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _read_json_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config() -> AppConfig:
    """Load env vars and static JSON config into a typed object."""
    load_dotenv()
    config = _read_json_config()

    telegram_token = os.getenv("TELEGRAM_TOKEN", "")
    groq_api_key = os.getenv("GROQ_API_KEY", "")

    if not telegram_token:
        raise ValueError("TELEGRAM_TOKEN is missing in .env")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY is missing in .env")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        telegram_token=telegram_token,
        groq_api_key=groq_api_key,
        groq_endpoint="https://api.groq.com/openai/v1/chat/completions",
        groq_model="llama-3.1-8b-instant",
        default_sources=config.get("default_sources", []),
        supported_categories=config.get("supported_categories", []),
        scheduler=SchedulerConfig(**config.get("scheduler", {})),
        limits=Limits(**config.get("limits", {})),
    )
