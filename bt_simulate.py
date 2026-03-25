"""
Backtest-Framework: Portfolio-Simulation.

Einziger Code-Pfad für Portfolio-Simulation mit allen Bug-Fixes.
Wird von bt_run.py aufgerufen.

Fixes:
  1. Cash-Tracking: Position-Sizing basiert auf FREIEM Cash
  2. Drawdown bei jeder Portfolio-Änderung (Eröffnung + Schließung)
  3. Konsistente Equity-Methode mit Leverage + Gebühren
  4. KO-Totalverlust: returned = max(0, invested + pnl)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd

from bt_config import BacktestConfig


@dataclass
class BacktestResult:
    """Ergebnis eines Backtest-Laufs."""
    config: BacktestConfig
    n_signals: int = 0         # Handelbare Signale (nach Filter)
    n_trades: int = 0          # Tatsächlich eingegangene Trades
    n_wins: int = 0
    win_rate: float = 0.0
    total_return: float = 0.0  # Prozent
    max_drawdown: float = 0.0  # Prozent
    efficiency: float = 0.0    # total_return / max_drawdown
    end_capital: float = 0.0
    total_deposited: float = 0.0  # Gesamte Einzahlungen (Start + monatlich)
    skipped_cash: int = 0      # Übersprungen wegen Cash-Mangel
    skipped_pos: int = 0       # Übersprungen wegen Positionslimit
    skipped_ticker: int = 0    # Übersprungen weil Ticker schon offen
    skipped_pause: int = 0     # Übersprungen wegen Pause-Regel
    equity: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)

    def summary_line(self) -> str:
        """Einzeilige Zusammenfassung für Tabellen."""
        return (f"{self.config.label():>35s} | "
                f"{self.n_signals:>4d} Sig {self.n_trades:>4d} Tr {self.win_rate:>5.1f}% WR | "
                f"{self.total_return:>+7.1f}% Ret {self.max_drawdown:>5.1f}% DD "
                f"{self.efficiency:>5.1f} Eff | "
                f"€{self.end_capital:>9,.2f}")


def _apply_signal_filters(signals: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Config-spezifische Filter auf Signale anwenden (Vetos, SL-Band, R/R, Richtung)."""
    if len(signals) == 0:
        return signals
    mask = pd.Series(True, index=signals.index)
    if not cfg.ignore_vetos and "vetoed" in signals.columns:
        mask = mask & (~signals["vetoed"])
    if cfg.min_sl_dist > 0:
        mask = mask & (signals["sl_dist_pct"] >= cfg.min_sl_dist)
    if cfg.max_sl_dist < 1.0:
        mask = mask & (signals["sl_dist_pct"] <= cfg.max_sl_dist)
    if cfg.min_rr > 0:
        mask = mask & (signals["risk_reward"] >= cfg.min_rr)
    if cfg.only_long:
        mask = mask & (signals["direction"] == "LONG")
    if cfg.exclude_indices and "index" in signals.columns:
        mask = mask & (~signals["index"].isin(cfg.exclude_indices))
    if cfg.pattern_filter and "pattern" in signals.columns:
        mask = mask & (signals["pattern"].isin(cfg.pattern_filter))
    if cfg.custom_veto is not None:
        mask = mask & (~signals.apply(cfg.custom_veto, axis=1))
    return signals[mask].copy().reset_index(drop=True)


def simulate(signals: pd.DataFrame, cfg: BacktestConfig) -> BacktestResult:
    """
    Portfolio-Simulation mit allen Fixes.

    Wendet Config-spezifische Filter an (SL-Band, R/R),
    dann simuliert die Kapitalentwicklung.
    """
    signals = _apply_signal_filters(signals, cfg)

    # Signal-Ranking: bei gleichen Tagen die besten zuerst
    if cfg.signal_ranking != "none" and len(signals) > 0:
        import re

        if cfg.signal_ranking == "sl_dist_asc":
            # Engster SL zuerst (praezisestes Setup)
            signals = signals.sort_values(["date", "sl_dist_pct"],
                                          ascending=[True, True]).reset_index(drop=True)

        elif cfg.signal_ranking == "sl_dist_desc":
            # Weitester SL zuerst (mehr Luft)
            signals = signals.sort_values(["date", "sl_dist_pct"],
                                          ascending=[True, False]).reset_index(drop=True)

        elif cfg.signal_ranking == "pattern_prio":
            # ema50_bounce vor gap_up (historisch bessere WR)
            prio = {"ema50_bounce": 0, "gap_up_continuation": 1}
            if "pattern" in signals.columns:
                signals["_prio"] = signals["pattern"].map(prio).fillna(9)
                signals = signals.sort_values(["date", "_prio"]).drop(columns="_prio").reset_index(drop=True)

        elif cfg.signal_ranking == "adx":
            # Hoechster ADX zuerst (staerkster Trend)
            if "detail" in signals.columns:
                def _parse_adx(detail):
                    m = re.search(r'ADX=(\d+)', str(detail))
                    return int(m.group(1)) if m else 0
                signals["_adx"] = signals["detail"].apply(_parse_adx)
                signals = signals.sort_values(["date", "_adx"],
                                              ascending=[True, False]).drop(columns="_adx").reset_index(drop=True)

        elif cfg.signal_ranking == "slope":
            # Hoechster EMA50-Slope zuerst (staerkster Aufwaertstrend)
            if "detail" in signals.columns:
                def _parse_slope(detail):
                    m = re.search(r'Slope=([\d.]+)', str(detail))
                    return float(m.group(1)) if m else 0
                signals["_slope"] = signals["detail"].apply(_parse_slope)
                signals = signals.sort_values(["date", "_slope"],
                                              ascending=[True, False]).drop(columns="_slope").reset_index(drop=True)

        elif cfg.signal_ranking == "combo_score":
            # Kombination: hoher ADX + enger SL = bestes Setup
            if "detail" in signals.columns:
                def _parse_adx2(detail):
                    m = re.search(r'ADX=(\d+)', str(detail))
                    return int(m.group(1)) if m else 25
                signals["_adx"] = signals["detail"].apply(_parse_adx2)
                # Score: ADX normiert (0-1) + (1/SL-Dist normiert)
                adx_max = signals["_adx"].max() or 1
                sl_max = signals["sl_dist_pct"].max() or 1
                signals["_score"] = (signals["_adx"] / adx_max * 0.5 +
                                     (1 - signals["sl_dist_pct"] / sl_max) * 0.5)
                signals = signals.sort_values(["date", "_score"],
                                              ascending=[True, False]).drop(
                    columns=["_adx", "_score"]).reset_index(drop=True)

        elif cfg.signal_ranking == "persistence_score":
            # combo_score + Persistenz-Gewichtung
            if "detail" in signals.columns and "persistence" in signals.columns:
                def _parse_adx3(detail):
                    m = re.search(r'ADX=(\d+)', str(detail))
                    return int(m.group(1)) if m else 25
                signals["_adx"] = signals["detail"].apply(_parse_adx3)
                adx_max = signals["_adx"].max() or 1
                sl_max = signals["sl_dist_pct"].max() or 1
                base = (signals["_adx"] / adx_max * 0.5 +
                        (1 - signals["sl_dist_pct"] / sl_max) * 0.5)
                signals["_score"] = base + signals["persistence"] * cfg.persistence_weight
                signals = signals.sort_values(["date", "_score"],
                                              ascending=[True, False]).drop(
                    columns=["_adx", "_score"]).reset_index(drop=True)

        elif cfg.signal_ranking == "random":
            signals = signals.sample(frac=1, random_state=42).sort_values("date").reset_index(drop=True)
    free_cash = cfg.start_capital
    open_positions: list[dict] = []
    peak_portfolio = cfg.start_capital
    max_dd = 0.0
    equity_rows: list[dict] = []
    taken_trades: list[dict] = []
    n_skipped_cash = 0
    n_skipped_pos = 0
    n_skipped_ticker = 0
    n_paused = 0
    total_deposited = cfg.start_capital
    last_deposit_month = None

    # ── Pause-Tracking ──
    consecutive_losses = 0
    recent_outcomes: list[int] = []   # 1=Win, 0=Loss für Rolling WR
    pause_remaining = 0               # Verbleibende Signale im Pause-Modus

    def _apply_monthly_deposit(date) -> None:
        nonlocal free_cash, total_deposited, last_deposit_month
        if cfg.monthly_deposit <= 0:
            return
        month_key = (date.year, date.month)
        if last_deposit_month is None:
            last_deposit_month = month_key
            return
        if month_key != last_deposit_month:
            # Einzahlung fuer jeden fehlenden Monat
            y0, m0 = last_deposit_month
            y1, m1 = month_key
            months_diff = (y1 - y0) * 12 + (m1 - m0)
            deposit = cfg.monthly_deposit * months_diff
            free_cash += deposit
            total_deposited += deposit
            last_deposit_month = month_key

    def _update_drawdown() -> tuple[float, float]:
        nonlocal peak_portfolio, max_dd
        locked = sum(p["invested"] for p in open_positions)
        portfolio = free_cash + locked
        if portfolio > peak_portfolio:
            peak_portfolio = portfolio
        dd = (peak_portfolio - portfolio) / peak_portfolio * 100 if peak_portfolio > 0 else 0
        if dd > max_dd:
            max_dd = dd
        return portfolio, locked

    def _record_equity(date) -> None:
        portfolio, locked = _update_drawdown()
        equity_rows.append({
            "date": date,
            "free_cash": round(free_cash, 2),
            "locked": round(locked, 2),
            "portfolio": round(portfolio, 2),
        })

    if len(signals) > 0:
        _record_equity(signals["date"].iloc[0])

    for _, sig in signals.iterrows():
        # ── Monatliche Einzahlung ──
        _apply_monthly_deposit(sig["date"])

        # ── Positionen schließen die fällig sind ──
        closed = [p for p in open_positions if p["exit_date"] <= sig["date"]]
        for p in closed:
            returned = p["invested"] + p["pnl_euro"]
            if returned < 0:
                returned = 0  # KO-Totalverlust
            free_cash += returned
            open_positions.remove(p)
            _record_equity(p["exit_date"])

            # ── Pause-Tracking: Win/Loss registrieren ──
            is_win = p["pnl_euro"] > 0
            if is_win:
                consecutive_losses = 0
            else:
                consecutive_losses += 1
            recent_outcomes.append(1 if is_win else 0)
            if len(recent_outcomes) > cfg.pause_rolling_window:
                recent_outcomes[:] = recent_outcomes[-cfg.pause_rolling_window:]

            # Pause-Trigger prüfen
            if cfg.pause_after_losses > 0 and consecutive_losses >= cfg.pause_after_losses:
                pause_remaining = max(pause_remaining, cfg.pause_signals)
                consecutive_losses = 0  # Reset nach Trigger
            if (cfg.pause_rolling_wr > 0
                    and len(recent_outcomes) >= cfg.pause_rolling_window):
                rolling_wr = sum(recent_outcomes) / len(recent_outcomes)
                if rolling_wr < cfg.pause_rolling_wr:
                    pause_remaining = max(pause_remaining, cfg.pause_signals)

        # ── Pause-Regel ──
        if pause_remaining > 0:
            sig_idx = sig.get("index", "")
            if not cfg.pause_indices or sig_idx in cfg.pause_indices:
                pause_remaining -= 1
                n_paused += 1
                continue

        # ── Prüfungen ──
        open_tickers = {p["ticker"] for p in open_positions}
        if sig["ticker"] in open_tickers:
            n_skipped_ticker += 1
            continue

        if cfg.max_positions > 0 and len(open_positions) >= cfg.max_positions:
            n_skipped_pos += 1
            continue

        sl_dist = sig["sl_dist_pct"]
        if sl_dist <= 0:
            continue

        # ── Position-Sizing ──
        locked = sum(p["invested"] for p in open_positions)
        portfolio = free_cash + locked

        if cfg.sizing_method == "fixed_free":
            invested = free_cash * cfg.sizing_pct
            notional = invested * cfg.leverage

        elif cfg.sizing_method == "risk_free":
            risk_amount = free_cash * cfg.sizing_pct
            notional = risk_amount / sl_dist
            invested = notional / cfg.leverage
            if invested > free_cash * cfg.risk_free_cap:
                invested = free_cash * cfg.risk_free_cap
                notional = invested * cfg.leverage

        elif cfg.sizing_method == "risk_portfolio":
            risk_amount = portfolio * cfg.sizing_pct
            notional = risk_amount / sl_dist
            invested = notional / cfg.leverage
            if invested > free_cash * cfg.risk_portfolio_cap:
                invested = free_cash * cfg.risk_portfolio_cap
                notional = invested * cfg.leverage

        elif cfg.sizing_method == "risk_tiered":
            # Gestaffeltes Risiko: Prozent haengt von Portfolio-Groesse ab
            risk_pct = cfg.sizing_pct  # Fallback
            for threshold, tier_pct in cfg.sizing_tiers:
                if portfolio < threshold:
                    risk_pct = tier_pct
                    break
            else:
                # Portfolio groesser als alle Schwellenwerte → letzten Tier nehmen
                if cfg.sizing_tiers:
                    risk_pct = cfg.sizing_tiers[-1][1]
            risk_amount = portfolio * risk_pct
            notional = risk_amount / sl_dist
            invested = notional / cfg.leverage
            if invested > free_cash * cfg.risk_portfolio_cap:
                invested = free_cash * cfg.risk_portfolio_cap
                notional = invested * cfg.leverage

        else:
            raise ValueError(f"Unbekannte sizing_method: {cfg.sizing_method}")

        # Max-Invest Cap (feste Obergrenze in Euro)
        if cfg.max_invest > 0 and invested > cfg.max_invest:
            invested = cfg.max_invest
            notional = invested * cfg.leverage

        # Cash-Check
        if invested < cfg.min_invest:
            continue
        if invested > free_cash - cfg.min_cash_reserve:
            n_skipped_cash += 1
            continue

        pnl_euro = notional * sig["pnl_pct"] / 100 - cfg.fees

        # Cash beim Kauf reduzieren
        free_cash -= invested
        _record_equity(sig["date"])

        open_positions.append({
            "exit_date": sig["exit_date"],
            "invested": invested,
            "pnl_euro": pnl_euro,
            "ticker": sig["ticker"],
        })

        taken_trades.append({
            "date": sig["date"],
            "exit_date": sig["exit_date"],
            "ticker": sig["ticker"],
            "name": sig.get("name", ""),
            "direction": sig.get("direction", ""),
            "entry": sig.get("entry", 0),
            "target": sig.get("target", 0),
            "stop_loss": sig.get("stop_loss", 0),
            "outcome": sig["outcome"],
            "pnl_pct": sig["pnl_pct"],
            "invested": round(invested, 2),
            "notional": round(notional, 2),
            "pnl_euro": round(pnl_euro, 2),
            "days_held": sig["days_held"],
            "risk_reward": sig.get("risk_reward", 0),
            "sl_dist_pct": round(sl_dist * 100, 2),
            "index": sig.get("index", ""),
        })

    # Offene Positionen am Ende schließen
    for p in sorted(open_positions, key=lambda x: x["exit_date"]):
        returned = p["invested"] + p["pnl_euro"]
        if returned < 0:
            returned = 0
        free_cash += returned
        open_positions.remove(p)
        _record_equity(p["exit_date"])

    # Ergebnis zusammenstellen
    n_trades = len(taken_trades)
    n_wins = sum(1 for t in taken_trades if t["outcome"] == "TARGET")
    wr = n_wins / n_trades * 100 if n_trades > 0 else 0
    # Rendite bezogen auf total eingezahltes Kapital
    total_ret = (free_cash - total_deposited) / total_deposited * 100

    equity_df = pd.DataFrame(equity_rows)
    if len(equity_df) > 0:
        equity_df = equity_df.sort_values("date")
    trades_df = pd.DataFrame(taken_trades)

    return BacktestResult(
        config=cfg,
        n_signals=len(signals),
        n_trades=n_trades,
        n_wins=n_wins,
        win_rate=round(wr, 1),
        total_return=round(total_ret, 1),
        max_drawdown=round(max_dd, 1),
        efficiency=round(total_ret / max_dd, 1) if max_dd > 0 else 0,
        end_capital=round(free_cash, 2),
        total_deposited=round(total_deposited, 2),
        skipped_cash=n_skipped_cash,
        skipped_pos=n_skipped_pos,
        skipped_ticker=n_skipped_ticker,
        skipped_pause=n_paused,
        equity=equity_df,
        trades=trades_df,
    )
