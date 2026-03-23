"""
Backtest-Framework: Signal-Sammlung.

Einziger Code-Pfad für Signal-Sammlung mit allen Bug-Fixes aus
analyze_corrected_backtest.py. Wird von bt_run.py aufgerufen.

Fixes:
  1. Loop bis len(df)-1, nicht len(df)-MAX_HOLD_DAYS (kein Abschneiden)
  2. Exit-Daten aus DataFrame-Index (Handelstage, nicht Kalender)
  3. Blocking pro Ticker für hypothetische Trade-Dauer
  4. Kein Blocking wenn kein Target gefunden
"""

from __future__ import annotations

import pandas as pd

from backtest import (
    TICKERS, _download, _build_market_contexts,
    compute_all, analyze_stock, compute_targets, _evaluate_trade,
)
from bt_config import BacktestConfig


_NEUTRAL_MARKET = {
    "index_name": "DAX", "index_trend": "neutral",
    "index_change_1m": 0.0, "vix_level": None, "vix_regime": "normal",
}

_NO_FUNDAMENTALS = {
    "earnings_date": None, "days_to_earnings": None,
    "eps_estimate": None, "eps_surprise_prev": None,
    "analyst_rating": None, "analyst_count": 0,
    "analyst_target": None, "analyst_target_upside_pct": None,
    "forward_pe": None, "trailing_pe": None,
    "market_cap": None, "dividend_yield": None,
}


def collect_signals(cfg: BacktestConfig, verbose: bool = True) -> pd.DataFrame:
    """
    Alle Signale aus dem DE-Universum sammeln.

    Returns: DataFrame mit handelbaren Signalen (gefiltert nach Veto + R/R).
             Enthält auch die Roh-Analyse-Daten für spätere Auswertung.
    """
    dax_df = _download("^GDAXI", days=cfg.download_days_idx)
    vix_df = _download("^VIX", days=cfg.download_days_idx)
    market_contexts = _build_market_contexts(dax_df, vix_df)

    all_signals = []
    n_tickers = len(TICKERS)

    for t_idx, (ticker, name) in enumerate(TICKERS.items()):
        if verbose:
            print(f"\r  [{t_idx+1}/{n_tickers}] {ticker:20s}", end="", flush=True)

        try:
            df_raw = _download(ticker, days=cfg.download_days)
        except Exception:
            continue

        if len(df_raw) < cfg.warmup_bars + 20:
            continue

        df = compute_all(df_raw.copy())
        in_trade_until = -1

        for i in range(cfg.warmup_bars, len(df) - 1):
            if i <= in_trade_until:
                continue

            date = df.index[i]
            df_slice = df.iloc[:i + 1]

            # Markt-Kontext
            market = _NEUTRAL_MARKET.copy()
            if cfg.use_market_veto:
                for offset in range(5):
                    lookup = date - pd.Timedelta(days=offset)
                    if lookup in market_contexts:
                        market = market_contexts[lookup]
                        break
            else:
                market["_skip_market_veto"] = True

            # Analyse
            analysis = analyze_stock(
                df_slice, _NO_FUNDAMENTALS, market,
                news_score=0.0, news_count=0, sector_score=0.0,
            )

            direction = analysis["direction"]
            vetoed = analysis.get("vetoed", False)

            # Targets
            targets = compute_targets(df_slice, direction)
            if targets["target"] is None or targets["risk_reward"] is None:
                continue

            rr = targets["risk_reward"]

            # Trade-Ergebnis
            outcome = _evaluate_trade(
                df, i, direction,
                targets["entry"], targets["target"], targets["stop_loss"],
            )

            # Truncation-Check
            remaining = len(df) - 1 - i
            truncated = (outcome["outcome"] == "TIMEOUT"
                         and remaining < cfg.max_hold_days)

            # Exit-Datum aus DataFrame-Index
            exit_idx = min(i + outcome["days_held"], len(df) - 1)
            exit_date = df.index[exit_idx]

            sl_dist_pct = abs(targets["entry"] - targets["stop_loss"]) / targets["entry"]

            signal = {
                "date": date,
                "exit_date": exit_date,
                "ticker": ticker,
                "name": name,
                "direction": direction,
                "entry": targets["entry"],
                "target": targets["target"],
                "stop_loss": targets["stop_loss"],
                "risk_reward": rr,
                "sl_dist_pct": sl_dist_pct,
                "outcome": outcome["outcome"],
                "pnl_pct": outcome["pnl_pct"],
                "days_held": outcome["days_held"],
                "vetoed": vetoed,
                "truncated": truncated,
                # Analyse-Details für spätere Auswertung
                "score": analysis.get("score", 0),
                "confidence": analysis.get("confidence", 0),
                "n_contra": analysis.get("n_contra", 0),
            }

            # Custom-Veto
            if cfg.custom_veto and cfg.custom_veto(signal):
                signal["vetoed"] = True

            all_signals.append(signal)

            # Blocking: Ticker für hypothetische Trade-Dauer sperren
            in_trade_until = i + outcome["days_held"]

    if verbose:
        print(f"\r  {len(all_signals)} Roh-Signale aus {n_tickers} Tickern" + " " * 30)

    signals_df = pd.DataFrame(all_signals)
    if len(signals_df) == 0:
        return signals_df

    # Filter anwenden (abhaengig von Config)
    mask = pd.Series(True, index=signals_df.index)
    if not cfg.ignore_vetos:
        mask = mask & (~signals_df["vetoed"])
    if cfg.min_rr > 0:
        mask = mask & (signals_df["risk_reward"] >= cfg.min_rr)
    if cfg.only_long:
        mask = mask & (signals_df["direction"] == "LONG")
    if cfg.min_sl_dist > 0:
        mask = mask & (signals_df["sl_dist_pct"] >= cfg.min_sl_dist)
    if cfg.max_sl_dist < 1.0:
        mask = mask & (signals_df["sl_dist_pct"] <= cfg.max_sl_dist)
    filtered = signals_df[mask].copy().sort_values("date").reset_index(drop=True)

    if verbose:
        n_vetoed = signals_df["vetoed"].sum()
        n_truncated = filtered["truncated"].sum() if len(filtered) > 0 else 0
        print(f"  Roh: {len(signals_df)}, Gevetot: {n_vetoed}, Nach Filter: {len(filtered)}")
        print(f"  -> {len(filtered)} handelbare Signale ({n_truncated} am Datenende abgeschnitten)")

    return filtered
