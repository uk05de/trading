"""
sectors.py – Sector scoring based on recent price trends.

Computes a composite score per sector:
  0.4 × avg_return_5d + 0.6 × avg_return_14d

Normalized to -100 … +100.
"""

from __future__ import annotations

import datetime as dt
import streamlit as st

from db import _connect
from markets import SECTORS, SECTOR_MAP


@st.cache_data(ttl=3600, show_spinner=False)
def compute_sector_scores() -> dict[str, dict]:
    """
    Compute sector trend scores from the prices table.

    Returns {sector_name: {score, n_tickers, avg_5d, avg_14d, arrow}}
    for each sector that has data.  Index sectors are excluded.
    """
    conn = _connect()
    today = dt.date.today()

    # Boundaries (calendar days → covers enough trading days)
    cutoff_30d = (today - dt.timedelta(days=30)).isoformat()

    # Nur aktive DE-Ticker und Indizes (keine deaktivierten US-Titel)
    _valid_tickers = {t for t in SECTOR_MAP
                      if t.endswith(".DE") or t.endswith(".F") or t.startswith("^")}

    # Per ticker: latest close, close ~5 trading days ago, ~14 trading days ago
    # Using ROW_NUMBER to pick the Nth-most-recent row per ticker
    rows = conn.execute("""
        WITH ranked AS (
            SELECT ticker, date, close,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices
            WHERE date >= ?
        )
        SELECT
            cur.ticker,
            cur.close  AS close_now,
            d5.close   AS close_5d,
            d14.close  AS close_14d
        FROM ranked cur
        LEFT JOIN ranked d5  ON d5.ticker  = cur.ticker AND d5.rn  = 6
        LEFT JOIN ranked d14 ON d14.ticker = cur.ticker AND d14.rn = 15
        WHERE cur.rn = 1
    """, (cutoff_30d,)).fetchall()
    conn.close()

    # Filtere auf bekannte Ticker
    rows = [r for r in rows if r["ticker"] in _valid_tickers]

    # Aggregate per sector + collect index tickers separately
    sector_data: dict[str, list[tuple[float | None, float | None]]] = {}
    index_data: dict[str, tuple[float | None, float | None]] = {}
    for r in rows:
        ticker = r["ticker"]
        sector = SECTOR_MAP.get(ticker)
        if not sector:
            continue
        c_now = r["close_now"]
        c_5d = r["close_5d"]
        c_14d = r["close_14d"]
        if not c_now or c_now <= 0:
            continue
        ret_5d = ((c_now - c_5d) / c_5d * 100) if c_5d and c_5d > 0 else None
        ret_14d = ((c_now - c_14d) / c_14d * 100) if c_14d and c_14d > 0 else None
        if sector.startswith("Index:"):
            index_data[sector] = (ret_5d, ret_14d)
        else:
            sector_data.setdefault(sector, []).append((ret_5d, ret_14d))

    results: dict[str, dict] = {}
    all_raw: list[float] = []

    # Index tiles (single ticker each)
    for idx_name, (r5, r14) in index_data.items():
        avg_5d = r5 if r5 is not None else 0
        avg_14d = r14 if r14 is not None else 0
        raw = 0.4 * avg_5d + 0.6 * avg_14d
        all_raw.append(raw)
        results[idx_name] = {
            "raw": raw,
            "n_tickers": 1,
            "avg_5d": round(avg_5d, 2),
            "avg_14d": round(avg_14d, 2),
            "is_index": True,
        }

    for sector in SECTORS:
        entries = sector_data.get(sector, [])
        if not entries:
            results[sector] = {"score": 0, "n_tickers": 0, "avg_5d": 0, "avg_14d": 0, "arrow": "→", "is_index": False}
            continue

        vals_5d = [r5 for r5, _ in entries if r5 is not None]
        vals_14d = [r14 for _, r14 in entries if r14 is not None]

        avg_5d = sum(vals_5d) / len(vals_5d) if vals_5d else 0
        avg_14d = sum(vals_14d) / len(vals_14d) if vals_14d else 0

        raw = 0.4 * avg_5d + 0.6 * avg_14d
        all_raw.append(raw)
        results[sector] = {
            "raw": raw,
            "n_tickers": len(entries),
            "avg_5d": round(avg_5d, 2),
            "avg_14d": round(avg_14d, 2),
            "is_index": False,
        }

    # Normalize to -100 … +100
    if all_raw:
        max_abs = max(abs(v) for v in all_raw) or 1
        for sector, d in results.items():
            if d["n_tickers"] == 0:
                continue
            raw = d.pop("raw", 0)
            score = raw / max_abs * 100
            d["score"] = round(score, 1)
            if score > 10:
                d["arrow"] = "↑"
            elif score < -10:
                d["arrow"] = "↓"
            else:
                d["arrow"] = "→"
    else:
        for d in results.values():
            d.pop("raw", None)
            d["score"] = 0
            d["arrow"] = "→"

    return results
