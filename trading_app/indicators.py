"""
indicators.py – Technical indicators for swing trading analysis.

All functions take a DataFrame with OHLCV columns and return it with
additional indicator columns attached.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators on daily OHLCV data."""
    out = df.copy()
    out = _trend(out)
    out = _momentum(out)
    out = _volatility(out)
    out = _volume(out)
    out = _support_resistance(out)
    return out


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def _trend(df: pd.DataFrame) -> pd.DataFrame:
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    # EMA50 Slope: prozentuale Veränderung der EMA50 über 10 Tage
    df["EMA50_Slope"] = df["EMA50"].pct_change(10) * 100

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    # ADX
    df["ADX"] = _adx(df, 14)

    return df


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(span=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

def _momentum(df: pd.DataFrame) -> pd.DataFrame:
    # RSI (14)
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # Stochastic %K / %D (14, 3) – kept for charts, not used in voting
    low14 = df["Low"].rolling(14).min()
    high14 = df["High"].rolling(14).max()
    df["Stoch_K"] = 100 * (df["Close"] - low14) / (high14 - low14).replace(0, np.nan)
    df["Stoch_D"] = df["Stoch_K"].rolling(3).mean()

    # Rate of Change
    df["ROC"] = df["Close"].pct_change(10) * 100
    df["ROC_5d"] = df["Close"].pct_change(5) * 100

    # Higher Lows / Lower Highs (5-day pattern)
    # Count how many of the last 4 daily lows are higher than the previous
    _lows = df["Low"].rolling(1).min()  # just daily lows
    _hl_count = sum(
        (df["Low"].shift(i) > df["Low"].shift(i + 1)).astype(int)
        for i in range(4)
    )
    df["Higher_Lows"] = _hl_count  # 0-4: how many of last 4 lows are rising
    _lh_count = sum(
        (df["High"].shift(i) < df["High"].shift(i + 1)).astype(int)
        for i in range(4)
    )
    df["Lower_Highs"] = _lh_count  # 0-4: how many of last 4 highs are falling

    # Gap detection
    df["Gap_Pct"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100

    return df


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def _volatility(df: pd.DataFrame) -> pd.DataFrame:
    # ATR (14)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(span=14, adjust=False).mean()
    df["ATR_pct"] = df["ATR"] / df["Close"] * 100

    # Bollinger Bands (20, 2)
    sma20 = df["Close"].rolling(20).mean()
    std20 = df["Close"].rolling(20).std()
    df["BB_Upper"] = sma20 + 2 * std20
    df["BB_Lower"] = sma20 - 2 * std20
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / sma20 * 100
    df["BB_Pct"] = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"]).replace(0, np.nan)

    return df


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def _volume(df: pd.DataFrame) -> pd.DataFrame:
    df["Volume"] = df["Volume"].replace(0, np.nan).infer_objects(copy=False).ffill().bfill()
    df["Vol_SMA20"] = df["Volume"].rolling(20).mean()
    df["Vol_Ratio"] = df["Volume"] / df["Vol_SMA20"].replace(0, np.nan)
    return df


# ---------------------------------------------------------------------------
# Support / Resistance (pivot-based)
# ---------------------------------------------------------------------------

def _support_resistance(df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
    """Find nearest support and resistance from rolling pivots."""
    highs = df["High"].rolling(lookback, center=True).max()
    lows = df["Low"].rolling(lookback, center=True).min()

    # Simplified: use recent swing levels
    df["Resistance"] = df["High"].rolling(lookback).max()
    df["Support"] = df["Low"].rolling(lookback).min()

    # Distance to S/R in %
    df["Dist_Resistance_pct"] = (df["Resistance"] - df["Close"]) / df["Close"] * 100
    df["Dist_Support_pct"] = (df["Close"] - df["Support"]) / df["Close"] * 100

    return df


# ---------------------------------------------------------------------------
# Fibonacci levels for a recent swing
# ---------------------------------------------------------------------------

def fibonacci_levels(high: float, low: float) -> dict[str, float]:
    """Calculate Fibonacci retracement and extension levels."""
    diff = high - low
    return {
        "fib_0": high,
        "fib_236": high - 0.236 * diff,
        "fib_382": high - 0.382 * diff,
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff,
        "fib_786": high - 0.786 * diff,
        "fib_1000": low,
        "ext_1272": high + 0.272 * diff,
        "ext_1618": high + 0.618 * diff,
    }
