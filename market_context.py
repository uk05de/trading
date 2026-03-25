"""
market_context.py – Broader market environment analysis.

Evaluates index trends (DAX for DE, S&P 500 for US) and VIX volatility
to provide market-level context per region.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st


def _analyze_index(symbol: str, name: str) -> dict:
    """Analyze a single index: trend, EMA, RSI, monthly change."""
    result = {
        "index_name": name,
        "trend": "neutral",
        "above_ema50": False,
        "above_ema200": False,
        "rsi": 50.0,
        "change_1m": 0.0,
    }
    try:
        df = yf.download(symbol, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        if len(df) > 200:
            close = df["Close"]
            ema50 = close.ewm(span=50, adjust=False).mean()
            ema200 = close.ewm(span=200, adjust=False).mean()

            result["above_ema50"] = bool(close.iloc[-1] > ema50.iloc[-1])
            result["above_ema200"] = bool(close.iloc[-1] > ema200.iloc[-1])

            # RSI
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            result["rsi"] = round(float(rsi.iloc[-1]), 1)

            # Monthly change
            if len(close) >= 20:
                result["change_1m"] = round(
                    (close.iloc[-1] / close.iloc[-20] - 1) * 100, 1
                )

            # Trend
            if result["above_ema50"] and result["above_ema200"]:
                result["trend"] = "bull"
            elif not result["above_ema50"] and not result["above_ema200"]:
                result["trend"] = "bear"
            else:
                result["trend"] = "neutral"
    except Exception:
        pass
    return result


@st.cache_data(ttl=900, show_spinner=False)
def get_market_context() -> dict:
    """
    Analyze market conditions for DE indices.

    Returns dict with:
      - DAX: {index_name, trend, above_ema50, above_ema200, rsi, change_1m}
      - TecDAX: {index_name, trend, ...}
      - MDAX: {index_name, trend, ...}
      - vix_level: float or None
      - vix_regime: "low" / "normal" / "high" / "extreme"
    """
    dax = _analyze_index("^GDAXI", "DAX")
    tecdax = _analyze_index("^TECDAX", "TecDAX")
    mdax = _analyze_index("^MDAXI", "MDAX")

    # --- VIX (global volatility gauge) ---
    vix_level = None
    vix_regime = "normal"
    try:
        vix = yf.download("^VIX", period="3mo", interval="1d",
                          progress=False, auto_adjust=True)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = [c[0] for c in vix.columns]

        if len(vix) > 0:
            level = float(vix["Close"].iloc[-1])
            vix_level = round(level, 1)

            if level < 15:
                vix_regime = "low"
            elif level < 25:
                vix_regime = "normal"
            elif level < 35:
                vix_regime = "high"
            else:
                vix_regime = "extreme"
    except Exception:
        pass

    return {
        "DAX": dax,
        "TecDAX": tecdax,
        "MDAX": mdax,
        "DE": dax,  # Kompatibilität
        "vix_level": vix_level,
        "vix_regime": vix_regime,
    }


def _ticker_region(ticker: str) -> str:
    """Determine market region from ticker symbol."""
    if ticker.endswith(".DE") or ticker.startswith("^GDAXI") or \
       ticker.startswith("^MDAXI") or ticker.startswith("^TECDAX"):
        return "DE"
    return "US"


def for_ticker(market: dict, ticker: str) -> dict:
    """
    Extract region-specific market context for a given ticker.

    Returns flat dict with generic keys used by analyzer.py:
      index_name, index_trend, index_change_1m, vix_level, vix_regime
    """
    region = _ticker_region(ticker)
    r = market.get(region, {})
    return {
        "index_name": r.get("index_name", "?"),
        "index_trend": r.get("trend", "neutral"),
        "index_change_1m": r.get("change_1m", 0.0),
        "vix_level": market.get("vix_level"),
        "vix_regime": market.get("vix_regime", "normal"),
    }
