"""
trade_analytics.py – Trade-Analyse fuer Live-Performance.

Ersetzt learner.py. Misst und analysiert abgeschlossene Trades
um das System zu verbessern.

Analysen:
  1. Post-Exit Tracking (Kurs nach Trade-Schliessung)
  2. SL-Validierung (war der SL zu eng?)
  3. Target-Optimierung (schliesse ich zu frueh?)
  4. Win/Loss Sequenzen + Erwartungswert
  5. Haltedauer-Analyse
  6. Verpasste Trades
  7. Cluster-Risiko
  8. Sektor/Pattern-Performance
"""

from __future__ import annotations

import datetime as dt
import logging
import numpy as np
import pandas as pd

from db import get_trades, update_trade, _connect
from markets import get_sector, get_index

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Post-Exit Tracking (laeuft im Scanner bei jedem Scan)
# ---------------------------------------------------------------------------

def track_post_exit(price_data: dict[str, pd.DataFrame]) -> int:
    """
    Fuer kuerzlich geschlossene Trades: Kurs 5/10/20 Tage nach Exit tracken.

    Args:
        price_data: Dict {ticker: DataFrame} mit OHLCV-Daten (aus Scanner Batch-Download)

    Returns: Anzahl aktualisierter Trades
    """
    closed = get_trades(status="CLOSED")
    if not closed:
        return 0

    updated = 0
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()

    for trade in closed:
        # Nur Trades der letzten 30 Tage die noch kein Post-Exit haben
        if not trade.get("exit_date") or trade["exit_date"] < cutoff:
            continue
        if trade.get("post_exit_20d_pct") is not None:
            continue

        ticker = trade["ticker"]
        df = price_data.get(ticker)
        if df is None or df.empty:
            continue

        exit_date = pd.Timestamp(trade["exit_date"])
        exit_price = trade.get("exit_price") or trade.get("current_price")
        if not exit_price or exit_price <= 0:
            continue

        # Kurstage nach Exit
        future = df[df.index > exit_date]
        if len(future) < 5:
            continue

        direction = trade["direction"]
        entry_price = trade["entry_price"]
        sl = trade.get("stop_loss") or 0
        risk = abs(entry_price - sl) if sl else 0

        updates = {}

        for n_days, col in [(5, "post_exit_5d_pct"), (10, "post_exit_10d_pct"),
                            (20, "post_exit_20d_pct")]:
            if len(future) >= n_days:
                price_at_n = float(future["Close"].iloc[n_days - 1])
                if direction == "LONG":
                    pct = (price_at_n - exit_price) / exit_price * 100
                else:
                    pct = (exit_price - price_at_n) / exit_price * 100
                updates[col] = round(pct, 2)

        # Max-Kurs in 20 Tagen nach Exit (verglichen mit Exit-Preis)
        window = future.iloc[:min(20, len(future))]
        if direction == "LONG":
            max_price = float(window["High"].max())
            updates["post_exit_max_pct"] = round((max_price - exit_price) / exit_price * 100, 2)
        else:
            min_price = float(window["Low"].min())
            updates["post_exit_max_pct"] = round((exit_price - min_price) / exit_price * 100, 2)

        # Max/Min R waehrend des Trades (aus Kursdaten waehrend Haltezeit)
        entry_date = pd.Timestamp(trade["entry_date"])
        during = df[(df.index >= entry_date) & (df.index <= exit_date)]
        if len(during) > 0 and risk > 0:
            if direction == "LONG":
                max_profit = float(during["High"].max()) - entry_price
                min_profit = float(during["Low"].min()) - entry_price
            else:
                max_profit = entry_price - float(during["Low"].min())
                min_profit = entry_price - float(during["High"].max())
            updates["max_r_during"] = round(max_profit / risk, 2)
            updates["min_r_during"] = round(min_profit / risk, 2)

        if updates:
            update_trade(trade["id"], updates)
            updated += 1

    return updated


# ---------------------------------------------------------------------------
# 2. Analyse-Funktionen (fuer Dashboard)
# ---------------------------------------------------------------------------

def get_trade_analytics() -> dict:
    """
    Berechne alle Analysen aus abgeschlossenen Trades.

    Returns dict mit allen Metriken fuer das Dashboard.
    """
    closed = get_trades(status="CLOSED")
    if not closed:
        return {"has_data": False, "n_trades": 0}

    # TODO: Spaeter wieder auf nicht-Test Trades einschraenken:
    # trades = [t for t in closed if not t.get("exclude_learning")]
    trades = list(closed)
    if not trades:
        return {"has_data": False, "n_trades": 0}

    n = len(trades)
    returns = [t.get("return_pct") or 0 for t in trades]
    winners = [t for t in trades if (t.get("return_pct") or 0) > 0]
    losers = [t for t in trades if (t.get("return_pct") or 0) <= 0]

    # --- Basis-Metriken ---
    wr = len(winners) / n * 100 if n > 0 else 0
    avg_win = np.mean([t["return_pct"] for t in winners]) if winners else 0
    avg_loss = np.mean([abs(t["return_pct"]) for t in losers]) if losers else 0
    expectancy = (wr / 100 * avg_win) - ((1 - wr / 100) * avg_loss)

    # --- SL-Disziplin (basierend auf Profit R) ---
    sl_breached = 0
    sl_held = 0
    from ko_calc import stock_to_product
    for t in trades:
        sl = t.get("stop_loss")
        exit_p = t.get("exit_price")
        entry = t.get("entry_price")
        if not sl or not exit_p or not entry:
            continue
        # Profit R bei Exit berechnen (auf Produkt-Ebene wenn KO)
        ko = t.get("ko_level")
        bv = t.get("bv") or 1.0
        d = t["direction"]
        if ko:
            ep = stock_to_product(entry, ko, d, bv)
            xp = stock_to_product(exit_p, ko, d, bv)
            sp = stock_to_product(sl, ko, d, bv)
            risk = abs(ep - sp)
            profit = xp - ep
        else:
            risk = abs(entry - sl)
            profit = (exit_p - entry) if d == "LONG" else (entry - exit_p)
        exit_r = profit / risk if risk > 0 else 0
        if exit_r <= -1.0:
            sl_breached += 1
        elif exit_r < 0:
            sl_held += 1  # Verlust aber SL nicht durchbrochen (manuell vorher raus)

    # --- Post-Exit Analyse ---
    closed_too_early = 0
    post_exit_gains = []
    for t in winners:
        pe = t.get("post_exit_10d_pct")
        if pe is not None:
            post_exit_gains.append(pe)
            if pe > 3:  # Kurs lief noch >3% weiter
                closed_too_early += 1

    # --- SL-Validierung (war SL zu eng?) ---
    sl_too_tight = 0
    for t in losers:
        pe = t.get("post_exit_10d_pct")
        if pe is not None and pe > 5:  # Nach SL noch >5% gestiegen
            sl_too_tight += 1

    # --- Max R waehrend Trade ---
    max_r_values = [t["max_r_during"] for t in trades if t.get("max_r_during") is not None]
    min_r_values = [t["min_r_during"] for t in trades if t.get("min_r_during") is not None]

    # --- Haltedauer ---
    durations_win = []
    durations_loss = []
    for t in trades:
        if t.get("entry_date") and t.get("exit_date"):
            try:
                d = (dt.date.fromisoformat(t["exit_date"]) - dt.date.fromisoformat(t["entry_date"])).days
                if (t.get("return_pct") or 0) > 0:
                    durations_win.append(d)
                else:
                    durations_loss.append(d)
            except (ValueError, TypeError):
                pass

    # --- Win/Loss Sequenzen ---
    max_consecutive_wins = 0
    max_consecutive_losses = 0
    current_wins = 0
    current_losses = 0
    for t in trades:
        if (t.get("return_pct") or 0) > 0:
            current_wins += 1
            current_losses = 0
        else:
            current_losses += 1
            current_wins = 0
        max_consecutive_wins = max(max_consecutive_wins, current_wins)
        max_consecutive_losses = max(max_consecutive_losses, current_losses)

    # --- Pattern-Performance ---
    pattern_stats = {}
    conn = _connect()
    for t in trades:
        sig_id = t.get("signal_id")
        if sig_id:
            row = conn.execute("SELECT votes_detail FROM signals WHERE id = ?", (sig_id,)).fetchone()
            if row:
                vd = row["votes_detail"] or ""
                if vd.startswith("Pattern:"):
                    pat = vd.split("|")[0].replace("Pattern:", "").strip()
                    if pat not in pattern_stats:
                        pattern_stats[pat] = {"n": 0, "wins": 0, "returns": []}
                    pattern_stats[pat]["n"] += 1
                    pattern_stats[pat]["returns"].append(t.get("return_pct") or 0)
                    if (t.get("return_pct") or 0) > 0:
                        pattern_stats[pat]["wins"] += 1
    conn.close()

    for pat in pattern_stats:
        s = pattern_stats[pat]
        s["wr"] = round(s["wins"] / s["n"] * 100, 1) if s["n"] > 0 else 0
        s["avg_return"] = round(np.mean(s["returns"]), 2) if s["returns"] else 0

    # --- Sektor-Performance ---
    sector_stats = {}
    for t in trades:
        sector = get_sector(t["ticker"])
        if sector not in sector_stats:
            sector_stats[sector] = {"n": 0, "wins": 0, "total_return": 0}
        sector_stats[sector]["n"] += 1
        sector_stats[sector]["total_return"] += t.get("return_pct") or 0
        if (t.get("return_pct") or 0) > 0:
            sector_stats[sector]["wins"] += 1

    for sec in sector_stats:
        s = sector_stats[sec]
        s["wr"] = round(s["wins"] / s["n"] * 100, 1) if s["n"] > 0 else 0
        s["avg_return"] = round(s["total_return"] / s["n"], 2) if s["n"] > 0 else 0

    return {
        "has_data": True,
        "n_trades": n,
        "n_winners": len(winners),
        "n_losers": len(losers),
        "win_rate": round(wr, 1),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),

        # SL-Disziplin
        "sl_held": sl_held,
        "sl_breached": sl_breached,

        # Post-Exit
        "closed_too_early": closed_too_early,
        "avg_post_exit_gain": round(np.mean(post_exit_gains), 2) if post_exit_gains else None,

        # SL-Validierung
        "sl_too_tight": sl_too_tight,

        # Max R
        "avg_max_r": round(np.mean(max_r_values), 2) if max_r_values else None,
        "avg_min_r": round(np.mean(min_r_values), 2) if min_r_values else None,

        # Haltedauer
        "avg_days_win": round(np.mean(durations_win), 1) if durations_win else None,
        "avg_days_loss": round(np.mean(durations_loss), 1) if durations_loss else None,

        # Sequenzen
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,

        # Pattern
        "pattern_stats": pattern_stats,
        "sector_stats": sector_stats,
    }
