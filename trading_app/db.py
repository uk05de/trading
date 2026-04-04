"""
db.py – SQLite persistence layer.

Tables (Schema wird extern verwaltet, nicht hier erstellt):
  signals      – Technische Signale (entry, target, stop_loss, pattern, ...)
  trades       – Offene und geschlossene Trades (KO-Zertifikate)
  settings     – Key-Value-Einstellungen
  cash_ledger  – Buchungen (Ein-/Auszahlungen, Kaeufe, Verkaeufe)
  prices       – OHLCV-Kursdaten
  ai_assessments – KI-Bewertungen
"""

from __future__ import annotations

import json
import sqlite3
import datetime as dt
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("TRADING_DB_PATH",
               str(Path(__file__).parent / "data" / "trading.db")))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Verbindung zur DB testen. Schema wird extern verwaltet."""
    conn = _connect()
    conn.execute("SELECT 1")
    # Phase-2 Spalten (Trend-Following nach Target)
    for col, typ, default in [("trail_sl", "REAL", "NULL"), ("phase", "INTEGER", "1")]:
        try:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ} DEFAULT {default}")
            conn.commit()
        except Exception:
            pass  # Spalte existiert bereits
    conn.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_setting(key: str, default=None):
    """Get a setting value by key."""
    conn = _connect()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row:
        return row["value"]
    return default


def set_setting(key: str, value):
    """Set a setting value (upsert)."""
    conn = _connect()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Cash Ledger (Buchungen)
# ---------------------------------------------------------------------------

def add_ledger_entry(date: str, entry_type: str, amount: float,
                     description: str = None, trade_id: int = None) -> int:
    """Add a cash ledger entry. Returns the entry ID.

    Types:
        deposit     → Einzahlung (positive)
        withdrawal  → Auszahlung (negative)
        trade_buy   → Kauf von Zertifikaten (negative)
        trade_sell  → Verkauf von Zertifikaten (positive)
        correction  → Manuelle Korrektur (positive or negative)
    """
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO cash_ledger (date, type, amount, description, trade_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (date, entry_type, round(amount, 2), description, trade_id),
    )
    entry_id = cur.lastrowid
    conn.commit()
    conn.close()
    return entry_id


def get_ledger_entries(limit: int = 200) -> list[dict]:
    """Get all ledger entries, newest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM cash_ledger ORDER BY date DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_ledger_entry(entry_id: int):
    """Delete a ledger entry (only manual ones: deposit, withdrawal, correction)."""
    conn = _connect()
    row = conn.execute("SELECT type FROM cash_ledger WHERE id = ?", (entry_id,)).fetchone()
    if row and row["type"] in ("deposit", "withdrawal", "correction"):
        conn.execute("DELETE FROM cash_ledger WHERE id = ?", (entry_id,))
        conn.commit()
    conn.close()


def get_cash_balance() -> float:
    """Calculate current cash balance from all ledger entries."""
    conn = _connect()
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) as total FROM cash_ledger").fetchone()
    conn.close()
    return round(row["total"], 2)


def get_free_cash() -> dict:
    """
    Calculate free cash from ledger.

    The ledger tracks everything:
    - Deposits add cash
    - Withdrawals subtract cash
    - Trade buys subtract cash
    - Trade sells add cash
    - Corrections adjust cash

    The balance IS the free cash (money not locked in positions).

    Returns dict with:
        balance: Current cash balance from ledger
        locked_cash: Sum of invested amounts in open trades (informational)
        portfolio_value: balance + locked_cash
        open_count: Number of open positions
        positions: List of open positions with details
    """
    balance = get_cash_balance()
    open_trades = get_trades(status="OPEN")

    locked = 0.0
    positions = []
    for t in open_trades:
        # Test-Trades ignorieren
        if t.get("is_test", 0) == 1:
            continue
        product_bid = t.get("product_bid") or 0
        entry_price = t.get("entry_price") or 0
        size = t.get("size") or 0
        if product_bid > 0:
            invested = product_bid * size
        else:
            invested = entry_price * size
        locked += invested
        positions.append({
            "ticker": t["ticker"],
            "name": t.get("name", t["ticker"]),
            "invested": round(invested, 2),
            "size": size,
            "direction": t["direction"],
            "trade_id": t["id"],
        })

    return {
        "balance": balance,
        "locked_cash": round(locked, 2),
        "portfolio_value": round(balance + locked, 2),
        "open_count": len(open_trades),
        "positions": positions,
    }


def calc_position_size(free_cash: float, product_price: float,
                       pct: float = 0.20) -> dict:
    """
    Calculate recommended position size (20% of free cash).

    Returns dict with:
        invest_amount: Recommended € amount
        size: Recommended number of certificates (rounded down)
        invest_actual: size × product_price (actual investment)
        pct_used: Percentage of free cash used
    """
    if product_price <= 0 or free_cash <= 0:
        return {"invest_amount": 0, "size": 0, "invest_actual": 0, "pct_used": 0}

    invest_amount = free_cash * pct
    size = int(invest_amount / product_price)
    if size < 1:
        size = 0
    invest_actual = size * product_price

    return {
        "invest_amount": round(invest_amount, 2),
        "size": size,
        "invest_actual": round(invest_actual, 2),
        "pct_used": round(invest_actual / free_cash * 100, 1) if free_cash > 0 else 0,
    }


def calc_position_size_risk(free_cash: float, product_price: float,
                            entry: float, stop_loss: float,
                            ko_level: float, direction: str = "LONG",
                            bv: float = 1.0,
                            risk_pct: float = 0.02,
                            max_invest: float = 2500.0) -> dict:
    """
    Position-Sizing nach Risk-2%-Methode.

    Berechnet Stueckzahl so dass bei SL-Hit max risk_pct vom Cash verloren geht.

    Args:
        free_cash: Freies Cash
        product_price: Aktueller Zertifikatspreis (Bid)
        entry: Einstiegskurs Basiswert
        stop_loss: Stop-Loss Basiswert
        ko_level: Knock-Out-Schwelle
        direction: LONG/SHORT
        bv: Bezugsverhaeltnis
        risk_pct: Max Risiko pro Trade (0.02 = 2%)
        max_invest: Max Eigenkapital pro Position in EUR

    Returns dict with:
        risk_amount: Max Verlust in EUR
        size: Empfohlene Stueckzahl
        invest_actual: size × product_price
        pct_used: % vom Cash
        loss_at_sl: Tatsaechlicher Verlust bei SL in EUR
        method: "risk_2pct"
    """
    if product_price <= 0 or free_cash <= 0 or entry <= 0:
        return {"risk_amount": 0, "size": 0, "invest_actual": 0,
                "pct_used": 0, "loss_at_sl": 0, "method": "risk_2pct"}

    # Risikobetrag: max risk_pct vom freien Cash
    risk_amount = free_cash * risk_pct

    # Verlust pro Zertifikat bei SL
    from ko_calc import stock_to_product
    product_at_sl = stock_to_product(stop_loss, ko_level, direction, bv)
    loss_per_cert = product_price - product_at_sl
    if loss_per_cert <= 0:
        # SL liegt unter KO → Totalverlust
        loss_per_cert = product_price

    # Stueckzahl berechnen
    size = int(risk_amount / loss_per_cert) if loss_per_cert > 0 else 0

    # Max-Invest Cap
    invest_actual = size * product_price
    if max_invest > 0 and invest_actual > max_invest:
        size = int(max_invest / product_price)
        invest_actual = size * product_price

    if size < 1:
        size = 0
        invest_actual = 0

    loss_at_sl = size * loss_per_cert

    return {
        "risk_amount": round(risk_amount, 2),
        "size": size,
        "invest_actual": round(invest_actual, 2),
        "pct_used": round(invest_actual / free_cash * 100, 1) if free_cash > 0 else 0,
        "loss_at_sl": round(loss_at_sl, 2),
        "method": "risk_2pct",
    }


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def save_signal(signal: dict):
    """Insert or update a daily signal."""
    # Defaults fuer optionale Felder
    signal.setdefault("pattern", None)
    signal.setdefault("sl_dist_pct", None)
    signal.setdefault("detail", None)
    conn = _connect()
    conn.execute("""
        INSERT INTO signals (date, ticker, name, direction, pattern,
                             entry, target, stop_loss, risk_reward,
                             sl_dist_pct, score, adx, rsi, atr_pct,
                             detail)
        VALUES (:date, :ticker, :name, :direction, :pattern,
                :entry, :target, :stop_loss, :risk_reward,
                :sl_dist_pct, :score, :adx, :rsi, :atr_pct,
                :detail)
        ON CONFLICT(date, ticker, pattern) DO UPDATE SET
            direction=excluded.direction,
            entry=excluded.entry,
            target=excluded.target, stop_loss=excluded.stop_loss,
            risk_reward=excluded.risk_reward,
            sl_dist_pct=excluded.sl_dist_pct, score=excluded.score,
            adx=excluded.adx, rsi=excluded.rsi, atr_pct=excluded.atr_pct,
            detail=excluded.detail,
            created_at=datetime('now')
    """, signal)
    conn.commit()
    conn.close()


def get_latest_signal_date() -> str | None:
    """Return the most recent date that has signals."""
    conn = _connect()
    row = conn.execute("SELECT date FROM signals ORDER BY date DESC LIMIT 1").fetchone()
    conn.close()
    return row["date"] if row else None


def get_signals(date: str = None, direction: str = None,
                limit: int = 300) -> list[dict]:
    """Retrieve signals, optionally filtered."""
    conn = _connect()
    query = "SELECT * FROM signals WHERE 1=1"
    params: list = []
    if date:
        query += " AND date = ?"
        params.append(date)
    if direction:
        query += " AND direction = ?"
        params.append(direction)
    query += " ORDER BY ABS(score) DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signal_history(ticker: str, limit: int = 60) -> list[dict]:
    """Get historical signals for a specific ticker."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM signals WHERE ticker = ? ORDER BY date DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# AI Assessments
# ---------------------------------------------------------------------------

def save_ai_assessment(data: dict):
    """Speichere eine KI-Bewertung. Keine Deduplizierung – jeder Aufruf wird gespeichert."""
    conn = _connect()
    conn.execute("""
        INSERT INTO ai_assessments (date, ticker, direction, score, entry,
                                     target, stop_loss, risk_reward,
                                     reasoning, prompt, model)
        VALUES (:date, :ticker, :direction, :score, :entry,
                :target, :stop_loss, :risk_reward,
                :reasoning, :prompt, :model)
    """, data)
    conn.commit()
    conn.close()


def get_ai_assessments(ticker: str, limit: int = 2) -> list:
    """Letzte N KI-Bewertungen für einen Ticker (neueste zuerst)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM ai_assessments WHERE ticker = ? ORDER BY id DESC LIMIT ?",
        (ticker, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def save_prices(ticker: str, df):
    """Store OHLCV DataFrame in the prices table."""
    conn = _connect()
    rows = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        rows.append((
            ticker, date_str,
            float(row.get("Open", 0)),
            float(row.get("High", 0)),
            float(row.get("Low", 0)),
            float(row.get("Close", 0)),
            float(row.get("Volume", 0)),
        ))
    conn.executemany("""
        INSERT INTO prices (ticker, date, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, date) DO UPDATE SET
            open=excluded.open, high=excluded.high,
            low=excluded.low, close=excluded.close,
            volume=excluded.volume
    """, rows)
    conn.commit()
    conn.close()


def get_prices(ticker: str, start: str = None, end: str = None):
    """Load OHLCV data from DB. Returns list of dicts."""
    conn = _connect()
    query = "SELECT * FROM prices WHERE ticker = ?"
    params: list = [ticker]
    if start:
        query += " AND date >= ?"
        params.append(start)
    if end:
        query += " AND date <= ?"
        params.append(end)
    query += " ORDER BY date"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_prices_with_backfill(ticker: str, start: str = None, end: str = None) -> list[dict]:
    """
    Load prices from DB. If data is missing or has gaps, backfill
    from yfinance and store the result for future use.
    """
    import yfinance as yf

    rows = get_prices(ticker, start=start)
    today = dt.date.today().isoformat()

    need_fetch = False
    fetch_start = start or "2024-01-01"

    if not rows:
        # No data at all – fetch everything
        need_fetch = True
    else:
        first_date = rows[0]["date"]
        last_date = rows[-1]["date"]

        # Check if we need older data (signal date before our earliest price)
        if start and start < first_date:
            need_fetch = True
            fetch_start = start

        # Check if we need newer data (last price is stale)
        if last_date < today:
            need_fetch = True
            if not start or start >= first_date:
                # Only fetch the missing tail
                fetch_start = last_date

    if need_fetch:
        try:
            import pandas as pd
            df = yf.download(
                ticker,
                start=fetch_start,
                end=(dt.date.today() + dt.timedelta(days=1)).isoformat(),
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                save_prices(ticker, df)
        except Exception:
            pass
        # Re-read from DB
        rows = get_prices(ticker, start=start)

    if end and rows:
        rows = [r for r in rows if r["date"] <= end]

    return rows


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def open_trade(trade: dict) -> int:
    """Open a new trade. Returns the trade ID."""
    conn = _connect()
    trade.setdefault("is_test", 0)
    trade.setdefault("wkn", None)
    trade.setdefault("ko_level", None)
    trade.setdefault("bv", 1.0)
    trade.setdefault("isin", None)
    trade.setdefault("emittent", None)
    trade.setdefault("product_bid", None)
    trade.setdefault("entry_fees", 1.0)
    trade.setdefault("notes", None)
    trade.setdefault("current_price", trade.get("entry_price"))

    cur = conn.execute("""
        INSERT INTO trades (signal_id, ticker, name, direction,
                            entry_date, entry_price, size,
                            target, stop_loss, notes, is_test,
                            wkn, ko_level, bv, isin, emittent, product_bid,
                            entry_fees, current_price)
        VALUES (:signal_id, :ticker, :name, :direction,
                :entry_date, :entry_price, :size,
                :target, :stop_loss, :notes, :is_test,
                :wkn, :ko_level, :bv, :isin, :emittent, :product_bid,
                :entry_fees, :current_price)
    """, trade)
    trade_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Automatische Buchung: Kauf = Abgang (nicht bei Test-Trades)
    _is_test = trade.get("is_test", 0) == 1
    _pb = trade.get("product_bid") or 0
    _sz = trade.get("size") or 0
    _fees = trade.get("entry_fees") or 0
    if _pb > 0 and _sz > 0 and not _is_test:
        _buy_amount = _pb * _sz + _fees
        add_ledger_entry(
            date=trade["entry_date"],
            entry_type="trade_buy",
            amount=-round(_buy_amount, 2),
            description=f"Kauf {trade['direction']} {trade.get('name', trade['ticker'])} "
                        f"({_sz:.0f} Stk. × €{_pb:.2f} + €{_fees:.2f} Gebühren)",
            trade_id=trade_id,
        )

    return trade_id


def _refresh_prices_for_ticker(ticker: str):
    """Fetch latest prices from yfinance and save to DB.

    Called at trade close to ensure the learning module has
    up-to-date OHLCV data, not just the morning scan snapshot.
    """
    try:
        import yfinance as yf
        import pandas as pd
        end = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        start = (dt.date.today() - dt.timedelta(days=5)).isoformat()
        df = yf.download(ticker, start=start, end=end,
                         interval="1d", progress=False, auto_adjust=True)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            save_prices(ticker, df)
    except Exception:
        pass  # best effort – don't block the close


def close_trade(trade_id: int, exit_date: str, exit_price: float,
                fees: float = 0, notes: str = None):
    """Close an open trade and calculate returns.

    Also refreshes price data for the ticker so the learning
    module has accurate OHLCV data from the close day.
    """
    conn = _connect()
    trade = conn.execute(
        "SELECT * FROM trades WHERE id = ?", (trade_id,)
    ).fetchone()
    if not trade:
        conn.close()
        return

    trade = dict(trade)
    entry = trade["entry_price"]
    size = trade["size"] or 1
    entry_fees = trade.get("entry_fees") or 0
    total_fees = entry_fees + fees  # entry + close fees

    if trade["direction"] == "LONG":
        return_pct = (exit_price - entry) / entry * 100
        return_abs = (exit_price - entry) * size - total_fees
    else:  # SHORT
        return_pct = (entry - exit_price) / entry * 100
        return_abs = (entry - exit_price) * size - total_fees

    update_notes = trade.get("notes") or ""
    if notes:
        update_notes = f"{update_notes}\n{notes}".strip() if update_notes else notes

    conn.execute("""
        UPDATE trades SET
            exit_date = ?, exit_price = ?, fees = ?,
            status = 'CLOSED', return_pct = ?, return_abs = ?,
            current_price = ?, notes = ?
        WHERE id = ?
    """, (exit_date, exit_price, total_fees, round(return_pct, 2),
          round(return_abs, 2), exit_price, update_notes, trade_id))
    conn.commit()
    conn.close()

    # Automatische Buchung: Verkauf = Eingang (nicht bei Test-Trades)
    _is_test = trade.get("is_test", 0) == 1
    _pb = trade.get("product_bid") or 0
    _ko = trade.get("ko_level")
    _bv = trade.get("bv") or 1.0
    _dir = trade["direction"]
    if not _is_test:
        if _pb > 0 and _ko and size > 0:
            from ko_calc import stock_to_product
            _exit_prod = stock_to_product(exit_price, _ko, _dir, _bv)
            _sell_amount = _exit_prod * size - fees
            add_ledger_entry(
                date=exit_date,
                entry_type="trade_sell",
                amount=round(_sell_amount, 2),
                description=f"Verkauf {_dir} {trade.get('name', trade['ticker'])} "
                            f"({size:.0f} Stk. × €{_exit_prod:.2f} - €{fees:.2f} Gebühren, "
                            f"P&L: {return_pct:+.1f}%)",
                trade_id=trade_id,
            )
        elif size > 0:
            _sell_amount = exit_price * size - fees
            add_ledger_entry(
                date=exit_date,
                entry_type="trade_sell",
                amount=round(_sell_amount, 2),
                description=f"Verkauf {_dir} {trade.get('name', trade['ticker'])} "
                            f"({size:.0f} Stk. × €{exit_price:.2f} - €{fees:.2f}, "
                            f"P&L: {return_pct:+.1f}%)",
                trade_id=trade_id,
            )

    # Refresh prices so learning has accurate close-day data
    _refresh_prices_for_ticker(trade["ticker"])


def delete_trade(trade_id: int):
    """Permanently delete a trade and its ledger entries."""
    conn = _connect()
    conn.execute("DELETE FROM cash_ledger WHERE trade_id = ?", (trade_id,))
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()


def update_trade(trade_id: int, updates: dict):
    """Update editable fields of a trade."""
    allowed = ["direction", "entry_date", "entry_price", "exit_date", "exit_price",
               "target", "stop_loss", "size", "notes", "fees", "status",
               "return_pct", "return_abs",
               "current_price", "trail_sl", "phase",
               "is_test", "wkn", "ko_level", "bv",
               "isin", "emittent", "product_bid", "entry_fees",
               "post_exit_5d_pct", "post_exit_10d_pct", "post_exit_20d_pct",
               "post_exit_max_pct", "max_r_during", "min_r_during"]
    sets = []
    vals = []
    for key in allowed:
        if key in updates:
            sets.append(f"{key} = ?")
            vals.append(updates[key])
    if not sets:
        return
    vals.append(trade_id)

    # Prüfen ob is_test sich ändert → Ledger anpassen
    if "is_test" in updates:
        conn = _connect()
        old = conn.execute(
            "SELECT is_test FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        conn.close()
        old_val = (old["is_test"] or 0) if old else 0
        new_val = updates["is_test"]

        if old_val == 0 and new_val == 1:
            # Wurde zum Test-Trade → Ledger-Einträge entfernen
            _remove_ledger_for_trade(trade_id)
        elif old_val == 1 and new_val == 0:
            # Wurde zum echten Trade → Ledger-Einträge erstellen
            _create_ledger_for_trade(trade_id)

    conn = _connect()
    conn.execute(
        f"UPDATE trades SET {', '.join(sets)} WHERE id = ?", vals
    )
    conn.commit()
    conn.close()


def _remove_ledger_for_trade(trade_id: int):
    """Remove all ledger entries for a trade (when marked as test)."""
    conn = _connect()
    conn.execute("DELETE FROM cash_ledger WHERE trade_id = ?", (trade_id,))
    conn.commit()
    conn.close()


def _create_ledger_for_trade(trade_id: int):
    """Create ledger entries for a trade (when unmarked as test)."""
    trade = get_trade(trade_id)
    if not trade:
        return

    _pb = trade.get("product_bid") or 0
    _sz = trade.get("size") or 0
    _fees = trade.get("entry_fees") or 0
    _dir = trade["direction"]
    _name = trade.get("name", trade["ticker"])

    # Kauf-Buchung
    if _pb > 0 and _sz > 0:
        _buy_amount = _pb * _sz + _fees
        add_ledger_entry(
            date=trade["entry_date"],
            entry_type="trade_buy",
            amount=-round(_buy_amount, 2),
            description=f"Kauf {_dir} {_name} "
                        f"({_sz:.0f} Stk. × €{_pb:.2f} + €{_fees:.2f} Gebühren)",
            trade_id=trade_id,
        )

    # Verkauf-Buchung (nur wenn Trade geschlossen)
    if trade.get("status") == "CLOSED" and trade.get("exit_price"):
        _ko = trade.get("ko_level")
        _bv = trade.get("bv") or 1.0
        _exit = trade["exit_price"]
        _close_fees = (trade.get("fees") or 0) - _fees  # total_fees - entry_fees
        if _close_fees < 0:
            _close_fees = 0
        _ret_pct = trade.get("return_pct") or 0

        if _pb > 0 and _ko and _sz > 0:
            from ko_calc import stock_to_product
            _exit_prod = stock_to_product(_exit, _ko, _dir, _bv)
            _sell_amount = _exit_prod * _sz - _close_fees
            add_ledger_entry(
                date=trade["exit_date"],
                entry_type="trade_sell",
                amount=round(_sell_amount, 2),
                description=f"Verkauf {_dir} {_name} "
                            f"({_sz:.0f} Stk. × €{_exit_prod:.2f} - €{_close_fees:.2f}, "
                            f"P&L: {_ret_pct:+.1f}%)",
                trade_id=trade_id,
            )
        elif _sz > 0:
            _sell_amount = _exit * _sz - _close_fees
            add_ledger_entry(
                date=trade["exit_date"],
                entry_type="trade_sell",
                amount=round(_sell_amount, 2),
                description=f"Verkauf {_dir} {_name} "
                            f"({_sz:.0f} Stk. × €{_exit:.2f} - €{_close_fees:.2f}, "
                            f"P&L: {_ret_pct:+.1f}%)",
                trade_id=trade_id,
            )


def get_open_trade_tickers() -> dict[str, list[dict]]:
    """Return {ticker: [trade_dicts]} for all open trades, sorted FIFO."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY entry_date ASC"
    ).fetchall()
    conn.close()
    result: dict[str, list[dict]] = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["ticker"], []).append(d)
    return result


def get_open_trades_for_ticker(ticker: str) -> list[dict]:
    """Get all open trades for a ticker, ordered FIFO (oldest first)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'OPEN' AND ticker = ? "
        "ORDER BY entry_date ASC", (ticker,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def partial_close_trade(
    ticker: str,
    sell_qty: float,
    exit_date: str,
    exit_price: float,
    fees: float = 1.0,
    notes: str = None,
) -> list[dict]:
    """
    FIFO-based partial (or full) close across open trades for a ticker.

    exit_price is on stock/underlying level.
    fees = Verkaufsgebühr for this one sell transaction.
    Entry fees are split proportionally per closed portion.

    Returns list of dicts describing each closed portion.
    """
    trades = get_open_trades_for_ticker(ticker)
    if not trades:
        return []

    total_available = sum(t["size"] or 1 for t in trades)
    if sell_qty > total_available:
        sell_qty = total_available

    remaining = sell_qty
    results = []

    for trade in trades:
        if remaining <= 0:
            break

        t_size = trade["size"] or 1
        t_entry_fees = trade.get("entry_fees") or 0

        if remaining >= t_size:
            # Volle Schließung dieses Trades
            portion_fees = fees * (t_size / sell_qty)
            close_trade(
                trade["id"],
                exit_date=exit_date,
                exit_price=exit_price,
                fees=portion_fees,
                notes=notes,
            )
            results.append({
                "trade_id": trade["id"],
                "action": "closed",
                "qty": t_size,
                "entry_price": trade["entry_price"],
            })
            remaining -= t_size
        else:
            # Teilverkauf: Trade splitten
            sold_ratio = remaining / t_size
            keep_ratio = 1 - sold_ratio
            sold_entry_fees = round(t_entry_fees * sold_ratio, 2)
            keep_entry_fees = round(t_entry_fees * keep_ratio, 2)
            portion_fees = fees * (remaining / sell_qty)

            # P/L für den verkauften Teil berechnen
            entry = trade["entry_price"]
            total_close_fees = sold_entry_fees + portion_fees
            if trade["direction"] == "LONG":
                ret_pct = (exit_price - entry) / entry * 100
                ret_abs = (exit_price - entry) * remaining - total_close_fees
            else:
                ret_pct = (entry - exit_price) / entry * 100
                ret_abs = (entry - exit_price) * remaining - total_close_fees

            # 1) Neuen CLOSED-Trade für verkauften Teil anlegen
            conn = _connect()
            _notes = notes or ""
            _orig_notes = trade.get("notes") or ""
            _split_notes = f"Teilverkauf von Trade #{trade['id']}"
            if _notes:
                _split_notes = f"{_split_notes}\n{_notes}"

            conn.execute("""
                INSERT INTO trades (signal_id, ticker, name, direction,
                    entry_date, entry_price, size,
                    target, stop_loss, notes, is_test,
                    wkn, ko_level, bv, isin, emittent, product_bid,
                    entry_fees, current_price,
                    exit_date, exit_price, fees, status,
                    return_pct, return_abs)
                VALUES (?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, 'CLOSED',
                    ?, ?)
            """, (
                trade.get("signal_id"), trade["ticker"], trade["name"],
                trade["direction"],
                trade["entry_date"], trade["entry_price"], remaining,
                trade.get("target"), trade.get("stop_loss"),
                _split_notes, trade.get("is_test", 0),
                trade.get("wkn"), trade.get("ko_level"), trade.get("bv"),
                trade.get("isin"), trade.get("emittent"),
                trade.get("product_bid"),
                sold_entry_fees, exit_price,
                exit_date, exit_price, round(total_close_fees, 2),
                round(ret_pct, 2), round(ret_abs, 2),
            ))

            # 2) Original-Trade: Size und Entry-Fees reduzieren
            new_size = t_size - remaining
            conn.execute("""
                UPDATE trades SET size = ?, entry_fees = ?
                WHERE id = ?
            """, (new_size, keep_entry_fees, trade["id"]))

            conn.commit()
            conn.close()

            results.append({
                "trade_id": trade["id"],
                "action": "partial",
                "qty": remaining,
                "remaining": new_size,
                "entry_price": trade["entry_price"],
            })
            remaining = 0

    # Refresh prices for learning
    _refresh_prices_for_ticker(ticker)
    return results


def get_trades(status: str = None) -> list[dict]:
    """Get trades, optionally filtered by status."""
    conn = _connect()
    query = "SELECT t.*, s.score as signal_score FROM trades t LEFT JOIN signals s ON t.signal_id = s.id"
    params = []
    if status:
        query += " WHERE t.status = ?"
        params.append(status)
    query += " ORDER BY t.entry_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trade(trade_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute(
        "SELECT t.*, s.score as signal_score "
        "FROM trades t LEFT JOIN signals s ON t.signal_id = s.id "
        "WHERE t.id = ?", (trade_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_trade_stats() -> dict:
    """Aggregate statistics for closed trades."""
    conn = _connect()
    stats = {"total_trades": 0, "open": 0, "closed": 0,
             "winners": 0, "losers": 0, "total_return": 0,
             "avg_return_pct": 0, "best": 0, "worst": 0}

    stats["open"] = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE status = 'OPEN'"
    ).fetchone()[0]
    stats["closed"] = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE status = 'CLOSED'"
    ).fetchone()[0]
    stats["total_trades"] = stats["open"] + stats["closed"]

    if stats["closed"] > 0:
        row = conn.execute("""
            SELECT SUM(return_abs) as total_return,
                   AVG(return_pct) as avg_return_pct,
                   MAX(return_pct) as best,
                   MIN(return_pct) as worst,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) as winners,
                   SUM(CASE WHEN return_pct <= 0 THEN 1 ELSE 0 END) as losers
            FROM trades WHERE status = 'CLOSED'
        """).fetchone()
        if row:
            stats["total_return"] = row["total_return"] or 0
            stats["avg_return_pct"] = row["avg_return_pct"] or 0
            stats["best"] = row["best"] or 0
            stats["worst"] = row["worst"] or 0
            stats["winners"] = row["winners"] or 0
            stats["losers"] = row["losers"] or 0

    conn.close()
    return stats


# ---------------------------------------------------------------------------
# Signal-Persistenz
# ---------------------------------------------------------------------------

def get_signal_persistence(lookback_days: int = 10) -> dict[str, int]:
    """Zaehle an wie vielen verschiedenen Tagen jedes Ticker+Pattern Signal erschien.

    Returns: {(ticker, pattern): anzahl_tage}
    """
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=lookback_days)).isoformat()
    conn = _connect()
    rows = conn.execute(
        "SELECT ticker, pattern, COUNT(DISTINCT date) as tage "
        "FROM signals WHERE date >= ? AND pattern IS NOT NULL "
        "GROUP BY ticker, pattern",
        (cutoff,),
    ).fetchall()
    conn.close()
    return {(r["ticker"], r["pattern"]): r["tage"] for r in rows}


# ---------------------------------------------------------------------------
# Trade Alerts (Notification-Tracking)
# ---------------------------------------------------------------------------

def _ensure_alerts_table():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            alert_type  TEXT NOT NULL,
            fired_at    TEXT NOT NULL,
            profit_r    REAL,
            message     TEXT,
            UNIQUE(ticker, alert_type)
        )
    """)
    conn.commit()
    conn.close()


def record_alert(ticker: str, alert_type: str, profit_r: float = None,
                 message: str = None) -> bool:
    """Record alert. Returns True if new (= should send), False if already exists."""
    import datetime as _dt
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO trade_alerts (ticker, alert_type, fired_at, profit_r, message) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker, alert_type, _dt.datetime.now().isoformat(), profit_r, message),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_alert_time(ticker: str, alert_type: str) -> str | None:
    """Return fired_at timestamp for an alert, or None."""
    conn = _connect()
    row = conn.execute(
        "SELECT fired_at FROM trade_alerts WHERE ticker = ? AND alert_type = ?",
        (ticker, alert_type),
    ).fetchone()
    conn.close()
    return row["fired_at"] if row else None


def clear_alerts_for_ticker(ticker: str):
    """Remove all alerts for a ticker (when position fully closed)."""
    conn = _connect()
    conn.execute("DELETE FROM trade_alerts WHERE ticker = ?", (ticker,))
    conn.commit()
    conn.close()


def get_alerted_tickers() -> set[str]:
    """Return set of tickers that have any alerts."""
    conn = _connect()
    rows = conn.execute("SELECT DISTINCT ticker FROM trade_alerts").fetchall()
    conn.close()
    return {r["ticker"] for r in rows}


def get_open_tickers() -> set[str]:
    """Return set of tickers with open trades."""
    conn = _connect()
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM trades WHERE status = 'OPEN'"
    ).fetchall()
    conn.close()
    return {r["ticker"] for r in rows}


# Initialize on import
init_db()
_ensure_alerts_table()
