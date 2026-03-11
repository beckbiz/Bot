"""Ranking, clustering, and trending keyword extraction."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any


class NewsRanker:
    @staticmethod
    def _recency_score(published_at: str | None) -> float:
        if not published_at:
            return 0.1
        try:
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            delta_hours = max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
            return 1.0 / math.log(delta_hours + 2, 2)
        except ValueError:
            return 0.1

    def rank(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        source_count = Counter(item.get("source", "") for item in articles)
        scored: list[dict[str, Any]] = []
        for article in articles:
            importance = int(article.get("importance") or 1)
            recency = self._recency_score(article.get("published_at") or article.get("inserted_at"))
            source_penalty = 1 / (1 + (source_count[article.get("source", "")] - 1) * 0.3)
            final_score = importance * 0.7 + recency * 3 + source_penalty
            clone = dict(article)
            clone["ranking_score"] = round(final_score, 3)
            scored.append(clone)

        return sorted(scored, key=lambda x: x["ranking_score"], reverse=True)

    def cluster_articles(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters: list[list[dict[str, Any]]] = []

        for article in articles:
            matched = False
            for cluster in clusters:
                if SequenceMatcher(
                    None,
                    article.get("title", "").lower(),
                    cluster[0].get("title", "").lower(),
                ).ratio() > 0.75:
                    cluster.append(article)
                    matched = True
                    break
            if not matched:
                clusters.append([article])

        merged: list[dict[str, Any]] = []
        for cluster in clusters:
            lead = dict(cluster[0])
            lead["cluster_size"] = len(cluster)
            if len(cluster) > 1:
                lead["source"] = f"{lead.get('source')} (+{len(cluster)-1} Quellen)"
            merged.append(lead)

        return merged

    @staticmethod
    def trending_topics(articles: list[dict[str, Any]], top_n: int = 8) -> list[str]:
        stop_words = {
            "the", "and", "for", "with", "that", "from", "this", "news", "über", "und", "der", "die",
            "ein", "eine", "von", "mit", "bei", "nach", "new", "will", "says", "report",
        }
        tokens: list[str] = []
        for article in articles:
            text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
            words = re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", text)
            tokens.extend([word for word in words if word not in stop_words])

        return [word.title() for word, _ in Counter(tokens).most_common(top_n)]
