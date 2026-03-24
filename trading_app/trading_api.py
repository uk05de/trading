"""
trading_api.py – Minimaler REST-API Server fuer HA Integration.

Laeuft parallel zu Streamlit auf Port 8502.
Endpoints:
  GET /api/status     → Portfolio-Uebersicht + Trade-Alerts
  POST /api/refresh   → Trades aktualisieren (Kurse + Bids)
"""

from __future__ import annotations

import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger(__name__)


def _get_trade_status() -> dict:
    """Berechne aktuellen Trade-Status fuer HA Sensoren."""
    from db import get_trades, get_free_cash
    from ko_calc import stock_to_product

    open_trades = get_trades(status="OPEN")
    cash = get_free_cash()

    trades = []
    alerts = []

    for t in open_trades:
        ko = t.get("ko_level")
        bv = t.get("bv") or 1.0
        d = t["direction"]
        entry_stock = t["entry_price"]
        cur_stock = t.get("current_price") or entry_stock
        sl = t.get("stop_loss")
        bid = t.get("product_bid")

        # Profit R berechnen
        profit_r = None
        if sl and ko and entry_stock:
            ep = stock_to_product(entry_stock, ko, d, bv)
            sp = stock_to_product(sl, ko, d, bv)
            cp = bid if bid else stock_to_product(cur_stock, ko, d, bv)
            risk = abs(ep - sp)
            profit = cp - ep
            profit_r = round(profit / risk, 2) if risk > 0 else None

        trade_info = {
            "id": t["id"],
            "ticker": t["ticker"],
            "name": t["name"],
            "direction": d,
            "profit_r": profit_r,
            "product_bid": bid,
            "entry_price": entry_stock,
            "current_price": cur_stock,
            "stop_loss": sl,
            "target": t.get("target"),
        }
        trades.append(trade_info)

        # Alerts
        if profit_r is not None:
            if profit_r <= -1.0:
                alerts.append({
                    "type": "sl_breach",
                    "severity": "critical",
                    "message": f"{t['name']}: SL DURCHBROCHEN ({profit_r:+.2f}R)",
                    "trade_id": t["id"],
                    "profit_r": profit_r,
                })
            elif profit_r <= -0.8:
                alerts.append({
                    "type": "sl_warning",
                    "severity": "warning",
                    "message": f"{t['name']}: Nahe SL ({profit_r:+.2f}R)",
                    "trade_id": t["id"],
                    "profit_r": profit_r,
                })
            elif profit_r >= 2.0:
                alerts.append({
                    "type": "target_hit",
                    "severity": "info",
                    "message": f"{t['name']}: TARGET erreicht ({profit_r:+.2f}R)",
                    "trade_id": t["id"],
                    "profit_r": profit_r,
                })
            elif profit_r >= 1.5:
                alerts.append({
                    "type": "target_near",
                    "severity": "info",
                    "message": f"{t['name']}: Nahe Target ({profit_r:+.2f}R)",
                    "trade_id": t["id"],
                    "profit_r": profit_r,
                })

    return {
        "open_trades": len(trades),
        "trades": trades,
        "alerts": alerts,
        "has_critical": any(a["severity"] == "critical" for a in alerts),
        "has_warning": any(a["severity"] == "warning" for a in alerts),
        "cash": cash.get("balance", 0),
        "portfolio": cash.get("portfolio_value", 0),
    }


def _refresh_trades() -> dict:
    """Trades aktualisieren und Status zurueckgeben."""
    from scanner import refresh_open_trades
    n = refresh_open_trades()
    status = _get_trade_status()
    status["refreshed"] = n
    return status


class TradingAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            data = _get_trade_status()
            self._send_json(data)
        elif self.path == "/api/health":
            self._send_json({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/refresh":
            data = _refresh_trades()
            self._send_json(data)
        else:
            self.send_error(404)

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        log.info(format, *args)


def run_api(port: int = 8502):
    """Starte den API-Server."""
    server = HTTPServer(("0.0.0.0", port), TradingAPIHandler)
    log.info("Trading API gestartet auf Port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_api()
