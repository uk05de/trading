"""
app.py – DAX / TecDAX / MDAX Dashboard.

Run with:  .venv/bin/streamlit run app.py
"""

from __future__ import annotations

import json
import datetime as dt
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

from scanner import run_scan, refresh_open_trades, retry_failed, run_ai_for_top_signals
from markets import (DAX_COMPONENTS, TECDAX_COMPONENTS, MDAX_COMPONENTS,
                     DOW_COMPONENTS, NASDAQ_COMPONENTS, INDICES)
from db import (get_signals, get_signal_history,
                get_prices, get_prices_with_backfill,
                open_trade, close_trade, update_trade, delete_trade,
                get_trades, get_trade, get_trade_stats, get_open_trade_tickers,
                get_latest_signal_date,
                get_free_cash, calc_position_size,
                add_ledger_entry, get_ledger_entries, delete_ledger_entry,
                get_cash_balance)
from ko_calc import (stock_to_product, product_to_stock, calc_leverage,
                      convert_targets, trade_summary)
from ko_search import lookup_isin, calc_ideal_ko, evaluate_product, refresh_product_price, clear_price_cache
from components import (render_chart, render_trade_actions,
                        render_position_metrics, render_position_trades_table,
                        render_trade_detail_caption)
from sectors import compute_sector_scores
from markets import get_sector, get_index

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(ticker: str) -> str:
    """Einheit für Kursanzeige: € für DE-Aktien, $ für US-Aktien, Pkt. für Indizes."""
    if ticker.startswith("^"):
        return "Pkt."
    if ticker.endswith(".DE"):
        return "€"
    return "$"


def _fmt(value: float, ticker: str) -> str:
    """Kurs formatieren mit passender Einheit."""
    return f"{value:.2f} {_unit(ticker)}"


def _de_date(iso: str) -> str:
    """ISO-Datum (YYYY-MM-DD) ins deutsche Format (DD.MM.YYYY) umwandeln."""
    try:
        return dt.date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso or "–"


def _eur(val, sign: bool = False) -> str:
    """Betrag im deutschen Format: 1.234,56 €. Mit sign=True: +1.234,56 €"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "–"
    prefix = "+" if sign and val > 0 else ""
    formatted = f"{abs(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if val < 0:
        return f"-{formatted} €"
    return f"{prefix}{formatted} €"


def _num(val, decimals: int = 2, sign: bool = False, suffix: str = "") -> str:
    """Zahl im deutschen Format: 1.234,56. Optional mit Vorzeichen und Suffix."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "–"
    prefix = "+" if sign and val > 0 else ""
    formatted = f"{abs(val):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if val < 0:
        return f"-{formatted}{suffix}"
    return f"{prefix}{formatted}{suffix}"


def _pct(val, sign: bool = True) -> str:
    """Prozent im deutschen Format: +12,5%"""
    return _num(val, decimals=1, sign=sign, suffix="%")


from ui_colors import color_for_r, style_trades_df as _style_trades_df


def _group_trade_rows(rows: list[dict]) -> list[dict]:
    """
    Gruppiere Trade-Rows nach Ticker.
    Einzelne Trades bleiben unverändert (_n_trades=1).
    Mehrere Trades pro Ticker → eine Zusammenfassungszeile.
    """
    from collections import defaultdict
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ticker[r["Ticker"]].append(r)

    grouped = []
    for ticker, trades in by_ticker.items():
        if len(trades) == 1:
            trades[0]["_n_trades"] = 1
            grouped.append(trades[0])
        else:
            # Sortiert nach trade_id (ältester zuerst)
            trades.sort(key=lambda t: t["trade_id"])
            latest = trades[-1]  # neuester Trade für Hinweis
            total_size = sum(t.get("Stk.", 1) for t in trades)
            total_invest = sum(t.get("Einstieg", 0) * t.get("Stk.", 1) for t in trades)
            avg_entry = round(total_invest / total_size, 2) if total_size else 0
            total_wert = sum(t.get("Aktuell", 0) * t.get("Stk.", 1) for t in trades)
            # P/L korrigieren: jeder Einzel-Trade hat 1€ Verkauf eingerechnet,
            # aber bei Gesamtposition fällt nur 1× Verkaufsgebühr an
            _n = len(trades)
            total_pnl_abs = sum(t.get("P/L €", 0) for t in trades) + (_n - 1)  # zu viel abgezogene Verkaufsgebühren zurück
            total_pnl_pct = round(total_pnl_abs / total_invest * 100, 1) if total_invest > 0 else 0

            summary = {
                "trade_id": trades[0]["trade_id"],
                "Name": trades[0]["Name"],
                "Ticker": ticker,
                "Richtung": trades[0]["Richtung"],
                "Produkt": trades[0].get("Produkt", ""),
                "Stk.": total_size,
                "Einstieg": avg_entry,
                "Aktuell": latest.get("Aktuell", 0),
                "Invest": round(total_invest, 2),
                "Wert": round(total_wert, 2),
                "P/L %": total_pnl_pct,
                "P/L €": round(total_pnl_abs, 2),
                "_n_trades": len(trades),
            }
            # Optionale Felder nur wenn in Quelldaten vorhanden
            _all_keys = set()
            for t in trades:
                _all_keys.update(t.keys())
            # Profit R: gewichteter Durchschnitt ueber alle Einzeltrades
            _total_r = 0.0
            _r_count = 0
            for _t in trades:
                _pr = _t.get("Profit R")
                if _pr is not None:
                    _stk = _t.get("Stk.", 1)
                    _total_r += _pr * _stk
                    _r_count += _stk
            summary["Profit R"] = round(_total_r / _r_count, 2) if _r_count > 0 else None

            # Hinweis: schlimmsten nehmen (SL durchbrochen hat Prioritaet)
            _worst_hint = ""
            for _t in trades:
                _h = _t.get("Hinweis", "")
                if "SL DURCHBROCHEN" in _h:
                    _worst_hint = _h
                    break
                elif _h and not _worst_hint:
                    _worst_hint = _h
            summary["Hinweis"] = _worst_hint

            _optional = {
                "Stop": latest, "Ziel": latest,
                "RSI": latest, "Seit": trades[0], "Produkt Bid": latest,
                "Tage": max(trades, key=lambda t: t.get("Tage", 0)),
            }
            for key, src in _optional.items():
                if key in _all_keys:
                    summary[key] = src.get(key)
            grouped.append(summary)
    return grouped


def _build_trade_row(t: dict) -> dict:
    """
    Baut eine Display-Zeile für einen offenen Trade aus DB-Daten.
    Gemeinsame Funktion für Dashboard und Meine-Trades-Tabelle.
    """
    ko = t.get("ko_level")
    bv = t.get("bv") or 1.0
    _dir = t["direction"]
    cur_stock = t.get("current_price") or t["entry_price"]
    entry_stock = t["entry_price"]
    _entry_fees = t.get("entry_fees") or 1.0
    _est_total_fees = _entry_fees + 1.0
    _size = t.get("size") or 1

    if ko:
        _prod_bid = t.get("product_bid")
        cur_prod = _prod_bid if _prod_bid else stock_to_product(cur_stock, ko, _dir, bv)
        entry_prod = stock_to_product(entry_stock, ko, _dir, bv)
        stop_stock = t.get("stop_loss")
        tgt_stock = t.get("target")
        stop_prod = stock_to_product(stop_stock, ko, _dir, bv) if stop_stock else None
        tgt_prod = stock_to_product(tgt_stock, ko, _dir, bv) if tgt_stock else None
        _invest = entry_prod * _size
        _raw_pnl = (cur_prod - entry_prod) * _size
        pnl_abs = _raw_pnl - _est_total_fees
        pnl_pct = pnl_abs / _invest * 100 if _invest > 0 else 0
    else:
        cur_prod = cur_stock
        entry_prod = entry_stock
        stop_prod = t.get("stop_loss")
        tgt_prod = t.get("target")
        _invest = entry_prod * _size
        _raw_pnl = (cur_prod - entry_prod) * _size if cur_prod and entry_prod else 0
        pnl_abs = _raw_pnl - _est_total_fees
        pnl_pct = pnl_abs / _invest * 100 if _invest > 0 else 0

    # Profit in R berechnen (auf Produkt-Ebene, konsistent mit P/L)
    # Bei KO-Zertifikaten: Profit = Aktuell - Einstieg (IMMER, egal ob LONG/SHORT)
    # Das SHORT ist im Produktpreis eingebaut (stock_to_product)
    _orig_sl_stock = t.get("stop_loss")
    _profit_r = None
    if _orig_sl_stock and entry_stock and _orig_sl_stock > 0 and entry_stock > 0:
        if ko:
            _sl_prod = stock_to_product(_orig_sl_stock, ko, _dir, bv)
            _risk_prod = abs(entry_prod - _sl_prod)
            _profit_prod = cur_prod - entry_prod
            _profit_r = round(_profit_prod / _risk_prod, 2) if _risk_prod > 0 else None
        else:
            _risk = abs(entry_stock - _orig_sl_stock)
            if _dir == "LONG":
                _profit = cur_stock - entry_stock
            else:
                _profit = entry_stock - cur_stock
            _profit_r = round(_profit / _risk, 2) if _risk > 0 else None

    # Hinweis basierend auf Profit R
    _hinweis = ""
    if _profit_r is not None:
        if _profit_r <= -1.0:
            _hinweis = "⚠️ SL DURCHBROCHEN — sofort prüfen!"
        elif _profit_r >= 2.0:
            _hinweis = "🎯 Target erreicht — Gewinnmitnahme!"
        elif _profit_r >= 1.5:
            _hinweis = "✅ Nahe Target"

    _row = {
        "trade_id": t["id"],
        "Name": t["name"],
        "Richtung": t["direction"],
        "Stk.": _size,
        "Einstieg": round(entry_prod, 2),
        "Aktuell": round(cur_prod, 2),
        "Stop": round(stop_prod, 2) if stop_prod else None,
        "Ziel": round(tgt_prod, 2) if tgt_prod else None,
        "P/L %": round(pnl_pct, 1),
        "P/L €": round(pnl_abs, 2),
        "Profit R": _profit_r,
        "Hinweis": _hinweis,
        "Tage": (dt.date.today() - dt.date.fromisoformat(t["entry_date"])).days,
        "Ticker": t["ticker"],
    }
    return _row


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(page_title="DAX Screener", page_icon="📊", layout="wide")

# Kompaktere Metrics + Mobile Optimierung
st.markdown("""
<style>
    /* Oberen Rand reduzieren */
    .block-container {
        padding-top: 3rem;
        padding-bottom: 0rem;
    }

    /* Inline-Code in Info/Warning-Boxen lesbar machen */
    [data-testid="stAlert"] code {
        background: rgba(0, 0, 0, 0.3) !important;
        color: #4ade80 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
    }

    /* Metrics kompakter */
    [data-testid="stMetric"] { padding: 0.5rem 0 0.5rem 0; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
    [data-testid="stMetricLabel"] { font-size: 0.7rem; }
    [data-testid="stMetricDelta"] { font-size: 0.7rem; }

    /* Mobile: kompakter + Columns als Grid */
    @media (max-width: 768px) {
        [data-testid="stMetric"] { padding: 0.5rem 0 0.5rem 0; }
        [data-testid="stMetricValue"] { font-size: 1.4rem; }
        [data-testid="stMetricLabel"] { font-size: 0.7rem; }
        [data-testid="stMetricDelta"] { font-size: 0.7rem; }

        /* Nur Metric-Columns auf Mobile wrappen (nicht Formular-Felder) */
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
            flex-wrap: wrap !important;
            gap: 0 !important;
        }
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
            min-width: 33% !important;
            flex: 0 0 33% !important;
        }

        /* Tabs kompakter */
        .stTabs [data-baseweb="tab"] { font-size: 0.8rem; padding: 6px 8px; }

        /* Titel kleiner */
        h1 { font-size: 1.6rem !important; }
        h2 { font-size: 1.4rem !important; }
        h3 { font-size: 1.2rem !important; }

        /* Tabellen kompakter */
        .stDataFrame { font-size: 0.75rem; }

        /* Sektor-Kacheln: 3 pro Zeile auf Mobile */
        .sector-tile {
            flex: 1 1 calc(33.3% - 6px) !important;
            min-width: 60px !important;
            font-size: 0.85em;
        }
        .sector-tile > div:last-child { font-size: 1.1em !important; }
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar Aktionen (unter der Navigation)
# ---------------------------------------------------------------------------
with st.sidebar:
    _do_refresh = st.button("Trades aktualisieren", use_container_width=True)
    _do_ai_batch = st.button("KI-Bewertung", use_container_width=True)
    if st.button("Alles aktualisieren", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.session_state["run_scan"] = True
        st.rerun()

if _do_refresh:
    clear_price_cache()
    import scanner as _scanner_mod
    _refresh_bar = st.progress(0, text="Trades aktualisieren ...")
    _scanner_mod.progress_callback = lambda d, t, txt: _refresh_bar.progress(d / t, text=f"Trades: {txt}")
    _n_updated = refresh_open_trades()
    _scanner_mod.progress_callback = None
    _refresh_bar.empty()
    if _n_updated:
        st.toast(f"{_n_updated} Trade(s) aktualisiert", icon="✅")
    else:
        st.toast("Keine offenen Trades", icon="⚠️")

if _do_ai_batch:
    _sr = st.session_state.get("scan_results")
    if _sr is not None and not _sr.empty:
        _n_cand = (_sr["Score"].abs() >= 40).sum()
        if _n_cand > 0:
            _ai_progress = st.progress(0, text=f"KI-Bewertung: 0/{_n_cand} ...")
            def _ai_cb(done, total):
                _ai_progress.progress(done / total, text=f"KI-Bewertung: {done}/{total} ...")
            _sr = run_ai_for_top_signals(_sr, threshold=40.0, progress_callback=_ai_cb)
            _ai_progress.empty()
            st.session_state["scan_results"] = _sr
            st.toast(f"KI: {_n_cand} bewertet", icon="🤖")
        else:
            st.toast("Keine Signale mit Score >= 40", icon="⚠️")
    else:
        st.toast("Zuerst Scan starten", icon="⚠️")

# ---------------------------------------------------------------------------
# Style helpers (module level)
# ---------------------------------------------------------------------------

def _color_pnl(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return "color: #00e676"
        elif val < 0:
            return "color: #ff1744"
    return ""

def _color_delta(val):
    if isinstance(val, (int, float)):
        if val > 0:
            return "background-color: rgba(0,200,83,0.15); color: #00e676"
        elif val < 0:
            return "background-color: rgba(255,23,68,0.15); color: #ff1744"
    return "color: #666"

def _color_direction(val):
    if val == "LONG":
        return "background-color: rgba(0,200,83,0.2); color: #00e676; font-weight: bold"
    elif val == "SHORT":
        return "background-color: rgba(255,23,68,0.2); color: #ff1744; font-weight: bold"
    return ""

def _style_direction(val):
    if val == "LONG":
        return "background-color: rgba(0,200,83,0.2); color: #00e676; font-weight: bold"
    elif val == "SHORT":
        return "background-color: rgba(255,23,68,0.2); color: #ff1744; font-weight: bold"
    return "color: #9e9e9e"

def _style_score(val):
    if isinstance(val, (int, float)):
        if val > 30:
            return "color: #00e676; font-weight: bold"
        elif val < -30:
            return "color: #ff1744; font-weight: bold"
    return ""


# ---------------------------------------------------------------------------
# Dialog: Trade Details
# ---------------------------------------------------------------------------
@st.dialog("Trade Details", width="large")
def show_trade_dialog(trade_id: int):
    trade = get_trade(trade_id)
    if not trade:
        st.error("Trade nicht gefunden.")
        return
    _dir_emoji = "🟢" if trade["direction"] == "LONG" else "🔴"
    _is_closed = trade.get("status") == "CLOSED"

    _id_str = trade.get("isin") or trade.get("wkn") or ""
    _title_suffix = f" - {_id_str}" if _id_str else ""
    _title_c, _spacer_c, _toggle_c = st.columns([4, 2, 1])
    with _title_c:
        st.markdown(f"### {_dir_emoji} {trade['direction']}: {trade['name']} ({trade['ticker']}){_title_suffix}")
    with _toggle_c:
        _is_excluded = bool(trade.get("is_test", 0))
        _new_excluded = st.toggle(
            "Test Trade",
            value=_is_excluded,
            key=f"dlg_exclude_{trade['id']}",
            help="Test-Trade (vom Learning ausschließen)",
        )
        if _new_excluded != _is_excluded:
            update_trade(trade["id"], {"is_test": int(_new_excluded)})
            st.rerun()

    # --- Einheitliches Layout: Metrics → Chart → Tabelle → Aktionen ---
    render_position_metrics([trade], kp="dlg_")
    render_chart(trade["ticker"], trade["name"], trades=[trade], kp="dlg_")

    st.markdown("#### Trade Details")
    render_position_trades_table([trade], kp="dlg_")
    render_trade_detail_caption([trade])

    # --- KI-Bewertung ---
    _trade_ticker = trade["ticker"]
    st.divider()
    st.markdown("#### KI-Bewertung")

    from db import get_ai_assessments, save_ai_assessment
    from ai_opinion import get_ai_opinion, PROMPT_TEMPLATE

    _t_ai_hist = get_ai_assessments(_trade_ticker, limit=2)
    _t_ai_cur = _t_ai_hist[0] if _t_ai_hist else None

    if _t_ai_cur:
        _t_ai_prev = _t_ai_hist[1] if len(_t_ai_hist) > 1 else None

        if _t_ai_prev:
            st.markdown("##### Vorherige → Aktuelle Bewertung")
            _ta1, _ta2 = st.columns(2)
            for _col, _data, _label in [(_ta1, _t_ai_prev, "Vorherige"), (_ta2, _t_ai_cur, "Aktuelle")]:
                with _col:
                    st.markdown(f"**{_label}**")
                    st.caption(_data.get("created_at", ""))
                    _d = _data["direction"]
                    _e = "🟢" if _d == "LONG" else "🔴"
                    st.metric("Richtung", f"{_e} {_d}")
                    st.metric("Score", f"{_data.get('score', 0):+.1f}")
                    st.metric("Ziel", _fmt(_data.get("target"), _trade_ticker))
                    st.metric("Stop-Loss", _fmt(_data.get("stop_loss"), _trade_ticker))
            if _t_ai_prev["direction"] != _t_ai_cur["direction"]:
                st.warning(f"Richtungswechsel: {_t_ai_prev['direction']} -> {_t_ai_cur['direction']}")
        else:
            _d = _t_ai_cur["direction"]
            _e = "🟢" if _d == "LONG" else "🔴"
            _tm1, _tm2, _tm3, _tm4 = st.columns(4)
            _tm1.metric("Richtung", f"{_e} {_d}")
            _tm2.metric("Score", f"{_t_ai_cur.get('score', 0):+.1f}")
            _tm3.metric("Ziel", _fmt(_t_ai_cur.get("target"), _trade_ticker))
            _tm4.metric("Stop-Loss", _fmt(_t_ai_cur.get("stop_loss"), _trade_ticker))

        st.markdown("**Begründung:**")
        st.text_area("Begründung", _t_ai_cur.get("reasoning", "–"), height=200, disabled=True, key=f"ai_reason_trade_{trade['id']}", label_visibility="collapsed")
        with st.expander("Verwendeter Prompt"):
            st.code(_t_ai_cur.get("prompt", PROMPT_TEMPLATE), language="text")
    else:
        st.info("Noch keine KI-Bewertung vorhanden.")

    if st.button("KI-Analyse starten", type="primary", key=f"ai_trade_{trade['id']}"):
        with st.spinner("Claude analysiert ..."):
            from indicators import compute_all
            from fundamentals import get_fundamentals
            from news_sentiment import get_news_sentiment
            from markets import get_sector, get_index, SECTOR_MAP
            from sectors import compute_sector_scores

            from scanner import _download
            _t_raw = _download(_trade_ticker)

            if _t_raw is not None and len(_t_raw) > 30:
                _t_df = compute_all(_t_raw)
                _t_df.dropna(subset=["RSI", "ATR", "EMA50"], inplace=True)
                _t_fund = get_fundamentals(_trade_ticker)
                _t_ns, _t_nc, _ = get_news_sentiment(_trade_ticker)
                _t_sec = get_sector(_trade_ticker)
                _t_idx = get_index(_trade_ticker)
                _t_sec_score = 0.0
                _s = SECTOR_MAP.get(_trade_ticker)
                if _s and not _s.startswith("Index:"):
                    _ss = compute_sector_scores()
                    _t_sec_score = _ss.get(_s, {}).get("score", 0.0)

                _t_tech = {"direction": trade["direction"], "score": 0}
                _t_result = get_ai_opinion(
                    _trade_ticker, trade["name"], _t_df, _t_fund,
                    _t_ns, _t_nc, _t_sec, _t_sec_score, _t_idx, _t_tech,
                )
                if _t_result.get("error"):
                    st.error(f"Fehler: {_t_result['error']}")
                else:
                    save_ai_assessment({
                        "date": dt.date.today().isoformat(),
                        "ticker": _trade_ticker,
                        "direction": _t_result["direction"],
                        "score": _t_result["score"],
                        "entry": _t_result["entry"],
                        "target": _t_result["target"],
                        "stop_loss": _t_result["stop_loss"],
                        "risk_reward": _t_result["risk_reward"],
                        "reasoning": _t_result["reasoning"],
                        "prompt": _t_result["prompt"],
                        "model": _t_result["model"],
                    })
                    st.rerun()
            else:
                st.error("Kursdaten konnten nicht geladen werden.")

    st.divider()
    if _is_closed:
        _ct_edit, _ct_del = st.tabs(["Trade bearbeiten", "Trade löschen"])

        with _ct_edit:
            with st.form(f"dlg_edit_closed_{trade['id']}"):
                ce1, ce2 = st.columns(2)
                with ce1:
                    ce_entry_date = st.date_input(
                        "Einstiegsdatum",
                        value=dt.date.fromisoformat(trade["entry_date"]),
                        key=f"dlg_ce_edate_{trade['id']}",
                    )
                    ce_entry_price = st.number_input(
                        "Einstiegskurs (€)",
                        value=max(float(trade["entry_price"] or 0.01), 0.01),
                        min_value=0.01, step=0.01, format="%.2f",
                        key=f"dlg_ce_eprice_{trade['id']}",
                    )
                    ce_exit_date = st.date_input(
                        "Ausstiegsdatum",
                        value=dt.date.fromisoformat(trade["exit_date"]) if trade.get("exit_date") else dt.date.today(),
                        key=f"dlg_ce_xdate_{trade['id']}",
                    )
                    ce_exit_price = st.number_input(
                        "Ausstiegskurs (€)",
                        value=float(trade.get("exit_price") or 0),
                        min_value=0.0, step=0.01, format="%.2f",
                        key=f"dlg_ce_xprice_{trade['id']}",
                    )
                with ce2:
                    ce_size = st.number_input(
                        "Stückzahl", value=float(trade["size"] or 1),
                        min_value=0.01, step=1.0, format="%.2f",
                        key=f"dlg_ce_size_{trade['id']}",
                    )
                    ce_fees = st.number_input(
                        "Gebühren (€)", value=float(trade.get("fees") or 0),
                        min_value=0.0, step=0.01, format="%.2f",
                        key=f"dlg_ce_fees_{trade['id']}",
                    )
                    ce_wkn = st.text_input(
                        "WKN", value=trade.get("wkn") or "",
                        key=f"dlg_ce_wkn_{trade['id']}",
                    )
                    ce_ko = st.number_input(
                        "KO-Schwelle (€)", value=float(trade.get("ko_level") or 0),
                        min_value=0.0, step=0.01, format="%.2f",
                        key=f"dlg_ce_ko_{trade['id']}",
                    )
                    ce_bv = st.number_input(
                        "BV", value=float(trade.get("bv") or 0.1),
                        min_value=0.001, step=0.01, format="%.3f",
                        key=f"dlg_ce_bv_{trade['id']}",
                    )
                ce_notes = st.text_input(
                    "Notizen", value=trade.get("notes") or "",
                    key=f"dlg_ce_notes_{trade['id']}",
                )

                if st.form_submit_button("Speichern", type="primary", width="stretch"):
                    _ce_dir = trade["direction"]
                    if ce_entry_price > 0 and ce_exit_price > 0:
                        if _ce_dir == "LONG":
                            _ce_ret_pct = (ce_exit_price - ce_entry_price) / ce_entry_price * 100
                            _ce_ret_abs = (ce_exit_price - ce_entry_price) * ce_size - ce_fees
                        else:
                            _ce_ret_pct = (ce_entry_price - ce_exit_price) / ce_entry_price * 100
                            _ce_ret_abs = (ce_entry_price - ce_exit_price) * ce_size - ce_fees
                    else:
                        _ce_ret_pct = 0
                        _ce_ret_abs = 0
                    update_trade(trade["id"], {
                        "entry_date": ce_entry_date.isoformat(),
                        "entry_price": ce_entry_price,
                        "exit_date": ce_exit_date.isoformat(),
                        "exit_price": ce_exit_price,
                        "size": ce_size,
                        "fees": ce_fees,
                        "notes": ce_notes or None,
                        "wkn": ce_wkn or None,
                        "ko_level": ce_ko if ce_ko > 0 else None,
                        "bv": ce_bv if ce_ko > 0 else 1.0,
                        "return_pct": round(_ce_ret_pct, 2),
                        "return_abs": round(_ce_ret_abs, 2),
                    })
                    st.success(f"Trade #{trade['id']} aktualisiert.")
                    st.rerun()

        with _ct_del:
            st.warning(f"Trade #{trade['id']} **{trade['name']}** unwiderruflich löschen?")
            _cd_confirm = st.checkbox("Ja, ich bin sicher", key=f"dlg_cd_confirm_{trade['id']}")
            if st.button("Trade löschen", type="primary",
                         disabled=not _cd_confirm,
                         key=f"dlg_cd_btn_{trade['id']}"):
                delete_trade(trade["id"])
                st.success(f"Trade #{trade['id']} gelöscht.")
                st.rerun()
    else:
        render_trade_actions(trade, kp="dlg_")


# ---------------------------------------------------------------------------
# Dialog: Positions-Ansicht (gruppiert nach Ticker)
# ---------------------------------------------------------------------------
@st.dialog("Position Details", width="large")
def show_position_dialog(ticker: str):
    from db import get_open_trades_for_ticker
    trades = get_open_trades_for_ticker(ticker)
    if not trades:
        st.error("Keine offenen Trades für diesen Ticker.")
        return

    first = trades[0]
    _dir_emoji = "🟢" if first["direction"] == "LONG" else "🔴"
    _id_str = first.get("isin") or first.get("wkn") or ""
    _title_suffix = f" - {_id_str}" if _id_str else ""
    _title_c, _spacer_c, _toggle_c = st.columns([4, 2, 1])
    with _title_c:
        st.markdown(f"### {_dir_emoji} {first['direction']}: {first['name']} ({ticker}){_title_suffix}")
        st.caption(f"{len(trades)} Trades · Position gesamt")
    with _toggle_c:
        _is_excluded = all(bool(t.get("is_test", 0)) for t in trades)
        _new_excluded = st.toggle(
            "Test Trade",
            value=_is_excluded,
            key="pos_dlg_exclude",
            help="Test-Trade (alle Trades dieser Position vom Learning ausschließen)",
        )
        if _new_excluded != _is_excluded:
            for t in trades:
                update_trade(t["id"], {"is_test": int(_new_excluded)})
            st.rerun()

    render_position_metrics(trades, kp="pos_dlg_")
    render_chart(first["ticker"], first["name"], trades=trades, kp="pos_dlg_")

    st.markdown("#### Einzelne Trades")
    render_position_trades_table(trades, kp="pos_dlg_")
    render_trade_detail_caption(trades)

    # Aktionen (FIFO für Close, Auswahl für Edit/Delete)
    st.divider()
    render_trade_actions(trades[0], kp="pos_dlg_", all_trades=trades)


# ---------------------------------------------------------------------------
# Dialog: Signal Details
# ---------------------------------------------------------------------------
@st.dialog("Signal Details", width="large")
def show_signal_dialog(ticker: str):
    # Load latest signal for this ticker from DB (by date desc)
    _hist = get_signal_history(ticker, limit=1)
    selected_row = _hist[0] if _hist else None
    if not selected_row:
        st.error(f"Signal für {ticker} nicht gefunden.")
        return

    # Map to display column names
    _col_map = {
        "ticker": "Ticker", "name": "Name", "direction": "Richtung",
        "score": "Score", "entry": "Entry", "pattern": "Pattern",
        "target": "Ziel", "stop_loss": "Stop-Loss",
        "risk_reward": "R/R",
        "detail": "Detail",
        "rsi": "RSI", "adx": "ADX", "atr_pct": "ATR%",
        "analyst_rating": "Analyst", "analyst_target": "Kursziel",
    }
    sr = {}
    for k, v in selected_row.items():
        sr[_col_map.get(k, k)] = v

    name = sr["Name"]
    direction = sr["Richtung"]
    dir_color = {"LONG": "green", "SHORT": "red"}.get(direction, "gray")
    base_sig = selected_row

    # Check for active trade on this ticker
    _open_trades_map = get_open_trade_tickers()
    _active_trades_list = _open_trades_map.get(ticker, [])
    _active_trade = _active_trades_list[0] if _active_trades_list else None

    # ── Header (always visible) ──
    _pattern_name = sr.get("Pattern", "") or ""

    st.markdown(f"### {name} ({ticker})")
    _hc1, _hc2, _hc3, _hc4, _hc5, _hc6 = st.columns(6)
    _hc1.metric("Richtung", direction)
    _hc2.metric("Pattern", _pattern_name or "–")
    _hc3.metric("Score", f"{sr['Score']:.1f}")
    _hc4.metric("Einstieg", _fmt(sr['Entry'], ticker))
    _hc5.metric("Ziel", _fmt(sr['Ziel'], ticker) if pd.notna(sr.get('Ziel')) else "–")
    _hc6.metric("Stop-Loss", _fmt(sr['Stop-Loss'], ticker) if pd.notna(sr.get('Stop-Loss')) else "–")

    if _active_trade:
        _ko = _active_trade.get("ko_level")
        _bv = _active_trade.get("bv") or 1.0
        _prod_id = _active_trade.get("isin") or _active_trade.get("wkn") or ""
        _trade_dir = _active_trade["direction"]
        if _ko:
            _entry_p = stock_to_product(_active_trade['entry_price'], _ko, _trade_dir, _bv)
            _info = f"Aktiver Trade: {_trade_dir} seit {_de_date(_active_trade['entry_date'])} · Einstieg: {_entry_p:.2f} €"  # KO-Produkt immer in €
            if _prod_id:
                _info += f" · {_prod_id}"
        else:
            _info = (f"Aktiver Trade: {_trade_dir} seit {_de_date(_active_trade['entry_date'])} · "
                     f"Einstieg: {_fmt(_active_trade['entry_price'], ticker)}")
        st.success(_info)

    # ── Tabs ──
    _tab_names = ["Kurschart", "Score-Details", "Termine & News", "KI-Bewertung"]
    if not _active_trade:
        _tab_names.append("Trade eröffnen")

    _tabs = st.tabs(_tab_names)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1: Kurschart mit Handelsmarken
    # ══════════════════════════════════════════════════════════════════════
    with _tabs[0]:
        _sig_data = {
            "price": sr["Entry"],
            "target": sr.get("Ziel"),
            "stop_loss": sr.get("Stop-Loss"),
            "analyst_target": sr.get("Kursziel"),
            "date": selected_row.get("date", dt.date.today().isoformat()),
            "direction": direction,
        }
        _overlay_trades = _active_trades_list if _active_trades_list else None
        render_chart(ticker, name, signal=_sig_data, trades=_overlay_trades)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2: Score-Aufschlüsselung
    # ══════════════════════════════════════════════════════════════════════
    with _tabs[1]:
        # Detail-Text anzeigen (aus Scanner)
        _detail_text = sr.get("Detail", "")
        if _detail_text:
            st.markdown("#### Signal-Details")
            st.text(_detail_text)

        # Technische Kennzahlen
        st.markdown("#### Technische Kennzahlen")
        ki1, ki2, ki3, ki4 = st.columns(4)
        ki1.metric("RSI", f"{sr['RSI']:.1f}" if pd.notna(sr.get('RSI')) else "–")
        ki2.metric("ADX", f"{sr['ADX']:.1f}" if pd.notna(sr.get('ADX')) else "–")
        ki3.metric("ATR%", f"{sr['ATR%']:.2f}%" if pd.notna(sr.get('ATR%')) else "–")
        ki4.metric("Analyst-Rating", sr.get("Analyst") or "–")

        if pd.notna(sr.get("Kursziel")):
            upside = (sr["Kursziel"] / sr["Entry"] - 1) * 100
            st.caption(f"Analysten-Kursziel: {_fmt(sr['Kursziel'], ticker)} ({upside:+.1f}%)")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3: Termine & News
    # ══════════════════════════════════════════════════════════════════════
    with _tabs[2]:
        col_events, col_news = st.columns([1, 2])

        with col_events:
            st.markdown("#### Anstehende Termine")
            from fundamentals import get_upcoming_events
            events = get_upcoming_events(ticker)
            if events:
                for ev in events:
                    days_away = (dt.date.fromisoformat(ev["date"]) - dt.date.today()).days
                    if days_away < 0:
                        continue
                    urgency = "🔴" if days_away <= 7 else "🟡" if days_away <= 21 else "⚪"
                    detail = f" – {ev['detail']}" if ev.get("detail") else ""
                    st.markdown(
                        f"{urgency} **{ev['type']}**: {ev['date']} "
                        f"(in {days_away} Tagen){detail}"
                    )
            else:
                st.caption("Keine anstehenden Termine bekannt.")

        with col_news:
            st.markdown("#### Aktuelle Nachrichten")
            from news_sentiment import get_news_sentiment as _get_news
            _ns_score, _ns_count, _ns_articles = _get_news(ticker)

            if _ns_score > 0.5:
                st.success(f"Nachrichten-Stimmung: **positiv** ({_ns_score:+.1f})")
            elif _ns_score < -0.5:
                st.error(f"Nachrichten-Stimmung: **negativ** ({_ns_score:+.1f})")
            else:
                st.info(f"Nachrichten-Stimmung: **neutral** ({_ns_score:+.1f})")

            if _ns_articles:
                for art in _ns_articles[:8]:
                    s_emoji = {"positiv": "🟢", "negativ": "🔴", "neutral": "⚪"}.get(art["sentiment"], "⚪")
                    title = art["title"]
                    pub = art.get("publisher", "")
                    date = art.get("date", "")
                    link = art.get("link", "")
                    header = f"{s_emoji} [{title}]({link})" if link else f"{s_emoji} **{title}**"
                    meta = " · ".join(filter(None, [pub, date]))
                    st.markdown(header)
                    if meta:
                        st.caption(meta)
            else:
                st.caption("Keine aktuellen Nachrichten gefunden.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4: KI-Bewertung
    # ══════════════════════════════════════════════════════════════════════
    with _tabs[3]:
        from ai_opinion import get_ai_opinion, PROMPT_TEMPLATE
        from db import get_ai_assessments, save_ai_assessment

        _ai_history = get_ai_assessments(ticker, limit=2)
        _ai_current = _ai_history[0] if _ai_history else None

        if _ai_current:
            _ai_prev = _ai_history[1] if len(_ai_history) > 1 else None

            if _ai_prev:
                # Alt vs. Neu Vergleich
                st.markdown("##### Vergleich: Vorherige → Aktuelle Bewertung")
                _ka1, _ka2 = st.columns(2)
                with _ka1:
                    st.markdown("**Vorherige Bewertung**")
                    st.caption(_ai_prev.get("created_at", ""))
                    _prev_dir = _ai_prev["direction"]
                    _pc = "🟢" if _prev_dir == "LONG" else "🔴"
                    st.metric("Richtung", f"{_pc} {_prev_dir}")
                    _prev_score = _ai_prev.get('score', 0) or 0
                    st.metric("Score", f"{_prev_score:+.1f}")
                    st.metric("Einstieg", _fmt(_ai_prev.get("entry"), ticker))
                    st.metric("Ziel", _fmt(_ai_prev.get("target"), ticker))
                    st.metric("Stop-Loss", _fmt(_ai_prev.get("stop_loss"), ticker))
                    rr = _ai_prev.get("risk_reward")
                    st.metric("R/R", f"{rr:.1f}" if rr else "–")
                with _ka2:
                    st.markdown("**Aktuelle Bewertung**")
                    st.caption(_ai_current.get("created_at", ""))
                    _cur_dir = _ai_current["direction"]
                    _cc = "🟢" if _cur_dir == "LONG" else "🔴"
                    st.metric("Richtung", f"{_cc} {_cur_dir}")
                    _cur_score = _ai_current.get('score', 0) or 0
                    st.metric("Score", f"{_cur_score:+.1f}")
                    st.metric("Einstieg", _fmt(_ai_current.get("entry"), ticker))
                    st.metric("Ziel", _fmt(_ai_current.get("target"), ticker))
                    st.metric("Stop-Loss", _fmt(_ai_current.get("stop_loss"), ticker))
                    rr = _ai_current.get("risk_reward")
                    st.metric("R/R", f"{rr:.1f}" if rr else "–")

                # Richtungswechsel hervorheben
                if _ai_prev["direction"] != _ai_current["direction"]:
                    st.warning(f"⚠️ Richtungswechsel: {_ai_prev['direction']} → {_ai_current['direction']}")

                st.divider()
            else:
                # Nur aktuelle Bewertung
                st.markdown("##### KI-Bewertung")
                st.caption(_ai_current.get("created_at", ""))
                _kc1, _kc2, _kc3, _kc4, _kc5 = st.columns(5)
                _cur_dir = _ai_current["direction"]
                _cur_score = _ai_current.get('score', 0) or 0
                _kc1.metric("Richtung", _cur_dir)
                _kc2.metric("Score", f"{_cur_score:+.1f}")
                _kc3.metric("Einstieg", _fmt(_ai_current.get("entry"), ticker))
                _kc4.metric("Ziel", _fmt(_ai_current.get("target"), ticker))
                _kc5.metric("Stop-Loss", _fmt(_ai_current.get("stop_loss"), ticker))
                st.divider()

            # Begründung
            st.markdown("**Begründung:**")
            st.text_area("Begründung", _ai_current.get("reasoning", "–"), height=200, disabled=True, key="ai_reason_signal", label_visibility="collapsed")

            # Prompt anzeigen (einklappbar)
            with st.expander("Verwendeter Prompt"):
                st.code(_ai_current.get("prompt", PROMPT_TEMPLATE), language="text")

        else:
            st.info("Noch keine KI-Bewertung vorhanden.")

        # Button für neue Bewertung
        if st.button("KI-Analyse starten", type="primary", key="ai_assess_btn"):
            with st.spinner("Claude analysiert …"):
                # Daten laden
                from indicators import compute_all
                from fundamentals import get_fundamentals
                from news_sentiment import get_news_sentiment
                from market_context import get_market_context, for_ticker
                from markets import get_sector, get_index, SECTOR_MAP
                from sectors import compute_sector_scores
                from db import save_prices

                from scanner import _download
                _ai_raw = _download(ticker)

                if _ai_raw is not None and len(_ai_raw) > 30:
                    _ai_df = compute_all(_ai_raw)
                    _ai_df.dropna(subset=["RSI", "ATR", "EMA50"], inplace=True)
                    _ai_fund = get_fundamentals(ticker)
                    _ai_ns, _ai_nc, _ = get_news_sentiment(ticker)
                    _ai_sector = get_sector(ticker)
                    _ai_index = get_index(ticker)
                    _ai_sec_score = 0.0
                    _sec = SECTOR_MAP.get(ticker)
                    if _sec and not _sec.startswith("Index:"):
                        _ss = compute_sector_scores()
                        _ai_sec_score = _ss.get(_sec, {}).get("score", 0.0)

                    _ai_tech = {
                        "direction": sr.get("Richtung", "–"),
                        "score": sr.get("Score", 0),
                    }

                    _ai_result = get_ai_opinion(
                        ticker, name, _ai_df, _ai_fund,
                        _ai_ns, _ai_nc, _ai_sector, _ai_sec_score,
                        _ai_index, _ai_tech,
                    )

                    if _ai_result.get("error"):
                        st.error(f"Fehler: {_ai_result['error']}")
                    else:
                        save_ai_assessment({
                            "date": dt.date.today().isoformat(),
                            "ticker": ticker,
                            "direction": _ai_result["direction"],
                            "score": _ai_result["score"],
                            "entry": _ai_result["entry"],
                            "target": _ai_result["target"],
                            "stop_loss": _ai_result["stop_loss"],
                            "risk_reward": _ai_result["risk_reward"],
                            "reasoning": _ai_result["reasoning"],
                            "prompt": _ai_result["prompt"],
                            "model": _ai_result["model"],
                        })
                        st.rerun()
                else:
                    st.error("Kursdaten konnten nicht geladen werden.")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 5: Trade eröffnen (kein aktiver Trade)
    # ══════════════════════════════════════════════════════════════════════
    if not _active_trade:
        with _tabs[4]:
            from ko_search import search_ko, lookup_isin, evaluate_product
            from db import calc_position_size_risk

            _sig_price = base_sig["entry"]
            _sig_sl = base_sig.get("stop_loss")
            _sig_tgt = base_sig.get("target")
            _sig_dir = base_sig["direction"]

            if not _sig_sl or not _sig_tgt:
                st.warning("Signal hat kein Stop-Loss oder Target.")
            else:
                # ── Shared: Metriken + Formular ──
                def _render_metrics_and_form(selected, form_key):
                    """Metriken und Formular fuer ein ausgewaehltes Produkt."""
                    if not selected:
                        return

                    _ko_level = selected["ko_level"]
                    _bv = selected.get("bv", 1.0)
                    _bid = selected["bid"]
                    _ask = selected.get("ask") or _bid

                    # Metriken
                    _cash_info = get_free_cash()
                    _size = 0
                    if _ask and _ask > 0 and _ko_level:
                        _ps = calc_position_size_risk(
                            _cash_info["balance"], _ask,
                            _sig_price, _sig_sl, _ko_level, _sig_dir, _bv)
                        _m1, _m2, _m3, _m4, _m5 = st.columns(5)
                        _m1.metric("WKN", selected["wkn"])
                        _m2.metric("Ask (Kauf)", f"{_ask:.2f} EUR")
                        _m3.metric("Hebel", f"{selected['hebel']:.1f}x")
                        _m4.metric("Invest", _eur(_ps['invest_actual']))
                        _m5.metric("Risiko bei SL", _eur(_ps['loss_at_sl']))
                        _size = _ps["size"]
                    st.code(selected["isin"], language=None)

                    # Formular — Defaults setzen bevor das Form rendert
                    _kp_key = f"dlg_tf_kp_{form_key}"
                    _sz_key = f"dlg_tf_sz_{form_key}"
                    if _kp_key not in st.session_state:
                        st.session_state[_kp_key] = float(_ask) if _ask else 0.0
                    if _sz_key not in st.session_state:
                        st.session_state[_sz_key] = float(_size) if _size > 0 else 1.0

                    st.divider()
                    with st.form(f"dlg_sig_trade_{form_key}", clear_on_submit=True):
                        _fc1, _fc2, _fc3 = st.columns(3)
                        with _fc1:
                            trade_kaufpreis = st.number_input(
                                "Kaufpreis (Produkt)",
                                min_value=0.0, step=0.01, format="%.2f",
                                key=_kp_key,
                            )
                        with _fc2:
                            trade_stueck = st.number_input(
                                "Stück",
                                min_value=1.0, step=1.0, format="%.0f",
                                key=_sz_key,
                            )
                        with _fc3:
                            trade_entry_date = st.date_input(
                                "Kaufdatum", value=dt.date.today(),
                                key=f"dlg_tf_dt_{form_key}",
                            )
                        trade_is_test = st.checkbox("Test-Trade", key=f"dlg_tf_test_{form_key}")
                        submitted = st.form_submit_button(
                            "Trade eröffnen", type="primary", use_container_width=True)
                        if submitted and trade_kaufpreis > 0:
                            from ko_calc import product_to_stock
                            _actual_entry_stock = product_to_stock(
                                trade_kaufpreis, _ko_level, _sig_dir, _bv)
                            _trade_id = open_trade({
                                "signal_id": base_sig.get("id"),
                                "ticker": ticker, "name": name,
                                "direction": _sig_dir,
                                "entry_date": trade_entry_date.isoformat(),
                                "entry_price": _actual_entry_stock,
                                "size": int(trade_stueck),
                                "target": _sig_tgt, "stop_loss": _sig_sl,
                                "isin": selected["isin"],
                                "wkn": selected["wkn"],
                                "ko_level": _ko_level, "bv": _bv,
                                "emittent": selected["emittent"],
                                "entry_fees": 1.0,
                                "is_test": int(trade_is_test),
                                "current_price": _actual_entry_stock,
                                "product_bid": trade_kaufpreis,
                            })
                            if _trade_id:
                                st.success(f"Trade #{_trade_id} eröffnet!")
                                st.rerun()
                            else:
                                st.error("Fehler beim Eröffnen.")

                # ── Sub-Tabs: Automatisch / Manuell ──
                _sub_auto, _sub_manual = st.tabs(["Automatisch", "Manuell"])

                # ── TAB: Automatisch ──────────────────────
                with _sub_auto:
                    _slider_c, _btn_c = st.columns([3, 1])
                    with _slider_c:
                        _ko_buffer = st.slider(
                            "Mindestabstand KO unter SL (%)", 1.0, 10.0, 3.0, 0.5,
                            key="dlg_sig_ko_buffer",
                            help="Je weiter weg, desto sicherer (weniger Hebel). 3% = Standard.",
                        )
                    with _btn_c:
                        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                        _do_refresh = st.button("Neu suchen", key="dlg_sig_ko_refresh_auto",
                                                use_container_width=True)

                    _auto_key = f"ko_auto_{ticker}_{_sig_sl}_{_ko_buffer}"
                    if _auto_key not in st.session_state or _do_refresh:
                        with st.spinner("Suche KO-Zertifikate..."):
                            st.session_state[_auto_key] = search_ko(
                                ticker, _sig_price, _sig_sl, _sig_dir,
                                ko_buffer_pct=_ko_buffer)
                    _auto_results = st.session_state.get(_auto_key, [])

                    if _auto_results:
                        _ko_rows = []
                        for i, r in enumerate(_auto_results):
                            _ko_rows.append({
                                "#": i + 1,
                                "WKN": r["wkn"],
                                "Emittent": r["emittent"],
                                "KO": f"{r['ko_level']:.2f}",
                                "Hebel": f"{r['hebel']:.1f}x",
                                "Bid": f"{r['bid']:.2f}",
                                "Spread": f"{r['spread_pct']:.1f}%",
                                "KO-Abstand": f"{r['ko_abstand_sl_pct']:.1f}%",
                            })
                        st.dataframe(pd.DataFrame(_ko_rows), hide_index=True,
                                     width="stretch")

                        _sel_idx = st.selectbox(
                            "Zertifikat", range(len(_auto_results)),
                            format_func=lambda i: (
                                f"#{i+1} {_auto_results[i]['wkn']} "
                                f"({_auto_results[i]['emittent']}, "
                                f"Hebel {_auto_results[i]['hebel']:.1f}x, "
                                f"Spread {_auto_results[i]['spread_pct']:.1f}%)"),
                            key="dlg_sig_ko_select_auto",
                        )
                        _auto_selected = _auto_results[_sel_idx]
                        _render_metrics_and_form(_auto_selected, "auto")
                    else:
                        st.warning("Keine passenden KO-Zertifikate gefunden. "
                                   "Suche manuell auf Trade Republic und trage die ISIN im Tab 'Manuell' ein.")

                # ── TAB: Manuell (ISIN-Suche) ────────────
                with _sub_manual:
                    _ko_info = calc_ideal_ko(_sig_price, _sig_sl, _sig_dir)
                    if "error" not in _ko_info:
                        _typ = "Long" if _sig_dir == "LONG" else "Short"
                        st.info(
                            f"Typ: `{_typ}` · "
                            f"KO-Schwelle: `{_ko_info['ko_range_min']:.2f} – {_ko_info['ko_range_max']:.2f} EUR` · "
                            f"Idealer KO: `{_ko_info['ko_ideal']:.2f} EUR` · "
                            f"Hebel: `~{_ko_info['leverage']:.0f}x`"
                        )

                    _isin_state_key = f"ko_isin_{ticker}"

                    _ic1, _ic2 = st.columns([3, 1])
                    with _ic1:
                        _m_isin = st.text_input("ISIN", placeholder="DE000...",
                                                key="dlg_sig_m_isin")
                    with _ic2:
                        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                        _do_m = st.button("Suchen", key="dlg_sig_m_btn",
                                          use_container_width=True)
                    if _do_m and _m_isin and len(_m_isin) >= 12:
                        with st.spinner("Lade..."):
                            _mp = lookup_isin(_m_isin)
                        if _mp:
                            st.session_state[_isin_state_key] = {
                                "isin": _mp["isin"], "wkn": _mp.get("wkn", ""),
                                "emittent": _mp.get("emittent", ""),
                                "ko_level": _mp.get("ko_level", 0),
                                "bid": _mp.get("bid", 0), "ask": 0,
                                "hebel": _mp.get("leverage", 0),
                                "bv": _mp.get("bv", 1.0), "spread_pct": 0,
                                "ko_abstand_sl_pct": 0,
                                "underlying": _mp.get("underlying", ""),
                                "direction": _mp.get("direction", _sig_dir),
                            }
                        else:
                            st.error("Nicht gefunden.")

                    _manual_selected = st.session_state.get(_isin_state_key)
                    if _manual_selected:
                        _render_metrics_and_form(_manual_selected, "manual")



# =========================================================================
# PAGE: Empfehlungen (top)
# =========================================================================
def page_empfehlungen():

    # Only scan when explicitly requested; otherwise load from DB
    results_df = pd.DataFrame()
    active_trades_df = pd.DataFrame()
    market = {}
    _failed_tickers = []

    if st.session_state.get("run_scan"):
        # Flag SOFORT zurücksetzen damit ein Rerun keinen neuen Scan startet
        st.session_state["run_scan"] = False
        import scanner as _scanner_mod
        _scan_bar = st.progress(0, text="Scan: Download ...")
        _scanner_mod.progress_callback = lambda d, t, txt: _scan_bar.progress(d / t, text=f"Scan: {txt}")
        scan_result = run_scan()
        _scanner_mod.progress_callback = None
        _scan_bar.empty()
        # Scan speichert Signale in DB — results_df bleibt leer,
        # damit der DB-Pfad unten Tage+Rang berechnet.
        if isinstance(scan_result, tuple):
            _sr = scan_result
            if len(_sr) >= 4:
                _failed_tickers = _sr[3]
            if len(_sr) >= 2 and not _sr[1].empty:
                _grouped = _group_trade_rows(_sr[1].to_dict("records"))
                active_trades_df = pd.DataFrame(_grouped)
        if _failed_tickers:
            st.session_state["_failed_tickers"] = _failed_tickers
        else:
            st.session_state.pop("_failed_tickers", None)

    # Signale immer aus DB laden (nicht aus session_state cachen,
    # damit alle Sessions den gleichen Stand sehen)
    if results_df.empty:
        _open_tickers = {t["ticker"] for t in get_trades(status="OPEN")}

        # Alle Signale der letzten 10 Tage laden
        _all_signals = []
        _search_date = dt.date.today()
        for _d in range(10):
            _date_str = _search_date.isoformat()
            _day_signals = get_signals(date=_date_str, limit=500)
            _day_patterns = [s for s in _day_signals if s.get("pattern")]
            # Ticker mit offenen Trades ausfiltern
            _day_patterns = [s for s in _day_patterns if s["ticker"] not in _open_tickers]
            _all_signals.extend(_day_patterns)
            _search_date -= dt.timedelta(days=1)

        if not _all_signals:
            st.info("Keine Pattern-Signale in den letzten 10 Tagen gefunden. Scan starten!")
        if _all_signals:
            from db import get_signal_persistence
            _persistence = get_signal_persistence(lookback_days=10)

            results_df = pd.DataFrame(_all_signals).rename(columns={
                "ticker": "Ticker", "name": "Name", "direction": "Richtung",
                "score": "Score", "entry": "Entry", "pattern": "Pattern",
                "target": "Ziel", "stop_loss": "Stop-Loss",
                "risk_reward": "R/R", "date": "Datum",
                "detail": "Detail",
            })
            _db_col_map = {
                "rsi": "RSI", "adx": "ADX", "atr_pct": "ATR%",
                "analyst_rating": "Analyst",
                "analyst_target": "Kursziel",
            }
            for db_col, display_col in _db_col_map.items():
                if db_col in results_df.columns and display_col not in results_df.columns:
                    results_df[display_col] = results_df[db_col]
            for col in ["RSI", "ADX", "ATR%", "Analyst", "Kursziel"]:
                if col not in results_df.columns:
                    results_df[col] = None
            if "Ticker" in results_df.columns:
                if "Sparte" not in results_df.columns:
                    results_df["Sparte"] = results_df["Ticker"].map(get_sector)
                if "Index" not in results_df.columns:
                    results_df["Index"] = results_df["Ticker"].map(get_index)
                # Persistenz (Tage) und Rang berechnen
                results_df["Tage"] = results_df.apply(
                    lambda r: _persistence.get((r["Ticker"], r["Pattern"]), 1), axis=1)
                # Rang = Score + Persistenz × 0.2 (normiert auf Score-Skala)
                _score_max = results_df["Score"].max() or 1
                results_df["Rang"] = (
                    results_df["Score"] / _score_max * 0.5
                    + results_df["Tage"] * 0.2
                ).round(2)
            if "Entry" in results_df.columns and "Stop-Loss" in results_df.columns:
                results_df["SL-Dist%"] = ((results_df["Entry"] - results_df["Stop-Loss"]).abs()
                                           / results_df["Entry"] * 100).round(1)
            if "Datum" in results_df.columns:
                results_df["Datum"] = results_df["Datum"].apply(_de_date)
            # Pro Ticker nur das neueste Signal behalten (nach Datum, nicht Rang!)
            if "Ticker" in results_df.columns and "Datum" in results_df.columns:
                results_df["_date_sort"] = pd.to_datetime(
                    results_df["Datum"], format="%d.%m.%Y", errors="coerce")
                results_df = results_df.sort_values("_date_sort", ascending=False)
                results_df = results_df.drop_duplicates(subset=["Ticker", "Pattern"], keep="first")
                results_df = results_df.drop(columns=["_date_sort"])
            results_df = results_df.sort_values("Rang", ascending=False)
            st.session_state["scan_results"] = results_df

    # Datenstand immer in Sidebar (aus DB)
    def _fmt_db_ts(ts_str):
        if not ts_str:
            return "–"
        try:
            _d = dt.datetime.fromisoformat(ts_str)
            # DB speichert UTC (SQLite datetime('now')) → nach Lokalzeit
            if _d.tzinfo is None:
                import zoneinfo
                _d = _d.replace(tzinfo=dt.timezone.utc).astimezone(
                    zoneinfo.ZoneInfo("Europe/Berlin"))
            return _d.strftime("%d.%m.%Y %H:%M Uhr")
        except (ValueError, TypeError):
            return ts_str

    from db import _connect as _db_connect, get_setting
    try:
        _conn = _db_connect()
        _sig_ts = _conn.execute(
            "SELECT MAX(created_at) FROM signals").fetchone()[0]
        _conn.close()
        _trade_ts = get_setting("last_trade_refresh")
        from db import DB_PATH as _db_path
        _conn2 = _db_connect()
        _n_sigs = _conn2.execute("SELECT COUNT(*) FROM signals WHERE date = ?",
                                 (dt.date.today().isoformat(),)).fetchone()[0]
        _conn2.close()
        st.sidebar.caption("**Datenstand:**")
        st.sidebar.caption(f"Signale: {_fmt_db_ts(_sig_ts)}")
        if _trade_ts:
            st.sidebar.caption(f"Trades: {_fmt_db_ts(_trade_ts)}")
        st.sidebar.caption(f"DB: {_db_path} ({_n_sigs} heute)")
    except Exception:
        pass

    # Load open trades from DB (always, independent of scan)
    _db_open_trades = get_trades(status="OPEN")
    if active_trades_df.empty and _db_open_trades:
        _rows = [_build_trade_row(t) for t in _db_open_trades]
        _rows = _group_trade_rows(_rows)
        active_trades_df = pd.DataFrame(_rows)

    if results_df.empty:
        st.warning("Keine Daten vorhanden. Bitte zuerst einen Scan starten.")
        return

    # ── Konsens-Spalten aus DB ergänzen wenn sie fehlen ──
    if "Konsens" not in results_df.columns and not results_df.empty:
        from db import get_ai_assessments
        _konsens, _ki_dir, _ki_score = [], [], []
        _today = dt.date.today().isoformat()
        for _, _r in results_df.iterrows():
            _ai_list = get_ai_assessments(_r["Ticker"], limit=1)
            _ai = _ai_list[0] if _ai_list else None
            if _ai and _ai.get("date") == _today and _ai.get("direction"):
                _ki_dir.append(_ai["direction"])
                _ki_score.append(_ai.get("score"))
                if _ai["direction"] == _r["Richtung"]:
                    _konsens.append("\u2605\u2605\u2605")
                else:
                    _konsens.append("\u26a0")
            else:
                _konsens.append("\u2013")
                _ki_dir.append(None)
                _ki_score.append(None)
        results_df = results_df.copy()
        results_df["Konsens"] = _konsens
        results_df["KI"] = _ki_dir
        results_df["KI-Score"] = _ki_score
        st.session_state["scan_results"] = results_df

    # --- Market context banner (immer laden, 15 min Cache) ---
    try:
        from market_context import get_market_context
        _mkt = get_market_context()
        _emoji = {"bull": "🟢", "bear": "🔴", "neutral": "⚪"}
        _parts = []
        for _idx_name in ("DAX", "TecDAX", "MDAX"):
            _d = _mkt.get(_idx_name, {})
            _t = _d.get("trend", "neutral")
            _parts.append(f"{_idx_name} {_emoji.get(_t, '⚪')} {_t.upper()} ({_d.get('change_1m', 0):+.1f}% 1M)")
        _vix = _mkt.get("vix_level", "?")
        st.info(
            f"**Marktumfeld:** "
            + " · ".join(_parts)
            + f" · VIX: {_vix} ({_mkt.get('vix_regime', '?')})"
        )
    except Exception:
        pass

    # --- Pattern-System Markt-Warning (DAX SMA200 / EMA20) ---
    try:
        from backtest import _download as _bt_download
        _dax_warn = _bt_download("^GDAXI", days=300)
        if _dax_warn is not None and len(_dax_warn) >= 200:
            _dax_c = float(_dax_warn["Close"].iloc[-1])
            _dax_sma200 = float(_dax_warn["Close"].rolling(200).mean().iloc[-1])
            _dax_ema20 = float(_dax_warn["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            if _dax_c < _dax_sma200:
                st.error(
                    f"⚠️ **Achtung: DAX unter SMA200** ({_dax_c:,.0f} < {_dax_sma200:,.0f}) — "
                    f"Markt in Schwächephase. Neue Trades mit Vorsicht!"
                )
            elif _dax_c > _dax_ema20 and _dax_c < _dax_sma200 * 1.02:
                st.warning(
                    f"🔄 **Mögliche Erholung: DAX über EMA20** ({_dax_c:,.0f} > {_dax_ema20:,.0f}) — "
                    f"aber noch nahe SMA200 ({_dax_sma200:,.0f}). Vorsichtig einsteigen."
                )
    except Exception:
        pass

    # --- Summary metrics ---
    if not results_df.empty:

        # --- Sector tiles (colored HTML, visual overview) ---
        _sector_scores = compute_sector_scores()
        if _sector_scores:
            _idx_tiles = [(n, d) for n, d in _sector_scores.items()
                          if d.get("is_index") and "Dow" not in n and "Nasdaq" not in n]
            _sec_tiles = [(n, d) for n, d in _sector_scores.items() if not d.get("is_index")]
            _idx_tiles.sort(key=lambda x: x[1]["score"], reverse=True)
            _sec_tiles.sort(key=lambda x: x[1]["score"], reverse=True)

            def _tile_bg(score):
                if score > 50: return "#1b5e20"
                if score > 20: return "#2e7d32"
                if score > 5:  return "#388e3c"
                if score > -5: return "#455a64"
                if score > -20: return "#c62828"
                if score > -50: return "#b71c1c"
                return "#7f0000"

            def _render_tiles(items, max_cols=5):
                html = (
                    f'<div style="display:flex; flex-wrap:wrap; gap:6px;">'
                )
                for name, data in items:
                    _score = data["score"]
                    _bg = _tile_bg(_score)
                    _label = name.replace("Index: ", "")
                    _n = data["n_tickers"]
                    _tt = f"{_n} Titel · " if _n > 1 else ""
                    html += (
                        f'<div class="sector-tile" style="background:{_bg}; border-radius:8px; padding:8px 10px; '
                        f'text-align:center;flex:1 1 calc(20% - 6px); min-width:80px;" '
                        f'title="{_tt}5d: {data["avg_5d"]:+.1f}% · 14d: {data["avg_14d"]:+.1f}%">'
                        f'<div style="font-size:0.75em; color:#ccc;">{_label}</div>'
                        f'<div style="font-size:1.3em; font-weight:bold;">{data["arrow"]} {_score:+.0f}</div>'
                        f'</div>'
                    )
                html += '</div>'
                return html

            # Index row (5 indices)
            if _idx_tiles:
                st.markdown(_render_tiles(_idx_tiles), unsafe_allow_html=True)
                st.divider()

            # Sector rows (5 per row)
            if _sec_tiles:
                st.markdown(
                    f'<div style="margin-top:6px;">{_render_tiles(_sec_tiles)}</div>',
                    unsafe_allow_html=True,
                )

        st.divider()

        # --- Filter ---
        # Collect available sectors + indices for multiselect options
        _avail_sectors = sorted(results_df["Sparte"].dropna().unique()) if "Sparte" in results_df.columns else []
        _avail_indices = sorted(results_df["Index"].dropna().unique()) if "Index" in results_df.columns else []

        _age_options = {"Heute": 0, "1 Tag": 1, "2 Tage": 2, "3 Tage": 3, "5 Tage": 5, "Alle": 10}
        filter_col1, filter_col2 = st.columns(2)
        with filter_col1:
            _age_label = st.selectbox(
                "Signale seit", options=list(_age_options.keys()),
                key="flt_age",
            )
        with filter_col2:
            sector_filter = st.multiselect(
                "Sparte", _avail_sectors, default=[],
                placeholder="Alle Sparten",
                key="flt_sector",
            )

        _df = results_df.copy()

        # Alter-Filter
        _age_days = _age_options[_age_label]
        if _age_days < 10 and "Datum" in _df.columns:
            _df["_date_sort"] = pd.to_datetime(_df["Datum"], format="%d.%m.%Y", errors="coerce")
            _cutoff_dt = dt.datetime.combine(dt.date.today() - dt.timedelta(days=_age_days), dt.time())
            _mask = _df["_date_sort"] >= _cutoff_dt
        else:
            _mask = pd.Series(True, index=_df.index)

        if sector_filter and "Sparte" in _df.columns:
            _mask = _mask & _df["Sparte"].isin(sector_filter)
        filtered = _df[_mask].copy()

        # Nach Rang sortieren (beste zuerst) + Index reset für Klick-Handler
        if not filtered.empty and "Rang" in filtered.columns:
            filtered = filtered.sort_values("Rang", ascending=False).reset_index(drop=True)

        # --- Recommendations table ---
        if filtered.empty:
            st.info("Keine Ergebnisse für die gewählten Filter.")
        else:
            display_cols = [
                "Datum", "Name", "Index", "Pattern", "Richtung",
                "Entry", "Stop-Loss", "Ziel", "SL-Dist%",
                "Rang", "Tage", "ADX", "RSI",
            ]
            display = filtered[[c for c in display_cols if c in filtered.columns]].copy()

            selection = st.dataframe(
                display,
                width="stretch",
                hide_index=True,
                height=min(45 * len(display) + 50, 800),
                on_select="rerun",
                selection_mode="single-row",
                key="signals_table",
                column_config={
                    "Name": st.column_config.TextColumn("Name"),
                    "Index": st.column_config.TextColumn("Index"),
                    "Pattern": st.column_config.TextColumn("Pattern"),
                    "Richtung": st.column_config.TextColumn("Richtung"),
                    "Entry": st.column_config.NumberColumn("Entry", format="%.2f"),
                    "SL-Dist%": st.column_config.NumberColumn("SL-Dist%", format="%.1f%%"),
                    "Rang": st.column_config.NumberColumn("Rang", format="%.2f"),
                    "Tage": st.column_config.NumberColumn("Tage", format="%d"),
                    "ADX": st.column_config.NumberColumn("ADX", format="%.0f"),
                    "RSI": st.column_config.NumberColumn("RSI", format="%.0f"),
                },
            )

            # Signal dialog: nur bei NEUER Selection öffnen
            _cur_sel = selection.selection.rows[0] if (
                selection and selection.selection and selection.selection.rows) else None
            _last_sel = st.session_state.get("_sig_sel_handled")
            if _cur_sel is not None and _cur_sel != _last_sel:
                st.session_state["_sig_sel_handled"] = _cur_sel
                clicked_ticker = filtered.iloc[_cur_sel]["Ticker"]
                show_signal_dialog(clicked_ticker)
            elif _cur_sel is None:
                st.session_state.pop("_sig_sel_handled", None)

    # --- Fehlgeschlagene Ticker: Retry-Tabelle ---
    _stored_failed = st.session_state.get("_failed_tickers", [])
    if _stored_failed:
        st.divider()
        _all_names = {**INDICES, **DAX_COMPONENTS, **TECDAX_COMPONENTS,
                      **MDAX_COMPONENTS, **DOW_COMPONENTS, **NASDAQ_COMPONENTS}
        _fail_df = pd.DataFrame({
            "Auswahl": [True] * len(_stored_failed),
            "Ticker": _stored_failed,
            "Name": [_all_names.get(t, t) for t in _stored_failed],
        })
        st.warning(f"**{len(_stored_failed)} Ticker fehlgeschlagen** – Daten konnten nicht geladen werden.")
        _edited = st.data_editor(
            _fail_df,
            column_config={
                "Auswahl": st.column_config.CheckboxColumn("", default=True),
                "Ticker": st.column_config.TextColumn("Ticker", disabled=True),
                "Name": st.column_config.TextColumn("Name", disabled=True),
            },
            hide_index=True,
            width="stretch",
            key="fail_editor",
        )
        _fc1, _fc2 = st.columns([1, 4])
        with _fc1:
            if st.button("Erneut laden", type="primary", key="retry_failed_btn"):
                _selected = _edited[_edited["Auswahl"]]["Ticker"].tolist()
                if _selected:
                    with st.spinner(f"Lade {len(_selected)} Ticker erneut …"):
                        _new_sigs, _still_failed = retry_failed(_selected)
                    if _still_failed:
                        st.session_state["_failed_tickers"] = _still_failed
                    else:
                        st.session_state.pop("_failed_tickers", None)
                    _n_ok = len(_selected) - len(_still_failed)
                    if _n_ok:
                        st.success(f"{_n_ok} Ticker erfolgreich nachgeladen.")
                    if _still_failed:
                        st.warning(f"{len(_still_failed)} weiterhin fehlgeschlagen.")
                    st.rerun()
                else:
                    st.info("Keine Ticker ausgewählt.")
        with _fc2:
            _all_checked = _edited["Auswahl"].all()
            if not _all_checked:
                if st.button("Alle auswählen", type="tertiary", key="select_all_failed"):
                    st.session_state["fail_editor"] = {"edited_rows": {
                        str(i): {"Auswahl": True} for i in range(len(_stored_failed))
                    }}
                    st.rerun()

    # --- Einzelticker-Check ---
    st.divider()
    with st.expander("Ticker prüfen (Debug)"):
        _all_names = {**INDICES, **DAX_COMPONENTS, **TECDAX_COMPONENTS,
                      **MDAX_COMPONENTS}
        _chk_c1, _chk_c2 = st.columns([3, 1])
        with _chk_c1:
            _chk_ticker = st.selectbox(
                "Ticker", options=sorted(_all_names.keys()),
                format_func=lambda t: f"{t} — {_all_names[t]}",
                key="chk_ticker",
                index=None,
                placeholder="Ticker wählen...",
            )
        with _chk_c2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            _chk_go = st.button("Prüfen", key="chk_go", use_container_width=True)

        if _chk_go and _chk_ticker:
            with st.spinner(f"Lade {_chk_ticker}..."):
                from scanner import _download
                from indicators import compute_all
                from patterns import detect_patterns

                _chk_df = _download(_chk_ticker)
                if _chk_df is None:
                    st.error(f"Download fehlgeschlagen für {_chk_ticker}")
                else:
                    if isinstance(_chk_df.columns, pd.MultiIndex):
                        _chk_df.columns = [c[0] for c in _chk_df.columns]
                    _chk_df = compute_all(_chk_df)
                    _chk_patterns = detect_patterns(_chk_df)

                    _last = _chk_df.iloc[-1]
                    st.markdown(
                        f"**{_all_names.get(_chk_ticker, _chk_ticker)}** · "
                        f"Close: {_last['Close']:.2f} · "
                        f"EMA20: {_last['EMA20']:.2f} · "
                        f"EMA50: {_last['EMA50']:.2f} · "
                        f"ADX: {_last.get('ADX', 0):.1f} · "
                        f"RSI: {_last.get('RSI', 0):.1f} · "
                        f"Daten: {len(_chk_df)} Tage ({_chk_df.index[0].strftime('%d.%m.%Y')} – {_chk_df.index[-1].strftime('%d.%m.%Y')})"
                    )

                    if _chk_patterns:
                        _p_rows = []
                        for p in _chk_patterns:
                            _risk = abs(p["entry"] - p["stop_loss"])
                            _target = round(p["entry"] + 2.0 * _risk, 2) if p.get("direction", "LONG") == "LONG" else round(p["entry"] - 2.0 * _risk, 2)
                            _p_rows.append({
                                "Pattern": p["pattern"],
                                "Richtung": p.get("direction", "LONG"),
                                "Entry": p["entry"],
                                "Stop-Loss": p["stop_loss"],
                                "Target (2R)": _target,
                                "SL-Dist%": f"{_risk / p['entry'] * 100:.1f}%",
                                "Detail": p.get("detail", ""),
                            })
                        st.dataframe(pd.DataFrame(_p_rows), hide_index=True, width="stretch")
                    else:
                        st.info("Keine Patterns erkannt.")


# =========================================================================
# PAGE: Meine Trades
# =========================================================================
def page_trades():
    st.header("Meine Trades")

    # --- Cash-Übersicht ---
    _ci = get_free_cash()
    _ci_c1, _ci_c2, _ci_c3, _ci_c4, _ci_c5 = st.columns(5)
    _ci_c1.metric("Freies Cash", _eur(_ci['balance']))
    _ci_c2.metric("Gebunden", _eur(_ci['locked_cash']))
    _ci_c3.metric("Portfolio", _eur(_ci['portfolio_value']))
    _ci_c4.metric("Offene Pos.", f"{_ci['open_count']} / 5")
    _ci_c5.metric("2% Risiko", _eur(_ci['balance'] * 0.02))
    if _ci["balance"] <= 0 and _ci["open_count"] == 0:
        st.info("Noch keine Buchungen vorhanden. Gehe zu **Konto** um deine erste Einzahlung zu buchen.")
    st.divider()

    # --- Trade statistics ---
    tstats = get_trade_stats()
    if tstats["total_trades"] > 0:
        ts1, ts2, ts3, ts4, ts5, ts6 = st.columns(6)
        ts1.metric("Offen", tstats["open"])
        ts2.metric("Geschlossen", tstats["closed"])
        ts3.metric("Gewinner", tstats["winners"])
        ts4.metric("Verlierer", tstats["losers"])
        ts5.metric("Ø Rendite", f"{tstats['avg_return_pct']:+.1f}%")
        ts6.metric("Gesamt P/L", f"{tstats['total_return']:+.2f} €")
        st.divider()

    # --- Portfolio-Verlauf ---
    all_trades = [t for t in get_trades() if not t.get("is_test")]
    if all_trades:
        # Datum-Range ermitteln (frühester Einstieg bis heute)
        _earliest = min(t["entry_date"] for t in all_trades)
        _date_range = pd.date_range(start=_earliest, end=dt.date.today(), freq="B")  # Börsentage

        # Preise aller beteiligten Ticker laden
        _price_cache = {}
        _tickers_needed = set(t["ticker"] for t in all_trades)
        for _tk in _tickers_needed:
            rows = get_prices(_tk, start=_earliest)
            if rows:
                _pdf = pd.DataFrame(rows)
                _pdf["date"] = pd.to_datetime(_pdf["date"])
                _pdf = _pdf.set_index("date").sort_index()
                _c = "close" if "close" in _pdf.columns else "Close"
                _price_cache[_tk] = _pdf[_c]

        # Pro Tag: Investiert (Einstandswert) + Aktueller Wert berechnen
        _invested_series = []
        _value_series = []
        _pnl_series = []

        for _day in _date_range:
            _day_str = _day.strftime("%Y-%m-%d")
            _invested_day = 0.0
            _value_day = 0.0

            for t in all_trades:
                # War dieser Trade an dem Tag aktiv?
                if t["entry_date"] > _day_str:
                    continue
                if t.get("status") == "CLOSED" and t.get("exit_date") and t["exit_date"] < _day_str:
                    continue

                _size = t.get("size") or 1
                _ko = t.get("ko_level")
                _bv = t.get("bv") or 1.0
                _tdir = t["direction"]
                _entry_stock = t["entry_price"]
                _fees = (t.get("entry_fees") or 1.0) + 1.0

                # Aktueller Kurs des Underlyings an diesem Tag
                _prices = _price_cache.get(t["ticker"])
                if _prices is None or _prices.empty:
                    continue
                # Nächsten verfügbaren Kurs finden (forward-fill)
                _avail = _prices[_prices.index <= _day]
                if _avail.empty:
                    continue
                _cur_stock = float(_avail.iloc[-1])

                if _ko:
                    _entry_p = stock_to_product(_entry_stock, _ko, _tdir, _bv)
                    _cur_p = stock_to_product(_cur_stock, _ko, _tdir, _bv)
                else:
                    _entry_p = _entry_stock
                    _cur_p = _cur_stock

                _invested_day += _entry_p * _size
                _value_day += _cur_p * _size - _fees

            _invested_series.append(_invested_day)
            _value_series.append(_value_day)
            _pnl_series.append(_value_day - _invested_day)

        _port_df = pd.DataFrame({
            "Datum": _date_range,
            "Investiert": _invested_series,
            "Wert": _value_series,
            "P/L": _pnl_series,
        })
        # Nur Tage mit aktiven Positionen anzeigen
        _port_df = _port_df[_port_df["Investiert"] > 0]

        if not _port_df.empty:
            _pfig = go.Figure()
            _pfig.add_trace(go.Scatter(
                x=_port_df["Datum"], y=_port_df["Investiert"],
                mode="lines", name="Investiert",
                line=dict(color="#78909c", width=1, dash="dash"),
            ))
            _pfig.add_trace(go.Scatter(
                x=_port_df["Datum"], y=_port_df["Wert"],
                mode="lines", name="Wert",
                line=dict(color="#42a5f5", width=2),
                fill="tonexty",
                fillcolor="rgba(66,165,245,0.1)",
            ))
            # Nulllinie für P/L
            _pfig.add_hline(y=0, line_dash="dot", line_color="#ffffff", line_width=0.5, opacity=0.3,
                            layer="below")
            _pfig.update_layout(
                height=300, template="plotly_dark",
                xaxis_rangeslider_visible=False,
                yaxis_title="€",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
                margin=dict(l=60, r=30, t=10, b=40),
            )
            st.plotly_chart(_pfig, use_container_width=True)

    # --- Open trades ---
    st.divider()
    st.subheader("Offene Trades")
    open_trades = get_trades(status="OPEN")

    if open_trades:
        _ot_rows = [_build_trade_row(t) for t in open_trades]
        _ot_rows = _group_trade_rows(_ot_rows)
        _ot_df = pd.DataFrame(_ot_rows)

        # Invest/Wert für Einzel-Trades berechnen
        if "Invest" not in _ot_df.columns:
            _ot_df["Invest"] = 0.0
        if "Wert" not in _ot_df.columns:
            _ot_df["Wert"] = 0.0
        _mask_single = _ot_df["_n_trades"] == 1
        _ot_df.loc[_mask_single, "Invest"] = (
            _ot_df.loc[_mask_single, "Einstieg"] * _ot_df.loc[_mask_single, "Stk."]
        ).round(2)
        _ot_df.loc[_mask_single, "Wert"] = (
            _ot_df.loc[_mask_single, "Aktuell"] * _ot_df.loc[_mask_single, "Stk."]
        ).round(2)

        _display_cols = [
            "trade_id", "_n_trades", "Name", "Richtung", "Stk.",
            "Einstieg", "Aktuell", "Stop", "Ziel",
            "Invest", "Wert", "P/L %", "P/L €",
            "Profit R", "Tage",
        ]

        _col_config = {
            "trade_id": None,
            "_n_trades": None,
            "Ticker": None,
            "Name": st.column_config.TextColumn("Name", help="Name des Basiswerts"),
            "Stk.": st.column_config.NumberColumn("Stk.", format="%.0f"),
            "Einstieg": st.column_config.NumberColumn("Einstieg", format="%.2f €"),
            "Aktuell": st.column_config.NumberColumn("Aktuell", format="%.2f €"),
            "Stop": st.column_config.NumberColumn("Stop", format="%.2f €"),
            "Ziel": st.column_config.NumberColumn("Ziel", format="%.2f €"),
            "Invest": st.column_config.NumberColumn("Invest", format="%.2f €"),
            "Wert": st.column_config.NumberColumn("Wert", format="%.2f €"),
            "P/L %": st.column_config.NumberColumn("P/L %", format="%+.1f%%"),
            "P/L €": st.column_config.NumberColumn("P/L €", format="%+.2f €"),
            "Profit R": st.column_config.NumberColumn(
                "Profit R", format="%+.2f R",
                help="-1R = Stop-Loss, 0R = Entry, 2R = Target"),
            "Tage": st.column_config.NumberColumn("Tage", format="%d", help="Tage seit Eröffnung"),
        }

        def _render_trade_table(df, title, emoji, key_suffix):
            """Rendere eine Trade-Tabelle mit Titel und Klick-Handler."""
            if df.empty:
                return
            st.markdown(f"#### {emoji} {title} ({len(df)})")
            _display = df[[c for c in _display_cols if c in df.columns]].copy()
            _styled = _style_trades_df(_display)
            _sel = st.dataframe(
                _styled, hide_index=True, width="stretch",
                height=min(45 * len(_display) + 50, 300),
                on_select="rerun", selection_mode="single-row",
                column_config=_col_config,
                key=f"trades_{key_suffix}",
            )
            if _sel and _sel.selection and _sel.selection.rows:
                _idx = _sel.selection.rows[0]
                _tid = int(df.iloc[_idx]["trade_id"])
                _tname = df.iloc[_idx]["Name"]
                _tticker = df.iloc[_idx]["Ticker"]
                _n = int(df.iloc[_idx].get("_n_trades", 1))
                _prev = st.session_state.get(f"_prev_{key_suffix}")
                if _prev != _tid:
                    st.session_state[f"_prev_{key_suffix}"] = _tid
                    if _n > 1:
                        show_position_dialog(_tticker)
                    else:
                        show_trade_dialog(_tid)
                else:
                    st.session_state[f"_prev_{key_suffix}"] = None
                    st.rerun()

        # Aufteilen nach Status
        _has_r = "Profit R" in _ot_df.columns and _ot_df["Profit R"].notna().any()
        if _has_r:
            _critical = _ot_df[_ot_df["Profit R"] <= -0.8].copy()
            _target = _ot_df[_ot_df["Profit R"] >= 1.5].copy()
            _running = _ot_df[
                (_ot_df["Profit R"] > -0.8) & (_ot_df["Profit R"] < 1.5)
            ].copy()
            # Trades ohne Profit R (kein SL) → running
            _no_r = _ot_df[_ot_df["Profit R"].isna()].copy()
            _running = pd.concat([_running, _no_r], ignore_index=True)
        else:
            _critical = pd.DataFrame()
            _target = pd.DataFrame()
            _running = _ot_df.copy()

        _render_trade_table(_critical, "Kritisch — Handlungsbedarf", "🔴", "critical")
        _render_trade_table(_target, "Nahe Target / Target erreicht", "🎯", "target")
        _render_trade_table(_running, "Laufende Trades", "🟢", "running")
    else:
        st.caption("Keine offenen Trades.")

    # --- Trade Analytics Dashboard ---
    st.divider()
    st.subheader("Trade-Analyse")

    from trade_analytics import get_trade_analytics
    _analytics = get_trade_analytics()

    if _analytics["has_data"]:
        # Basis-Metriken
        _am1, _am2, _am3, _am4, _am5, _am6 = st.columns(6)
        _am1.metric("Trades", f"{_analytics['n_trades']}")
        _am2.metric("Win-Rate", f"{_analytics['win_rate']:.0f}%")
        _am3.metric("Ø Gewinn", f"{_analytics['avg_win_pct']:+.1f}%")
        _am4.metric("Ø Verlust", f"-{_analytics['avg_loss_pct']:.1f}%")
        _am5.metric("Erwartungswert", f"{_analytics['expectancy']:+.2f}%")
        _am6.metric("Max Verlustserie", f"{_analytics['max_consecutive_losses']}")

        # Detail-Tabs
        _tab_sl, _tab_target, _tab_pattern, _tab_timing = st.tabs([
            "SL-Analyse", "Target-Analyse", "Pattern/Sektor", "Timing"
        ])

        with _tab_sl:
            _sc1, _sc2, _sc3 = st.columns(3)
            _sc1.metric("SL eingehalten", f"{_analytics['sl_held']}")
            _sc2.metric("SL durchbrochen", f"{_analytics['sl_breached']}",
                        delta=f"von {_analytics['n_losers']} Verlierern",
                        delta_color="off")
            _sc3.metric("SL zu eng?",
                        f"{_analytics['sl_too_tight']} Trades",
                        delta="erholten sich nach SL >5%" if _analytics['sl_too_tight'] > 0 else "keine Daten",
                        delta_color="off")

            if _analytics.get("avg_min_r") is not None:
                st.caption(f"Ø tiefster Punkt im Trade: **{_analytics['avg_min_r']:+.2f}R** "
                           f"(bei -1.0R wäre der SL exakt getroffen)")

        with _tab_target:
            _tc1, _tc2, _tc3 = st.columns(3)
            _tc1.metric("Zu früh geschlossen",
                        f"{_analytics['closed_too_early']} Trades",
                        delta=f"von {_analytics['n_winners']} Gewinnern",
                        delta_color="off")
            if _analytics.get("avg_post_exit_gain") is not None:
                _tc2.metric("Ø Kurs nach Exit",
                            f"{_analytics['avg_post_exit_gain']:+.1f}%",
                            delta="10 Tage nach Verkauf",
                            delta_color="off")
            if _analytics.get("avg_max_r") is not None:
                _tc3.metric("Ø höchster Punkt",
                            f"{_analytics['avg_max_r']:+.2f}R",
                            delta="während des Trades",
                            delta_color="off")

            if _analytics.get("avg_max_r") is not None and _analytics["avg_max_r"] > 2.0:
                st.info(f"💡 Deine Trades erreichten im Schnitt **{_analytics['avg_max_r']:.1f}R** — "
                        f"das Target von 2.0R könnte zu niedrig sein.")
            elif _analytics.get("avg_post_exit_gain") is not None and _analytics["avg_post_exit_gain"] > 3:
                st.info(f"💡 Nach deinen Verkäufen lief der Kurs im Schnitt noch **{_analytics['avg_post_exit_gain']:.1f}%** weiter. "
                        f"Schließt du zu früh?")

        with _tab_pattern:
            if _analytics["pattern_stats"]:
                st.markdown("**Pattern-Performance (Live):**")
                _pat_rows = []
                for pat, stats in sorted(_analytics["pattern_stats"].items(),
                                         key=lambda x: x[1]["wr"], reverse=True):
                    _pat_rows.append({
                        "Pattern": pat,
                        "Trades": stats["n"],
                        "WR": f"{stats['wr']:.0f}%",
                        "Ø Return": f"{stats['avg_return']:+.1f}%",
                    })
                st.dataframe(pd.DataFrame(_pat_rows), hide_index=True, width="stretch")

            if _analytics["sector_stats"]:
                st.markdown("**Sektor-Performance (Live):**")
                _sec_rows = []
                for sec, stats in sorted(_analytics["sector_stats"].items(),
                                         key=lambda x: x[1]["avg_return"], reverse=True):
                    if stats["n"] >= 2:
                        _sec_rows.append({
                            "Sektor": sec,
                            "Trades": stats["n"],
                            "WR": f"{stats['wr']:.0f}%",
                            "Ø Return": f"{stats['avg_return']:+.1f}%",
                        })
                if _sec_rows:
                    st.dataframe(pd.DataFrame(_sec_rows), hide_index=True, width="stretch")

        with _tab_timing:
            _tt1, _tt2, _tt3 = st.columns(3)
            if _analytics.get("avg_days_win") is not None:
                _tt1.metric("Ø Haltedauer Gewinner", f"{_analytics['avg_days_win']:.0f} Tage")
            if _analytics.get("avg_days_loss") is not None:
                _tt2.metric("Ø Haltedauer Verlierer", f"{_analytics['avg_days_loss']:.0f} Tage")
            _tt3.metric("Max Gewinnserie", f"{_analytics['max_consecutive_wins']}")

            if (_analytics.get("avg_days_loss") and _analytics.get("avg_days_win")
                    and _analytics["avg_days_loss"] > _analytics["avg_days_win"] * 2):
                st.warning(f"⚠️ Du hältst Verlierer ({_analytics['avg_days_loss']:.0f}d) deutlich länger "
                           f"als Gewinner ({_analytics['avg_days_win']:.0f}d). "
                           f"Klassischer Fehler — Verlierer schneller schließen!")
    else:
        st.caption("Noch keine geschlossenen Trades für Analyse.")

    # --- Closed trades ---
    st.divider()
    st.subheader("Geschlossene Trades")
    closed_trades = get_trades(status="CLOSED")

    if closed_trades:
        from ko_calc import stock_to_product as _s2p
        _ct_rows = []
        for ct in closed_trades:
            ko = ct.get("ko_level")
            bv = ct.get("bv") or 1.0
            _dir = ct["direction"]
            _size = ct.get("size") or 1
            _sl = ct.get("stop_loss")

            if ko:
                entry_prod = _s2p(ct["entry_price"], ko, _dir, bv)
                exit_prod = _s2p(ct["exit_price"], ko, _dir, bv) if ct.get("exit_price") else 0
                sl_prod = _s2p(_sl, ko, _dir, bv) if _sl else None
            else:
                entry_prod = ct["entry_price"]
                exit_prod = ct.get("exit_price") or 0
                sl_prod = _sl

            _invest = entry_prod * _size
            _wert = exit_prod * _size
            _fees = ct.get("fees") or 0
            _pnl_abs = _wert - _invest - _fees
            _pnl_pct = _pnl_abs / _invest * 100 if _invest > 0 else 0

            # Profit R
            _pr = None
            if sl_prod and entry_prod > 0:
                _risk = abs(entry_prod - sl_prod)
                _profit = exit_prod - entry_prod
                _pr = round(_profit / _risk, 2) if _risk > 0 else None

            # Haltedauer
            _tage = None
            if ct.get("entry_date") and ct.get("exit_date"):
                try:
                    _tage = (dt.date.fromisoformat(ct["exit_date"]) - dt.date.fromisoformat(ct["entry_date"])).days
                except (ValueError, TypeError):
                    pass

            _ct_rows.append({
                "trade_id": ct["id"],
                "_exit_sort": ct.get("exit_date") or "",
                "Verkauf": _de_date(ct.get("exit_date")),
                "Name": ct["name"],
                "Richtung": ct["direction"],
                "Produkt": ct.get("isin") or ct.get("wkn") or "",
                "Kauf": _de_date(ct["entry_date"]),
                "Einstieg": round(entry_prod, 2),
                "Ausstieg": round(exit_prod, 2),
                "Invest": round(_invest, 2),
                "Wert": round(_wert, 2),
                "P/L %": round(_pnl_pct, 1),
                "P/L €": round(_pnl_abs, 2),
                "Profit R": _pr,
                "Tage": _tage,
                "Stück": _size,
            })

        _ct_df = pd.DataFrame(_ct_rows)
        _ct_df = _ct_df.sort_values("_exit_sort", ascending=False).reset_index(drop=True)

        _ct_display_cols = [
            "trade_id", "_exit_sort",
            "Verkauf", "Name", "Richtung", "Produkt", "Kauf",
            "Stück", "Einstieg", "Ausstieg", "Invest", "Wert",
            "P/L %", "P/L €", "Profit R", "Tage",
        ]
        _ct_display = _ct_df[[c for c in _ct_display_cols if c in _ct_df.columns]]

        _ct_styled = _style_trades_df(_ct_display)
        _ct_sel = st.dataframe(
            _ct_styled,
            hide_index=True,
            width="stretch",
            height=min(45 * len(_ct_df) + 50, 400),
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "trade_id": None,
                "_exit_sort": None,
                "Stück": st.column_config.NumberColumn("Stück", format="%d"),
                "Einstieg": st.column_config.NumberColumn("Einstieg", format="%.2f €"),
                "Ausstieg": st.column_config.NumberColumn("Ausstieg", format="%.2f €"),
                "Invest": st.column_config.NumberColumn("Invest", format="%.2f €"),
                "Wert": st.column_config.NumberColumn("Wert", format="%.2f €"),
                "P/L %": st.column_config.NumberColumn("P/L %", format="%+.1f%%"),
                "P/L €": st.column_config.NumberColumn("P/L €", format="%+.2f €"),
                "Profit R": st.column_config.NumberColumn("Profit R", format="%+.2f R"),
                "Tage": st.column_config.NumberColumn("Tage", format="%d"),
            },
            key="trades_closed_table",
        )

        if _ct_sel and _ct_sel.selection and _ct_sel.selection.rows:
            _ct_idx = _ct_sel.selection.rows[0]
            _ct_trade_id = int(_ct_df.iloc[_ct_idx]["trade_id"])
            _prev_ct = st.session_state.get("_prev_closed_trade_sel")
            if _prev_ct != _ct_trade_id:
                st.session_state["_prev_closed_trade_sel"] = _ct_trade_id
                show_trade_dialog(_ct_trade_id)
            else:
                st.session_state["_prev_closed_trade_sel"] = None
                st.rerun()
    else:
        st.caption("Noch keine geschlossenen Trades.")


# =========================================================================
# PAGE: Konto (Buchungen)
# =========================================================================
def page_konto():
    st.header("Konto & Buchungen")

    # --- Übersicht ---
    _ki = get_free_cash()
    _kc1, _kc2, _kc3 = st.columns(3)
    _kc1.metric("Freies Cash", _eur(_ki['balance']))
    _kc2.metric("In Positionen", _eur(_ki['locked_cash']))
    _kc3.metric("Portfolio-Wert", _eur(_ki['portfolio_value']))
    st.divider()

    # --- Neue Buchung (alles eine Zeile) ---
    st.subheader("Neue Buchung")
    _buch_c1, _buch_c2, _buch_c3, _buch_c4, _buch_c5 = st.columns([1, 1, 2, 1, 1])
    with _buch_c1:
        _buch_type = st.selectbox(
            "Typ", ["Einzahlung", "Auszahlung", "Korrektur"],
            key="konto_buch_type",
        )
    with _buch_c2:
        if _buch_type == "Korrektur":
            _buch_amount = st.number_input(
                "Betrag (€)", step=50.0, value=0.0,
                format="%.2f", key="konto_buch_amount_corr",
                help="Positiv = Guthaben erhöhen, Negativ = Guthaben senken",
            )
        else:
            _buch_amount = st.number_input(
                "Betrag (€)", min_value=0.01, step=50.0, value=100.0,
                format="%.2f", key="konto_buch_amount",
            )
    with _buch_c3:
        _buch_desc = st.text_input(
            "Beschreibung (optional)", key="konto_buch_desc",
            placeholder="z.B. Überweisung von Girokonto",
        )
    with _buch_c4:
        _buch_date = st.date_input("Datum", value=dt.date.today(), key="konto_buch_date")
    with _buch_c5:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        _buch_save = st.button("Buchen", type="primary", key="konto_save_btn", use_container_width=True)

    if _buch_save:
        _type_map = {
            "Einzahlung": ("deposit", abs(_buch_amount)),
            "Auszahlung": ("withdrawal", -abs(_buch_amount)),
            "Korrektur": ("correction", _buch_amount),
        }
        _db_type, _db_amount = _type_map[_buch_type]
        _desc = _buch_desc or _buch_type
        add_ledger_entry(
            date=_buch_date.isoformat(),
            entry_type=_db_type,
            amount=_db_amount,
            description=_desc,
        )
        st.success(f"{_buch_type} über {_eur(abs(_db_amount))} gebucht.")
        st.rerun()

    if _buch_type == "Korrektur":
        st.caption("Korrekturen: Positiver Betrag erhöht das Guthaben, negativer senkt es.")

    # --- Buchungshistorie ---
    st.divider()
    st.subheader("Buchungshistorie")

    _entries = get_ledger_entries(limit=200)
    if _entries:
        _type_labels = {
            "deposit": "Einzahlung",
            "withdrawal": "Auszahlung",
            "trade_buy": "Kauf",
            "trade_sell": "Verkauf",
            "correction": "Korrektur",
        }

        _entry_rows = []
        _running = get_cash_balance()
        for e in _entries:
            _entry_rows.append({
                "id": e["id"],
                "Datum": e["date"],
                "Typ": _type_labels.get(e["type"], e["type"]),
                "Beschreibung": e.get("description") or "",
                "Betrag": e["amount"],
                "Saldo": _running,
                "_type": e["type"],
                "_deletable": e["type"] in ("deposit", "withdrawal", "correction"),
            })
            _running -= e["amount"]

        _hist_df = pd.DataFrame(_entry_rows)

        def _style_ledger(row):
            styles = [""] * len(row)
            betrag_idx = row.index.get_loc("Betrag")
            if row["_positive"]:
                styles[betrag_idx] = "color: #4caf50; font-weight: bold"
            else:
                styles[betrag_idx] = "color: #ef5350; font-weight: bold"
            return styles

        _show_df = _hist_df[["Datum", "Typ", "Beschreibung", "Betrag", "Saldo"]].copy()
        _show_df["Datum"] = _hist_df["Datum"].apply(_de_date)
        _show_df["_positive"] = _hist_df["Betrag"] > 0
        _show_df["Betrag"] = _hist_df["Betrag"].apply(lambda x: _eur(x, sign=True))
        _show_df["Saldo"] = _hist_df["Saldo"].apply(_eur)
        _show_df["_id"] = _hist_df["id"]
        _show_df["_deletable"] = _hist_df["_deletable"]

        _sel = st.dataframe(
            _show_df.style.apply(_style_ledger, axis=1),
            hide_index=True,
            width="stretch",
            height=min(45 * len(_show_df) + 50, 400),
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "_id": None,
                "_deletable": None,
                "_positive": None,
            },
            key="ledger_table",
        )

        # Bei Klick auf Zeile → Lösch-Dialog öffnen (nur für manuelle Buchungen)
        if _sel and _sel.selection and _sel.selection.rows:
            _row_idx = _sel.selection.rows[0]
            _clicked_id = int(_show_df.iloc[_row_idx]["_id"])
            _clicked_deletable = _show_df.iloc[_row_idx]["_deletable"]
            _clicked_label = (
                f'{_show_df.iloc[_row_idx]["Datum"]} | '
                f'{_show_df.iloc[_row_idx]["Typ"]} | '
                f'{_show_df.iloc[_row_idx]["Betrag"]} | '
                f'{_show_df.iloc[_row_idx]["Beschreibung"]}'
            )
            _prev = st.session_state.get("_prev_ledger_sel")
            if _prev != _clicked_id:
                st.session_state["_prev_ledger_sel"] = _clicked_id
                if _clicked_deletable:
                    st.session_state["_del_ledger_id"] = _clicked_id
                    st.session_state["_del_ledger_label"] = _clicked_label
                else:
                    st.toast("Trade-Buchungen können nicht manuell gelöscht werden.")
                    st.rerun()
            else:
                st.session_state["_prev_ledger_sel"] = None
                st.rerun()

        if "_del_ledger_id" in st.session_state:
            @st.dialog("Buchung löschen")
            def _confirm_delete():
                st.markdown(f"**{st.session_state['_del_ledger_label']}**")
                st.warning("Diese Buchung wirklich löschen?")
                _cc1, _cc2 = st.columns(2)
                if _cc1.button("Ja, löschen", type="primary", use_container_width=True):
                    delete_ledger_entry(st.session_state["_del_ledger_id"])
                    del st.session_state["_del_ledger_id"]
                    del st.session_state["_del_ledger_label"]
                    st.session_state.pop("_prev_ledger_sel", None)
                    st.rerun()
                if _cc2.button("Abbrechen", use_container_width=True):
                    del st.session_state["_del_ledger_id"]
                    del st.session_state["_del_ledger_label"]
                    st.session_state.pop("_prev_ledger_sel", None)
                    st.rerun()
            _confirm_delete()
    else:
        st.info("Noch keine Buchungen. Buche deine erste Einzahlung oben.")

    # --- Saldo-Verlauf Chart ---
    if _entries and len(_entries) > 1:
        st.divider()
        st.subheader("Saldo-Verlauf")
        # Chronologisch sortieren für Chart
        _chrono = sorted(_entries, key=lambda x: (x["date"], x["id"]))
        _saldo = 0.0
        _chart_data = []
        for e in _chrono:
            _saldo += e["amount"]
            _chart_data.append({
                "Datum": pd.Timestamp(e["date"]),
                "Saldo": _saldo,
            })
        _chart_df = pd.DataFrame(_chart_data)
        st.line_chart(_chart_df, x="Datum", y="Saldo", use_container_width=True)

    # --- DB Export ---
    st.divider()
    with st.expander("Datenbank-Export"):
        from db import DB_PATH
        if DB_PATH.exists():
            _db_bytes = DB_PATH.read_bytes()
            _db_size = len(_db_bytes) / 1024
            st.caption(f"DB: {DB_PATH.name} ({_db_size:,.0f} KB)")
            st.download_button(
                "DB herunterladen",
                data=_db_bytes,
                file_name=f"trading_{dt.date.today().isoformat()}.db",
                mime="application/x-sqlite3",
                use_container_width=True,
            )


# =========================================================================
# PAGE: Signal-Historie
# =========================================================================
def page_historie():
    st.header("Signal-Historie")

    hist_col1, hist_col2 = st.columns(2)
    with hist_col1:
        hist_date = st.date_input("Datum", value=dt.date.today())
    with hist_col2:
        hist_dir = st.selectbox("Richtung", ["Alle", "LONG", "SHORT", "NEUTRAL"])

    direction_filter = None if hist_dir == "Alle" else hist_dir
    signals = get_signals(date=hist_date.isoformat(), direction=direction_filter)

    if signals:
        sig_df = pd.DataFrame(signals)
        display_cols = ["date", "ticker", "name", "direction", "pattern", "score",
                        "entry", "target", "stop_loss", "risk_reward"]
        available = [c for c in display_cols if c in sig_df.columns]
        st.dataframe(
            sig_df[available].rename(columns={
                "date": "Datum", "ticker": "Ticker", "name": "Name",
                "direction": "Richtung", "pattern": "Pattern", "score": "Score",
                "entry": "Entry", "target": "Ziel", "stop_loss": "S/L",
                "risk_reward": "R/R",
            }),
            width="stretch", hide_index=True,
        )
    else:
        st.info(f"Keine Signale für {hist_date.strftime('%d.%m.%Y')} gefunden.")




# ═══════════════════════════════════════════════════════════════════════════
# PAGE: Wiki
# ═══════════════════════════════════════════════════════════════════════════
def page_wiki():
    import glob as _glob
    from pathlib import Path as _Path

    _wiki_dir = _Path(__file__).parent / "wiki"
    _wiki_dir.mkdir(exist_ok=True)

    st.header("Wiki")
    st.caption("Wissenssammlung zum Trading-System — Regeln, Prozesse, Erkenntnisse")

    # Alle .md Dateien laden
    _wiki_files = sorted(_wiki_dir.glob("*.md"))

    if not _wiki_files:
        st.info("Noch keine Wiki-Seiten vorhanden.")
    else:
        # Seitenauswahl
        _wiki_titles = []
        for _wf in _wiki_files:
            _first_line = _wf.read_text(encoding="utf-8").split("\n")[0]
            _title = _first_line.lstrip("# ").strip() if _first_line.startswith("#") else _wf.stem
            _wiki_titles.append(_title)

        _wiki_tab_objects = st.tabs(_wiki_titles)

        for _wi, (_wf, _wtab) in enumerate(zip(_wiki_files, _wiki_tab_objects)):
            with _wtab:
                _wiki_content = _wf.read_text(encoding="utf-8")

                # Edit-Modus
                _edit_key = f"wiki_edit_{_wf.stem}"
                if _edit_key not in st.session_state:
                    st.session_state[_edit_key] = False

                _wcol1, _wcol2 = st.columns([8, 2])
                with _wcol2:
                    if st.session_state[_edit_key]:
                        if st.button("Speichern", key=f"wiki_save_{_wi}", type="primary"):
                            _new_content = st.session_state.get(f"wiki_editor_{_wi}", _wiki_content)
                            _wf.write_text(_new_content, encoding="utf-8")
                            st.session_state[_edit_key] = False
                            st.rerun()
                        if st.button("Abbrechen", key=f"wiki_cancel_{_wi}"):
                            st.session_state[_edit_key] = False
                            st.rerun()
                    else:
                        if st.button("Bearbeiten", key=f"wiki_editbtn_{_wi}"):
                            st.session_state[_edit_key] = True
                            st.rerun()

                if st.session_state[_edit_key]:
                    st.text_area(
                        "Markdown bearbeiten",
                        value=_wiki_content,
                        height=500,
                        key=f"wiki_editor_{_wi}",
                        label_visibility="collapsed",
                    )
                else:
                    st.markdown(_wiki_content)

    # Neue Seite erstellen
    st.divider()
    with st.expander("Neue Wiki-Seite erstellen"):
        _new_wiki_name = st.text_input("Dateiname (ohne .md)", key="wiki_new_name",
                                        placeholder="z.B. 05_mein_thema")
        _new_wiki_title = st.text_input("Seitentitel", key="wiki_new_title",
                                         placeholder="z.B. Mein neues Thema")
        if st.button("Seite erstellen", key="wiki_create_btn"):
            if _new_wiki_name and _new_wiki_title:
                _new_path = _wiki_dir / f"{_new_wiki_name}.md"
                if _new_path.exists():
                    st.error("Datei existiert bereits!")
                else:
                    _new_path.write_text(f"# {_new_wiki_title}\n\nInhalt hier einfügen...\n",
                                          encoding="utf-8")
                    st.success(f"Seite '{_new_wiki_title}' erstellt!")
                    st.rerun()
            else:
                st.warning("Bitte Dateiname und Titel angeben.")

# =========================================================================
# Navigation Setup + Run
# =========================================================================
pg = st.navigation([
    st.Page(page_empfehlungen, title="Empfehlungen", default=True),
    st.Page(page_trades, title="Trades"),
    st.Page(page_konto, title="Konto"),
    st.Page(page_historie, title="Historie"),
    st.Page(page_wiki, title="Wiki"),
])
pg.run()