"""
patterns.py – LONG + SHORT Swing-Trading Pattern-Detektoren.

Arbeitet auf DataFrames mit OHLCV + technischen Indikatoren aus indicators.compute_all().
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Hauptfunktionen
# ---------------------------------------------------------------------------

def detect_patterns(df: pd.DataFrame) -> list[dict]:
    """Pruefe den LETZTEN Bar auf alle Patterns. Gibt Liste der Treffer."""
    if len(df) < 200:
        return []
    return _detect_at(df, len(df) - 1)


def scan_all_patterns(df: pd.DataFrame, warmup: int = 200) -> list[dict]:
    """Iteriere ueber alle Bars (ab warmup) und sammle erkannte Patterns."""
    results: list[dict] = []
    for i in range(warmup, len(df)):
        results.extend(_detect_at(df, i))
    return results


# ---------------------------------------------------------------------------
# Interne Erkennung an Index-Position i
# ---------------------------------------------------------------------------

def _detect_at(df: pd.DataFrame, i: int) -> list[dict]:
    """Pruefe alle Patterns (LONG + SHORT) am Bar mit iloc-Position i."""
    hits: list[dict] = []
    for fn in (_pullback_ema20, _breakout_consolidation, _support_bounce,
               _ema50_bounce, _bollinger_squeeze_up, _gap_up_continuation,
               _bearish_engulfing, _failed_rally, _breakdown_support,
               _death_cross_sell, _resistance_rejection, _gap_down_continuation):
        result = fn(df, i)
        if result is not None:
            hits.append(result)
    return hits


def _row(df: pd.DataFrame, i: int, col: str) -> float:
    """Sicherer Zugriff auf Skalar per iloc."""
    v = df[col].iloc[i]
    return float(v) if not pd.isna(v) else np.nan


MIN_SL_DIST_PCT = 0.05  # SL muss mindestens 5% vom Entry entfernt sein


def _make(df: pd.DataFrame, i: int, pattern: str, entry: float,
          stop_loss: float, detail: str,
          direction: str = "LONG") -> dict | None:
    """Erzeuge Signal-Dict. SL-Floor: min 5% Distanz, sonst None."""
    if entry <= 0:
        return None

    # SL-Floor: mindestens MIN_SL_DIST_PCT vom Entry
    if direction == "LONG":
        min_sl = entry * (1 - MIN_SL_DIST_PCT)
        if stop_loss > min_sl:
            stop_loss = min_sl
    else:  # SHORT
        max_sl = entry * (1 + MIN_SL_DIST_PCT)
        if stop_loss < max_sl:
            stop_loss = max_sl

    date = df.index[i]
    if hasattr(date, 'date'):
        date = date.date()
    return {
        "pattern": pattern,
        "direction": direction,
        "date": date,
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# 1. Pullback EMA20
# ---------------------------------------------------------------------------

def _pullback_ema20(df: pd.DataFrame, i: int) -> dict | None:
    if i < 5:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")
    rsi = _row(df, i, "RSI")

    if np.isnan(close) or np.isnan(ema20) or np.isnan(ema50) or np.isnan(rsi):
        return None

    # Aufwaertstrend
    if ema20 <= ema50:
        return None

    # Close nahe oder unter EMA20
    if close > ema20 * 1.01:
        return None

    # War in den letzten 5 Tagen ueber EMA20
    above_recent = any(
        float(df["Close"].iloc[i - j]) > float(df["EMA20"].iloc[i - j])
        for j in range(1, 6)
    )
    if not above_recent:
        return None

    # RSI abgekuehlt
    if not (35 <= rsi <= 55):
        return None

    # Gruene Kerze
    if close <= open_:
        return None

    low5 = float(df["Low"].iloc[i - 4:i + 1].min())
    sl = min(low5, ema50)

    return _make(df, i, "pullback_ema20", close, sl,
                 f"RSI={rsi:.0f} EMA20={ema20:.2f} Close={close:.2f}")


# ---------------------------------------------------------------------------
# 2. Breakout Consolidation
# ---------------------------------------------------------------------------

def _breakout_consolidation(df: pd.DataFrame, i: int) -> dict | None:
    if i < 100:
        return None
    close = _row(df, i, "Close")
    bb_width = _row(df, i, "BB_Width")
    vol_ratio = _row(df, i, "Vol_Ratio")

    if np.isnan(close) or np.isnan(bb_width) or np.isnan(vol_ratio):
        return None

    # Enge BB_Width: unter Median der letzten 100 Tage
    bb_median = float(df["BB_Width"].iloc[i - 99:i + 1].median())
    if bb_width >= bb_median:
        return None

    # Ausbruch ueber 20-Tage-Hoch
    high20 = float(df["High"].iloc[max(0, i - 20):i].max())  # letzte 20 Tage VOR heute
    if close <= high20:
        return None

    # Volumenbestaetigung
    if vol_ratio <= 1.3:
        return None

    sl = float(df["Low"].iloc[max(0, i - 19):i + 1].min())

    return _make(df, i, "breakout_consolidation", close, sl,
                 f"BB_W={bb_width:.1f} Hi20={high20:.2f} Vol={vol_ratio:.1f}x")


# ---------------------------------------------------------------------------
# 3. Support Bounce
# ---------------------------------------------------------------------------

def _support_bounce(df: pd.DataFrame, i: int) -> dict | None:
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    high = _row(df, i, "High")
    low = _row(df, i, "Low")
    support = _row(df, i, "Support")
    dist_sup = _row(df, i, "Dist_Support_pct")
    hl = _row(df, i, "Higher_Lows")
    atr = _row(df, i, "ATR")

    if any(np.isnan(v) for v in (close, open_, high, low, support, dist_sup, hl, atr)):
        return None

    # Nahe Support
    if dist_sup >= 2.0:
        return None

    # Steigende Tiefs
    if hl < 2:
        return None

    # Gruene Kerze, Close in oberer Haelfte
    if close <= open_:
        return None
    mid = (high + low) / 2
    if close <= mid:
        return None

    sl = support - atr * 0.5

    return _make(df, i, "support_bounce", close, sl,
                 f"Supp={support:.2f} Dist={dist_sup:.1f}% HL={hl:.0f}")


# ---------------------------------------------------------------------------
# 4. EMA50 Bounce
# ---------------------------------------------------------------------------

def _ema50_bounce(df: pd.DataFrame, i: int) -> dict | None:
    if i < 10:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    low = _row(df, i, "Low")
    ema50 = _row(df, i, "EMA50")
    ema50_slope = _row(df, i, "EMA50_Slope")
    adx = _row(df, i, "ADX")
    atr = _row(df, i, "ATR")

    if any(np.isnan(v) for v in (close, open_, low, ema50, ema50_slope, adx, atr)):
        return None

    # EMA50 steigt deutlich
    if ema50_slope <= 0.5:
        return None

    # Kurs beruehrt/nahe EMA50
    if low > ema50 * 1.02:
        return None

    # War vorher deutlich ueber EMA50 (mind. 3 der letzten 10 Tage)
    count_above = sum(
        1 for j in range(1, 11)
        if i - j >= 0 and float(df["Close"].iloc[i - j]) > float(df["EMA50"].iloc[i - j]) * 1.03
    )
    if count_above < 3:
        return None

    # ADX > 20
    if adx <= 20:
        return None

    # Gruene Kerze
    if close <= open_:
        return None

    sl = ema50 - atr

    return _make(df, i, "ema50_bounce", close, sl,
                 f"EMA50={ema50:.2f} Slope={ema50_slope:.1f}% ADX={adx:.0f}")


# ---------------------------------------------------------------------------
# 5. Bollinger Squeeze Up
# ---------------------------------------------------------------------------

def _bollinger_squeeze_up(df: pd.DataFrame, i: int) -> dict | None:
    if i < 100:
        return None
    close = _row(df, i, "Close")
    bb_upper = _row(df, i, "BB_Upper")
    bb_lower = _row(df, i, "BB_Lower")
    bb_width = _row(df, i, "BB_Width")
    macd = _row(df, i, "MACD")
    macd_sig = _row(df, i, "MACD_Signal")

    if any(np.isnan(v) for v in (close, bb_upper, bb_lower, bb_width, macd, macd_sig)):
        return None

    # BB_Width im unteren 25% der letzten 100 Tage
    bb_q25 = float(df["BB_Width"].iloc[i - 99:i + 1].quantile(0.25))
    if bb_width > bb_q25:
        return None

    # Ausbruch ueber oberes Band
    if close <= bb_upper:
        return None

    # MACD bestaetigt Momentum
    if macd <= macd_sig:
        return None

    sl = (bb_upper + bb_lower) / 2

    return _make(df, i, "bollinger_squeeze_up", close, sl,
                 f"BB_W={bb_width:.1f} Q25={bb_q25:.1f} MACD={macd:.2f}")


# ---------------------------------------------------------------------------
# 6. Gap-Up Continuation
# ---------------------------------------------------------------------------

def _gap_up_continuation(df: pd.DataFrame, i: int) -> dict | None:
    if i < 1:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    gap_pct = _row(df, i, "Gap_Pct")
    vol_ratio = _row(df, i, "Vol_Ratio")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")
    ema50_slope = _row(df, i, "EMA50_Slope")
    prev_close = _row(df, i - 1, "Close")

    if any(np.isnan(v) for v in (close, open_, gap_pct, vol_ratio, ema20, ema50, prev_close)):
        return None

    # Gap > 1.5%
    if gap_pct <= 1.5:
        return None

    # Hohes Volumen
    if vol_ratio <= 1.5:
        return None

    # Gruene Kerze
    if close <= open_:
        return None

    # Nicht gegen den Trend
    trend_ok = (ema20 > ema50) or (not np.isnan(ema50_slope) and ema50_slope > 0)
    if not trend_ok:
        return None

    sl = prev_close

    return _make(df, i, "gap_up_continuation", close, sl,
                 f"Gap={gap_pct:.1f}% Vol={vol_ratio:.1f}x")


# ===========================================================================
# SHORT Patterns
# ===========================================================================

# ---------------------------------------------------------------------------
# 7. Bearish Engulfing — Grosse rote Kerze verschluckt Vortag nach Rally
# ---------------------------------------------------------------------------

def _bearish_engulfing(df: pd.DataFrame, i: int) -> dict | None:
    if i < 5:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    high = _row(df, i, "High")
    prev_close = _row(df, i - 1, "Close")
    prev_open = _row(df, i - 1, "Open")
    vol_ratio = _row(df, i, "Vol_Ratio")
    rsi = _row(df, i, "RSI")

    if any(np.isnan(v) for v in (close, open_, high, prev_close, prev_open, vol_ratio, rsi)):
        return None

    # Rote Kerze
    if close >= open_:
        return None

    # Vortag war gruen
    if prev_close <= prev_open:
        return None

    # Heutige Kerze verschluckt Vortag (Open > prev Close, Close < prev Open)
    if open_ <= prev_close or close >= prev_open:
        return None

    # Vorherige Aufwaertsbewegung (mind. 3 der letzten 5 Tage gruen)
    green_count = sum(
        1 for j in range(1, 6)
        if i - j >= 0 and float(df["Close"].iloc[i - j]) > float(df["Open"].iloc[i - j])
    )
    if green_count < 3:
        return None

    # RSI war ueberkauft (> 60)
    if rsi <= 60:
        return None

    # Volumenbestaetigung
    if vol_ratio <= 1.2:
        return None

    sl = high

    return _make(df, i, "bearish_engulfing", close, sl,
                 f"RSI={rsi:.0f} Vol={vol_ratio:.1f}x", direction="SHORT")


# ---------------------------------------------------------------------------
# 8. Failed Rally (Lower High) — Abwaertstrend, Rally scheitert
# ---------------------------------------------------------------------------

def _failed_rally(df: pd.DataFrame, i: int) -> dict | None:
    if i < 20:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    high = _row(df, i, "High")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")
    rsi = _row(df, i, "RSI")
    adx = _row(df, i, "ADX")

    if any(np.isnan(v) for v in (close, open_, high, ema20, ema50, rsi, adx)):
        return None

    # Abwaertstrend: EMA20 < EMA50
    if ema20 >= ema50:
        return None

    # Kurs nahe oder ueber EMA20 (Rally-Versuch)
    if close < ema20 * 0.99:
        return None

    # Aber unter EMA50 (gescheiterter Ausbruch)
    if close > ema50:
        return None

    # Rote Kerze (Umkehr)
    if close >= open_:
        return None

    # ADX zeigt Trendstaerke
    if adx <= 20:
        return None

    # RSI im neutralen/ueberkauften Bereich (Rally hat stattgefunden)
    if rsi < 40:
        return None

    # Lower High: Aktuelles Hoch niedriger als 10-Tage-Hoch davor
    recent_high = float(df["High"].iloc[max(0, i - 10):i].max())
    if high >= recent_high:
        return None

    sl = max(high, ema50)

    return _make(df, i, "failed_rally", close, sl,
                 f"EMA20={ema20:.2f} EMA50={ema50:.2f} RSI={rsi:.0f}", direction="SHORT")


# ---------------------------------------------------------------------------
# 9. Breakdown unter Support — Bruch unter 20-Tage-Low
# ---------------------------------------------------------------------------

def _breakdown_support(df: pd.DataFrame, i: int) -> dict | None:
    if i < 21:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    vol_ratio = _row(df, i, "Vol_Ratio")
    ema50_slope = _row(df, i, "EMA50_Slope")
    atr = _row(df, i, "ATR")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")

    if any(np.isnan(v) for v in (close, open_, vol_ratio, ema50_slope, atr, ema20, ema50)):
        return None

    # Support = 20-Tage-Low VOR heute (nicht inklusive heute)
    support = float(df["Low"].iloc[max(0, i - 20):i].min())

    # Bruch unter Support
    if close >= support:
        return None

    # Abwaertstrend
    if ema20 >= ema50:
        return None

    # Rote Kerze
    if close >= open_:
        return None

    # Volumenbestaetigung
    if vol_ratio <= 1.2:
        return None

    sl = support + atr * 0.5

    return _make(df, i, "breakdown_support", close, sl,
                 f"Supp={support:.2f} Vol={vol_ratio:.1f}x", direction="SHORT")


# ---------------------------------------------------------------------------
# 10. Death Cross Sell — EMA20 kreuzt EMA50 nach unten
# ---------------------------------------------------------------------------

def _death_cross_sell(df: pd.DataFrame, i: int) -> dict | None:
    if i < 5:
        return None
    close = _row(df, i, "Close")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")
    adx = _row(df, i, "ADX")
    atr = _row(df, i, "ATR")

    if any(np.isnan(v) for v in (close, ema20, ema50, adx, atr)):
        return None

    # EMA20 gerade unter EMA50 gekreuzt (heute oder gestern)
    prev_ema20 = _row(df, i - 1, "EMA20")
    prev_ema50 = _row(df, i - 1, "EMA50")
    if np.isnan(prev_ema20) or np.isnan(prev_ema50):
        return None

    # Kreuzung: vorher EMA20 >= EMA50, jetzt EMA20 < EMA50
    if not (prev_ema20 >= prev_ema50 and ema20 < ema50):
        return None

    # Kurs unter beiden EMAs
    if close > ema20 or close > ema50:
        return None

    # ADX bestaetigt Trend
    if adx <= 18:
        return None

    sl = ema50 + atr

    return _make(df, i, "death_cross_sell", close, sl,
                 f"EMA20={ema20:.2f} EMA50={ema50:.2f} ADX={adx:.0f}", direction="SHORT")


# ---------------------------------------------------------------------------
# 11. Resistance Rejection — Abprall an Widerstand (langer oberer Docht)
# ---------------------------------------------------------------------------

def _resistance_rejection(df: pd.DataFrame, i: int) -> dict | None:
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    high = _row(df, i, "High")
    low = _row(df, i, "Low")
    resistance = _row(df, i, "Resistance")
    dist_res = _row(df, i, "Dist_Resistance_pct")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")

    if any(np.isnan(v) for v in (close, open_, high, low, resistance, dist_res, ema20, ema50)):
        return None

    # Nahe Resistance (innerhalb 2%)
    if dist_res >= 2.0:
        return None

    # Abwaertstrend (EMA20 < EMA50)
    if ema20 >= ema50:
        return None

    # Langer oberer Docht: Docht > 2× Kerzenkoerper
    body = abs(close - open_)
    upper_wick = high - max(close, open_)
    if body <= 0 or upper_wick < body * 2:
        return None

    # Close im unteren Drittel der Range
    range_ = high - low
    if range_ <= 0 or (close - low) > range_ / 3:
        return None

    sl = high

    return _make(df, i, "resistance_rejection", close, sl,
                 f"Res={resistance:.2f} Dist={dist_res:.1f}%", direction="SHORT")


# ---------------------------------------------------------------------------
# 12. Gap-Down Continuation — Gap nach unten mit Volumen
# ---------------------------------------------------------------------------

def _gap_down_continuation(df: pd.DataFrame, i: int) -> dict | None:
    if i < 1:
        return None
    close = _row(df, i, "Close")
    open_ = _row(df, i, "Open")
    gap_pct = _row(df, i, "Gap_Pct")
    vol_ratio = _row(df, i, "Vol_Ratio")
    ema20 = _row(df, i, "EMA20")
    ema50 = _row(df, i, "EMA50")
    ema50_slope = _row(df, i, "EMA50_Slope")
    prev_close = _row(df, i - 1, "Close")

    if any(np.isnan(v) for v in (close, open_, gap_pct, vol_ratio, ema20, ema50, prev_close)):
        return None

    # Gap nach unten > 1.5% (Gap_Pct ist negativ bei Gap-Down)
    if gap_pct >= -1.5:
        return None

    # Hohes Volumen
    if vol_ratio <= 1.5:
        return None

    # Rote Kerze
    if close >= open_:
        return None

    # Im Abwaertstrend (oder Trend kippt)
    trend_down = (ema20 < ema50) or (not np.isnan(ema50_slope) and ema50_slope < 0)
    if not trend_down:
        return None

    sl = prev_close

    return _make(df, i, "gap_down_continuation", close, sl,
                 f"Gap={gap_pct:.1f}% Vol={vol_ratio:.1f}x", direction="SHORT")
