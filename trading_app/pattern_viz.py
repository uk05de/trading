"""
pattern_viz.py – Scannt alle Ticker nach Pattern-Signalen und erstellt
je Pattern zwei Beispiel-Charts (Candlestick + Indikatoren + Entry/SL).

Nutzung:
    .venv/bin/python3 pattern_viz.py
"""

from __future__ import annotations

import datetime as dt
import os
import random

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest import _download
from indicators import compute_all
from markets import DAX_COMPONENTS, TECDAX_COMPONENTS, MDAX_COMPONENTS
from patterns import scan_all_patterns

TICKERS = {**DAX_COMPONENTS, **TECDAX_COMPONENTS, **MDAX_COMPONENTS}
OUT_DIR = "results/pattern_examples"
CACHE_PATH = "data/signals_patterns.pkl"
CONTEXT_BARS = 60  # Tage vor/nach dem Signal im Chart


def collect_signals(force_rescan: bool = False) -> pd.DataFrame:
    """Lade alle Ticker, berechne Indikatoren, scanne Patterns. Cached in PKL."""
    if not force_rescan and os.path.exists(CACHE_PATH):
        print(f"  Cache geladen: {CACHE_PATH}")
        return pd.read_pickle(CACHE_PATH)

    all_hits: list[dict] = []
    for ticker, name in TICKERS.items():
        print(f"  {ticker} ({name}) ...", end=" ")
        df = _download(ticker)
        if df.empty or len(df) < 250:
            print("uebersprungen")
            continue
        df = compute_all(df)
        hits = scan_all_patterns(df)
        for h in hits:
            h["ticker"] = ticker
            h["name"] = name
        all_hits.extend(hits)
        print(f"{len(hits)} Signale")

    signals = pd.DataFrame(all_hits)
    if not signals.empty:
        signals.to_pickle(CACHE_PATH)
        print(f"  -> Cache gespeichert: {CACHE_PATH}")
    return signals


def pick_examples(signals: pd.DataFrame, n_per_pattern: int = 2) -> dict[str, list[dict]]:
    """Waehle pro Pattern n zufaellige Beispiele (bevorzugt verschiedene Ticker)."""
    examples: dict[str, list[dict]] = {}
    for pat, group in signals.groupby("pattern"):
        # Versuche verschiedene Ticker
        tickers = group["ticker"].unique()
        picked = []
        if len(tickers) >= n_per_pattern:
            chosen_tickers = random.sample(list(tickers), n_per_pattern)
            for t in chosen_tickers:
                sub = group[group["ticker"] == t]
                picked.append(sub.sample(1).iloc[0].to_dict())
        else:
            picked = group.sample(min(n_per_pattern, len(group))).to_dict("records")
        examples[pat] = picked
    return examples


def make_chart(ticker: str, name: str, df_full: pd.DataFrame,
               signal: dict, out_path: str) -> None:
    """Erstelle Candlestick-Chart mit Indikatoren und Entry/SL-Markierung."""
    sig_date = pd.Timestamp(signal["date"])

    # Finde iloc-Position des Signal-Datums
    idx_pos = df_full.index.get_indexer([sig_date], method="nearest")[0]
    start = max(0, idx_pos - CONTEXT_BARS)
    end = min(len(df_full), idx_pos + CONTEXT_BARS)
    df = df_full.iloc[start:end].copy()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[
            f"{name} ({ticker}) — {signal['pattern']}",
            "RSI", "Volumen"
        ],
    )

    # --- Candlestick ---
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="OHLC", increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)

    # --- EMAs ---
    for ema, color in [("EMA20", "#2196F3"), ("EMA50", "#FF9800"), ("EMA200", "#9C27B0")]:
        if ema in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[ema], name=ema,
                line=dict(width=1.5, color=color),
            ), row=1, col=1)

    # --- Bollinger Bands ---
    if "BB_Upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"], name="BB Upper",
            line=dict(width=1, color="gray", dash="dot"),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"], name="BB Lower",
            line=dict(width=1, color="gray", dash="dot"),
            fill="tonexty", fillcolor="rgba(200,200,200,0.1)",
        ), row=1, col=1)

    # --- Entry-Markierung ---
    fig.add_trace(go.Scatter(
        x=[sig_date], y=[signal["entry"]],
        mode="markers+text", name="Entry",
        marker=dict(size=14, color="#4CAF50", symbol="triangle-up"),
        text=[f"Entry {signal['entry']:.2f}"],
        textposition="top center", textfont=dict(size=11, color="#4CAF50"),
    ), row=1, col=1)

    # --- Stop-Loss-Linie ---
    sl = signal["stop_loss"]
    fig.add_hline(
        y=sl, line_dash="dash", line_color="#F44336", line_width=1.5,
        annotation_text=f"SL {sl:.2f}",
        annotation_position="bottom right",
        annotation_font_color="#F44336",
        row=1, col=1,
    )

    # --- RSI ---
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(width=1.5, color="#7E57C2"),
        ), row=2, col=1)
        fig.add_hline(y=70, line_dash="dot", line_color="red", line_width=0.8, row=2, col=1)
        fig.add_hline(y=30, line_dash="dot", line_color="green", line_width=0.8, row=2, col=1)

    # --- Volumen ---
    colors = ["#26a69a" if c >= o else "#ef5350"
              for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"], name="Volumen",
        marker_color=colors, opacity=0.7,
    ), row=3, col=1)

    if "Vol_SMA20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["Vol_SMA20"], name="Vol SMA20",
            line=dict(width=1, color="#FF9800"),
        ), row=3, col=1)

    # --- Layout ---
    fig.update_layout(
        height=800, width=1200,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        title=dict(
            text=f"{signal['pattern']} — {name} ({ticker}) — {signal['date']}<br>"
                 f"<sub>{signal['detail']}</sub>",
            x=0.5,
        ),
        margin=dict(t=100),
    )

    fig.write_html(out_path, include_plotlyjs="cdn")
    print(f"    -> {out_path}")


def main():
    import sys
    force = "--rescan" in sys.argv

    os.makedirs(OUT_DIR, exist_ok=True)

    print("=== Signale sammeln ===")
    signals = collect_signals(force_rescan=force)
    if signals.empty:
        print("Keine Signale gefunden!")
        return

    print(f"\n=== {len(signals)} Signale gesamt ===")
    print(signals["pattern"].value_counts().to_string())

    print("\n=== Beispiele auswaehlen ===")
    examples = pick_examples(signals, n_per_pattern=2)

    print("\n=== Charts erstellen ===")
    for pat, sigs in sorted(examples.items()):
        for idx, sig in enumerate(sigs):
            ticker = sig["ticker"]
            name = sig["name"]

            # Daten erneut laden fuer Chart
            df = _download(ticker)
            df = compute_all(df)

            fname = f"{pat}_{idx + 1}_{ticker.replace('.', '_')}.html"
            make_chart(ticker, name, df, sig, os.path.join(OUT_DIR, fname))

    # Uebersicht als Index-HTML
    _write_index(examples)
    print(f"\nFertig! Charts in {OUT_DIR}/")


def _write_index(examples: dict[str, list[dict]]) -> None:
    """Erstelle eine Index-HTML mit Links zu allen Charts."""
    html = ["<html><head><title>Pattern-Beispiele</title>",
            "<style>body{font-family:sans-serif;max-width:900px;margin:40px auto;background:#1e1e1e;color:#eee}",
            "a{color:#64B5F6}table{border-collapse:collapse;width:100%}",
            "th,td{padding:8px 12px;border:1px solid #444;text-align:left}",
            "th{background:#333;position:sticky;top:0}</style></head><body>",
            "<h1>Pattern-Beispiele</h1><table>",
            "<thead><tr><th>Pattern</th><th>Ticker</th><th>Datum</th><th>Entry</th><th>SL</th><th>Detail</th><th>Chart</th></tr></thead>",
            "<tbody>"]

    for pat, sigs in sorted(examples.items()):
        for idx, sig in enumerate(sigs):
            ticker = sig["ticker"]
            fname = f"{pat}_{idx + 1}_{ticker.replace('.', '_')}.html"
            html.append(
                f"<tr><td>{pat}</td><td>{ticker}</td><td>{sig['date']}</td>"
                f"<td>{sig['entry']:.2f}</td><td>{sig['stop_loss']:.2f}</td>"
                f"<td>{sig['detail']}</td>"
                f"<td><a href='{fname}'>Chart</a></td></tr>"
            )

    html.append("</tbody></table></body></html>")
    path = os.path.join(OUT_DIR, "index.html")
    with open(path, "w") as f:
        f.write("\n".join(html))
    print(f"    -> {path}")


if __name__ == "__main__":
    main()
