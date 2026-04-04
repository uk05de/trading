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
    from ko_calc import calc_profit_r

    open_trades = get_trades(status="OPEN")
    cash = get_free_cash()

    trades = []
    alerts = []

    for t in open_trades:
        profit_r = calc_profit_r(t)

        trade_info = {
            "id": t["id"],
            "ticker": t["ticker"],
            "name": t["name"],
            "direction": t["direction"],
            "profit_r": profit_r,
            "product_bid": t.get("product_bid"),
            "entry_price": t["entry_price"],
            "current_price": t.get("current_price") or t["entry_price"],
            "stop_loss": t.get("stop_loss"),
            "target": t.get("target"),
        }
        trades.append(trade_info)

        if profit_r is not None:
            if profit_r <= -1.0:
                alerts.append({
                    "type": "sl_breach", "severity": "critical",
                    "message": f"{t['name']}: SL DURCHBROCHEN ({profit_r:+.2f}R)",
                    "trade_id": t["id"], "profit_r": profit_r,
                })
            elif profit_r <= -0.8:
                alerts.append({
                    "type": "sl_warning", "severity": "warning",
                    "message": f"{t['name']}: Nahe SL ({profit_r:+.2f}R)",
                    "trade_id": t["id"], "profit_r": profit_r,
                })
            elif profit_r >= 2.0:
                alerts.append({
                    "type": "target_hit", "severity": "info",
                    "message": f"{t['name']}: TARGET erreicht ({profit_r:+.2f}R)",
                    "trade_id": t["id"], "profit_r": profit_r,
                })
            elif profit_r >= 1.5:
                alerts.append({
                    "type": "target_near", "severity": "info",
                    "message": f"{t['name']}: Nahe Target ({profit_r:+.2f}R)",
                    "trade_id": t["id"], "profit_r": profit_r,
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

    # Notifications pruefen
    try:
        from notifications import check_and_notify, cleanup_closed_alerts
        check_and_notify()
        cleanup_closed_alerts()
    except Exception as e:
        log.warning("Notification-Check fehlgeschlagen: %s", e)

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
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/refresh":
            data = _refresh_trades()
            self._send_json(data)
        elif self.path == "/api/evening-summary":
            try:
                from notifications import send_evening_summary
                send_evening_summary()
                self._send_json({"status": "ok"})
            except Exception as e:
                self._send_json({"error": str(e)})
        elif self.path == "/api/scan":
            data = _full_scan()
            self._send_json(data)
        else:
            self.send_error(404)

    def _send_json(self, data):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            pass  # Client hat Verbindung geschlossen (HA Timeout)

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
            "description": f"Aktualisiert Trades alle {refresh_interval} Min (08:00-22:00). "
                           "Notifications werden direkt vom API-Server gesendet.",
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
            "trigger": [{"platform": "time_pattern",
                         **({"hours": f"/{full_scan_interval // 60}"} if full_scan_interval >= 60
                            else {"minutes": f"/{full_scan_interval}"})}],
            "condition": [{"condition": "time", "after": "09:00:00", "before": "18:00:00"}],
            "action": [{"service": "rest_command.trading_scan"}],
        },
        {
            "id": "trading_evening_summary",
            "alias": "Trading: Abend-Zusammenfassung",
            "description": "Taegliche Zusammenfassung aller offenen Positionen um 18:00",
            "mode": "single",
            "trigger": [{"platform": "time", "at": "18:00:00"}],
            "action": [{"service": "rest_command.trading_evening_summary"}],
        },
    ]

    # Alte Notification-Automationen entfernen (jetzt vom API-Server gehandhabt)
    for old_id in ("trading_sl_warning", "trading_sl_breach", "trading_target_hit"):
        try:
            req.delete(f"{ha_url}/config/automation/config/{old_id}",
                       headers=headers, timeout=5)
        except Exception:
            pass

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
            "  trading_evening_summary:\n"
            "    url: http://localhost:8502/api/evening-summary\n"
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
