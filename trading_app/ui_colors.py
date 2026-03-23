"""
ui_colors.py – Einheitliche Farbskala basierend auf Profit R.

Wird von app.py und components.py importiert (keine Streamlit-Widgets,
deshalb kein Zirkular-Import-Problem).
"""

from __future__ import annotations

import pandas as pd

# Farbskala: Profit R → Farbe
# >= 0R bleibt schwarz (nicht einfärben), nur Extreme werden farbig
GRADIENT = [
    "#00e676",  # leuchtend gruen (>= 2.0R = Target)
    "#66bb6a",  # gruen           (>= 1.5R)
    "#a5d6a7",  # hellgruen       (>= 0.75R)
    "",         # schwarz         (>= 0R, nicht einfaerben)
    "#ffb74d",  # orange          (>= -0.5R)
    "#ef5350",  # rot             (>= -0.75R)
    "#d32f2f",  # dunkelrot       (< -0.75R)
]
R_THRESHOLDS = [2.0, 1.5, 0.75, 0, -0.5, -0.75]


def color_for_r(r_val) -> str:
    """Farbe basierend auf Profit R Wert."""
    if r_val is None or (isinstance(r_val, float) and pd.isna(r_val)):
        return ""
    for i, t in enumerate(R_THRESHOLDS):
        if r_val >= t:
            return GRADIENT[i]
    return GRADIENT[-1]


def style_trades_df(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """Apply consistent coloring based on Profit R to P/L and Profit R columns."""

    def _color_by_profit_r(row):
        r_val = row.get("Profit R")
        color = color_for_r(r_val)
        if not color:
            return [""] * len(row)
        return [f"color: {color}" if col in ("P/L %", "P/L €", "Profit R", "Wert") else ""
                for col in row.index]

    if "Profit R" in df.columns:
        return df.style.apply(_color_by_profit_r, axis=1)
    return df.style
