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


def _full_scan() -> dict:
    """Voller Scan: neue Signale suchen + Trades aktualisieren."""
    try:
        from scanner import run_scan
        import streamlit as st
        st.cache_data.clear()
        result = run_scan()
        n_signals = len(result[0]) if result and len(result) > 0 else 0
    except Exception as e:
        log.warning("Full Scan Fehler: %s", e)
        n_signals = 0
    status = _get_trade_status()
    status["scan_signals"] = n_signals
    return status


class TradingAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            data = _get_trade_status()
            self._send_json(data)
        elif self.path == "/api/health":
            self._send_json({"status": "ok"})
        elif self.path == "/api/debug/sectors":
            from sectors import compute_sector_scores
            from db import _connect
            conn = _connect()
            n_prices = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            n_tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
            latest = conn.execute("SELECT MAX(date) FROM prices").fetchone()[0]
            conn.close()
            # Prüfe ob DB-Ticker in SECTOR_MAP matchen
            from markets import SECTOR_MAP
            db_tickers = [r[0] for r in conn.execute(
                "SELECT DISTINCT ticker FROM prices WHERE date >= '2026-03-20' LIMIT 20").fetchall()]
            mapped = [t for t in db_tickers if t in SECTOR_MAP]
            unmapped = [t for t in db_tickers if t not in SECTOR_MAP]
            conn.close()

            scores = compute_sector_scores()
            self._send_json({
                "n_prices": n_prices,
                "n_tickers": n_tickers,
                "latest_date": latest,
                "n_sectors": sum(1 for d in scores.values() if not d.get("is_index")),
                "n_indices": sum(1 for d in scores.values() if d.get("is_index")),
                "db_tickers_sample": db_tickers,
                "mapped": mapped,
                "unmapped": unmapped,
                "sector_map_sample": dict(list(SECTOR_MAP.items())[:5]),
                "sectors": {k: {"score": v["score"], "n": v["n_tickers"]}
                            for k, v in scores.items()},
            })
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/refresh":
            data = _refresh_trades()
            self._send_json(data)
        elif self.path == "/api/scan":
            data = _full_scan()
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


def _setup_ha_automations():
    """Lege HA Automationen automatisch an (einmalig beim Start)."""
    import os
    import requests as req

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Kein SUPERVISOR_TOKEN — HA Automationen nicht angelegt (lokaler Modus)")
        return

    ha_url = "http://supervisor/core/api"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Prüfe ob unsere Automationen schon existieren
    try:
        resp = req.get(f"{ha_url}/states", headers=headers, timeout=5)
        existing = {s["entity_id"] for s in resp.json()}
    except Exception as e:
        log.warning("HA API nicht erreichbar: %s", e)
        return

    # Config aus Add-on Options lesen
    notify_service = "notify.notify"
    full_scan_interval = 60
    refresh_interval = 15
    try:
        with open("/data/options.json") as f:
            options = json.load(f)
            notify_service = options.get("notify_service") or notify_service
            full_scan_interval = options.get("full_scan_interval_minutes", 60)
            refresh_interval = options.get("refresh_interval_minutes", 15)
    except FileNotFoundError:
        log.info("Keine options.json — nutze Defaults")
    log.info("Config: notify=%s, full_scan=%dmin, refresh=%dmin",
             notify_service, full_scan_interval, refresh_interval)

    automations = [
        {
            "id": "trading_refresh_trades",
            "alias": "Trading: Kurse aktualisieren",
            "description": f"Aktualisiert Trades alle {refresh_interval} Min (08:00-22:00)",
            "mode": "single",
            "trigger": [{"platform": "time_pattern", "minutes": f"/{refresh_interval}"}],
            "condition": [{"condition": "time", "after": "08:00:00", "before": "22:00:00"}],
            "action": [{"service": "rest_command.trading_refresh"}],
        },
        {
            "id": "trading_full_scan",
            "alias": "Trading: Voller Scan",
            "description": f"Sucht neue Signale alle {full_scan_interval} Min (09:00-18:00)",
            "mode": "single",
            "trigger": [{"platform": "time_pattern", "minutes": f"/{full_scan_interval}"}],
            "condition": [{"condition": "time", "after": "09:00:00", "before": "18:00:00"}],
            "action": [{"service": "rest_command.trading_scan"}],
        },
        {
            "id": "trading_sl_warning",
            "alias": "Trading: SL Warnung",
            "description": "Notification wenn ein Trade nahe am SL ist",
            "mode": "single",
            "trigger": [{"platform": "state", "entity_id": "sensor.trading_open_trades"}],
            "condition": [{
                "condition": "template",
                "value_template": "{{ state_attr('sensor.trading_open_trades', 'has_warning') == true }}"
            }],
            "action": [{
                "service": notify_service,
                "data": {
                    "title": "⚠️ Trading: SL Warnung",
                    "message": "{% for a in state_attr('sensor.trading_open_trades', 'alerts') %}{% if a.severity in ['warning','critical'] %}{{ a.message }}\n{% endif %}{% endfor %}"
                }
            }],
        },
        {
            "id": "trading_sl_breach",
            "alias": "Trading: SL Durchbrochen",
            "description": "Kritische Notification wenn SL durchbrochen",
            "mode": "single",
            "trigger": [{"platform": "state", "entity_id": "sensor.trading_open_trades"}],
            "condition": [{
                "condition": "template",
                "value_template": "{{ state_attr('sensor.trading_open_trades', 'has_critical') == true }}"
            }],
            "action": [{
                "service": notify_service,
                "data": {
                    "title": "🔴 TRADING: SL DURCHBROCHEN",
                    "message": "{% for a in state_attr('sensor.trading_open_trades', 'alerts') %}{% if a.severity == 'critical' %}{{ a.message }}\n{% endif %}{% endfor %}",
                    "data": {"push": {"sound": {"name": "default", "critical": 1}}}
                }
            }],
        },
        {
            "id": "trading_target_hit",
            "alias": "Trading: Target erreicht",
            "description": "Notification wenn Target erreicht",
            "mode": "single",
            "trigger": [{"platform": "state", "entity_id": "sensor.trading_open_trades"}],
            "condition": [{
                "condition": "template",
                "value_template": "{% for a in state_attr('sensor.trading_open_trades', 'alerts') | default([]) %}{% if a.type == 'target_hit' %}true{% endif %}{% endfor %}"
            }],
            "action": [{
                "service": notify_service,
                "data": {
                    "title": "🎯 Trading: Target erreicht!",
                    "message": "{% for a in state_attr('sensor.trading_open_trades', 'alerts') %}{% if a.type == 'target_hit' %}{{ a.message }}\n{% endif %}{% endfor %}"
                }
            }],
        },
    ]

    # REST Sensor + Command in HA anlegen
    # Das geht leider nicht per API — muss in configuration.yaml
    # Aber wir können prüfen ob der Sensor existiert und Hinweis geben
    if "sensor.trading_open_trades" not in existing:
        log.warning(
            "sensor.trading_open_trades existiert nicht in HA. "
            "Bitte in configuration.yaml einfuegen:\n\n"
            "rest:\n"
            "  - resource: http://localhost:8502/api/status\n"
            "    scan_interval: 300\n"
            "    sensor:\n"
            "      - name: Trading Open Trades\n"
            "        value_template: \"{{ value_json.open_trades }}\"\n"
            "        json_attributes:\n"
            "          - trades\n"
            "          - alerts\n"
            "          - has_critical\n"
            "          - has_warning\n"
            "          - cash\n"
            "          - portfolio\n\n"
            "rest_command:\n"
            "  trading_refresh:\n"
            "    url: http://localhost:8502/api/refresh\n"
            "    method: POST\n"
            "  trading_scan:\n"
            "    url: http://localhost:8502/api/scan\n"
            "    method: POST\n"
        )

    # Automationen anlegen
    for auto in automations:
        auto_id = auto["id"]
        try:
            resp = req.post(
                f"{ha_url}/config/automation/config/{auto_id}",
                headers=headers, json=auto, timeout=5)
            if resp.status_code in (200, 201):
                log.info("HA Automation angelegt: %s", auto["alias"])
            else:
                log.warning("HA Automation %s: %s", auto_id, resp.text[:200])
        except Exception as e:
            log.warning("HA Automation %s fehlgeschlagen: %s", auto_id, e)


def run_api(port: int = 8502):
    """Starte den API-Server."""
    # HA Automationen beim Start anlegen
    try:
        _setup_ha_automations()
    except Exception as e:
        log.warning("HA Setup fehlgeschlagen: %s", e)

    server = HTTPServer(("0.0.0.0", port), TradingAPIHandler)
    log.info("Trading API gestartet auf Port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_api()
