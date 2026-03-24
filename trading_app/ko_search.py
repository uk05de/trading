"""
ko_search.py – KO-Zertifikat Suche + Lookup via onvista API.

Funktionen:
  - search_ko():           Passende KO-Zertifikate fuer ein Signal suchen
  - lookup_isin():         Produktdetails per ISIN von onvista holen
  - calc_ideal_ko():       Ideales KO-Level aus Signal + Max-Verlust berechnen
  - evaluate_product():    Konkretes Produkt gegen Signal-Parameter pruefen
  - refresh_product_price(): Aktuellen Bid-Kurs eines Produkts holen
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import requests

log = logging.getLogger(__name__)

ONVISTA_BASE = "https://api.onvista.de/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
TIMEOUT = 10

# Trade Republic Emittenten
TRADE_REPUBLIC_ISSUERS = {
    53882: "HSBC",
    53159: "Société Générale",
    54101: "Vontobel",
}
DEFAULT_ISSUER_IDS = ",".join(str(k) for k in TRADE_REPUBLIC_ISSUERS)

# KO-Puffer: Mindestabstand zwischen SL und KO (in % vom SL)
KO_BUFFER_PCT = 3.0

# Cache: {isin: (timestamp, data)} – vermeidet doppelte API-Calls
_cache: dict[str, tuple[float, dict | None]] = {}
CACHE_TTL = 300  # 5 Minuten


def _get_cached(isin: str) -> dict | None:
    """Return cached result if still fresh, else None."""
    if isin in _cache:
        ts, data = _cache[isin]
        if time.time() - ts < CACHE_TTL:
            return data
    return None


def _set_cache(isin: str, data: dict | None):
    _cache[isin] = (time.time(), data)


def clear_price_cache():
    """Clear the ISIN lookup cache to force fresh API calls."""
    _cache.clear()


# ---------------------------------------------------------------------------
# KO-Zertifikat Suche
# ---------------------------------------------------------------------------

def _get_underlying_name(ticker: str) -> str:
    """Ticker → onvista URL-Name fuer den Referrer (z.B. SAP.DE → SAP)."""
    # .DE/.F Suffix entfernen
    clean = ticker.split(".")[0]
    # Mapping fuer bekannte Ticker die anders heissen
    name_map = {
        "1COV": "Covestro", "VOW3": "Volkswagen-VZ",
        "MBG": "Mercedes-Benz-Group", "DHL": "DHL-Group",
        "EOAN": "E-ON", "SY1": "Symrise", "HEN3": "Henkel-VZ",
        "PAH3": "Porsche-Automobil-Holding-VZ",
    }
    return name_map.get(clean, clean)


def search_ko(ticker: str, entry: float, stop_loss: float,
              direction: str = "LONG",
              ko_buffer_pct: float = KO_BUFFER_PCT,
              max_results: int = 5,
              issuer_ids: str = DEFAULT_ISSUER_IDS) -> list[dict]:
    """
    Suche passende KO-Zertifikate fuer ein Signal.

    Args:
        ticker: Aktien-Ticker (z.B. SAP.DE)
        entry: Einstiegskurs Basiswert
        stop_loss: Stop-Loss Basiswert
        direction: LONG oder SHORT
        ko_buffer_pct: Mindestabstand KO unter SL in %
        max_results: Max Anzahl Ergebnisse
        issuer_ids: Komma-separierte Emittenten-IDs

    Returns:
        Liste von Dicts mit: isin, wkn, name, emittent, ko_level, bid, ask,
        hebel, spread_pct, ko_abstand_pct, bv, open_end
    """
    if direction == "LONG":
        # KO muss unter SL liegen, mit Puffer
        ko_max = stop_loss * (1 - ko_buffer_pct / 100)
        # KO nicht zu weit weg (sonst zu wenig Hebel) — max 20% unter Entry
        ko_min = entry * 0.80
        exercise_right = 2  # CALL
    else:
        ko_max = entry * 1.20
        ko_min = stop_loss * (1 + ko_buffer_pct / 100)
        exercise_right = 1  # PUT

    # Query-Parameter zusammenbauen
    query_params = (
        f"entitySubType=KNOCKOUT_CERTIFICATE"
        f"&openEnded=1"
        f"&idExerciseRight={exercise_right}"
        f"&idIssuer={issuer_ids}"
        f"&knockOutAbsRange={ko_min:.1f};{ko_max:.1f}"
    )

    ul_name = _get_underlying_name(ticker)
    referrer = f"/derivate/Knock-Outs/Knock-Outs-auf-{ul_name}"

    url = (
        f"{ONVISTA_BASE}/derivatives/finder/configuration_query"
        f"?application=WEBSITE&device=DESKTOP"
        f"&page=0&perPage={max_results}"
        f"&queryParameters={urllib.parse.quote(query_params)}"
        f"&referrer={urllib.parse.quote(referrer)}"
    )

    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.warning("KO-Suche fehlgeschlagen fuer %s: %s", ticker, e)
        return []

    results = []
    for item in data.get("list", []):
        instr = item.get("instrument", {})
        quote = item.get("quote", {})
        issuer = item.get("issuer", {})

        ko_level = item.get("knockOutAbs")
        bid = quote.get("bid")
        ask = quote.get("ask")

        if not ko_level or not bid:
            continue

        # Hebel berechnen
        if direction == "LONG":
            hebel = entry / (entry - ko_level) if entry > ko_level else 0
            ko_abstand = (stop_loss - ko_level) / stop_loss * 100
        else:
            hebel = entry / (ko_level - entry) if ko_level > entry else 0
            ko_abstand = (ko_level - stop_loss) / stop_loss * 100

        results.append({
            "isin": instr.get("isin"),
            "wkn": instr.get("wkn"),
            "name": item.get("shortName", instr.get("name", "")),
            "emittent": issuer.get("name", ""),
            "ko_level": round(ko_level, 2),
            "bid": bid,
            "ask": ask,
            "hebel": round(hebel, 1),
            "spread_pct": round(item.get("spreadAskPct", 0), 2),
            "ko_abstand_sl_pct": round(ko_abstand, 1),
            "bv": item.get("coverRatio", 1.0),
            "open_end": item.get("openEnded", False),
            "direction": "LONG" if item.get("nameExerciseRight") == "CALL" else "SHORT",
        })

    # Sortieren nach Spread (niedrigster zuerst)
    results.sort(key=lambda x: x["spread_pct"])

    return results[:max_results]


# ---------------------------------------------------------------------------
# ISIN Lookup via onvista
# ---------------------------------------------------------------------------

def lookup_isin(isin: str) -> dict | None:
    """
    Fetch KO certificate details from onvista by ISIN.

    Returns dict with:
        isin, wkn, name, underlying, underlying_isin,
        direction (LONG/SHORT), ko_level, bv, bid, leverage,
        emittent, open_end, product_type, underlying_price,
        ko_distance_pct, intrinsic_value
    """
    cached = _get_cached(isin)
    if cached is not None:
        return cached

    try:
        url = f"{ONVISTA_BASE}/derivatives/ISIN:{isin}/snapshot"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.warning("ISIN lookup fehlgeschlagen für %s: %s", isin, e)
        return None

    try:
        instr = data.get("instrument", {})
        details = data.get("derivativesDetails", {})
        figure = data.get("derivativesFigure", {})
        issuer = data.get("derivativesIssuer", {})
        quote = data.get("quote", {})

        # Underlying
        ul_list = data.get("derivativesUnderlyingList", {}).get("list", [])
        ul = ul_list[0] if ul_list else {}
        ul_instr = ul.get("instrument", {})

        # BV (Bezugsverhältnis / Cover Ratio)
        bv = ul.get("coverRatio", 1.0)

        # KO-Schwelle aus Barrier-Liste
        ko_level = None
        barriers = ul.get("derivativesBarrierList", {}).get("list", [])
        for barrier in barriers:
            if barrier.get("typeBarrier") == "KNOCK_OUT":
                ko_level = barrier["barrier"]
                break
        # Fallback: Strike
        if ko_level is None:
            for barrier in barriers:
                if barrier.get("typeBarrier") == "STRIKE":
                    ko_level = barrier["barrier"]
                    break

        # Richtung: CALL = LONG, PUT = SHORT
        exercise_right = details.get("nameExerciseRight", "")
        direction = "LONG" if exercise_right == "CALL" else "SHORT"

        result = {
            "isin": instr.get("isin", isin),
            "wkn": instr.get("wkn"),
            "name": details.get("shortName") or instr.get("name"),
            "underlying": ul_instr.get("name"),
            "underlying_isin": ul_instr.get("isin"),
            "direction": direction,
            "ko_level": ko_level,
            "bv": bv,
            "bid": quote.get("bid"),
            "leverage": figure.get("gearingBid"),
            "emittent": issuer.get("name"),
            "open_end": details.get("openEnded", False),
            "product_type": details.get("nameSubcategory"),
            "underlying_price": figure.get("priceUnderlying"),
            "ko_distance_pct": figure.get("differenceKnockoutPct"),
            "intrinsic_value": figure.get("intrinsicValue"),
        }
        _set_cache(isin, result)
        return result

    except (KeyError, IndexError, TypeError) as e:
        log.warning("Fehler beim Parsen der onvista-Daten für %s: %s", isin, e)
        return None


def refresh_product_price(isin: str) -> dict | None:
    """
    Quick lookup: nur aktuellen Bid-Kurs und Underlying-Preis holen.

    Nutzt den vollen lookup_isin() mit Cache, extrahiert nur Preis-Felder.
    Returns dict with: bid, underlying_price, ko_distance_pct, leverage
    """
    product = lookup_isin(isin)
    if not product:
        return None
    return {
        "bid": product.get("bid"),
        "underlying_price": product.get("underlying_price"),
        "ko_distance_pct": product.get("ko_distance_pct"),
        "leverage": product.get("leverage"),
    }


# ---------------------------------------------------------------------------
# Ideales KO-Level berechnen
# ---------------------------------------------------------------------------

def calc_ideal_ko(entry: float, stop_loss: float, direction: str,
                  max_loss_pct: float = 0.30) -> dict:
    """
    Berechne das ideale KO-Level aus Entry, Stop-Loss und max. Verlust.

    Formel LONG:  KO = Entry - (Entry - SL) / max_loss_pct
    Formel SHORT: KO = Entry + (SL - Entry) / max_loss_pct

    Returns dict mit: ko_ideal, leverage, max_loss_at_sl_pct,
                      risk_stock_pct, ko_range_min, ko_range_max
    """
    if direction == "LONG":
        risk = entry - stop_loss
        if risk <= 0:
            return {"error": "Stop-Loss muss unter Entry liegen (LONG)"}
        ko_ideal = entry - risk / max_loss_pct
        leverage = entry / (entry - ko_ideal)
    else:  # SHORT
        risk = stop_loss - entry
        if risk <= 0:
            return {"error": "Stop-Loss muss über Entry liegen (SHORT)"}
        ko_ideal = entry + risk / max_loss_pct
        leverage = entry / (ko_ideal - entry)

    # Sinnvoller Bereich: ±5% um das Ideal
    # Enger = mehr Hebel (mehr Verlust bei SL), weiter = weniger Hebel (weniger Verlust)
    if direction == "LONG":
        # KO näher an Entry = mehr Hebel
        ko_range_max = ko_ideal * 1.02   # etwas näher → max ~32% Verlust
        ko_range_min = ko_ideal * 0.95   # weiter weg → ca. 27% Verlust
    else:
        ko_range_min = ko_ideal * 0.98
        ko_range_max = ko_ideal * 1.05

    return {
        "ko_ideal": round(ko_ideal, 2),
        "leverage": round(leverage, 1),
        "max_loss_at_sl_pct": round(max_loss_pct * 100, 1),
        "risk_stock_pct": round(risk / entry * 100, 2),
        "ko_range_min": round(ko_range_min, 2),
        "ko_range_max": round(ko_range_max, 2),
    }


# ---------------------------------------------------------------------------
# Produkt bewerten (nach ISIN-Lookup)
# ---------------------------------------------------------------------------

def evaluate_product(ko_level: float, bv: float,
                     entry: float, stop_loss: float, target: float,
                     direction: str, max_loss_pct: float = 0.30) -> dict:
    """
    Bewerte ein konkretes KO-Produkt gegen die Signal-Parameter.

    Berechnet:
      - Produktpreise bei Entry, SL, Ziel
      - Tatsächlicher Verlust bei SL
      - Gewinn bei Ziel
      - Hebel
      - Ob das Produkt innerhalb der Max-Verlust-Grenze liegt
      - KO-Abstand zum SL
    """
    from ko_calc import stock_to_product, calc_leverage

    product_entry = stock_to_product(entry, ko_level, direction, bv)
    product_sl = stock_to_product(stop_loss, ko_level, direction, bv)
    product_target = stock_to_product(target, ko_level, direction, bv)

    # Verlust bei SL
    if product_entry > 0:
        loss_at_sl = (product_sl - product_entry) / product_entry
        gain_at_target = (product_target - product_entry) / product_entry
    else:
        loss_at_sl = -1.0
        gain_at_target = 0.0

    leverage = calc_leverage(entry, ko_level, direction)

    # KO-Abstand vom SL (wie viel Puffer hat man?)
    if direction == "LONG":
        ko_sl_distance = stop_loss - ko_level
        ko_sl_distance_pct = ko_sl_distance / stop_loss * 100 if stop_loss > 0 else 0
        ko_entry_distance_pct = (entry - ko_level) / entry * 100
    else:
        ko_sl_distance = ko_level - stop_loss
        ko_sl_distance_pct = ko_sl_distance / stop_loss * 100 if stop_loss > 0 else 0
        ko_entry_distance_pct = (ko_level - entry) / entry * 100

    # Prüfung: liegt der Verlust innerhalb der Grenze?
    within_max_loss = round(abs(loss_at_sl) * 100, 1) <= round(max_loss_pct * 100, 1)
    # Prüfung: ist der KO sicher unter/über dem SL?
    ko_safe = ko_sl_distance > 0

    return {
        "product_entry": round(product_entry, 4),
        "product_sl": round(product_sl, 4),
        "product_target": round(product_target, 4),
        "loss_at_sl_pct": round(loss_at_sl * 100, 1),
        "gain_at_target_pct": round(gain_at_target * 100, 1),
        "leverage": round(leverage, 1),
        "ko_sl_distance_pct": round(ko_sl_distance_pct, 1),
        "ko_entry_distance_pct": round(ko_entry_distance_pct, 1),
        "within_max_loss": within_max_loss,
        "ko_safe": ko_safe,
    }
