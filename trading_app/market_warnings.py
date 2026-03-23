"""
market_warnings.py – Markt-Warnsignale fuer die Index-Charts.

Generiert Charts mit DAX/TecDAX/MDAX und markiert Zeitpunkte
an denen verschiedene Warnsignale getriggert haetten.

Nutzung:
    .venv/bin/python3 market_warnings.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest import _download
from markets import INDICES


OUT_DIR = Path("results/market_warnings")


def compute_warnings(df: pd.DataFrame) -> pd.DataFrame:
    """Berechne verschiedene Warnsignale auf Index-Daten."""
    w = pd.DataFrame(index=df.index)
    close = df["Close"]

    # EMAs und SMAs
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # 20-Tage-Hoch und Abstand
    high20 = close.rolling(20).max()
    dist_from_high = (close - high20) / high20 * 100

    # Warnsignale (True = Warnung aktiv)
    w["ema_cross"] = ema20 < ema50                     # EMA20 < EMA50
    w["below_sma200"] = close < sma200                  # Preis < SMA200
    w["drop_5pct"] = dist_from_high < -5                # 5% unter 20-Tage-Hoch
    w["drop_8pct"] = dist_from_high < -8                # 8% unter 20-Tage-Hoch
    w["rsi_weak"] = rsi < 40                            # RSI < 40

    # Kombination: mind. 2 von 3 Warnungen aktiv
    w["combo"] = (w["ema_cross"].astype(int) +
                  w["below_sma200"].astype(int) +
                  w["drop_5pct"].astype(int)) >= 2

    # Hilfsdaten fuer Chart
    w["close"] = close
    w["ema20"] = ema20
    w["ema50"] = ema50
    w["sma200"] = sma200
    w["rsi"] = rsi
    w["dist_from_high"] = dist_from_high

    return w


def make_warning_chart(index_ticker: str, index_name: str,
                       df: pd.DataFrame, warnings: pd.DataFrame,
                       out_path: Path) -> None:
    """Erstelle interaktiven Chart mit Warnsignalen."""

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=[
            f"{index_name} ({index_ticker}) mit Warnsignalen",
            "RSI (14)",
            "Abstand vom 20-Tage-Hoch (%)"
        ],
    )

    # --- Kurs + EMAs ---
    fig.add_trace(go.Scatter(
        x=df.index, y=df["Close"], name="Kurs",
        line=dict(width=1.5, color="#1565C0"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=warnings.index, y=warnings["ema20"], name="EMA20",
        line=dict(width=1, color="#4CAF50", dash="dot"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=warnings.index, y=warnings["ema50"], name="EMA50",
        line=dict(width=1, color="#FF9800", dash="dot"),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=warnings.index, y=warnings["sma200"], name="SMA200",
        line=dict(width=1, color="#9C27B0", dash="dash"),
    ), row=1, col=1)

    # --- Warnzonen als echte Traces (klickbar in Legende) ---
    y_max = df["Close"].max() * 1.10
    warning_types = [
        ("ema_cross",    "EMA20 < EMA50",       "rgba(255,152,0,0.15)"),
        ("below_sma200", "Preis < SMA200",       "rgba(156,39,176,0.15)"),
        ("drop_5pct",    "5% unter 20T-Hoch",    "rgba(244,67,54,0.15)"),
        ("combo",        "Kombination (>=2/3)",   "rgba(244,67,54,0.35)"),
    ]

    for col_name, label, color in warning_types:
        # y_max wo Warnung aktiv, None wo nicht
        y_vals = [y_max if active else None
                  for active in warnings[col_name]]

        fig.add_trace(go.Scatter(
            x=warnings.index, y=y_vals,
            mode="none",
            fill="tozeroy", fillcolor=color,
            name=label,
            connectgaps=False,
            hoverinfo="skip",
        ), row=1, col=1)

    # --- RSI ---
    fig.add_trace(go.Scatter(
        x=warnings.index, y=warnings["rsi"], name="RSI",
        line=dict(width=1.5, color="#7E57C2"),
        showlegend=False,
    ), row=2, col=1)
    fig.add_hline(y=40, line_dash="dot", line_color="red", line_width=0.8, row=2, col=1)
    fig.add_hline(y=60, line_dash="dot", line_color="green", line_width=0.8, row=2, col=1)

    # --- Abstand vom Hoch ---
    fig.add_trace(go.Scatter(
        x=warnings.index, y=warnings["dist_from_high"], name="Dist High",
        line=dict(width=1.5, color="#E91E63"),
        fill="tozeroy", fillcolor="rgba(233,30,99,0.1)",
        showlegend=False,
    ), row=3, col=1)
    fig.add_hline(y=-5, line_dash="dot", line_color="orange", line_width=1,
                  annotation_text="-5%", row=3, col=1)
    fig.add_hline(y=-8, line_dash="dot", line_color="red", line_width=1,
                  annotation_text="-8%", row=3, col=1)

    # --- Layout ---
    fig.update_layout(
        height=900, width=1400,
        template="plotly_dark",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=80),
    )

    fig.write_html(str(out_path), include_plotlyjs="cdn")
    print(f"  -> {out_path}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    indices = {
        "^GDAXI": "DAX 40",
        "^TECDAX": "TecDAX",
        "^MDAXI": "MDAX",
    }

    for ticker, name in indices.items():
        print(f"\n  {name} ({ticker})...")
        df = _download(ticker, days=2800)
        if df.empty:
            print(f"  Keine Daten fuer {ticker}")
            continue

        warnings = compute_warnings(df)

        # Statistik
        n_days = len(warnings)
        for col in ["ema_cross", "below_sma200", "drop_5pct", "combo"]:
            pct = warnings[col].sum() / n_days * 100
            print(f"    {col:>15s}: {pct:>5.1f}% der Tage aktiv")

        out_path = OUT_DIR / f"warnings_{ticker.replace('^', '')}.html"
        make_warning_chart(ticker, name, df, warnings, out_path)

    # Index-HTML
    html = ["<html><head><title>Markt-Warnsignale</title>",
            "<style>body{font-family:sans-serif;max-width:900px;margin:40px auto;background:#1e1e1e;color:#eee}",
            "a{color:#64B5F6;font-size:18px;display:block;margin:12px 0}</style></head><body>",
            "<h1>Markt-Warnsignale</h1>",
            "<p>Warnsignale die vor Markt-Korrekturen warnen koennten:</p>",
            "<ul><li><b>EMA20 &lt; EMA50</b> — mittelfristiger Trendwechsel</li>",
            "<li><b>Preis &lt; SMA200</b> — langfristiger Trend gebrochen</li>",
            "<li><b>5% unter 20-Tage-Hoch</b> — schnelle Korrektur</li>",
            "<li><b>Kombination (≥2 von 3)</b> — mehrere Signale gleichzeitig</li></ul>"]

    for ticker, name in indices.items():
        fname = f"warnings_{ticker.replace('^', '')}.html"
        html.append(f"<a href='{fname}'>{name} ({ticker})</a>")

    html.append("</body></html>")
    index_path = OUT_DIR / "index.html"
    index_path.write_text("\n".join(html))
    print(f"\n  Index: {index_path}")

    import subprocess
    subprocess.run(["open", str(index_path)])


if __name__ == "__main__":
    main()
