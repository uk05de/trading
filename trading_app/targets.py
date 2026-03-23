"""
targets.py – Swing-Trading Stop-Loss & Kursziel Berechnung.

Best Practices:
  1. Fester 2.5× ATR Stop-Loss (Backtest-optimal, März 2026)
  2. Ziel = nächstes signifikantes Hindernis (S/R, Fibonacci, Swing, Analyst)
  3. R/R wird ehrlich berechnet – kein künstliches Hochsetzen
  4. Mehrstufiges Trailing-Stop (Breakeven → 1R → enger)
  5. Multi-Timeframe Support/Resistance (nur für Targets, nicht für SL)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from indicators import fibonacci_levels


# ---------------------------------------------------------------------------
# Volatilitäts-Regime → ATR-Multiplikatoren
# ---------------------------------------------------------------------------

def _atr_stop_mult(atr_pct: float) -> float:
    """
    Return ATR-Multiplikator für Stop-Loss.

    Backtest-Ergebnis (März 2026): Fester 2.5× ATR ist optimal.
    Vorher volatilitätsangepasst (1.5/2.0/2.5) – brachte keinen Vorteil.
    2.5× ATR: höchste Ø P&L (+1.56%), beste Balance aus Schutz und Spielraum.
    """
    return 2.5


# ---------------------------------------------------------------------------
# Swing-Highs / Swing-Lows erkennen
# ---------------------------------------------------------------------------

def _find_swing_levels(df: pd.DataFrame, order: int = 5) -> tuple[list[float], list[float]]:
    """
    Finde Swing-Highs und Swing-Lows im Kursverlauf.

    Ein Swing-High ist ein Punkt, der höher ist als die `order` Bars davor und danach.
    Gibt (swing_highs, swing_lows) zurück – nur die Preisniveaus.
    """
    highs = df["High"].values
    lows = df["Low"].values
    swing_highs = []
    swing_lows = []

    for i in range(order, len(df) - order):
        # Swing High: höher als alle Nachbarn
        if highs[i] == max(highs[i - order:i + order + 1]):
            swing_highs.append(highs[i])
        # Swing Low: tiefer als alle Nachbarn
        if lows[i] == min(lows[i - order:i + order + 1]):
            swing_lows.append(lows[i])

    return swing_highs, swing_lows


# ---------------------------------------------------------------------------
# Support/Resistance: Multi-Timeframe Zonen
# ---------------------------------------------------------------------------

def _find_sr_zones(df: pd.DataFrame) -> dict:
    """
    Find support/resistance using multiple lookbacks and cluster them.

    Returns dict with nearest support/resistance and zone strength.
    """
    close = df["Close"].iloc[-1]
    supports = []
    resistances = []

    for lookback in [10, 20, 50]:
        if len(df) < lookback:
            continue
        recent = df.tail(lookback)
        s = recent["Low"].min()
        r = recent["High"].max()
        supports.append(s)
        resistances.append(r)

    # Fibonacci levels as additional S/R
    if len(df) >= 50:
        recent50 = df.tail(50)
        swing_high = recent50["High"].max()
        swing_low = recent50["Low"].min()
        fibs = fibonacci_levels(swing_high, swing_low)
        # Fib levels below current price = support, above = resistance
        for key, level in fibs.items():
            if "ext_" in key:
                continue
            if level < close * 0.99:
                supports.append(level)
            elif level > close * 1.01:
                resistances.append(level)

    # Cluster nearby levels (within 1% of each other)
    support = _best_cluster(supports, close, below=True)
    resistance = _best_cluster(resistances, close, below=False)

    # Fallback to simple if clustering fails
    if support is None:
        support = df["Low"].rolling(20).min().iloc[-1]
    if resistance is None:
        resistance = df["High"].rolling(20).max().iloc[-1]

    # Zone strength: how many levels cluster near the chosen S/R
    s_strength = sum(1 for s in supports if abs(s - support) / close < 0.015)
    r_strength = sum(1 for r in resistances if abs(r - resistance) / close < 0.015)

    return {
        "support": support,
        "resistance": resistance,
        "support_strength": s_strength,
        "resistance_strength": r_strength,
    }


def _best_cluster(levels: list[float], ref: float, below: bool) -> float | None:
    """Find the level closest to ref that has nearby confirmations."""
    if not levels:
        return None
    if below:
        candidates = sorted([l for l in levels if l < ref], reverse=True)
    else:
        candidates = sorted([l for l in levels if l > ref])
    if not candidates:
        return None

    # Score each candidate by proximity + cluster count
    best, best_score = candidates[0], 0
    for c in candidates:
        # Count nearby levels (within 1.5% of this candidate)
        nearby = sum(1 for l in levels if abs(l - c) / ref < 0.015)
        # Prefer levels closer to price
        proximity = 1 / (1 + abs(c - ref) / ref * 10)
        score = nearby * 0.6 + proximity * 0.4
        if score > best_score:
            best, best_score = c, score
    return best


# ---------------------------------------------------------------------------
# Neue Signale: Einstieg, Ziel, Stop-Loss
# ---------------------------------------------------------------------------

def _cluster_levels(levels: list[tuple[float, str]], ref: float,
                    cluster_pct: float = 1.5) -> list[dict]:
    """
    Clustere Preis-Level die nah beieinander liegen.

    Levels innerhalb von cluster_pct % zueinander werden zu einer Zone
    zusammengefasst. Jeder Cluster hat:
      - center: gewichteter Mittelpunkt
      - confirmations: Anzahl bestätigender Quellen
      - sources: Liste der Quellnamen

    Sortiert nach Abstand zu ref (nächster zuerst).
    """
    if not levels:
        return []

    # Nach Preis sortieren
    sorted_levels = sorted(levels, key=lambda x: x[0])
    threshold = ref * cluster_pct / 100

    clusters = []
    current_cluster = [sorted_levels[0]]

    for i in range(1, len(sorted_levels)):
        if sorted_levels[i][0] - current_cluster[-1][0] <= threshold:
            current_cluster.append(sorted_levels[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [sorted_levels[i]]
    clusters.append(current_cluster)

    result = []
    for cluster in clusters:
        prices = [p for p, _ in cluster]
        sources = list({s for _, s in cluster})  # unique sources
        result.append({
            "center": sum(prices) / len(prices),
            "confirmations": len(sources),
            "sources": sources,
        })

    # Sortiere nach Abstand zu ref
    result.sort(key=lambda c: abs(c["center"] - ref))
    return result


def _find_confirmed_target(entry: float, levels: list[tuple[float, str]],
                           direction: str, atr: float,
                           min_confirmations: int = 2) -> tuple[float | None, str | None]:
    """
    Finde das nächste bestätigte Hindernis (≥ min_confirmations Quellen).

    Levels werden geclustert. Nur Cluster mit genügend Bestätigungen
    werden als Ziel akzeptiert. Mindestabstand: 1× ATR vom Entry.

    Returns:
        (preis, quellen-beschreibung) oder (None, None) wenn kein
        bestätigtes Level existiert.
    """
    min_dist = atr  # Mindestabstand 1× ATR

    if direction == "LONG":
        relevant = [(p, s) for p, s in levels if p > entry + min_dist]
    else:
        relevant = [(p, s) for p, s in levels if p < entry - min_dist]

    if not relevant:
        return None, None

    clusters = _cluster_levels(relevant, entry)

    # Sortiere nach Abstand zum Entry (nächster zuerst)
    if direction == "LONG":
        clusters.sort(key=lambda c: c["center"])
    else:
        clusters.sort(key=lambda c: c["center"], reverse=True)

    # Nimm den nächsten Cluster mit genügend Bestätigungen
    for cluster in clusters:
        if cluster["confirmations"] >= min_confirmations:
            source_str = " + ".join(sorted(cluster["sources"]))
            return round(cluster["center"], 2), source_str

    return None, None


def compute_targets(df: pd.DataFrame, direction: str,
                    analyst_target: float = None) -> dict:
    """
    Compute entry, target, stop-loss for a new swing trade signal.

    Ziel = nächstes signifikantes Hindernis (Resistance, Swing-High,
    Fibonacci, Analysten-Kursziel). Kein Durchschnitt, kein ATR-Ziel.
    R/R wird ehrlich berechnet – ein schlechtes R/R bedeutet:
    Trade-Setup ist ungünstig.
    """
    last = df.iloc[-1]
    entry = last["Close"]
    atr = last["ATR"]
    atr_pct = last["ATR_pct"]
    stop_mult = _atr_stop_mult(atr_pct)

    # Multi-TF Support/Resistance
    sr = _find_sr_zones(df)
    support = sr["support"]
    resistance = sr["resistance"]

    # Fibonacci
    lookback_50 = min(50, len(df))
    recent = df.tail(lookback_50)
    swing_high = recent["High"].max()
    swing_low = recent["Low"].min()
    fibs = fibonacci_levels(swing_high, swing_low)

    # Swing-Highs/Lows als zusätzliche Level
    _sh, _sl = _find_swing_levels(df.tail(120))

    if direction == "LONG":
        # Stop-Loss: rein ATR-basiert (S/R-Anker entfernt, Backtest März 2026)
        stop_loss = entry - stop_mult * atr

        # Zielkandidaten sammeln (alle echten Marktlevels)
        target_levels = [
            (resistance, "Resistance"),
        ]
        if analyst_target and analyst_target > entry:
            target_levels.append((analyst_target, "Analyst"))
        for key, val in fibs.items():
            if val > entry:
                target_levels.append((val, "Fibonacci"))
        for sh in _sh:
            if sh > entry:
                target_levels.append((sh, "Swing-High"))

        # Nächstes bestätigtes Hindernis (≥ 2 Quellen in einer Zone)
        target, target_source = _find_confirmed_target(
            entry, target_levels, "LONG", atr)

    else:  # SHORT
        # Stop-Loss: rein ATR-basiert (S/R-Anker entfernt, Backtest März 2026)
        stop_loss = entry + stop_mult * atr

        target_levels = [
            (support, "Support"),
        ]
        if analyst_target and analyst_target < entry:
            target_levels.append((analyst_target, "Analyst"))
        for key, val in fibs.items():
            if val < entry:
                target_levels.append((val, "Fibonacci"))
        for sl in _sl:
            if sl < entry:
                target_levels.append((sl, "Swing-Low"))

        target, target_source = _find_confirmed_target(
            entry, target_levels, "SHORT", atr)

    # R/R ehrlich berechnen – None wenn kein bestätigtes Ziel
    if target is not None:
        risk = abs(entry - stop_loss)
        reward = abs(target - entry)
        risk_reward = round(reward / risk, 2) if risk > 0 else 0.0
    else:
        risk_reward = None

    return {
        "entry": round(entry, 2),
        "target": round(target, 2) if target is not None else None,
        "target_source": target_source,
        "stop_loss": round(stop_loss, 2),
        "risk_reward": risk_reward,
        "support": round(support, 2),
        "resistance": round(resistance, 2),
        "support_strength": sr["support_strength"],
        "resistance_strength": sr["resistance_strength"],
        "fib_levels": {k: round(v, 2) for k, v in fibs.items()},
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "volatility_regime": (
            "niedrig" if atr_pct < 1.5 else "hoch" if atr_pct > 3.0 else "normal"
        ),
    }
