"""Groq-backed AI summarization service with quota tracking and retries."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests

from database import Database

LOGGER = logging.getLogger(__name__)

PROMPT_TEMPLATE = """
Summarize the following news article into three concise bullet points.
Also classify its category and give an importance score from 1 to 10.

Return strict JSON only with this shape:
{
  "summary": "...",
  "category": "Technology|AI|Politics|Business|Science|Gaming|World",
  "importance": 1
}

Article text:
{text}
""".strip()


class AIService:
    def __init__(
        self,
        db: Database,
        api_key: str,
        endpoint: str,
        model: str,
        max_requests_per_minute: int,
        max_tokens_per_day: int,
    ) -> None:
        self.db = db
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = model
        self.max_requests_per_minute = max_requests_per_minute
        self.max_tokens_per_day = max_tokens_per_day
        self.session = requests.Session()

    def _can_make_request(self, estimated_tokens: int) -> bool:
        usage = self.db.get_usage()
        if usage["requests_this_minute"] >= self.max_requests_per_minute:
            LOGGER.warning("AI RPM limit reached")
            return False
        if usage["tokens_today"] + estimated_tokens > self.max_tokens_per_day:
            LOGGER.warning("AI daily token limit reached")
            return False
        return True

    def summarize(self, article_text: str) -> dict[str, Any]:
        if not article_text:
            return {
                "summary": "No content extracted.",
                "category": "World",
                "importance": 1,
            }

        prompt = PROMPT_TEMPLATE.format(text=article_text[:5000])
        estimated_tokens = max(200, len(prompt) // 4)
        if not self._can_make_request(estimated_tokens):
            return {
                "summary": "Rate-limited: summary pending.",
                "category": "World",
                "importance": 1,
            }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise news analysis assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, 5):
            try:
                response = self.session.post(self.endpoint, headers=headers, json=payload, timeout=30)
                if response.status_code in {429, 500, 502, 503, 504}:
                    sleep_for = attempt * 2
                    LOGGER.warning("Groq transient error %s. retry=%s", response.status_code, attempt)
                    time.sleep(sleep_for)
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = self._parse_json(content)
                usage = data.get("usage", {})
                completion_tokens = int(usage.get("total_tokens", estimated_tokens))
                self.db.log_usage(tokens_used=completion_tokens, requests_count=1)
                return parsed
            except requests.RequestException as exc:
                LOGGER.warning("Groq request failed attempt=%s: %s", attempt, exc)
                time.sleep(attempt * 2)
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("Groq response parse failure: %s", exc)
                break

        return {
            "summary": "Summary unavailable due to API error.",
            "category": "World",
            "importance": 1,
        }

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        raw = content.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                raise
            parsed = json.loads(match.group(0))

        summary = str(parsed.get("summary", "")).strip()
        if isinstance(parsed.get("summary"), list):
            summary = "\n".join(f"• {str(item).strip()}" for item in parsed["summary"] if str(item).strip())

        category = str(parsed.get("category", "World")).strip() or "World"
        importance_raw = parsed.get("importance", 1)
        try:
            importance = int(float(importance_raw))
        except (TypeError, ValueError):
            importance = 1

        return {
            "summary": summary or "Summary unavailable.",
            "category": category,
            "importance": max(1, min(10, importance)),
        }

