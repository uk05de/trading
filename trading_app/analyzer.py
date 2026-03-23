"""
analyzer.py – Combined scoring engine for swing trading (Tage bis Wochen).

Evaluates a stock across 4 dimensions:
  1. Technical indicators  (chart)
  2. Fundamental data      (earnings)
  3. Market context        (index, VIX, sector)
  4. News sentiment

12 focused conditions – each measures something unique.
No redundant double-counting, no mean-reversion in a trend system.
ADX acts as trend-strength multiplier, not a standalone vote.
"""

import json
import numpy as np
import pandas as pd

def _get_weights():
    """Standard-Gewichte (alle 1.0) — get_weights aus db.py entfernt."""
    return {}


def analyze_stock(df: pd.DataFrame, fundamentals: dict,
                  market: dict, news_score: float,
                  news_count: int,
                  sector_score: float = 0.0) -> dict:
    """
    Score a single stock.

    Args:
        df: DataFrame with all technical indicators computed
        fundamentals: dict from fundamentals.get_fundamentals()
        market: dict from market_context.get_market_context()
        news_score: float from news_sentiment
        news_count: int
        sector_score: float from sectors.compute_sector_scores() (-100..+100)

    Returns dict with:
        direction, score, confidence, tech_score, fund_score,
        market_score, news_score, votes_detail
    """
    weights = _get_weights()
    last = df.iloc[-1]
    votes: dict[str, dict] = {}

    # ===== TECHNICAL (6 conditions) =====
    tech_score = 0.0

    close = last["Close"]
    ema50_slope = last.get("EMA50_Slope", 0)
    ema50_rising = ema50_slope > 0.5
    ema50_falling = ema50_slope < -0.5
    macd_above = last.get("MACD", 0) > last.get("MACD_Signal", 0)
    adx = last.get("ADX", 0)

    # --- 1. EMA50 Slope – Haupttrend ---
    # Kernindikator: Steigt oder fällt der mittelfristige Trend?
    if ema50_rising:
        v = 2.0
        votes["ema50_trend"] = {"value": v, "detail": f"EMA50 steigt ({ema50_slope:+.1f}%) \u2192 Aufw\u00e4rtstrend"}
    elif ema50_falling:
        v = -2.0
        votes["ema50_trend"] = {"value": v, "detail": f"EMA50 f\u00e4llt ({ema50_slope:+.1f}%) \u2192 Abw\u00e4rtstrend"}
    else:
        v = 0.0
        votes["ema50_trend"] = {"value": v, "detail": f"EMA50 flach ({ema50_slope:+.1f}%)"}

    # --- 2. MACD Signal – Momentum ---
    v = 1.5 if macd_above else -1.5
    votes["macd_signal"] = {
        "value": v,
        "detail": f"MACD {'>' if macd_above else '<'} Signal",
    }

    # --- 3. ADX – Trendstärke-Multiplikator ---
    # ADX misst nur STÄRKE, nicht Richtung. Bei starkem Trend wird
    # der bisherige Score verstärkt, bei schwachem Trend abgeschwächt.
    if adx > 25:
        v = 1.0
        votes["adx_trend"] = {"value": v, "detail": f"ADX={adx:.0f} (starker Trend \u2192 Signal verst\u00e4rkt)"}
    elif adx < 15:
        v = -0.5
        votes["adx_trend"] = {"value": v, "detail": f"ADX={adx:.0f} (kein Trend \u2192 Signal abgeschw\u00e4cht)"}
    else:
        v = 0.0
        votes["adx_trend"] = {"value": v, "detail": f"ADX={adx:.0f} (moderater Trend)"}

    # --- 4. Bollinger Squeeze – Ausbruchserkennung ---
    bb_pct = last.get("BB_Pct", 0.5)
    bb_width = last.get("BB_Width", 5)
    if bb_width < 5 and bb_pct < 0.3:
        v = 1.5
        votes["bollinger_squeeze"] = {"value": v, "detail": "Bollinger Squeeze nahe unterem Band"}
    elif bb_width < 5 and bb_pct > 0.7:
        v = -1.5
        votes["bollinger_squeeze"] = {"value": v, "detail": "Bollinger Squeeze nahe oberem Band"}
    else:
        v = 0.0
        votes["bollinger_squeeze"] = {"value": v, "detail": f"BB%={bb_pct:.1%}, Breite={bb_width:.1f}%"}

    # --- 5. Volume Surge – Bestätigung ---
    vol_ratio = last.get("Vol_Ratio", 1.0)
    if vol_ratio > 1.5:
        v = 1.0
        votes["volume_surge"] = {"value": v, "detail": f"Volumen {vol_ratio:.1f}\u00d7 \u00fcber \u00d8"}
    else:
        v = 0.0
        votes["volume_surge"] = {"value": v, "detail": f"Volumen {vol_ratio:.1f}\u00d7 (normal)"}

    # --- 6. Support / Resistance Nähe ---
    dist_sup = last.get("Dist_Support_pct", 10)
    dist_res = last.get("Dist_Resistance_pct", 10)
    if dist_sup < 2:
        v = 1.5
        votes["support_near"] = {"value": v, "detail": f"Nahe Support ({dist_sup:.1f}% entfernt)"}
    else:
        votes["support_near"] = {"value": 0, "detail": f"Support {dist_sup:.1f}% entfernt"}

    if dist_res < 2:
        v = -1.0
        votes["resistance_near"] = {"value": v, "detail": f"Nahe Resistance ({dist_res:.1f}% entfernt)"}
    else:
        votes["resistance_near"] = {"value": 0, "detail": f"Resistance {dist_res:.1f}% entfernt"}

    # --- 7. Relative Stärke vs. Leitindex ---
    _idx_name = market.get("index_name", "Index")
    roc10 = last.get("ROC", 0)
    idx_change = market.get("index_change_1m", 0) or 0
    idx_10d_approx = idx_change / 2.5 if idx_change else 0
    rel_strength = roc10 - idx_10d_approx
    if rel_strength > 3:
        v = 1.5
        votes["relative_strength"] = {"value": v, "detail": f"Outperformer vs. {_idx_name} ({rel_strength:+.1f}%)"}
    elif rel_strength > 1:
        v = 0.5
        votes["relative_strength"] = {"value": v, "detail": f"Leicht st\u00e4rker als {_idx_name} ({rel_strength:+.1f}%)"}
    elif rel_strength < -3:
        v = -1.5
        votes["relative_strength"] = {"value": v, "detail": f"Underperformer vs. {_idx_name} ({rel_strength:+.1f}%)"}
    elif rel_strength < -1:
        v = -0.5
        votes["relative_strength"] = {"value": v, "detail": f"Leicht schw\u00e4cher als {_idx_name} ({rel_strength:+.1f}%)"}
    else:
        votes["relative_strength"] = {"value": 0, "detail": f"Rel. St\u00e4rke vs. {_idx_name}: {rel_strength:+.1f}% (neutral)"}

    # Sum technical
    for k, v_dict in votes.items():
        w = weights.get(k, 1.0)
        tech_score += v_dict["value"] * w

    # ===== FUNDAMENTAL (1 condition) =====
    fund_score = 0.0

    from fundamentals import earnings_signal
    e_score, e_detail = earnings_signal(fundamentals)
    votes["earnings_proximity"] = {"value": e_score, "detail": e_detail}

    w = weights.get("earnings_proximity", 1.0)
    fund_score += votes["earnings_proximity"]["value"] * w

    # ===== MARKET CONTEXT (3 conditions) =====
    mkt_score = 0.0

    # --- Index-Trend (deaktiviert: Leave-One-Out zeigte negativen Effekt) ---
    # Wird nur als Info angezeigt, Vote=0 → kein Einfluss auf Score/Richtung
    if market.get("index_trend") == "bull":
        votes["index_trend"] = {"value": 0, "detail": f"{_idx_name} bullisch (nur Info)"}
    elif market.get("index_trend") == "bear":
        votes["index_trend"] = {"value": 0, "detail": f"{_idx_name} b\u00e4risch (nur Info)"}
    else:
        votes["index_trend"] = {"value": 0, "detail": f"{_idx_name} neutral"}

    # --- VIX-Regime (zusammengeführt aus low/high) ---
    vix_regime = market.get("vix_regime", "normal")
    if vix_regime == "low":
        votes["vix_regime"] = {"value": 0.5, "detail": f"VIX={market.get('vix_level', '?')} (niedrig)"}
    elif vix_regime in ("high", "extreme"):
        votes["vix_regime"] = {"value": -1.0, "detail": f"VIX={market.get('vix_level', '?')} ({vix_regime})"}
    else:
        votes["vix_regime"] = {"value": 0, "detail": f"VIX={market.get('vix_level', '?')} (normal)"}

    # --- Sektor-Trend ---
    if sector_score > 30:
        v = 1.5
        votes["sector_trend"] = {"value": v, "detail": f"Sektor stark ({sector_score:+.0f})"}
    elif sector_score > 10:
        v = 0.5
        votes["sector_trend"] = {"value": v, "detail": f"Sektor leicht positiv ({sector_score:+.0f})"}
    elif sector_score < -30:
        v = -1.5
        votes["sector_trend"] = {"value": v, "detail": f"Sektor schwach ({sector_score:+.0f})"}
    elif sector_score < -10:
        v = -0.5
        votes["sector_trend"] = {"value": v, "detail": f"Sektor leicht negativ ({sector_score:+.0f})"}
    else:
        votes["sector_trend"] = {"value": 0, "detail": f"Sektor neutral ({sector_score:+.0f})"}

    for k in ["index_trend", "vix_regime", "sector_trend"]:
        if k in votes:
            w = weights.get(k, 1.0)
            mkt_score += votes[k]["value"] * w

    # ===== NEWS (1 condition) =====
    n_score = 0.0
    if news_score > 0.5:
        votes["news_sentiment"] = {"value": news_score, "detail": f"Nachrichten positiv ({news_count} Artikel)"}
    elif news_score < -0.5:
        votes["news_sentiment"] = {"value": news_score, "detail": f"Nachrichten negativ ({news_count} Artikel)"}
    else:
        votes["news_sentiment"] = {"value": 0, "detail": f"Nachrichten neutral ({news_count} Artikel)"}

    w = weights.get("news_sentiment", 1.0)
    n_score += votes["news_sentiment"]["value"] * w

    # ===== COMPOSITE =====
    total_score = tech_score + fund_score + mkt_score + n_score

    # Normalize to -100..+100 range
    # 12 conditions, theoretical max ~15 points.
    normalized = max(min(total_score / 15 * 100, 100), -100)

    # Direction – immer LONG oder SHORT, nie NEUTRAL
    direction = "LONG" if normalized > 0 else "SHORT"

    # Confidence (how strong is the signal)
    confidence = min(abs(normalized), 100)

    # ===== VETO-REGELN =====
    # Basierend auf Backtest-Analyse: bestimmte Konstellationen führen
    # überproportional häufig zu Verlierern.
    vetoed = False
    veto_reasons = []

    # Regel 1: MACD-Veto – wenn MACD gegen Signalrichtung stimmt,
    # sind 61.9% der Trades Verlierer. Win-Rate sinkt von 58% auf 38%.
    macd_vote = votes.get("macd_signal", {}).get("value", 0)
    if direction == "LONG" and macd_vote < 0:
        vetoed = True
        veto_reasons.append("MACD gegen LONG (Momentum fehlt)")
    elif direction == "SHORT" and macd_vote > 0:
        vetoed = True
        veto_reasons.append("MACD gegen SHORT (Momentum dagegen)")

    # Regel 2: Zu viele Gegen-Stimmen – wenn ≥2 Bedingungen gegen
    # die Signalrichtung stimmen, sinkt die Win-Rate auf 35.7%.
    n_against = 0
    for k, v_dict in votes.items():
        val = v_dict.get("value", 0)
        if val == 0:
            continue
        vote_bullish = val > 0
        signal_long = direction == "LONG"
        if vote_bullish != signal_long:
            n_against += 1
    if n_against >= 2:
        vetoed = True
        veto_reasons.append(f"{n_against} Bedingungen gegen Signalrichtung")

    # Regel 3: Marktumfeld-Veto – Nur LONG im Bullenmarkt handeln.
    # Backtest-Analyse März 2026 (Stufe 5):
    #   Nur LONG/bull + VIX<25: 45.7% Win, +2.84% Ø P&L, Effizienz 13.0
    #   vs. kein Filter:        35.5% Win, +0.65% Ø P&L, Effizienz 3.6
    # SHORT-Trades haben in keinem Marktumfeld zuverlässig funktioniert.
    # Neutral/Bear-LONG hat 16-18% Win-Rate → Geldverbrennung.
    index_trend = market.get("index_trend", "neutral")
    _skip_market_veto = market.get("_skip_market_veto", False)
    if not _skip_market_veto:
        if direction == "SHORT":
            vetoed = True
            veto_reasons.append("SHORT deaktiviert (keine zuverlässige Performance)")
        elif index_trend != "bull":
            vetoed = True
            veto_reasons.append(f"LONG nur im Bullenmarkt (aktuell: {index_trend})")

        # Regel 4: VIX-Veto – bei hoher Volatilität (VIX ≥ 25) sind
        # Stops unzuverlässig und die Win-Rate sinkt auf 25%.
        vix_regime_veto = market.get("vix_regime", "normal")
        if vix_regime_veto in ("high", "extreme"):
            vetoed = True
            veto_reasons.append(f"VIX zu hoch ({market.get('vix_level', '?')}, Regime: {vix_regime_veto})")

    # Serialize votes for storage
    votes_json = json.dumps(
        {k: {"value": v["value"], "detail": v["detail"]}
         for k, v in votes.items() if v["value"] != 0 or v["detail"]},
        ensure_ascii=False,
    )

    return {
        "direction": direction,
        "score": round(normalized, 1),
        "confidence": round(confidence, 1),
        "tech_score": round(tech_score, 2),
        "fund_score": round(fund_score, 2),
        "market_score": round(mkt_score, 2),
        "news_score": round(n_score, 2),
        "votes_detail": votes_json,
        "vetoed": vetoed,
        "veto_reasons": veto_reasons,
    }
