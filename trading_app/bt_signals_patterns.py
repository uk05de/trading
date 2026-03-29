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
# Scale-In Auswertung: gestaffelter Einstieg in 2-3 Tranchen
# ---------------------------------------------------------------------------

def _evaluate_trade_scale_in(df: pd.DataFrame, signal_idx: int,
                              direction: str, entry: float, target: float,
                              stop_loss: float, step_pct: float = 0,
                              n_steps: int = 3,
                              use_risk_steps: bool = False) -> dict:
    """
    Trade-Auswertung mit gestaffeltem Einstieg.

    Zwei Modi:
      step_pct > 0:     Fixe Prozent-Stufen (z.B. 3% = Entry, Entry-3%, Entry-6%)
      use_risk_steps:   Stufen relativ zum Risk (Entry, Entry-0.33R, Entry-0.67R)

    Returns: wie _evaluate_trade, plus avg_entry und n_tranches.
    """
    future = df.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_DAYS]

    # Kauf-Levels berechnen
    risk = abs(entry - stop_loss)
    if use_risk_steps and risk > 0:
        # Gleichmäßig zwischen Entry und SL verteilen
        if direction == "LONG":
            buy_levels = [entry - i * risk / n_steps for i in range(n_steps)]
        else:
            buy_levels = [entry + i * risk / n_steps for i in range(n_steps)]
    elif step_pct > 0:
        if direction == "LONG":
            buy_levels = [entry - i * step_pct / 100 * entry for i in range(n_steps)]
        else:
            buy_levels = [entry + i * step_pct / 100 * entry for i in range(n_steps)]
    else:
        buy_levels = [entry]

    # Tranche 1 ist immer gekauft
    n_total = len(buy_levels)  # geplante Tranchen
    bought = [entry]
    pending_levels = buy_levels[1:]

    def _calc_pnl(exit_px, direction):
        """P/L auf Basis des GESAMTEN geplanten Investments (n_total Tranchen).
        Ungefuellte Tranchen = 0 P/L (Cash blieb uninvestiert)."""
        total_pnl = 0.0
        for bp in bought:
            if direction == "LONG":
                total_pnl += exit_px - bp
            else:
                total_pnl += bp - exit_px
        # Bezogen auf das volle Investment (n_total × entry)
        full_invest = n_total * entry
        return round(total_pnl / full_invest * 100, 2) if full_invest > 0 else 0.0

    for day_n, (date, row) in enumerate(future.iterrows(), 1):
        low = float(row["Low"])
        high = float(row["High"])

        if direction == "LONG":
            still_pending = []
            for level in pending_levels:
                if low <= level:
                    bought.append(level)
                else:
                    still_pending.append(level)
            pending_levels = still_pending

            if low <= stop_loss:
                return {"outcome": "STOP", "pnl_pct": _calc_pnl(stop_loss, direction),
                        "days_held": day_n, "exit_price": stop_loss,
                        "exit_date": date, "n_tranches": len(bought),
                        "avg_entry": round(sum(bought) / len(bought), 2)}

            if high >= target:
                return {"outcome": "TARGET", "pnl_pct": _calc_pnl(target, direction),
                        "days_held": day_n, "exit_price": target,
                        "exit_date": date, "n_tranches": len(bought),
                        "avg_entry": round(sum(bought) / len(bought), 2)}
        else:
            still_pending = []
            for level in pending_levels:
                if high >= level:
                    bought.append(level)
                else:
                    still_pending.append(level)
            pending_levels = still_pending

            if high >= stop_loss:
                return {"outcome": "STOP", "pnl_pct": _calc_pnl(stop_loss, direction),
                        "days_held": day_n, "exit_price": stop_loss,
                        "exit_date": date, "n_tranches": len(bought),
                        "avg_entry": round(sum(bought) / len(bought), 2)}

            if low <= target:
                return {"outcome": "TARGET", "pnl_pct": _calc_pnl(target, direction),
                        "days_held": day_n, "exit_price": target,
                        "exit_date": date, "n_tranches": len(bought),
                        "avg_entry": round(sum(bought) / len(bought), 2)}

    if len(future) > 0:
        exit_px = float(future.iloc[-1]["Close"])
        return {"outcome": "TIMEOUT", "pnl_pct": _calc_pnl(exit_px, direction),
                "days_held": len(future), "exit_price": exit_px,
                "exit_date": future.index[-1], "n_tranches": len(bought),
                "avg_entry": round(sum(bought) / len(bought), 2)}

    return {"outcome": "NO_DATA", "pnl_pct": 0.0, "days_held": 0,
            "exit_price": entry, "exit_date": None,
            "n_tranches": 1, "avg_entry": entry}


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


def _evaluate_trade_breakeven(df: pd.DataFrame, signal_idx: int,
                              direction: str, entry: float, target: float,
                              stop_loss: float, trigger_pct: float) -> dict:
    """
    Trade-Auswertung mit Breakeven-Stop nach Recovery.

    Logik (LONG):
      1. Kurs faellt unter Entry - trigger_pct% (Trade war im Minus)
      2. Kurs erholt sich zurueck ueber Entry
      3. Ab jetzt: SL = Entry (Breakeven)

    Der Trade muss erst Schwaeche zeigen und sich erholen,
    bevor der Breakeven-Stop aktiviert wird.
    """
    future = df.iloc[signal_idx + 1: signal_idx + 1 + MAX_HOLD_DAYS]
    was_negative = False      # War der Trade schon im Minus?
    breakeven_active = False  # Wurde Breakeven aktiviert?

    for day_n, (date, row) in enumerate(future.iterrows(), 1):
        close = float(row["Close"])
        low = float(row["Low"])
        high = float(row["High"])

        current_sl = entry if breakeven_active else stop_loss

        if direction == "LONG":
            # SL-Check
            if low <= current_sl:
                pnl = (current_sl - entry) / entry * 100
                return {"outcome": "BREAKEVEN" if breakeven_active else "STOP",
                        "pnl_pct": round(pnl, 2), "days_held": day_n,
                        "exit_price": current_sl, "exit_date": date}
            # Target-Check
            if high >= target:
                pnl = (target - entry) / entry * 100
                return {"outcome": "TARGET", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": target, "exit_date": date}
            # Phase 1: War der Kurs schon trigger_pct% unter Entry?
            if not was_negative and low <= entry * (1 - trigger_pct / 100):
                was_negative = True
            # Phase 2: Kurs zurueck ueber Entry → Breakeven aktivieren
            if was_negative and not breakeven_active and close >= entry:
                breakeven_active = True
        else:  # SHORT
            if high >= current_sl:
                pnl = (entry - current_sl) / entry * 100
                return {"outcome": "BREAKEVEN" if breakeven_active else "STOP",
                        "pnl_pct": round(pnl, 2), "days_held": day_n,
                        "exit_price": current_sl, "exit_date": date}
            if low <= target:
                pnl = (entry - target) / entry * 100
                return {"outcome": "TARGET", "pnl_pct": round(pnl, 2),
                        "days_held": day_n, "exit_price": target, "exit_date": date}
            if not was_negative and high >= entry * (1 + trigger_pct / 100):
                was_negative = True
            if was_negative and not breakeven_active and close <= entry:
                breakeven_active = True

    # Timeout
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


def collect_pattern_signals(cfg: BacktestConfig,
                            target_rr: float | None = None,
                            trailing: bool = False,
                            breakeven_pct: float = 0.0,
                            scale_in_pct: float = 0.0,
                            scale_in_steps: int = 3,
                            scale_in_risk: bool = False,
                            override_sl_pct: float = 0.0,
                            sl_shift_pct: float = 0.0,
                            target_shift_pct: float = 0.0,
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
    # Cache-Pfad: unterschiedlich je nach target_rr, trailing, breakeven, scale-in
    trail_suffix = "_trail" if trailing else ""
    be_suffix = f"_be{breakeven_pct:.0f}" if breakeven_pct > 0 else ""
    if scale_in_risk:
        si_suffix = f"_siR{scale_in_steps}"
    elif scale_in_pct > 0:
        si_suffix = f"_si{scale_in_pct:.0f}x{scale_in_steps}"
    else:
        si_suffix = ""
    sl_suffix = f"_sl{override_sl_pct:.0f}" if override_sl_pct > 0 else ""
    shift_suffix = ""
    if sl_shift_pct != 0 or target_shift_pct != 0:
        shift_suffix = f"_sh{sl_shift_pct:.0f}s{target_shift_pct:.0f}t"
    _extra = trail_suffix + be_suffix + si_suffix + sl_suffix + shift_suffix
    _extra = trail_suffix + be_suffix + si_suffix
    if target_rr is not None:
        cache = f"data/signals_patterns_rr{target_rr:.1f}{_extra}.pkl"
    else:
        cache = CACHE_PATH.replace(".pkl", f"{_extra}.pkl") if _extra else CACHE_PATH

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

            # Target bestimmen (immer auf Basis des ORIGINALEN SL/Risk)
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

            # SL-Override NACH Target-Berechnung (Target bleibt vom Original)
            if override_sl_pct > 0:
                if direction == "LONG":
                    sl = entry * (1 - override_sl_pct / 100)
                else:
                    sl = entry * (1 + override_sl_pct / 100)

            # SL/Target verschieben (SL weiter weg, Target weiter weg)
            if sl_shift_pct != 0:
                if direction == "LONG":
                    sl = sl * (1 - sl_shift_pct / 100)  # SL tiefer
                else:
                    sl = sl * (1 + sl_shift_pct / 100)  # SL hoeher (SHORT)
            if target_shift_pct != 0:
                if direction == "LONG":
                    target = target * (1 + target_shift_pct / 100)  # Target hoeher
                else:
                    target = target * (1 - target_shift_pct / 100)  # Target tiefer (SHORT)

            # Trade auswerten
            if scale_in_risk or scale_in_pct > 0:
                outcome = _evaluate_trade_scale_in(
                    df, idx_pos, direction, entry, target, sl,
                    step_pct=scale_in_pct, n_steps=scale_in_steps,
                    use_risk_steps=scale_in_risk)
            elif breakeven_pct > 0:
                outcome = _evaluate_trade_breakeven(
                    df, idx_pos, direction, entry, target, sl, breakeven_pct)
            elif trailing and direction == "LONG":
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
