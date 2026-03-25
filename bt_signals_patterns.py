"""
Backtest-Framework: Pattern-basierte Signal-Sammlung.

Alternative zu bt_signals.collect_signals() — nutzt Pattern-Detektoren
aus patterns.py statt analyze_stock() + compute_targets().

SL = chartbasiert vom Pattern-Detektor (EMA, Support, Low etc.)
Target = chartbasiert via compute_targets() (naechstes Hindernis)
R/R = ergibt sich automatisch aus Entry, SL, Target

Ausgabe-Format identisch zu bt_signals → bt_simulate.simulate() funktioniert direkt.
"""

from __future__ import annotations

import os
import pandas as pd

import numpy as np

from backtest import TICKERS, _download, _evaluate_trade, MAX_HOLD_DAYS
from indicators import compute_all
from markets import get_index
from patterns import scan_all_patterns
from targets import compute_targets, _find_sr_zones, _find_swing_levels
from indicators import fibonacci_levels
from bt_config import BacktestConfig

CACHE_PATH = "data/signals_patterns_ct.pkl"


# ---------------------------------------------------------------------------
# Trailing-Auswertung: SL nachziehen + Target updaten
# ---------------------------------------------------------------------------

def _evaluate_trade_trailing(df: pd.DataFrame, signal_idx: int,
                             entry: float, target: float,
                             stop_loss: float) -> dict:
    """
    Trade-Auswertung mit taeglichem Trailing-SL und Target-Update.

    Trailing-SL (nur LONG, nur hoeher):
      - Start: Pattern-SL
      - Ab 1R Gewinn: max(alter_SL, Breakeven)
      - Ab 2R Gewinn: max(alter_SL, Entry + 1R)
      - Ab 3R Gewinn: max(alter_SL, Close - 1.2 * ATR)
      - Sonst: max(alter_SL, Close - 2.5 * ATR)

    Target-Update (nur hoeher):
      - Taeglich: naechste Resistance/Fibonacci/Swing-High ueber Close
      - Nur akzeptiert wenn hoeher als bisheriges Target
    """
    initial_risk = entry - stop_loss
    if initial_risk <= 0:
        return {"outcome": "NO_DATA", "pnl_pct": 0.0, "days_held": 0,
                "exit_price": entry, "exit_date": None,
                "final_sl": stop_loss, "final_target": target}

    current_sl = stop_loss
    current_target = target
    future = df.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_DAYS]

    for day_n, (date, row) in enumerate(future.iterrows(), 1):
        close = float(row["Close"])
        low = float(row["Low"])
        high = float(row["High"])
        atr = float(row["ATR"]) if not np.isnan(row["ATR"]) else initial_risk

        # --- SL-Check zuerst (konservativ) ---
        if low <= current_sl:
            pnl = (current_sl - entry) / entry * 100
            return {"outcome": "STOP", "pnl_pct": round(pnl, 2),
                    "days_held": day_n, "exit_price": current_sl,
                    "exit_date": date,
                    "final_sl": current_sl, "final_target": current_target}

        # --- Target-Check ---
        if high >= current_target:
            pnl = (current_target - entry) / entry * 100
            return {"outcome": "TARGET", "pnl_pct": round(pnl, 2),
                    "days_held": day_n, "exit_price": current_target,
                    "exit_date": date,
                    "final_sl": current_sl, "final_target": current_target}

        # --- Trailing-SL updaten (nach Tagesschluss, konservativ) ---
        # Kein Trailing unter 2R — Trade braucht Luft zum Atmen
        profit = close - entry
        profit_in_r = profit / initial_risk

        if profit_in_r >= 3:
            new_sl = close - 1.5 * atr
        elif profit_in_r >= 2:
            new_sl = max(entry + initial_risk, close - 2.0 * atr)
        else:
            new_sl = stop_loss  # Kein Trailing unter 2R

        # SL darf nur steigen (LONG)
        if new_sl > current_sl:
            current_sl = round(new_sl, 2)

        # --- Target updaten (alle 5 Tage, Performance) ---
        if day_n % 5 == 0 and signal_idx + day_n < len(df):
            df_slice = df.iloc[:signal_idx + day_n + 1]
            new_targets = compute_targets(df_slice, "LONG")
            if new_targets["target"] is not None and new_targets["target"] > current_target:
                current_target = round(new_targets["target"], 2)

    # Timeout
    if len(future) > 0:
        exit_px = float(future.iloc[-1]["Close"])
        pnl = (exit_px - entry) / entry * 100
        return {"outcome": "TIMEOUT", "pnl_pct": round(pnl, 2),
                "days_held": len(future), "exit_price": exit_px,
                "exit_date": future.index[-1],
                "final_sl": current_sl, "final_target": current_target}

    return {"outcome": "NO_DATA", "pnl_pct": 0.0, "days_held": 0,
            "exit_price": entry, "exit_date": None,
            "final_sl": current_sl, "final_target": current_target}


def collect_pattern_signals(cfg: BacktestConfig,
                            target_rr: float | None = None,
                            trailing: bool = False,
                            force_rescan: bool = False,
                            verbose: bool = True) -> pd.DataFrame:
    """
    Sammle Pattern-basierte Signale ueber alle Ticker.

    1. Pro Ticker: _download() -> compute_all() -> scan_all_patterns()
    2. SL = vom Pattern-Detektor (chartbasiert)
    3. Target:
       - target_rr=None (default): chartbasiert via compute_targets()
       - target_rr=2.0 etc.: fixes R/R (Entry + rr * Risk)
    4. R/R = ergibt sich aus Entry, SL, Target
    5. Outcome:
       - trailing=False: statisch (_evaluate_trade)
       - trailing=True: Trailing-SL + Target-Update (_evaluate_trade_trailing)
    6. Ergebnis wird gecached in PKL

    Returns: DataFrame im gleichen Format wie bt_signals.collect_signals()
    """
    # Cache-Pfad: unterschiedlich je nach target_rr und trailing
    trail_suffix = "_trail" if trailing else ""
    if target_rr is not None:
        cache = f"data/signals_patterns_rr{target_rr:.1f}{trail_suffix}.pkl"
    else:
        cache = CACHE_PATH.replace(".pkl", f"{trail_suffix}.pkl") if trailing else CACHE_PATH

    if not force_rescan and os.path.exists(cache):
        if verbose:
            print(f"  Cache geladen: {cache}")
        return pd.read_pickle(cache)

    all_signals: list[dict] = []
    n_tickers = len(TICKERS)
    n_no_target = 0

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
        hits = scan_all_patterns(df, warmup=cfg.warmup_bars)

        # Persistenz-Map: (pattern, date) -> True fuer alle Hits VOR Blocking
        _hit_dates: dict[str, set] = {}  # pattern -> {date1, date2, ...}
        for h in hits:
            _hit_dates.setdefault(h["pattern"], set()).add(pd.Timestamp(h["date"]))

        # Blocking: pro Ticker nur ein Trade gleichzeitig
        in_trade_until = -1

        for hit in hits:
            # iloc-Position des Signals finden
            sig_date = pd.Timestamp(hit["date"])
            idx_pos = df.index.get_indexer([sig_date], method="nearest")[0]

            # Blocking pruefen
            if idx_pos <= in_trade_until:
                continue

            entry = hit["entry"]
            sl = hit["stop_loss"]
            direction = hit.get("direction", "LONG")
            risk = abs(entry - sl)

            if risk <= 0 or entry <= 0:
                continue

            sl_dist_pct = risk / entry

            # Target bestimmen
            if target_rr is not None:
                # Fixes R/R
                if direction == "LONG":
                    target = entry + target_rr * risk
                else:
                    target = entry - target_rr * risk
                rr = target_rr
            else:
                # Chartbasiertes Target via compute_targets()
                df_slice = df.iloc[:idx_pos + 1]
                targets = compute_targets(df_slice, direction)

                if targets["target"] is None:
                    n_no_target += 1
                    continue

                target = targets["target"]
                reward = abs(target - entry)
                rr = round(reward / risk, 2) if risk > 0 else 0.0

            # Trade auswerten
            if trailing and direction == "LONG":
                outcome = _evaluate_trade_trailing(
                    df, idx_pos, entry, target, sl,
                )
            else:
                outcome = _evaluate_trade(
                    df, idx_pos, direction, entry, target, sl,
                )

            # Truncation-Check
            remaining = len(df) - 1 - idx_pos
            truncated = (outcome["outcome"] == "TIMEOUT"
                         and remaining < cfg.max_hold_days)

            # Exit-Datum
            exit_idx = min(idx_pos + outcome["days_held"], len(df) - 1)
            exit_date = df.index[exit_idx]

            # Persistenz: wie viele Tage dieses Pattern in den letzten N Tagen?
            _pat_dates = _hit_dates.get(hit["pattern"], set())
            _lb_start = sig_date - pd.Timedelta(days=cfg.persistence_lookback)
            _persistence = sum(1 for d in _pat_dates if _lb_start <= d <= sig_date)

            signal = {
                "date": sig_date,
                "exit_date": exit_date,
                "ticker": ticker,
                "name": name,
                "direction": direction,
                "entry": entry,
                "target": round(target, 2),
                "stop_loss": sl,
                "risk_reward": rr,
                "sl_dist_pct": sl_dist_pct,
                "outcome": outcome["outcome"],
                "pnl_pct": outcome["pnl_pct"],
                "days_held": outcome["days_held"],
                "vetoed": False,
                "truncated": truncated,
                "pattern": hit["pattern"],
                "detail": hit["detail"],
                "index": get_index(ticker),
                "persistence": _persistence,
            }

            all_signals.append(signal)

            # Blocking: Ticker fuer Trade-Dauer sperren
            in_trade_until = idx_pos + outcome["days_held"]

    if verbose:
        print(f"\r  {len(all_signals)} Pattern-Signale aus {n_tickers} Tickern" + " " * 30)
        if target_rr is None and n_no_target > 0:
            print(f"  ({n_no_target} Signale ohne chartbasiertes Target uebersprungen)")

    signals_df = pd.DataFrame(all_signals)
    if not signals_df.empty:
        signals_df = signals_df.sort_values("date").reset_index(drop=True)
        signals_df.to_pickle(cache)
        if verbose:
            print(f"  -> Cache: {cache}")
            print(f"  Pattern-Verteilung:")
            print(signals_df["pattern"].value_counts().to_string(header=False))
            if target_rr is None:
                rr_desc = signals_df["risk_reward"].describe()
                print(f"  R/R Verteilung: Median={rr_desc['50%']:.1f}, "
                      f"Mean={rr_desc['mean']:.1f}, Min={rr_desc['min']:.1f}, Max={rr_desc['max']:.1f}")

    return signals_df
