"""
backtest.py – Historisches Backtesting des Swing-Trading-Systems.

Stellt Basisfunktionen bereit, die vom Backtest-Framework (bt_*.py) genutzt werden:
  - _download(): Kursdaten laden (DB + Yahoo-Fallback)
  - _build_market_contexts(): Markt-Kontext pro Tag aus DAX/VIX
  - _evaluate_trade(): Trade-Ergebnis simulieren
  - TICKERS, MAX_HOLD_DAYS, WARMUP_BARS: Konfiguration

Re-Exports für bt_signals.py:
  - compute_all (aus indicators)
  - analyze_stock (aus analyzer)
  - compute_targets (aus targets)
"""

from __future__ import annotations

import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf

from indicators import compute_all
from analyzer import analyze_stock
from targets import compute_targets
from markets import DAX_COMPONENTS, TECDAX_COMPONENTS, MDAX_COMPONENTS


# ─── Konfiguration ─────────────────────────────────────────────────────
# Alle deutschen Titel (DAX + TecDAX + MDAX)
# US-Titel deaktiviert: brauchen eigenen Markt-Kontext + Veto-Regeln
TICKERS = {**DAX_COMPONENTS, **TECDAX_COMPONENTS, **MDAX_COMPONENTS}
TICKER = list(TICKERS.keys())[0]  # Default für Einzeltest
WARMUP_BARS = 200         # Bars für Indikator-Warm-Up (EMA200 braucht ~200)
MAX_HOLD_DAYS = 100       # Timeout nach 100d – validiert als optimal (250d: +16% vs 100d: +299%)
MIN_CONFIDENCE = 0        # Kein Confidence-Filter – Veto + R/R filtern besser


# ─── Daten laden ───────────────────────────────────────────────────────

def _download(ticker: str, days: int = 1400) -> pd.DataFrame:
    """Lade OHLCV-Daten: zuerst aus DB, fehlende Tage von Yahoo nachladen."""
    from db import get_prices, save_prices

    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    start_str = start.isoformat()

    # 1. Aus DB laden
    rows = get_prices(ticker, start=start_str)

    need_fetch = False
    fetch_start = start

    if not rows:
        need_fetch = True
    else:
        first_date = rows[0]["date"]
        last_date = rows[-1]["date"]
        # Ältere Daten nötig?
        if start_str < first_date:
            need_fetch = True
        # Neuere Daten nötig? (älter als 1 Tag)
        if last_date < (end - dt.timedelta(days=1)).isoformat():
            need_fetch = True
            if start_str >= first_date:
                fetch_start = dt.date.fromisoformat(last_date)

    if need_fetch:
        fetch_end = end + dt.timedelta(days=1)
        df_new = yf.download(ticker, start=fetch_start, end=fetch_end,
                             interval="1d", progress=False, auto_adjust=True)
        if isinstance(df_new.columns, pd.MultiIndex):
            df_new.columns = [c[0] for c in df_new.columns]
        if not df_new.empty:
            save_prices(ticker, df_new)
        # Neu aus DB lesen (komplett)
        rows = get_prices(ticker, start=start_str)

    if not rows:
        return pd.DataFrame()

    # Dict-Rows → DataFrame
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    # Nur OHLCV-Spalten behalten
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─── Markt-Kontext aus historischen Daten ──────────────────────────────

def _build_market_contexts(dax_df: pd.DataFrame,
                           vix_df: pd.DataFrame) -> dict:
    """
    Berechne Markt-Kontext (DAX-Trend, VIX-Regime) für jeden Handelstag
    aus historischen Daten. Kein Look-Ahead.

    Returns: {pd.Timestamp: market_context_dict}
    """
    # Pre-compute DAX EMAs on full history
    dax_close = dax_df["Close"]
    dax_ema50 = dax_close.ewm(span=50, adjust=False).mean()
    dax_ema200 = dax_close.ewm(span=200, adjust=False).mean()

    contexts = {}
    for i in range(200, len(dax_df)):
        date = dax_df.index[i]
        c = dax_close.iloc[i]
        e50 = dax_ema50.iloc[i]
        e200 = dax_ema200.iloc[i]

        above50 = c > e50
        above200 = c > e200

        if above50 and above200:
            trend = "bull"
        elif not above50 and not above200:
            trend = "bear"
        else:
            trend = "neutral"

        # Monatsveränderung
        change_1m = 0.0
        if i >= 20:
            change_1m = round((c / dax_close.iloc[i - 20] - 1) * 100, 1)

        # VIX zum gleichen Datum (oder letzter verfügbarer Wert)
        vix_level = None
        vix_regime = "normal"
        vix_before = vix_df[vix_df.index <= date]
        if len(vix_before) > 0:
            level = float(vix_before["Close"].iloc[-1])
            vix_level = round(level, 1)
            if level < 15:
                vix_regime = "low"
            elif level < 25:
                vix_regime = "normal"
            elif level < 35:
                vix_regime = "high"
            else:
                vix_regime = "extreme"

        contexts[date] = {
            "index_name": "DAX",
            "index_trend": trend,
            "index_change_1m": change_1m,
            "vix_level": vix_level,
            "vix_regime": vix_regime,
        }
    return contexts


# ─── Trade-Auswertung ─────────────────────────────────────────────────

def _evaluate_trade(df: pd.DataFrame, signal_idx: int, direction: str,
                    entry: float, target: float | None,
                    stop_loss: float) -> dict:
    """
    Prüfe was nach dem Signal passiert.

    Für jeden Folgetag:
      - Stop-Loss zuerst prüfen (konservativ)
      - Dann Target prüfen
      - Nach MAX_HOLD_DAYS: Timeout → Ausstieg zum Schlusskurs

    Returns: {outcome, pnl_pct, days_held, exit_price, exit_date}
    """
    future = df.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_DAYS]

    for day_n, (date, row) in enumerate(future.iterrows(), 1):
        if direction == "LONG":
            # Stop getroffen? (Intraday-Tief)
            if row["Low"] <= stop_loss:
                pnl = (stop_loss - entry) / entry * 100
                return {"outcome": "STOP", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": stop_loss,
                        "exit_date": date}
            # Target getroffen? (Intraday-Hoch)
            if target and row["High"] >= target:
                pnl = (target - entry) / entry * 100
                return {"outcome": "TARGET", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": target,
                        "exit_date": date}
        else:  # SHORT
            if row["High"] >= stop_loss:
                pnl = (entry - stop_loss) / entry * 100
                return {"outcome": "STOP", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": stop_loss,
                        "exit_date": date}
            if target and row["Low"] <= target:
                pnl = (entry - target) / entry * 100
                return {"outcome": "TARGET", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": target,
                        "exit_date": date}

    # Timeout – Ausstieg zum letzten Schlusskurs
    if len(future) > 0:
        exit_px = float(future.iloc[-1]["Close"])
        if direction == "LONG":
            pnl = (exit_px - entry) / entry * 100
        else:
            pnl = (entry - exit_px) / entry * 100
        return {"outcome": "TIMEOUT", "pnl_pct": round(pnl, 2),
                "days_held": len(future), "exit_price": exit_px,
                "exit_date": future.index[-1]}

    return {"outcome": "NO_DATA", "pnl_pct": 0.0, "days_held": 0,
            "exit_price": entry, "exit_date": None}
