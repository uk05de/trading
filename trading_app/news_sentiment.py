"""
news_sentiment.py – Basic news sentiment from yfinance headlines.

Uses keyword matching on English headlines (yfinance returns English news
even for German stocks). Returns a score from -2 to +2.
"""

from __future__ import annotations

import datetime as dt
import yfinance as yf


# Keyword lists (financial context)
_POSITIVE = {
    "upgrade", "upgrades", "upgraded", "buy", "outperform", "beats",
    "surpass", "surpasses", "record", "profit", "growth", "grows",
    "strong", "surge", "surges", "soars", "jumps", "rally", "rallies",
    "bullish", "breakout", "dividend", "raises", "boost", "boosts",
    "positive", "optimistic", "beat", "exceeded", "exceeds", "recovery",
    "expansion", "upside", "momentum", "higher", "gain", "gains",
    "winner", "winners", "top pick", "overweight", "innovation",
}

_NEGATIVE = {
    "downgrade", "downgrades", "downgraded", "sell", "underperform",
    "misses", "miss", "missed", "loss", "losses", "decline", "declines",
    "drops", "drop", "falls", "fall", "crash", "crashes", "plunge",
    "plunges", "bearish", "warning", "warns", "weak", "weaker",
    "risk", "risks", "cut", "cuts", "layoffs", "layoff", "lawsuit",
    "fraud", "scandal", "debt", "default", "bankruptcy", "recall",
    "negative", "pessimistic", "underweight", "lower", "worst",
    "investigation", "probe", "fine", "fined", "penalty",
}


def get_news_sentiment(ticker_str: str) -> tuple[float, int, list[dict]]:
    """
    Analyze recent news for a ticker.

    Returns:
        score:      -2.0 to +2.0
        news_count: number of recent articles
        articles:   list of {title, date, sentiment} dicts
    """
    try:
        tk = yf.Ticker(ticker_str)
        news_items = tk.news or []
    except Exception:
        return 0.0, 0, []

    if not news_items:
        return 0.0, 0, []

    articles = []
    pos_count = 0
    neg_count = 0

    for item in news_items[:20]:  # Limit to 20 most recent
        title = item.get("title", "")
        link = item.get("link", "")
        publisher = item.get("publisher", "")
        pub_date = ""
        if "providerPublishTime" in item:
            try:
                pub_date = dt.datetime.fromtimestamp(
                    item["providerPublishTime"]
                ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        # Handle content.title format (newer yfinance)
        if not title and "content" in item:
            content = item["content"]
            if isinstance(content, dict):
                title = content.get("title", "")
                if not link:
                    link = content.get("canonicalUrl", {}).get("url", "")
                if not publisher:
                    provider = content.get("provider", {})
                    publisher = provider.get("displayName", "") if isinstance(provider, dict) else ""
                if not pub_date:
                    pdate = content.get("pubDate", "")
                    if pdate:
                        pub_date = pdate[:16]

        words = set(title.lower().split())
        pos_hits = words & _POSITIVE
        neg_hits = words & _NEGATIVE

        if pos_hits:
            sentiment = "positiv"
            pos_count += 1
        elif neg_hits:
            sentiment = "negativ"
            neg_count += 1
        else:
            sentiment = "neutral"

        articles.append({
            "title": title,
            "date": pub_date,
            "sentiment": sentiment,
            "publisher": publisher,
            "link": link,
        })

    total = pos_count + neg_count
    if total == 0:
        return 0.0, len(articles), articles

    # Net sentiment normalized to -2..+2
    net = (pos_count - neg_count) / max(total, 1)
    score = net * 2.0

    return round(score, 2), len(articles), articles
