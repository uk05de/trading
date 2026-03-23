"""
fundamentals.py – Earnings dates, analyst ratings, and company fundamentals.

Uses yfinance Ticker objects. Handles missing data gracefully since
German stocks (.DE) often have incomplete coverage.
"""

from __future__ import annotations

import datetime as dt
import numpy as np
import yfinance as yf


def get_fundamentals(ticker_str: str) -> dict:
    """
    Fetch fundamental data for a ticker. Returns a dict with:
      - earnings_date: next earnings date or None
      - days_to_earnings: int or None
      - eps_estimate: float or None
      - eps_actual_prev: float or None
      - analyst_rating: str or None  (e.g. 'Buy', 'Hold', 'Sell')
      - analyst_target: float or None
      - analyst_target_upside_pct: float or None
      - forward_pe: float or None
      - trailing_pe: float or None
      - market_cap: float or None
      - dividend_yield: float or None
    """
    result = {
        "earnings_date": None,
        "days_to_earnings": None,
        "eps_estimate": None,
        "eps_surprise_prev": None,
        "analyst_rating": None,
        "analyst_count": 0,
        "analyst_target": None,
        "analyst_target_upside_pct": None,
        "forward_pe": None,
        "trailing_pe": None,
        "market_cap": None,
        "dividend_yield": None,
        "sector": None,
        "industry": None,
    }

    # Indices have no fundamentals – skip API calls to avoid 404 errors
    if ticker_str.startswith("^"):
        return result

    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}
    except Exception:
        return result

    # Basic info
    result["forward_pe"] = info.get("forwardPE")
    result["trailing_pe"] = info.get("trailingPE")
    result["market_cap"] = info.get("marketCap")
    result["dividend_yield"] = info.get("dividendYield")
    result["sector"] = info.get("sector")
    result["industry"] = info.get("industry")

    # Analyst recommendations
    result["analyst_rating"] = info.get("recommendationKey")
    result["analyst_count"] = info.get("numberOfAnalystOpinions", 0) or 0

    # Analyst price target
    target = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and current and current > 0:
        result["analyst_target"] = target
        result["analyst_target_upside_pct"] = (target - current) / current * 100

    # Earnings dates
    try:
        cal = tk.calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    next_date = ed[0] if isinstance(ed, list) else ed
                    if hasattr(next_date, "date"):
                        result["earnings_date"] = next_date.strftime("%Y-%m-%d")
                        result["days_to_earnings"] = (next_date.date() - dt.date.today()).days
            elif hasattr(cal, "columns"):
                # DataFrame format
                if "Earnings Date" in cal.columns:
                    dates = cal["Earnings Date"].dropna()
                    if len(dates) > 0:
                        next_date = dates.iloc[0]
                        if hasattr(next_date, "date"):
                            result["earnings_date"] = next_date.strftime("%Y-%m-%d")
                            result["days_to_earnings"] = (next_date.date() - dt.date.today()).days
    except Exception:
        pass

    # EPS estimate & previous surprise
    try:
        ed = tk.earnings_dates
        if ed is not None and len(ed) > 0:
            # Future dates have estimates, past dates have actuals
            future = ed[ed.index >= dt.datetime.now(dt.timezone.utc)]
            past = ed[ed.index < dt.datetime.now(dt.timezone.utc)]

            if len(future) > 0 and "EPS Estimate" in future.columns:
                est = future["EPS Estimate"].dropna()
                if len(est) > 0:
                    result["eps_estimate"] = float(est.iloc[0])

            if len(past) > 0 and "Surprise(%)" in past.columns:
                surprise = past["Surprise(%)"].dropna()
                if len(surprise) > 0:
                    result["eps_surprise_prev"] = float(surprise.iloc[0])
    except Exception:
        pass

    return result


def earnings_signal(fundamentals: dict) -> tuple[float, str]:
    """
    Score earnings-related signal (-2 to +2).
    Returns (score, explanation).
    """
    dte = fundamentals.get("days_to_earnings")
    if dte is None:
        return 0.0, "Kein Earnings-Datum bekannt"

    if dte < 0:
        return 0.0, "Earnings bereits vorbei"

    if dte > 21:
        return 0.0, f"Earnings in {dte} Tagen (zu weit weg)"

    # Within 21 days of earnings
    surprise = fundamentals.get("eps_surprise_prev")
    eps_est = fundamentals.get("eps_estimate")

    if dte <= 7:
        # Very close to earnings – high uncertainty
        if surprise is not None and surprise > 10:
            return 1.0, f"Earnings in {dte}d, letzte Überraschung +{surprise:.0f}%"
        elif surprise is not None and surprise < -10:
            return -1.0, f"Earnings in {dte}d, letzte Überraschung {surprise:.0f}%"
        else:
            return 0.0, f"Earnings in {dte}d – Vorsicht, hohe Unsicherheit"

    # 7-21 days out
    if surprise is not None and surprise > 15:
        return 1.5, f"Earnings in {dte}d, stark positive Historie (+{surprise:.0f}%)"
    elif surprise is not None and surprise < -15:
        return -1.5, f"Earnings in {dte}d, stark negative Historie ({surprise:.0f}%)"

    return 0.0, f"Earnings in {dte}d"


def analyst_signal(fundamentals: dict) -> tuple[float, str]:
    """Score based on analyst consensus (-2 to +2)."""
    rating = fundamentals.get("analyst_rating")
    upside = fundamentals.get("analyst_target_upside_pct")
    count = fundamentals.get("analyst_count", 0)

    score = 0.0
    parts = []

    if rating:
        rating_scores = {
            "strong_buy": 2.0, "buy": 1.5, "outperform": 1.0,
            "hold": 0.0, "neutral": 0.0,
            "underperform": -1.0, "sell": -1.5, "strong_sell": -2.0,
        }
        score += rating_scores.get(rating.lower().replace(" ", "_"), 0)
        parts.append(f"Rating: {rating} ({count} Analysten)")

    if upside is not None:
        if upside > 20:
            score += 1.0
            parts.append(f"Kursziel +{upside:.0f}% über aktuellem Kurs")
        elif upside < -10:
            score -= 1.0
            parts.append(f"Kursziel {upside:.0f}% unter aktuellem Kurs")
        else:
            parts.append(f"Kursziel {upside:+.0f}%")

    explanation = "; ".join(parts) if parts else "Keine Analystenabdeckung"
    return min(max(score, -2), 2), explanation


def get_upcoming_events(ticker_str: str) -> list[dict]:
    """
    Fetch upcoming events/dates for a ticker.
    Returns a list of {date, type, detail} dicts sorted by date.
    """
    events = []

    if ticker_str.startswith("^"):
        return events

    try:
        tk = yf.Ticker(ticker_str)
        info = tk.info or {}
    except Exception:
        return events

    # Earnings date
    try:
        cal = tk.calendar
        if cal is not None:
            if isinstance(cal, dict):
                for key in ["Earnings Date", "Ex-Dividend Date", "Dividend Date"]:
                    val = cal.get(key)
                    if val:
                        dates = val if isinstance(val, list) else [val]
                        for d in dates:
                            if hasattr(d, "strftime"):
                                events.append({
                                    "date": d.strftime("%Y-%m-%d"),
                                    "type": key,
                                    "detail": "",
                                })
            elif hasattr(cal, "index"):
                for key in cal.index:
                    val = cal.loc[key]
                    if hasattr(val, "strftime"):
                        events.append({
                            "date": val.strftime("%Y-%m-%d"),
                            "type": str(key),
                            "detail": "",
                        })
                    elif isinstance(val, list):
                        for d in val:
                            if hasattr(d, "strftime"):
                                events.append({
                                    "date": d.strftime("%Y-%m-%d"),
                                    "type": str(key),
                                    "detail": "",
                                })
    except Exception:
        pass

    # Upcoming earnings from earnings_dates
    try:
        ed = tk.earnings_dates
        if ed is not None and len(ed) > 0:
            future = ed[ed.index >= dt.datetime.now(dt.timezone.utc)]
            for idx, row in future.head(3).iterrows():
                date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
                eps_est = row.get("EPS Estimate")
                detail = f"EPS-Schätzung: {eps_est:.2f}" if eps_est and not np.isnan(eps_est) else ""
                # Avoid duplicates
                if not any(e["date"] == date_str and "Earnings" in e["type"] for e in events):
                    events.append({
                        "date": date_str,
                        "type": "Quartalszahlen",
                        "detail": detail,
                    })
    except Exception:
        pass

    # Ex-dividend from info
    try:
        ex_div = info.get("exDividendDate")
        if ex_div:
            ex_date = dt.datetime.fromtimestamp(ex_div)
            if ex_date.date() >= dt.date.today():
                div_rate = info.get("dividendRate", "")
                detail = f"Dividende: {div_rate:.2f} €" if div_rate else ""
                if not any(e["type"] == "Ex-Dividend Date" for e in events):
                    events.append({
                        "date": ex_date.strftime("%Y-%m-%d"),
                        "type": "Ex-Dividende",
                        "detail": detail,
                    })
    except Exception:
        pass

    # Sort by date
    events.sort(key=lambda e: e["date"])

    # Translate event types to German
    translations = {
        "Earnings Date": "Quartalszahlen",
        "Ex-Dividend Date": "Ex-Dividende",
        "Dividend Date": "Dividendenzahlung",
    }
    for e in events:
        e["type"] = translations.get(e["type"], e["type"])

    return events
