"""
scanner.py – Daily DAX 40 scan orchestrator.

Downloads data, computes indicators, fetches fundamentals + news,
runs the analyzer, computes targets, and stores everything in the DB.
"""

from __future__ import annotations

import logging
import datetime as dt
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st

from markets import (DAX_COMPONENTS, TECDAX_COMPONENTS, MDAX_COMPONENTS,
                     DOW_COMPONENTS, NASDAQ_COMPONENTS, INDICES,
                     get_sector, get_index, SECTOR_MAP)
from indicators import compute_all
from patterns import detect_patterns, MIN_SL_DIST_PCT
from fundamentals import get_fundamentals  # retry_failed + KI-Batch
from news_sentiment import get_news_sentiment  # nur KI-Batch
from market_context import get_market_context  # Scan + retry + KI-Batch
from db import save_signal, save_prices, get_open_trade_tickers, update_trade, save_ai_assessment
from ko_search import refresh_product_price
from ko_calc import stock_to_product

# Pattern-System Konfiguration
PATTERN_RR = 2.0                          # Fixes Risk/Reward
PATTERN_WINNERS = {"ema50_bounce", "gap_up_continuation"}  # Getestete Gewinner-Patterns
RISK_PCT = 0.02                           # 2% vom freien Cash riskieren
MAX_INVEST = 2500.0                       # Max Eigenkapital pro Position

log = logging.getLogger(__name__)

# Progress callback – can be set externally (e.g. by app.py) before calling
# run_scan() / refresh_open_trades(). Signature: callback(done, total, text)
progress_callback = None


def _get_sector_score(ticker: str) -> float:
    """Sektor-Score für einen Ticker, 0.0 für Indizes."""
    from sectors import compute_sector_scores
    sec = SECTOR_MAP.get(ticker)
    if not sec or sec.startswith("Index:"):
        return 0.0
    scores = compute_sector_scores()
    data = scores.get(sec)
    return data.get("score", 0.0) if data else 0.0


def _download(ticker: str, days: int = 365) -> pd.DataFrame | None:
    """Download daily data for one ticker."""
    try:
        end = dt.date.today() + dt.timedelta(days=1)
        start = end - dt.timedelta(days=days)
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if df.empty or len(df) < 50:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["Volume"] = df["Volume"].replace(0, np.nan).infer_objects(copy=False).ffill().bfill()
        df.dropna(subset=["Close"], inplace=True)
        return df
    except Exception as e:
        log.warning("Download %s fehlgeschlagen: %s", ticker, e)
        return None


def _batch_download(tickers: list[str], days: int = 365) -> dict[str, pd.DataFrame]:
    """Batch-download daily data for multiple tickers at once."""
    end = dt.date.today() + dt.timedelta(days=1)
    start = end - dt.timedelta(days=days)
    result = {}
    try:
        raw = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
        )
        if raw.empty:
            return result
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    df = raw.copy()
                else:
                    df = raw[ticker].copy()
                df = df.dropna(how="all")
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                if df.empty or len(df) < 50:
                    continue
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                if "Volume" in df.columns:
                    df["Volume"] = df["Volume"].replace(0, np.nan).infer_objects(copy=False).ffill().bfill()
                df.dropna(subset=["Close"], inplace=True)
                if len(df) >= 50:
                    result[ticker] = df
            except Exception:
                continue
    except Exception as e:
        log.warning("Batch-Download fehlgeschlagen: %s", e)
    return result


@st.cache_data(ttl=86400, show_spinner=False)  # 24h – voller Scan nur manuell/cron
def run_scan() -> tuple[pd.DataFrame, dict]:
    """
    Scan all DAX 40 stocks + deutsche Indizes.

    Returns:
        results_df: DataFrame with one row per stock, sorted by |score|
        market: market context dict
    """
    today = dt.date.today().isoformat()
    market = get_market_context()

    # Load open trades to detect active positions
    open_trades = get_open_trade_tickers()

    results = []
    trade_updates = []  # updated open trade rows for the dashboard
    failed_tickers = []
    all_tickers = {**INDICES, **DAX_COMPONENTS, **TECDAX_COMPONENTS, **MDAX_COMPONENTS,
                    **DOW_COMPONENTS, **NASDAQ_COMPONENTS}

    # Batch-Download aller Ticker auf einmal
    log.info("Starte Batch-Download für %d Ticker …", len(all_tickers))
    _all_data = _batch_download(list(all_tickers.keys()))
    log.info("Batch-Download: %d / %d erfolgreich", len(_all_data), len(all_tickers))

    _total = len(all_tickers)
    _done = 0
    for ticker, name in all_tickers.items():
        _done += 1
        if progress_callback:
            progress_callback(_done, _total, f"{ticker} ({_done}/{_total})")

        try:
            # 1. Price data + indicators
            raw_df = _all_data.get(ticker)
            if raw_df is None:
                log.info("Überspringe %s: kein Download", ticker)
                failed_tickers.append(ticker)
                continue

            # Save raw prices to DB
            save_prices(ticker, raw_df)

            df = compute_all(raw_df)
            df.dropna(subset=["RSI", "ATR", "EMA50"], inplace=True)
            if len(df) < 30:
                log.info("Überspringe %s: nur %d Zeilen nach Indikatoren", ticker, len(df))
                continue

            last = df.iloc[-1]

            # ── Active trade(s)? → Kurs + Produkt-Bid aktualisieren ──
            if ticker in open_trades:
                trade_list = open_trades[ticker]
                _cur_price = float(last["Close"])

                for trade in trade_list:
                    _entry = trade["entry_price"]
                    _d = trade["direction"]
                    if _d == "LONG":
                        _unr_pct = (_cur_price - _entry) / _entry * 100
                        _unr_abs = (_cur_price - _entry) * (trade.get("size") or 1)
                    else:
                        _unr_pct = (_entry - _cur_price) / _entry * 100
                        _unr_abs = (_entry - _cur_price) * (trade.get("size") or 1)

                    trade_db_update = {
                        "current_price": _cur_price,
                        "unrealized_pct": round(_unr_pct, 2),
                        "unrealized_abs": round(_unr_abs, 2),
                        "rec_date": today,
                    }

                    _trade_isin = trade.get("isin")
                    if _trade_isin:
                        _prod_price = refresh_product_price(_trade_isin)
                        if _prod_price and _prod_price.get("bid"):
                            trade_db_update["product_bid"] = _prod_price["bid"]

                    update_trade(trade["id"], trade_db_update)

                    # Dashboard-Row bauen (wird in app.py via _build_trade_row gemacht)
                    # Hier nur minimal loggen
                    log.info("TRADE UPDATE: %s #%d %s Kurs=%.2f",
                             ticker, trade["id"], trade["direction"], _cur_price)
                continue  # Skip normal signal generation

            # ── No active trade → Pattern-Erkennung + Signal ──
            # 3. Pattern-Detektoren auf letzten Bar
            patterns = detect_patterns(df)

            # Nur Gewinner-Patterns behalten
            patterns = [p for p in patterns if p["pattern"] in PATTERN_WINNERS]

            if not patterns:
                continue  # Kein Pattern erkannt → kein Signal

            # Bei mehreren Patterns am gleichen Tag: bestes nach Combo-Score
            import re
            best_pattern = patterns[0]
            best_score = 0
            for p in patterns:
                # ADX aus Detail parsen
                m = re.search(r'ADX=(\d+)', p.get("detail", ""))
                adx_val = int(m.group(1)) if m else 25
                sl_dist = abs(p["entry"] - p["stop_loss"]) / p["entry"] if p["entry"] > 0 else 0.05
                # Combo-Score: hoher ADX + enger SL
                score = adx_val * 0.5 + (1 / max(sl_dist, 0.01)) * 0.01
                if score > best_score:
                    best_score = score
                    best_pattern = p

            pat = best_pattern
            entry = pat["entry"]
            sl = pat["stop_loss"]
            direction = pat.get("direction", "LONG")
            risk = abs(entry - sl)
            sl_dist_pct = risk / entry if entry > 0 else 0

            # Target: Fix R/R
            if direction == "LONG":
                target = round(entry + PATTERN_RR * risk, 2)
            else:
                target = round(entry - PATTERN_RR * risk, 2)

            rr = PATTERN_RR

            # 4. Combo-Score fuer Ranking
            adx_val = round(last.get("ADX", 0), 1)
            combo_score = round(adx_val * 0.5 + (1 / max(sl_dist_pct, 0.01)) * 0.01, 1)

            # 5. Build result row
            row = {
                "Ticker": ticker,
                "Name": name,
                "Index": get_index(ticker),
                "Sparte": get_sector(ticker),
                "Preis": round(last["Close"], 2),
                "Richtung": direction,
                "Pattern": pat["pattern"],
                "Entry": entry,
                "Score": combo_score,
                "Ziel": target,
                "Stop-Loss": sl,
                "R/R": rr,
                "SL-Dist%": round(sl_dist_pct * 100, 1),
                "RSI": round(last.get("RSI", 0), 1),
                "ADX": round(adx_val, 1),
                "ATR%": round(last.get("ATR_pct", 0), 2),
                "Detail": pat.get("detail", ""),
            }
            results.append(row)

            # 6. Save to DB
            save_signal({
                "date": today,
                "ticker": ticker,
                "name": name,
                "direction": direction,
                "pattern": pat["pattern"],
                "entry": entry,
                "target": target,
                "stop_loss": sl,
                "risk_reward": rr,
                "sl_dist_pct": sl_dist_pct,
                "score": combo_score,
                "adx": round(adx_val, 1),
                "rsi": round(last.get("RSI", 0), 1),
                "atr_pct": round(last.get("ATR_pct", 0), 2),
                "detail": pat.get("detail", ""),
            })
            log.info("PATTERN: %s %s %s score=%.1f", ticker, direction, pat["pattern"], combo_score)

        except Exception as e:
            log.error("Fehler bei %s (%s): %s", ticker, name, e, exc_info=True)
            continue

    if not results and not trade_updates:
        return pd.DataFrame(), pd.DataFrame(), market, failed_tickers

    results_df = pd.DataFrame(results) if results else pd.DataFrame()
    if not results_df.empty:
        results_df = results_df.sort_values("Score", ascending=False)

    trades_df = pd.DataFrame(trade_updates) if trade_updates else pd.DataFrame()

    # Post-Exit Tracking: Kurs 5/10/20 Tage nach Trade-Schliessung
    try:
        from trade_analytics import track_post_exit
        n_tracked = track_post_exit(_all_data)
        if n_tracked > 0:
            log.info("Post-Exit Tracking: %d Trades aktualisiert", n_tracked)
    except Exception as e:
        log.warning("Post-Exit Tracking fehlgeschlagen: %s", e)

    # Heutige Signale bereinigen: Signale die im Scan nicht mehr gefunden
    # wurden aus der DB loeschen (z.B. Kurs ist vom EMA50 weggelaufen)
    try:
        from db import _connect
        _found_today = {(r["Ticker"], r["Pattern"]) for r in results} if results else set()
        _conn = _connect()
        _db_today = _conn.execute(
            "SELECT ticker, pattern FROM signals WHERE date = ? AND pattern IS NOT NULL",
            (today,)).fetchall()
        _stale = [(r["ticker"], r["pattern"]) for r in _db_today
                  if (r["ticker"], r["pattern"]) not in _found_today]
        for _t, _p in _stale:
            _conn.execute("DELETE FROM signals WHERE date = ? AND ticker = ? AND pattern = ?",
                          (today, _t, _p))
            log.info("Signal bereinigt: %s %s (nicht mehr erkannt)", _t, _p)
        if _stale:
            _conn.commit()
        _conn.close()
    except Exception as e:
        log.warning("Signal-Bereinigung fehlgeschlagen: %s", e)

    log.info("Scan fertig: %d Signale, %d Trade-Updates, %d fehlgeschlagen",
             len(results), len(trade_updates), len(failed_tickers))
    return results_df, trades_df, market, failed_tickers


def retry_failed(tickers: list[str]) -> tuple[list[dict], list[str]]:
    """
    Retry scan for specific tickers that previously failed.

    Returns (new_signals, still_failed) where new_signals is a list of
    result rows compatible with the main scan output.
    """
    today = dt.date.today().isoformat()
    market = get_market_context()
    open_trades = get_open_trade_tickers()

    all_names = {**INDICES, **DAX_COMPONENTS, **TECDAX_COMPONENTS, **MDAX_COMPONENTS,
                 **DOW_COMPONENTS, **NASDAQ_COMPONENTS}

    new_signals = []
    still_failed = []

    for ticker in tickers:
        name = all_names.get(ticker, ticker)
        try:
            raw_df = _download(ticker)
            if raw_df is None:
                still_failed.append(ticker)
                continue

            save_prices(ticker, raw_df)
            df = compute_all(raw_df)
            df.dropna(subset=["RSI", "ATR", "EMA50"], inplace=True)
            if len(df) < 30:
                still_failed.append(ticker)
                continue

            last = df.iloc[-1]
            fund = get_fundamentals(ticker)

            if ticker in open_trades:
                # Active trade(s) — nur Kurs aktualisieren
                _cur = float(last["Close"])
                for trade in trade_list:
                    _d = trade["direction"]
                    _e = trade["entry_price"]
                    _s = trade.get("size") or 1
                    _unr_pct = ((_cur - _e) / _e * 100) if _d == "LONG" else ((_e - _cur) / _e * 100)
                    update_trade(trade["id"], {
                        "current_price": _cur,
                        "unrealized_pct": round(_unr_pct, 2),
                        "unrealized_abs": round((_cur - _e) * _s if _d == "LONG" else (_e - _cur) * _s, 2),
                        "rec_date": today,
                    })
                continue

            # Pattern-Erkennung
            patterns = detect_patterns(df)
            patterns = [p for p in patterns if p["pattern"] in PATTERN_WINNERS]

            if not patterns:
                continue

            pat = patterns[0]  # Bestes Pattern
            entry = pat["entry"]
            sl = pat["stop_loss"]
            direction = pat.get("direction", "LONG")
            risk = abs(entry - sl)
            sl_dist_pct = risk / entry if entry > 0 else 0.05

            if direction == "LONG":
                target = round(entry + PATTERN_RR * risk, 2)
            else:
                target = round(entry - PATTERN_RR * risk, 2)

            adx_val = round(last.get("ADX", 0), 1)
            combo_score = round(adx_val * 0.5 + (1 / max(sl_dist_pct, 0.01)) * 0.01, 1)

            row = {
                "Ticker": ticker, "Name": name,
                "Index": get_index(ticker),
                "Sparte": get_sector(ticker),
                "Preis": round(last["Close"], 2),
                "Richtung": direction,
                "Pattern": pat["pattern"],
                "Entry": entry,
                "Score": combo_score,
                "Ziel": target,
                "Stop-Loss": sl,
                "R/R": PATTERN_RR,
                "SL-Dist%": round(sl_dist_pct * 100, 1),
                "RSI": round(last.get("RSI", 0), 1),
                "ADX": adx_val,
                "ATR%": round(last.get("ATR_pct", 0), 2),
                "Detail": pat.get("detail", ""),
            }
            new_signals.append(row)

            save_signal({
                "date": today, "ticker": ticker, "name": name,
                "direction": direction,
                "pattern": pat["pattern"],
                "entry": entry,
                "target": target, "stop_loss": sl, "risk_reward": PATTERN_RR,
                "sl_dist_pct": sl_dist_pct,
                "score": combo_score,
                "adx": adx_val,
                "rsi": round(last.get("RSI", 0), 1),
                "atr_pct": round(last.get("ATR_pct", 0), 2),
                "detail": pat.get("detail", ""),
            })
            log.info("Retry PATTERN: %s %s %s score=%.1f", ticker, direction, pat["pattern"], combo_score)

        except Exception as e:
            log.error("Retry Fehler bei %s: %s", ticker, e, exc_info=True)
            still_failed.append(ticker)

    return new_signals, still_failed


def refresh_open_trades() -> int:
    """
    Quick refresh for open trades: Kurs + Produkt-Bid aktualisieren.

    Returns number of successfully updated trades.
    """
    today = dt.date.today().isoformat()
    open_trades = get_open_trade_tickers()
    if not open_trades:
        return 0

    n_updated = 0
    _total = len(open_trades)
    _done = 0
    for ticker, trade_list in open_trades.items():
        _done += 1
        if progress_callback:
            progress_callback(_done, _total, f"{ticker} ({_done}/{_total})")
        try:
            raw_df = _download(ticker)
            if raw_df is None:
                continue

            save_prices(ticker, raw_df)
            _cur = float(raw_df["Close"].iloc[-1])

            for trade in trade_list:
                _d = trade["direction"]
                _e = trade["entry_price"]
                _s = trade.get("size") or 1
                _unr_pct = ((_cur - _e) / _e * 100) if _d == "LONG" else ((_e - _cur) / _e * 100)

                trade_db_update = {
                    "current_price": _cur,
                    "unrealized_pct": round(_unr_pct, 2),
                    "unrealized_abs": round((_cur - _e) * _s if _d == "LONG" else (_e - _cur) * _s, 2),
                    "rec_date": today,
                }

                _trade_isin = trade.get("isin")
                if _trade_isin:
                    _prod_price = refresh_product_price(_trade_isin)
                    if _prod_price and _prod_price.get("bid"):
                        trade_db_update["product_bid"] = _prod_price["bid"]

                update_trade(trade["id"], trade_db_update)
                n_updated += 1
                log.info("Refresh: %s #%d %s Kurs=%.2f", ticker, trade["id"], _d, _cur)

        except Exception as e:
            log.error("Refresh Fehler bei %s: %s", ticker, e, exc_info=True)
            continue

    if n_updated > 0:
        from db import set_setting
        set_setting("last_trade_refresh", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))

    return n_updated


def run_ai_for_top_signals(results_df: pd.DataFrame,
                           threshold: float = 40.0,
                           max_workers: int = 5,
                           model: str = "sonnet",
                           progress_callback=None) -> pd.DataFrame:
    """
    KI-Batch für Top-Signale aus einem Scan-Ergebnis.

    Separat aufrufbar – manuell per Button oder automatisch im Nachtlauf.
    Ergänzt results_df um Konsens-Spalten (Konsens, KI, KI-Score, K-Ziel, K-Stop).

    Args:
        results_df: DataFrame aus run_scan()
        threshold: Mindest-|Score| für KI-Bewertung (default 40)
        max_workers: Parallele Claude-Aufrufe
        model: Claude-Modell
        progress_callback: Optional callable(done, total)

    Returns:
        results_df mit Konsens-Spalten
    """
    if results_df.empty:
        return results_df

    today = dt.date.today().isoformat()
    market = get_market_context()
    all_names = {**INDICES, **DAX_COMPONENTS, **TECDAX_COMPONENTS,
                 **MDAX_COMPONENTS, **DOW_COMPONENTS, **NASDAQ_COMPONENTS}

    # Kandidaten filtern
    candidates_df = results_df[results_df["Score"].abs() >= threshold]
    if candidates_df.empty:
        log.info("KI-Batch: Keine Ticker mit |Score| >= %.0f", threshold)
        return results_df

    log.info("KI-Batch: %d Kandidaten mit |Score| >= %.0f", len(candidates_df), threshold)

    # Daten für KI-Batch laden (Download + Indikatoren)
    tickers = candidates_df["Ticker"].tolist()
    data_map = _batch_download(tickers)

    ai_candidates = []
    for _, row in candidates_df.iterrows():
        ticker = row["Ticker"]
        raw_df = data_map.get(ticker)
        if raw_df is None:
            continue
        df = compute_all(raw_df)
        df.dropna(subset=["RSI", "ATR", "EMA50"], inplace=True)
        if len(df) < 30:
            continue

        fund = get_fundamentals(ticker)
        news_sc, news_cnt, _ = get_news_sentiment(ticker)

        ai_candidates.append({
            "ticker": ticker,
            "name": row.get("Name", all_names.get(ticker, ticker)),
            "df": df,
            "fundamentals": fund,
            "news_score": news_sc,
            "news_count": news_cnt,
            "sector": get_sector(ticker),
            "sector_score": _get_sector_score(ticker),
            "index": get_index(ticker),
            "tech_analysis": {
                "direction": row["Richtung"],
                "score": row["Score"],
            },
        })

    if not ai_candidates:
        log.info("KI-Batch: Keine Daten für Kandidaten verfügbar")
        return results_df

    # KI-Batch ausführen
    from ai_opinion import run_ai_batch
    ai_results = run_ai_batch(ai_candidates, max_workers=max_workers,
                              model=model, progress_callback=progress_callback)

    # Konsens-Spalten berechnen
    konsens_col = []
    ai_dir_col = []
    ai_score_col = []
    ai_target_col = []
    ai_stop_col = []

    for _, row in results_df.iterrows():
        t = row["Ticker"]
        ai = ai_results.get(t)
        if ai and not ai.get("error") and ai.get("direction"):
            # In DB speichern
            save_ai_assessment({
                "date": today, "ticker": t,
                "direction": ai["direction"],
                "score": ai.get("score"),
                "entry": ai.get("entry"),
                "target": ai.get("target"),
                "stop_loss": ai.get("stop_loss"),
                "risk_reward": ai.get("risk_reward"),
                "reasoning": ai.get("reasoning"),
                "prompt": ai.get("prompt"),
                "model": ai.get("model"),
            })
            ai_dir_col.append(ai["direction"])
            ai_score_col.append(ai.get("score"))

            if ai["direction"] == row["Richtung"]:
                konsens_col.append("\u2605\u2605\u2605")
                tech_tgt = row.get("Ziel")
                ai_tgt = ai.get("target")
                if tech_tgt and ai_tgt:
                    if row["Richtung"] == "LONG":
                        ai_target_col.append(min(tech_tgt, ai_tgt))
                    else:
                        ai_target_col.append(max(tech_tgt, ai_tgt))
                else:
                    ai_target_col.append(tech_tgt)
                ai_stop_col.append(row.get("Stop-Loss"))
            else:
                konsens_col.append("\u26a0")
                ai_target_col.append(None)
                ai_stop_col.append(None)
        else:
            konsens_col.append("\u2013")
            ai_dir_col.append(None)
            ai_score_col.append(None)
            ai_target_col.append(None)
            ai_stop_col.append(None)

    results_df = results_df.copy()
    results_df["Konsens"] = konsens_col
    results_df["KI"] = ai_dir_col
    results_df["KI-Score"] = ai_score_col
    results_df["K-Ziel"] = ai_target_col
    results_df["K-Stop"] = ai_stop_col

    n_konsens = sum(1 for k in konsens_col if k == "\u2605\u2605\u2605")
    n_warn = sum(1 for k in konsens_col if k == "\u26a0")
    log.info("KI-Batch fertig: %d Konsens, %d Widerspruch, %d ohne KI",
             n_konsens, n_warn, sum(1 for k in konsens_col if k == "\u2013"))
    return results_df
