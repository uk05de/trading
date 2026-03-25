"""
components.py – Shared rendering functions for trade detail views.

Used by both the Meine-Trades page (expanders) and the Trade-Detail dialog.
"""

from __future__ import annotations

import datetime as dt
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from db import (get_prices_with_backfill, close_trade, update_trade, delete_trade,
                get_open_trades_for_ticker, partial_close_trade,
                open_trade, get_signals)
from ko_calc import stock_to_product, product_to_stock, calc_leverage


def _unit(ticker: str) -> str:
    if ticker.startswith("^"):
        return "Pkt."
    if ticker.endswith(".DE"):
        return "€"
    return "$"


def _fmt(value: float, ticker: str) -> str:
    return f"{value:.2f} {_unit(ticker)}"


def _de_date(iso: str) -> str:
    """ISO-Datum (YYYY-MM-DD) ins deutsche Format (DD.MM.YYYY) umwandeln."""
    try:
        return dt.date.fromisoformat(iso).strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso or "–"


# ---------------------------------------------------------------------------
# render_trade_detail_caption – details below the trades table
# ---------------------------------------------------------------------------
def render_trade_detail_caption(trades: list[dict]):
    """Show Basiswert/KO/Ziel/Stop captions below the trades table."""
    # For grouped positions: only show per-trade notes
    if len(trades) != 1:
        for t in trades:
            if t.get("notes"):
                st.caption(f"#{t['id']} Notizen: {t['notes']}")
        return

    t = trades[0]
    _closed = t.get("status") == "CLOSED"
    _ko = t.get("ko_level")
    _bv = t.get("bv") or 1.0
    _d = t["direction"]
    _bu = _unit(t["ticker"])

    parts = []

    if _ko:
        parts.append(f"Basiswert: Einstieg {t['entry_price']:.2f} {_bu}")
        if _closed and t.get("exit_price"):
            parts.append(f"Ausstieg {t['exit_price']:.2f} {_bu}")
        elif t.get("current_price"):
            parts.append(f"Aktuell {t['current_price']:.2f} {_bu}")
        parts.append(f"KO {_ko:.2f} {_bu}")
        parts.append(f"BV {_bv}")
        if not _closed and t.get("current_price"):
            _hebel = calc_leverage(t["current_price"], _ko, _d)
            if _hebel and _hebel != float("inf"):
                parts.append(f"Hebel {_hebel:.1f}x")
            if _d == "LONG":
                _ko_dist = (t["current_price"] - _ko) / t["current_price"] * 100
            else:
                _ko_dist = (_ko - t["current_price"]) / t["current_price"] * 100
            parts.append(f"KO-Abstand {_ko_dist:.1f}%")

    if not _closed:
        _tgt = t.get("rec_target") or t.get("target")
        _stp = t.get("rec_stop") or t.get("stop_loss")
        if _ko:
            if _tgt:
                _tgt_p = stock_to_product(_tgt, _ko, _d, _bv)
                parts.append(f"Ziel {_tgt_p:.2f} € ({_tgt:.2f} {_bu})")
            if _stp:
                _stp_p = stock_to_product(_stp, _ko, _d, _bv)
                parts.append(f"Stop {_stp_p:.2f} € ({_stp:.2f} {_bu})")
        else:
            if _tgt:
                parts.append(f"Ziel {_tgt:.2f} {_bu}")
            if _stp:
                parts.append(f"Stop {_stp:.2f} {_bu}")

    if parts:
        st.caption(" · ".join(parts))

    if _closed:
        st.caption(f"{_de_date(t['entry_date'])} → {_de_date(t.get('exit_date'))}")

    if t.get("notes"):
        st.caption(f"Notizen: {t['notes']}")


# ---------------------------------------------------------------------------
# render_chart – unified candlestick chart
# ---------------------------------------------------------------------------
def render_chart(ticker: str, name: str, *,
                 trades: list[dict] | None = None,
                 signal: dict | None = None,
                 ai_assessment: dict | None = None,
                 kp: str = ""):
    """
    Unified candlestick chart for all contexts.

    Modes (determined by which params are provided):
      - signal only:           Empfehlungs-Chart (Signal-Dialog)
      - trades only (1):       Einzel-Trade-Chart
      - trades only (N):       Positions-Chart
      - signal + trades:       Signal-Chart mit aktivem Trade-Overlay
    """
    _trades = trades or []
    _has_signal = signal is not None
    _is_position = len(_trades) > 1
    _is_single = len(_trades) == 1 and not _has_signal
    _is_overlay = _has_signal and bool(_trades)
    _first = _trades[0] if _trades else None
    _has_ko = bool(_first.get("ko_level")) if _first else False

    # ── Zeitraum bestimmen ──
    if _has_signal:
        _sig_date = signal.get("date", dt.date.today().isoformat())
        _start = (dt.date.fromisoformat(_sig_date) - dt.timedelta(days=180)).isoformat()
        _end = None
    elif _trades:
        _earliest = min(t["entry_date"] for t in _trades)
        _start = (dt.date.fromisoformat(_earliest) - dt.timedelta(days=90)).isoformat()
        _is_closed = _is_single and _trades[0].get("status") == "CLOSED" and _trades[0].get("exit_date")
        _end = (dt.date.fromisoformat(_trades[0]["exit_date"]) + dt.timedelta(days=14)).isoformat() if _is_closed else None
    else:
        return

    # ── Daten laden ──
    if _end:
        _rows = get_prices_with_backfill(ticker, start=_start, end=_end)
    else:
        _rows = get_prices_with_backfill(ticker, start=_start)
    if not _rows:
        st.caption("Keine Chartdaten verfügbar.")
        return

    _df = pd.DataFrame(_rows)
    _df["date"] = pd.to_datetime(_df["date"])
    _df = _df.set_index("date").sort_index()

    _o = "open" if "open" in _df.columns else "Open"
    _h = "high" if "high" in _df.columns else "High"
    _l = "low" if "low" in _df.columns else "Low"
    _c = "close" if "close" in _df.columns else "Close"

    # ── Subplots: Preis oben (80%), Volumen unten (20%) ──
    from plotly.subplots import make_subplots
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.8, 0.2], vertical_spacing=0.02,
    )
    fig.add_trace(go.Candlestick(
        x=_df.index,
        open=_df[_o], high=_df[_h], low=_df[_l], close=_df[_c],
        name=name, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ), row=1, col=1)

    _ref_entry = None  # Referenz-Einstieg für hrects
    _x0 = _df.index[0]   # linker Rand für Linien
    _x1 = _df.index[-1]  # rechter Rand für Linien

    # y-Range für sichtbaren Bereich (Kursdaten + 5% Puffer)
    _price_low = _df[_l].min()
    _price_high = _df[_h].max()
    _price_range = _price_high - _price_low
    _y_min = _price_low - _price_range * 0.05
    _y_max = _price_high + _price_range * 0.05

    def _hline(y, label, color, group, dash="solid", width=2,
               side="left", show_legend=False, visible=True):
        """Horizontale Linie als togglebarer Scatter-Trace.
        Linien außerhalb des sichtbaren Bereichs → Trace am Rand mit Pfeil-Label."""
        _vis = True if visible else "legendonly"
        if y > _y_max:
            # Oberhalb: Trace am oberen Rand (damit Legende funktioniert)
            fig.add_trace(go.Scatter(
                x=[_x0, _x1], y=[_y_max, _y_max],
                mode="lines+text",
                text=["", f"▲ {label}"],
                textposition="middle right",
                textfont=dict(color=color, size=10),
                line=dict(color=color, width=width, dash=dash),
                legendgroup=group, name=group,
                showlegend=show_legend, visible=_vis,
            ), row=1, col=1)
            return
        if y < _y_min:
            # Unterhalb: Trace am unteren Rand
            fig.add_trace(go.Scatter(
                x=[_x0, _x1], y=[_y_min, _y_min],
                mode="lines+text",
                text=["", f"▼ {label}"],
                textposition="middle right",
                textfont=dict(color=color, size=10),
                line=dict(color=color, width=width, dash=dash),
                legendgroup=group, name=group,
                showlegend=show_legend, visible=_vis,
            ), row=1, col=1)
            return
        _txt_l = ["", label]
        _pos_l = "middle right"
        fig.add_trace(go.Scatter(
            x=[_x0, _x1], y=[y, y],
            mode="lines+text",
            text=_txt_l, textposition=_pos_l,
            textfont=dict(color=color, size=10),
            line=dict(color=color, width=width, dash=dash),
            legendgroup=group,
            name=group,
            showlegend=show_legend,
            visible=_vis,
        ), row=1, col=1)

    # ══════════════════════════════════════════════════════════════════════
    # SIGNAL-Linien – Gruppe "Technisch" (Labels links)
    # ══════════════════════════════════════════════════════════════════════
    if _has_signal:
        _sig_price = signal["price"]
        _sig_dir = signal.get("direction", "LONG")
        _sig_tgt = signal.get("target")
        _sig_stp = signal.get("stop_loss")
        _sig_analyst = signal.get("analyst_target")
        _ref_entry = _sig_price

        # Signal-Datum (bleibt als vline – nicht togglebar)
        fig.add_vline(x=pd.Timestamp(_sig_date), line_dash="dash",
                      line_color="#ffffff", line_width=1, opacity=0.4)
        fig.add_annotation(x=pd.Timestamp(_sig_date), y=1.02, yref="paper",
                           text=f"Signal {_sig_date}", showarrow=False,
                           font=dict(color="#aaaaaa", size=10))

        # Einstieg (erste Linie der Gruppe → showlegend=True)
        _hline(_sig_price, f"Einstieg: {_fmt(_sig_price, ticker)}",
               "#2979ff", "Technisch", show_legend=True)

        # Ziel
        if _sig_tgt and pd.notna(_sig_tgt):
            _hline(_sig_tgt, f"Ziel: {_fmt(_sig_tgt, ticker)}",
                   "#00e676", "Technisch", dash="dash")
            fig.add_hrect(y0=min(_sig_price, _sig_tgt), y1=max(_sig_price, _sig_tgt),
                          fillcolor="rgba(0,200,83,0.07)", line_width=0)

        # Stop-Loss
        if _sig_stp and pd.notna(_sig_stp):
            _hline(_sig_stp, f"Stop: {_fmt(_sig_stp, ticker)}",
                   "#ff1744", "Technisch", dash="dot")
            fig.add_hrect(y0=min(_sig_price, _sig_stp), y1=max(_sig_price, _sig_stp),
                          fillcolor="rgba(255,23,68,0.07)", line_width=0)

        # Analysten-Kursziel (eigenes Legendenelement, immer sichtbar)
        if _sig_analyst and pd.notna(_sig_analyst):
            _hline(_sig_analyst, f"Analysten: {_fmt(_sig_analyst, ticker)}",
                   "#ff9100", "Analysten", dash="dashdot", width=1, show_legend=True)

    # ══════════════════════════════════════════════════════════════════════
    # KI-Linien – Gruppe "KI" (Labels rechts, default AUS)
    # ══════════════════════════════════════════════════════════════════════
    _ai = ai_assessment
    if not _ai and _has_signal:
        # Aus DB laden falls nicht übergeben
        try:
            from db import get_ai_assessments
            _ai_list = get_ai_assessments(ticker, limit=1)
            if _ai_list:
                _ai = _ai_list[0]
        except Exception:
            pass

    if _ai and _ai.get("entry"):
        _ai_entry = _ai["entry"]
        _ai_tgt = _ai.get("target")
        _ai_stp = _ai.get("stop_loss")
        _ai_dir = _ai.get("direction", "")

        _hline(_ai_entry, f"KI Einstieg: {_fmt(_ai_entry, ticker)}",
               "#ce93d8", "KI", show_legend=True, visible=False, side="right")

        if _ai_tgt and pd.notna(_ai_tgt):
            _hline(_ai_tgt, f"KI Ziel: {_fmt(_ai_tgt, ticker)}",
                   "#81c784", "KI", dash="dash", visible=False, side="right")

        if _ai_stp and pd.notna(_ai_stp):
            _hline(_ai_stp, f"KI Stop: {_fmt(_ai_stp, ticker)}",
                   "#e57373", "KI", dash="dot", visible=False, side="right")

    # ══════════════════════════════════════════════════════════════════════
    # TRADE-Linien (magenta / bunt bei Position)
    # ══════════════════════════════════════════════════════════════════════
    if _trades:
        _chart_entries = []  # (price, size) für Ø-Berechnung

        for i, t in enumerate(_trades):
            _color = _ENTRY_COLORS[i % len(_ENTRY_COLORS)] if _is_position else "#e040fb"
            _entry_dt = pd.Timestamp(t["entry_date"])

            _ep = t["entry_price"]
            _chart_entries.append((_ep, t.get("size") or 1))

            # Vertikale Linie (Kaufdatum)
            fig.add_vline(x=_entry_dt, line_dash="solid", line_color=_color,
                          line_width=1, opacity=0.7)
            _y_ann = 1.02 - i * 0.04 if _is_position else 1.02
            fig.add_annotation(x=_entry_dt, y=_y_ann, yref="paper",
                               text=f"Kauf {_de_date(t['entry_date'])}",
                               showarrow=False, font=dict(color=_color, size=9))

            # Horizontale Linie (Einstiegskurs)
            if _is_position:
                _sz = t.get("size") or 1
                _lbl = f"#{t['id']}: {_sz:.0f} Stk. @ {_fmt(_ep, ticker)}"
                _ann = "top right" if i == 0 else "top left"
            elif _is_overlay:
                _lbl = f"Mein Einstieg: {_fmt(_ep, ticker)}"
                _ann = "top right"
            else:
                _lbl = f"Einstieg: {_fmt(_ep, ticker)}"
                _ann = "top right"
            fig.add_hline(y=_ep, line_dash="solid", line_color=_color,
                          line_width=2, opacity=0.7 if _is_position else 1.0,
                          annotation_text=_lbl, annotation_position=_ann,
                          annotation_font_color=_color)

        # Ø-Einstiegslinie (nur Position)
        _total_sz = sum(s for _, s in _chart_entries)
        _total_cost = sum(p * s for p, s in _chart_entries)
        _avg_entry = _total_cost / _total_sz if _total_sz else 0
        if _is_position:
            fig.add_hline(y=_avg_entry, line_dash="dash",
                          line_color="#ffffff", line_width=2, opacity=0.6,
                          annotation_text=f"Ø Einstieg: {_fmt(_avg_entry, ticker)}",
                          annotation_position="bottom right",
                          annotation_font_color="#ffffff")

        # Referenz für hrects setzen
        if _is_position:
            _ref_entry = _avg_entry
        elif not _is_overlay:
            _ref_entry = _chart_entries[0][0]

        # Ausstieg (nur geschlossener Einzel-Trade)
        _is_closed = _is_single and _trades[0].get("status") == "CLOSED" and _trades[0].get("exit_date")
        if _is_closed:
            _exit_date = _trades[0]["exit_date"]
            _exit_dt = pd.Timestamp(_exit_date)
            _entry_dt_0 = pd.Timestamp(_trades[0]["entry_date"])
            fig.add_vline(x=_exit_dt, line_dash="solid", line_color="#ffd740",
                          line_width=1, opacity=0.7)
            fig.add_annotation(x=_exit_dt, y=1.02, yref="paper",
                               text=f"Verkauf {_de_date(_exit_date)}",
                               showarrow=False, font=dict(color="#ffd740", size=9))
            fig.add_vrect(x0=_entry_dt_0, x1=_exit_dt,
                          fillcolor="rgba(224,64,251,0.06)", line_width=0)

            if _trades[0].get("exit_price"):
                _chart_exit = _trades[0]["exit_price"]
                _ec = "#76ff03" if (_trades[0].get("return_pct") or 0) >= 0 else "#ff1744"
                fig.add_hline(y=_chart_exit, line_dash="solid", line_color=_ec,
                              line_width=2,
                              annotation_text=f"Verkauf: {_fmt(_chart_exit, ticker)}",
                              annotation_position="bottom right",
                              annotation_font_color=_ec)

        # Ziel / Stop / Original (nicht im Overlay-Modus)
        if not _is_overlay:
            _latest = _trades[-1]
            _rec_tgt = _latest.get("rec_target")
            _orig_tgt = _latest.get("target")
            _show_tgt = _rec_tgt or _orig_tgt
            if _show_tgt and _ref_entry:
                _tl = "Empf. Ziel" if _rec_tgt and _is_single else "Ziel"
                fig.add_hline(y=_show_tgt, line_dash="dash", line_color="#76ff03",
                              line_width=2,
                              annotation_text=f"{_tl}: {_fmt(_show_tgt, ticker)}",
                              annotation_position="bottom right",
                              annotation_font_color="#76ff03")
                fig.add_hrect(y0=min(_ref_entry, _show_tgt),
                              y1=max(_ref_entry, _show_tgt),
                              fillcolor="rgba(0,200,83,0.07)", line_width=0)

            _rec_stp = _latest.get("rec_stop")
            _orig_stp = _latest.get("stop_loss")
            _show_stp = _rec_stp or _orig_stp
            if _show_stp and _ref_entry:
                _sl = "Empf. Stop" if _rec_stp and _is_single else "Stop"
                fig.add_hline(y=_show_stp, line_dash="dot", line_color="#ff6e40",
                              line_width=2,
                              annotation_text=f"{_sl}: {_fmt(_show_stp, ticker)}",
                              annotation_position="bottom right",
                              annotation_font_color="#ff6e40")
                fig.add_hrect(y0=min(_ref_entry, _show_stp),
                              y1=max(_ref_entry, _show_stp),
                              fillcolor="rgba(255,23,68,0.07)", line_width=0)

            # Original vs. Empfehlung (nur Einzel-Trade)
            if _is_single:
                if _orig_tgt and _rec_tgt and abs(_orig_tgt - _rec_tgt) > 0.5:
                    fig.add_hline(y=_orig_tgt, line_dash="dashdot",
                                  line_color="#76ff03", line_width=1, opacity=0.4,
                                  annotation_text=f"Orig. Ziel: {_fmt(_orig_tgt, ticker)}",
                                  annotation_position="top left",
                                  annotation_font_color="#76ff03")
                if _orig_stp and _rec_stp and abs(_orig_stp - _rec_stp) > 0.5:
                    fig.add_hline(y=_orig_stp, line_dash="dashdot",
                                  line_color="#ff6e40", line_width=1, opacity=0.4,
                                  annotation_text=f"Orig. Stop: {_fmt(_orig_stp, ticker)}",
                                  annotation_position="bottom left",
                                  annotation_font_color="#ff6e40")
        else:
            # Overlay-Modus: Empf. Ziel/Stop vom Trade
            _ot = _trades[0]
            rec_tgt = _ot.get("rec_target")
            if rec_tgt:
                fig.add_hline(y=rec_tgt, line_dash="dash", line_color="#76ff03",
                              line_width=2,
                              annotation_text=f"Empf. Ziel: {_fmt(rec_tgt, ticker)}",
                              annotation_position="bottom right",
                              annotation_font_color="#76ff03")
            rec_stp = _ot.get("rec_stop")
            if rec_stp:
                fig.add_hline(y=rec_stp, line_dash="dot", line_color="#ff6e40",
                              line_width=2,
                              annotation_text=f"Empf. Stop: {_fmt(rec_stp, ticker)}",
                              annotation_position="bottom right",
                              annotation_font_color="#ff6e40")

        # KO-Schwelle
        _ko_lvl = _first.get("ko_level") if _first else None
        _direction = _first.get("direction", "LONG") if _first else "LONG"
        if _has_ko and _ko_lvl:
            fig.add_hline(y=_ko_lvl, line_dash="solid", line_color="#ff0000",
                          line_width=3, opacity=0.8,
                          annotation_text=f"KO: {_fmt(_ko_lvl, ticker)}",
                          annotation_position="bottom left",
                          annotation_font_color="#ff0000")
            if _direction == "LONG":
                fig.add_hrect(y0=_ko_lvl * 0.95, y1=_ko_lvl,
                              fillcolor="rgba(255,0,0,0.15)", line_width=0)
            else:
                fig.add_hrect(y0=_ko_lvl, y1=_ko_lvl * 1.05,
                              fillcolor="rgba(255,0,0,0.15)", line_width=0)

    # ══════════════════════════════════════════════════════════════════════
    # Trendkanal (nicht bei geschlossenen Trades)
    # ══════════════════════════════════════════════════════════════════════
    _show_trend = True
    if _is_single and _trades and _trades[0].get("status") == "CLOSED":
        _show_trend = False

    if _show_trend and len(_df) >= 20:
        try:
            _n_trend = min(50, len(_df))
            _trend_data = _df.iloc[-_n_trend:]
            _n_fit = _n_trend - 3
            _fit_data = _trend_data.iloc[:_n_fit]

            _fit_closes = _fit_data[_c].values
            _fit_highs = _fit_data[_h].values
            _fit_lows = _fit_data[_l].values
            _x_fit = np.arange(_n_fit)

            slope, intercept = np.polyfit(_x_fit, _fit_closes, 1)
            _reg = slope * _x_fit + intercept
            _upper_off = np.max(_fit_highs - _reg)
            _lower_off = np.min(_fit_lows - _reg)

            _future_days = 10
            _trend_dates = _trend_data.index
            _proj_date = _trend_dates[-1] + pd.Timedelta(days=_future_days * 7 // 5)
            _x_end = _n_trend - 1 + _future_days

            _show_tk_legend = True
            for _off, _tc in [
                (_upper_off, "rgba(255,82,82,0.5)"),
                (_lower_off, "rgba(76,175,80,0.5)"),
            ]:
                _y0 = slope * 0 + intercept + _off
                _y1 = slope * _x_end + intercept + _off
                fig.add_trace(go.Scatter(
                    x=[_trend_dates[0], _proj_date], y=[_y0, _y1],
                    mode="lines", name="Trendkanal",
                    line=dict(color=_tc, width=1, dash="dash"),
                    legendgroup="trendkanal",
                    showlegend=_show_tk_legend,
                ), row=1, col=1)
                _show_tk_legend = False
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════
    # Technische Indikatoren (togglebar via Legende)
    # ══════════════════════════════════════════════════════════════════════
    # Indikatoren berechnen aus den Rohdaten
    _has_indicators = False
    try:
        from indicators import compute_all as _compute_all
        _rn = {}
        if _o != "Open":
            _rn = {_o: "Open", _h: "High", _l: "Low", _c: "Close"}
        if "volume" in _df.columns:
            _rn["volume"] = "Volume"
        _ind = _compute_all(_df.rename(columns=_rn) if _rn else _df)
        if len(_ind) >= 20:
            _has_indicators = True
    except Exception:
        pass

    if _has_indicators:
        # EMA 20 (gelb, dünn)
        if "EMA20" in _ind.columns:
            fig.add_trace(go.Scatter(
                x=_ind.index, y=_ind["EMA20"],
                mode="lines", name="EMA 20",
                line=dict(color="#ffeb3b", width=1),
            ), row=1, col=1)

        # EMA 50 (orange)
        if "EMA50" in _ind.columns:
            fig.add_trace(go.Scatter(
                x=_ind.index, y=_ind["EMA50"],
                mode="lines", name="EMA 50",
                line=dict(color="#ff9800", width=1.5),
            ), row=1, col=1)

        # Bollinger Bands (grau, gefüllt) – als eine Legendengruppe
        if "BB_Upper" in _ind.columns and "BB_Lower" in _ind.columns:
            fig.add_trace(go.Scatter(
                x=_ind.index, y=_ind["BB_Upper"],
                mode="lines", name="Bollinger",
                line=dict(color="rgba(158,158,158,0.5)", width=1),
                legendgroup="bollinger",
            ), row=1, col=1)
            fig.add_trace(go.Scatter(
                x=_ind.index, y=_ind["BB_Lower"],
                mode="lines", name="Bollinger",
                line=dict(color="rgba(158,158,158,0.5)", width=1),
                fill="tonexty", fillcolor="rgba(158,158,158,0.08)",
                legendgroup="bollinger",
                showlegend=False,
            ), row=1, col=1)

        # Support / Resistance (gepunktete Linien, eine Legendengruppe)
        _show_sr_legend = True
        if "Support" in _ind.columns:
            _sup = _ind["Support"].iloc[-1]
            if pd.notna(_sup) and _sup > 0:
                fig.add_trace(go.Scatter(
                    x=[_ind.index[0], _ind.index[-1]], y=[_sup, _sup],
                    mode="lines+text", name="S/R",
                    text=["", f"Support: {_sup:.1f}"],
                    textposition="middle right",
                    textfont=dict(color="#4caf50", size=10),
                    line=dict(color="#4caf50", width=1, dash="dot"),
                    legendgroup="sr",
                    showlegend=_show_sr_legend,
                ), row=1, col=1)
                _show_sr_legend = False
        if "Resistance" in _ind.columns:
            _res = _ind["Resistance"].iloc[-1]
            if pd.notna(_res) and _res > 0:
                fig.add_trace(go.Scatter(
                    x=[_ind.index[0], _ind.index[-1]], y=[_res, _res],
                    mode="lines+text", name="S/R",
                    text=["", f"Resistance: {_res:.1f}"],
                    textposition="middle right",
                    textfont=dict(color="#f44336", size=10),
                    line=dict(color="#f44336", width=1, dash="dot"),
                    legendgroup="sr",
                    showlegend=_show_sr_legend,
                ), row=1, col=1)

        # Volumen (eigener Subplot unten)
        if "Volume" in _ind.columns:
            fig.add_trace(go.Bar(
                x=_ind.index, y=_ind["Volume"],
                name="Volumen",
                marker_color="rgba(100,181,246,0.3)",
            ), row=2, col=1)

    # ══════════════════════════════════════════════════════════════════════
    # Layout
    # ══════════════════════════════════════════════════════════════════════
    _chart_h = 600 if _has_signal else 550

    fig.update_layout(
        height=_chart_h,
        template="plotly_dark",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(size=10),
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
        margin=dict(l=60, r=30, t=40, b=30),
    )
    # Preis-Achse: fixiert auf Kursdaten, damit entfernte Linien nicht stauchen
    fig.update_yaxes(range=[_y_min, _y_max], row=1, col=1)
    fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=1, col=1)
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])], row=2, col=1)
    fig.update_yaxes(title_text="Basiswert", row=1, col=1)
    # Volumen-Achse (unten)
    fig.update_yaxes(title_text="Vol.", row=2, col=1, showgrid=False)
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# render_position_view – grouped view for multiple trades on same ticker
# ---------------------------------------------------------------------------

_ENTRY_COLORS = ["#e040fb", "#40c4ff", "#ffd740", "#69f0ae", "#ff6e40"]


def render_position_metrics(trades: list[dict], kp: str = ""):
    """Render compact metrics for a position (single or grouped, open or closed)."""
    first = trades[0]
    _is_closed = first.get("status") == "CLOSED"
    _n = len(trades)

    total_size = sum(t["size"] or 1 for t in trades)
    total_invest = 0.0
    total_value = 0.0
    total_entry_fees = 0.0

    for t in trades:
        _ko = t.get("ko_level")
        _bv = t.get("bv") or 1.0
        _d = t["direction"]
        _s = t["size"] or 1
        _ef = t.get("entry_fees") or 1.0
        total_entry_fees += _ef

        if _ko:
            ep = stock_to_product(t["entry_price"], _ko, _d, _bv)
            if _is_closed and t.get("exit_price"):
                cp = stock_to_product(t["exit_price"], _ko, _d, _bv)
            else:
                _bid = t.get("product_bid")
                cur_stock = t.get("current_price") or t["entry_price"]
                cp = _bid if _bid else stock_to_product(cur_stock, _ko, _d, _bv)
        else:
            ep = t["entry_price"]
            if _is_closed and t.get("exit_price"):
                cp = t["exit_price"]
            else:
                cp = t.get("current_price") or t["entry_price"]
        total_invest += ep * _s
        total_value += cp * _s

    avg_entry = total_invest / total_size if total_size else 0
    if _is_closed:
        total_fees = sum(t.get("fees") or 0 for t in trades)
    else:
        total_fees = total_entry_fees + 1.0  # alle Kaufgebühren + 1 Verkauf
    pnl_abs = total_value - total_invest - total_fees
    pnl_pct = pnl_abs / total_invest * 100 if total_invest > 0 else 0

    # Profit R: gewichteter Durchschnitt ueber alle Trades der Position
    from ko_calc import calc_profit_r
    _profit_r = None
    _weighted_r = 0.0
    _weight_total = 0.0
    for t in trades:
        _r = calc_profit_r(t)
        if _r is not None:
            _w = t.get("size") or 1
            _weighted_r += _r * _w
            _weight_total += _w
    if _weight_total > 0:
        _profit_r = round(_weighted_r / _weight_total, 2)

    # Einheitliche Farbe basierend auf Profit R
    from ui_colors import color_for_r as _color_for_r
    _r_color = _color_for_r(_profit_r) if _profit_r is not None else ""

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Invest", f"{total_invest:.2f} €")
    if _r_color:
        c2.markdown(f"**{'Erlös' if _is_closed else 'Wert'}**<br><span style='font-size:1.5em;color:{_r_color}'>{total_value:.2f} €</span>", unsafe_allow_html=True)
        c3.markdown(f"**P/L €**<br><span style='font-size:1.5em;color:{_r_color}'>{pnl_abs:+.2f} €</span>", unsafe_allow_html=True)
        c4.markdown(f"**P/L %**<br><span style='font-size:1.5em;color:{_r_color}'>{pnl_pct:+.1f}%</span>", unsafe_allow_html=True)
        c5.markdown(f"**Profit R**<br><span style='font-size:1.5em;color:{_r_color}'>{_profit_r:+.2f} R</span>", unsafe_allow_html=True)
    else:
        c2.metric("Erlös" if _is_closed else "Wert", f"{total_value:.2f} €")
        c3.metric("P/L €", f"{pnl_abs:+.2f} €")
        c4.metric("P/L %", f"{pnl_pct:+.1f}%")
        c5.metric("Profit R", "–")



def render_position_trades_table(trades: list[dict], kp: str = ""):
    """Render a detail table for trades (single or grouped, open or closed)."""
    _is_closed = trades[0].get("status") == "CLOSED"
    _n = len(trades)
    rows = []

    for t in trades:
        _ko = t.get("ko_level")
        _bv = t.get("bv") or 1.0
        _d = t["direction"]
        _s = t["size"] or 1
        _sl_stock = t.get("stop_loss")
        _tgt_stock = t.get("target")

        if _ko:
            ep = stock_to_product(t["entry_price"], _ko, _d, _bv)
            if _is_closed and t.get("exit_price"):
                cp = stock_to_product(t["exit_price"], _ko, _d, _bv)
            else:
                _bid = t.get("product_bid")
                cur_stock = t.get("current_price") or t["entry_price"]
                cp = _bid if _bid else stock_to_product(cur_stock, _ko, _d, _bv)
            sp = stock_to_product(_sl_stock, _ko, _d, _bv) if _sl_stock else None
            tp = stock_to_product(_tgt_stock, _ko, _d, _bv) if _tgt_stock else None
        else:
            ep = t["entry_price"]
            if _is_closed and t.get("exit_price"):
                cp = t["exit_price"]
            else:
                cp = t.get("current_price") or t["entry_price"]
            sp = _sl_stock
            tp = _tgt_stock

        _invest = ep * _s
        _val = cp * _s
        if _is_closed:
            _fees = t.get("fees") or 0
        else:
            _ef = t.get("entry_fees") or 1.0
            _fees = _ef + 1.0
        _pnl = _val - _invest - _fees
        _pnl_pct = _pnl / _invest * 100 if _invest > 0 else 0

        # Profit R
        _pr = None
        if sp and ep > 0:
            _risk = abs(ep - sp)
            _prof = cp - ep
            _pr = round(_prof / _risk, 2) if _risk > 0 else None

        row = {
            "Trade": f"#{t['id']}",
            "Kauf": _de_date(t["entry_date"]),
            "Stück": _s,
            "Einstieg": round(ep, 2),
        }
        if _is_closed:
            row["Ausstieg"] = round(cp, 2)
        else:
            row["Aktuell"] = round(cp, 2)
        row["Stop"] = round(sp, 2) if sp else None
        row["Ziel"] = round(tp, 2) if tp else None
        row["P/L €"] = round(_pnl, 2)
        row["P/L %"] = round(_pnl_pct, 1)
        row["Profit R"] = _pr
        rows.append(row)

    # Zusammenfassungszeile bei Gruppen (vor der Einzeltabelle)
    if _n > 1:
        _trade_ids = ",".join(f"#{t['id']}" for t in trades)
        _earliest = min(t["entry_date"] for t in trades)
        _total_size = sum(r["Stück"] for r in rows)
        _total_invest = sum(r["Einstieg"] * r["Stück"] for r in rows)
        _avg_entry = round(_total_invest / _total_size, 2) if _total_size else 0
        _total_pnl = sum(r["P/L €"] for r in rows)
        _total_pnl_pct = round(_total_pnl / _total_invest * 100, 1) if _total_invest > 0 else 0
        # Gewichteter Profit R
        _total_pr = 0.0
        _pr_count = 0
        for r in rows:
            if r["Profit R"] is not None:
                _total_pr += r["Profit R"] * r["Stück"]
                _pr_count += r["Stück"]
        _avg_pr = round(_total_pr / _pr_count, 2) if _pr_count > 0 else None

        _cur_val = rows[-1].get("Aktuell") or rows[-1].get("Ausstieg")
        summary_row = {
            "Trade": _trade_ids,
            "Kauf": _de_date(_earliest),
            "Stück": _total_size,
            "Einstieg": _avg_entry,
        }
        if _is_closed:
            summary_row["Ausstieg"] = _cur_val
        else:
            summary_row["Aktuell"] = _cur_val
        summary_row["Stop"] = rows[0].get("Stop")
        summary_row["Ziel"] = rows[0].get("Ziel")
        summary_row["P/L €"] = round(_total_pnl, 2)
        summary_row["P/L %"] = _total_pnl_pct
        summary_row["Profit R"] = _avg_pr

        st.markdown("**Gesamt-Position:**")
        _sum_df = pd.DataFrame([summary_row])
        st.dataframe(_style_trade_detail_df(_sum_df), hide_index=True, width="stretch", column_config=_get_trade_col_config(_is_closed))

    # Einzeltrades
    if _n > 1:
        st.markdown("**Einzelne Trades:**")
    df = pd.DataFrame(rows)
    st.dataframe(_style_trade_detail_df(df), hide_index=True, width="stretch", column_config=_get_trade_col_config(_is_closed))


def _style_trade_detail_df(df: pd.DataFrame):
    """Style trade detail table — Farbe basierend auf Profit R fuer alle P/L Spalten."""
    from ui_colors import color_for_r as _color_for_r

    def _color_row(row):
        r_val = row.get("Profit R")
        color = _color_for_r(r_val)
        if not color:
            return [""] * len(row)
        return [f"color: {color}" if col in ("P/L %", "P/L €", "Profit R") else ""
                for col in row.index]

    if "Profit R" in df.columns:
        return df.style.apply(_color_row, axis=1)
    return df.style


def _get_trade_col_config(_is_closed: bool) -> dict:
    """Column config fuer Trade-Tabellen."""
    cfg = {
        "Stück": st.column_config.NumberColumn("Stück", format="%d"),
        "Einstieg": st.column_config.NumberColumn("Einstieg", format="%.2f €"),
        "Stop": st.column_config.NumberColumn("Stop", format="%.2f €"),
        "Ziel": st.column_config.NumberColumn("Ziel", format="%.2f €"),
        "P/L €": st.column_config.NumberColumn("P/L €", format="%+.2f €"),
        "P/L %": st.column_config.NumberColumn("P/L %", format="%+.1f%%"),
        "Profit R": st.column_config.NumberColumn("Profit R", format="%+.2f R"),
    }
    if _is_closed:
        cfg["Ausstieg"] = st.column_config.NumberColumn("Ausstieg", format="%.2f €")
    else:
        cfg["Aktuell"] = st.column_config.NumberColumn("Aktuell", format="%.2f €")
    return cfg


# ---------------------------------------------------------------------------
# render_trade_actions
# ---------------------------------------------------------------------------
def render_trade_actions(trade: dict, kp: str = "", all_trades: list[dict] | None = None):
    """Render close/edit/delete forms for an open trade."""
    _has_ko = bool(trade.get("ko_level"))
    _ko_lvl = trade.get("ko_level")
    _bv_val = trade.get("bv") or 1.0
    _t_dir = trade["direction"]
    _cur_price = trade.get("current_price")

    # Action tabs: Close / Buy More / Edit / Delete
    _act_close, _act_buy, _act_edit, _act_delete = st.tabs([
        "Trade schließen", "Nachkauf", "Trade bearbeiten", "Trade löschen",
    ])

    # --- Close ---
    with _act_close:
        _size = trade["size"] or 1
        _cl_entry_fees = trade.get("entry_fees") or 1.0
        _entry_price_safe = float(trade.get("entry_price") or 0)

        # Gesamtposition für diesen Ticker (FIFO)
        _all_open = get_open_trades_for_ticker(trade["ticker"])
        _total_available = sum(t["size"] or 1 for t in _all_open)

        # Session-State Keys
        _sk_price = f"{kp}close_price_{trade['id']}"
        _sk_fees = f"{kp}close_fees_{trade['id']}"
        _sk_qty = f"{kp}close_qty_{trade['id']}"
        _cl_fees = st.session_state.get(_sk_fees, 1.0)
        _cl_qty = st.session_state.get(_sk_qty, float(_size))
        _cl_total_fees = _cl_entry_fees * (_cl_qty / _size) + _cl_fees

        # Info bei mehreren Trades
        if len(_all_open) > 1:
            st.info(f"Position: {_total_available:.0f} Stk. in {len(_all_open)} Trades (FIFO bei Teilverkauf)")

        # Defaults und Vorschau je nach KO oder Direkt
        _preview_abs = 0.0
        _preview_pct = 0.0
        if _entry_price_safe <= 0:
            st.warning("Einstiegskurs ist 0 — bitte zuerst unter 'Trade bearbeiten' korrigieren.")
        elif _has_ko:
            _entry_prod_cl = stock_to_product(_entry_price_safe, _ko_lvl, _t_dir, _bv_val)
            _prod_bid = trade.get("product_bid")
            _default_prod = _prod_bid if _prod_bid else (
                stock_to_product(_cur_price, _ko_lvl, _t_dir, _bv_val) if _cur_price else _entry_prod_cl
            )
            _cl_prod_price = st.session_state.get(_sk_price, _default_prod)
            _cl_invest = _entry_prod_cl * _cl_qty
            _preview_abs = (_cl_prod_price - _entry_prod_cl) * _cl_qty - _cl_total_fees
            _preview_pct = _preview_abs / _cl_invest * 100 if _cl_invest > 0 else 0
            _color = "green" if _preview_abs >= 0 else "red"
            _partial_hint = f" (Teilverkauf {_cl_qty:.0f}/{_size:.0f})" if _cl_qty < _size else ""
            _fifo_hint = f" (FIFO über {len(_all_open)} Trades)" if _cl_qty > _size and len(_all_open) > 1 else ""
            st.markdown(
                f"**Vorschau:** :{_color}[{_preview_pct:+.1f}%] · "
                f":{_color}[{_preview_abs:+.2f} €] · "
                f"Produkt: {_entry_prod_cl:.2f} → {_cl_prod_price:.2f} €"
                f"{_partial_hint}{_fifo_hint}"
            )
        else:
            _close_default = float(_cur_price or _entry_price_safe or 1.0)
            _cl_price = st.session_state.get(_sk_price, _close_default)
            _cl_invest = _entry_price_safe * _cl_qty
            if trade["direction"] == "LONG":
                _preview_abs = (_cl_price - _entry_price_safe) * _cl_qty - _cl_total_fees
            else:
                _preview_abs = (_entry_price_safe - _cl_price) * _cl_qty - _cl_total_fees
            _preview_pct = _preview_abs / _cl_invest * 100 if _cl_invest > 0 else 0
            _color = "green" if _preview_abs >= 0 else "red"
            _partial_hint = f" (Teilverkauf {_cl_qty:.0f}/{_size:.0f})" if _cl_qty < _size else ""
            _fifo_hint = f" (FIFO über {len(_all_open)} Trades)" if _cl_qty > _size and len(_all_open) > 1 else ""
            st.markdown(
                f"**Vorschau:** :{_color}[{_preview_pct:+.1f}%] · "
                f":{_color}[{_preview_abs:+.2f} €]"
                f"{_partial_hint}{_fifo_hint}"
            )

        # Formular
        with st.form(f"{kp}close_trade_{trade['id']}", clear_on_submit=True):
            ct1, ct2, ct3, ct4, ct5 = st.columns(5)
            with ct1:
                close_date = st.date_input("Ausstiegsdatum", value=dt.date.today(),
                                           key=f"{kp}close_date_{trade['id']}")
            with ct2:
                if _has_ko:
                    close_prod_price = st.number_input(
                        "Verkaufskurs Produkt (€)", value=max(_default_prod, 0.01),
                        min_value=0.01, step=0.01, format="%.2f",
                        key=_sk_price,
                    )
                else:
                    close_price = st.number_input(
                        "Ausstiegskurs Basiswert", value=max(_close_default, 0.01),
                        min_value=0.01, step=0.01, format="%.2f",
                        key=_sk_price,
                    )
            with ct3:
                close_qty = st.number_input(
                    "Menge", value=float(_size),
                    min_value=1.0, max_value=float(_total_available),
                    step=1.0, format="%.0f",
                    key=_sk_qty,
                    help=f"Gesamt verfügbar: {_total_available:.0f} Stk.",
                )
            with ct4:
                close_fees = st.number_input(
                    "Verkaufsgebühr (€)", value=1.0, min_value=0.0,
                    step=0.5, format="%.2f",
                    key=_sk_fees,
                )
            with ct5:
                close_notes = st.text_input("Notizen",
                                            key=f"{kp}close_notes_{trade['id']}")

            _btn_label = "Trade schließen" if close_qty >= _size else "Teilverkauf"
            close_submitted = st.form_submit_button(
                _btn_label, type="primary", width="stretch")
            if close_submitted:
                _errors = []
                if not trade.get("entry_price") or float(trade["entry_price"]) <= 0:
                    _errors.append("Einstiegskurs ist 0 — bitte zuerst unter 'Trade bearbeiten' korrigieren.")

                if _has_ko:
                    if close_prod_price <= 0:
                        _errors.append("Verkaufskurs muss > 0 sein.")
                    _exit_stock = product_to_stock(close_prod_price, _ko_lvl, _t_dir, _bv_val)
                else:
                    if close_price <= 0:
                        _errors.append("Ausstiegskurs muss > 0 sein.")
                    _exit_stock = close_price

                if _errors:
                    for _e in _errors:
                        st.error(_e)
                else:
                    if close_qty == _size and len(_all_open) == 1:
                        # Einfacher Fall: ganzen (einzigen) Trade schließen
                        close_trade(
                            trade["id"],
                            exit_date=close_date.isoformat(),
                            exit_price=_exit_stock,
                            fees=close_fees,
                            notes=close_notes or None,
                        )
                        st.success(f"Trade #{trade['id']} geschlossen: {_preview_pct:+.1f}% "
                                   f"({_preview_abs:+.2f} €)")
                    else:
                        # Teilverkauf oder FIFO über mehrere Trades
                        results = partial_close_trade(
                            ticker=trade["ticker"],
                            sell_qty=close_qty,
                            exit_date=close_date.isoformat(),
                            exit_price=_exit_stock,
                            fees=close_fees,
                            notes=close_notes or None,
                        )
                        _n_closed = sum(1 for r in results if r["action"] == "closed")
                        _n_partial = sum(1 for r in results if r["action"] == "partial")
                        _parts = []
                        if _n_closed:
                            _parts.append(f"{_n_closed} Trade{'s' if _n_closed > 1 else ''} geschlossen")
                        if _n_partial:
                            _r = [r for r in results if r["action"] == "partial"][0]
                            _parts.append(f"Teilverkauf ({_r['qty']:.0f} Stk., {_r['remaining']:.0f} verbleibend)")
                        st.success(f"{close_qty:.0f} Stk. verkauft: {' · '.join(_parts)}")
                    st.rerun()

    # --- Nachkauf ---
    with _act_buy:
        st.caption("Neuen Trade zum selben Basiswert eröffnen (gleiche Richtung & Produkt)")
        # Letztes Signal für diesen Ticker finden
        _sigs = get_signals(limit=300)
        _latest_sig = None
        for _s in _sigs:
            if _s["ticker"] == trade["ticker"]:
                _latest_sig = _s
                break

        with st.form(f"{kp}nachkauf_{trade['id']}", clear_on_submit=True):
            _nk1, _nk2, _nk3, _nk4 = st.columns(4)
            with _nk1:
                _nk_date = st.date_input("Kaufdatum", value=dt.date.today(),
                                         key=f"{kp}nk_date_{trade['id']}")
            with _nk2:
                if _has_ko:
                    _prod_bid = trade.get("product_bid")
                    _nk_default = _prod_bid if _prod_bid else (
                        stock_to_product(_cur_price, _ko_lvl, _t_dir, _bv_val)
                        if _cur_price else 0.01
                    )
                    _nk_price = st.number_input(
                        "Kaufkurs Produkt (€)", value=max(_nk_default, 0.01),
                        min_value=0.01, step=0.01, format="%.2f",
                        key=f"{kp}nk_price_{trade['id']}",
                    )
                else:
                    _nk_default = float(_cur_price or trade["entry_price"] or 0.01)
                    _nk_price = st.number_input(
                        "Kaufkurs (€)", value=max(_nk_default, 0.01),
                        min_value=0.01, step=0.01, format="%.2f",
                        key=f"{kp}nk_price_{trade['id']}",
                    )
            with _nk3:
                _nk_size = st.number_input(
                    "Stückzahl", value=float(trade["size"] or 1),
                    min_value=1.0, step=1.0, format="%.0f",
                    key=f"{kp}nk_size_{trade['id']}",
                )
            with _nk4:
                _nk_fees = st.number_input(
                    "Kaufgebühr (€)", value=1.0, min_value=0.0,
                    step=0.5, format="%.2f",
                    key=f"{kp}nk_fees_{trade['id']}",
                )

            # Invest-Vorschau
            _nk_invest = _nk_price * _nk_size
            st.caption(f"Invest: {_nk_invest:.2f} € · {_nk_size:.0f} Stk. × {_nk_price:.2f} €")

            _nk_submitted = st.form_submit_button(
                "Nachkauf eröffnen", type="primary", width="stretch")
            if _nk_submitted:
                if _has_ko:
                    _nk_entry_stock = product_to_stock(_nk_price, _ko_lvl, _t_dir, _bv_val)
                else:
                    _nk_entry_stock = _nk_price

                _new_trade = {
                    "signal_id": _latest_sig["id"] if _latest_sig else trade.get("signal_id"),
                    "ticker": trade["ticker"],
                    "name": trade["name"],
                    "direction": _t_dir,
                    "entry_date": _nk_date.isoformat(),
                    "entry_price": _nk_entry_stock,
                    "size": _nk_size,
                    "target": trade.get("rec_target") or trade.get("target"),
                    "stop_loss": trade.get("rec_stop") or trade.get("stop_loss"),
                    "notes": f"Nachkauf zu Trade #{trade['id']}",
                    "exclude_learning": trade.get("exclude_learning", 0),
                    "wkn": trade.get("wkn"),
                    "ko_level": _ko_lvl,
                    "bv": _bv_val,
                    "isin": trade.get("isin"),
                    "emittent": trade.get("emittent"),
                    "entry_fees": _nk_fees,
                    "rec_score": trade.get("rec_score"),
                    "rec_confidence": trade.get("rec_confidence"),
                    "current_price": trade.get("current_price"),
                    "product_bid": trade.get("product_bid"),
                }
                _new_id = open_trade(_new_trade)
                st.success(f"Nachkauf #{_new_id}: {_nk_size:.0f} Stk. × {_nk_price:.2f} € = {_nk_invest:.2f} €")
                st.rerun()

    # --- Edit ---
    with _act_edit:
        # Trade-Auswahl bei mehreren Trades
        _edit_trades = all_trades if all_trades and len(all_trades) > 1 else [trade]
        if len(_edit_trades) > 1:
            _ed_options = {
                f"#{t['id']}: {t['size']:.0f} Stk. @ {_de_date(t['entry_date'])}": t
                for t in _edit_trades
            }
            _ed_sel = st.radio(
                "Trade auswählen",
                list(_ed_options.keys()),
                key=f"{kp}edit_select",
                horizontal=True,
            )
            _ed_trade = _ed_options[_ed_sel]
        else:
            _ed_trade = trade

        _ed_ko = _ed_trade.get("ko_level")
        _ed_bv = _ed_trade.get("bv") or 1.0
        _ed_dir = _ed_trade["direction"]
        _ed_has_ko = bool(_ed_ko)

        # Produkt-Info (nicht editierbar)
        if _ed_has_ko:
            _ed_prod_entry = stock_to_product(_ed_trade["entry_price"], _ed_ko, _ed_dir, _ed_bv)
            _prod_id = _ed_trade.get("isin") or _ed_trade.get("wkn") or ""
            _info_parts = [
                f"**{_ed_dir}**",
                _prod_id if _prod_id else None,
                f"Emittent: {_ed_trade.get('emittent')}" if _ed_trade.get("emittent") else None,
                f"KO: {_ed_ko:.2f} {_unit(_ed_trade['ticker'])}",
                f"BV: {_ed_bv}",
            ]
            st.caption(" · ".join(p for p in _info_parts if p))
        else:
            _ed_prod_entry = float(_ed_trade["entry_price"] or 0.01)
            st.caption(f"**{_ed_dir}** · Direkt (ohne KO-Produkt)")

        with st.form(f"{kp}edit_trade_{_ed_trade['id']}"):
            ed1, ed2, ed3, ed4 = st.columns(4)
            with ed1:
                ed_entry_date = st.date_input(
                    "Kaufdatum",
                    value=dt.date.fromisoformat(_ed_trade["entry_date"]),
                    key=f"{kp}ed_date_{_ed_trade['id']}",
                )
            with ed2:
                ed_prod_price = st.number_input(
                    "Einstiegskurs (Produkt €)" if _ed_has_ko else "Einstiegskurs",
                    value=max(_ed_prod_entry, 0.01),
                    min_value=0.01, step=0.01, format="%.2f",
                    key=f"{kp}ed_price_{_ed_trade['id']}",
                )
            with ed3:
                ed_size = st.number_input(
                    "Stückzahl",
                    value=float(_ed_trade["size"] or 1),
                    min_value=0.01, step=1.0, format="%.2f",
                    key=f"{kp}ed_size_{_ed_trade['id']}",
                )
            with ed4:
                ed_notes = st.text_input(
                    "Notizen",
                    value=_ed_trade.get("notes") or "",
                    key=f"{kp}ed_notes_{_ed_trade['id']}",
                )

            # Invest-Vorschau
            if _ed_has_ko:
                _new_invest = ed_prod_price * ed_size
                _old_invest = _ed_prod_entry * float(_ed_trade["size"] or 1)
                if abs(_new_invest - _old_invest) > 0.01:
                    st.caption(
                        f"Invest: {_old_invest:.2f} € → {_new_invest:.2f} € "
                        f"(Δ {_new_invest - _old_invest:+.2f} €)"
                    )

            ed_submitted = st.form_submit_button(
                "Änderungen speichern", type="primary", width="stretch")
            if ed_submitted:
                if _ed_has_ko:
                    ed_entry_stock = product_to_stock(ed_prod_price, _ed_ko, _ed_dir, _ed_bv)
                else:
                    ed_entry_stock = ed_prod_price

                _updates = {
                    "entry_date": ed_entry_date.isoformat(),
                    "entry_price": ed_entry_stock,
                    "size": ed_size,
                    "notes": ed_notes or None,
                }
                update_trade(_ed_trade["id"], _updates)
                st.success(f"Trade #{_ed_trade['id']} aktualisiert.")
                st.rerun()

    # --- Delete ---
    with _act_delete:
        _del_trades = all_trades if all_trades and len(all_trades) > 1 else [trade]

        if len(_del_trades) > 1:
            _del_options = ["Alle Trades"] + [
                f"#{t['id']}: {t['size']:.0f} Stk. @ {_de_date(t['entry_date'])}"
                for t in _del_trades
            ]
            _del_sel = st.radio(
                "Was löschen?",
                _del_options,
                key=f"{kp}del_select",
            )
            _del_all = _del_sel == "Alle Trades"
        else:
            _del_all = False
            _del_sel = None

        if _del_all:
            _del_label = f"**Alle {len(_del_trades)} Trades** für {trade['name']} ({trade['ticker']})"
        elif _del_sel and len(_del_trades) > 1:
            _del_idx = _del_options.index(_del_sel) - 1  # -1 wegen "Alle Trades"
            _del_single = _del_trades[_del_idx]
            _del_label = f"Trade #{_del_single['id']} ({_del_single['size']:.0f} Stk.)"
        else:
            _del_single = trade
            _del_label = f"Trade #{trade['id']} **{trade['name']}** ({trade['ticker']})"

        st.warning(f"{_del_label} unwiderruflich löschen?")
        _confirm_key = f"{kp}confirm_del"
        _confirm = st.checkbox("Ja, ich bin sicher", key=_confirm_key)
        if st.button("Löschen", type="primary",
                     disabled=not _confirm,
                     key=f"{kp}del_btn"):
            if _del_all:
                for t in _del_trades:
                    delete_trade(t["id"])
                st.success(f"{len(_del_trades)} Trades gelöscht.")
            else:
                _target = _del_single if len(_del_trades) > 1 else trade
                delete_trade(_target["id"])
                st.success(f"Trade #{_target['id']} gelöscht.")
            st.rerun()
