"""
ko_calc.py – Knock-Out Zertifikat Umrechnung.

Rechnet zwischen Basiswert (Aktie) und KO-Produkt um.

KO Long (Bull):  Produktpreis = (Aktienkurs - KO-Schwelle) × BV
KO Short (Bear): Produktpreis = (KO-Schwelle - Aktienkurs) × BV

BV = Bezugsverhältnis (z.B. 0.1 bedeutet 10 Zertifikate = 1 Aktie)
"""


def stock_to_product(stock_price: float, ko_level: float,
                     direction: str, bv: float = 1.0) -> float:
    """Aktienkurs → Produktpreis."""
    if direction == "LONG":
        return max(0, (stock_price - ko_level) * bv)
    else:  # SHORT
        return max(0, (ko_level - stock_price) * bv)


def product_to_stock(product_price: float, ko_level: float,
                     direction: str, bv: float = 1.0) -> float:
    """Produktpreis → Aktienkurs."""
    if bv <= 0:
        return 0
    if direction == "LONG":
        return ko_level + product_price / bv
    else:  # SHORT
        return ko_level - product_price / bv


def calc_leverage(stock_price: float, ko_level: float,
                  direction: str) -> float:
    """Aktuellen Hebel berechnen."""
    if direction == "LONG":
        diff = stock_price - ko_level
    else:
        diff = ko_level - stock_price
    if diff <= 0:
        return float("inf")
    return stock_price / diff


def convert_targets(stock_stop: float, stock_target: float,
                    ko_level: float, direction: str,
                    bv: float = 1.0) -> dict:
    """
    Aktien-Stop/Ziel in Produktpreise umrechnen.

    Returns dict with:
        product_stop, product_target,
        ko_distance_pct (Abstand zum KO in %)
    """
    product_stop = stock_to_product(stock_stop, ko_level, direction, bv)
    product_target = stock_to_product(stock_target, ko_level, direction, bv)

    # Abstand zum Knock-Out
    if direction == "LONG":
        ko_distance_pct = (stock_stop - ko_level) / stock_stop * 100 if stock_stop > 0 else 0
    else:
        ko_distance_pct = (ko_level - stock_stop) / stock_stop * 100 if stock_stop > 0 else 0

    return {
        "product_stop": round(product_stop, 4),
        "product_target": round(product_target, 4),
        "ko_distance_pct": round(ko_distance_pct, 1),
    }


def trade_summary(entry_product: float, size: float,
                  stock_price: float, ko_level: float,
                  direction: str, bv: float,
                  stock_stop: float = None,
                  stock_target: float = None) -> dict:
    """
    Vollständige Übersicht für einen KO-Trade.

    Args:
        entry_product: Kaufpreis des Zertifikats
        size: Anzahl Zertifikate
        stock_price: Aktueller Aktienkurs
        ko_level: Knock-Out-Schwelle
        direction: LONG/SHORT
        bv: Bezugsverhältnis
        stock_stop: Stop-Loss auf Aktienebene
        stock_target: Kursziel auf Aktienebene
    """
    invest = entry_product * size
    current_product = stock_to_product(stock_price, ko_level, direction, bv)
    leverage = calc_leverage(stock_price, ko_level, direction)

    # P/L
    pnl_pct = (current_product - entry_product) / entry_product * 100 if entry_product > 0 else 0
    pnl_abs = (current_product - entry_product) * size

    result = {
        "invest": round(invest, 2),
        "current_product": round(current_product, 4),
        "leverage": round(leverage, 1),
        "pnl_pct": round(pnl_pct, 2),
        "pnl_abs": round(pnl_abs, 2),
    }

    # Stop/Target auf Produktebene
    if stock_stop:
        result["product_stop"] = round(
            stock_to_product(stock_stop, ko_level, direction, bv), 4)
        result["stop_loss_abs"] = round(
            (result["product_stop"] - entry_product) * size, 2)
    if stock_target:
        result["product_target"] = round(
            stock_to_product(stock_target, ko_level, direction, bv), 4)
        result["target_gain_abs"] = round(
            (result["product_target"] - entry_product) * size, 2)

    # Totalverlust-Abstand
    if direction == "LONG":
        ko_distance = (stock_price - ko_level) / stock_price * 100
    else:
        ko_distance = (ko_level - stock_price) / stock_price * 100
    result["ko_distance_pct"] = round(ko_distance, 1)

    return result
