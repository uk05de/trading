"""
notifications.py – Smart Trade Notifications via HA API.

Sendet Benachrichtigungen direkt ueber die HA REST API.
Alerts werden pro Position (Ticker) in der DB getrackt,
damit jeder Alert nur einmal feuert.

Alert-Typen:
  sl_warning   -0.8R  "Hast du die Stop-Order gesetzt?"
  sl_breach    -1.0R  "Sofort pruefen!" (critical)
  sl_reminder  60min nach sl_breach, wenn Trade noch offen
  target_2r    2.0R   "Gewinn mitnehmen?"
  target_25r   2.5R   Milestone
  target_3r    3.0R   Milestone
  target_4r    4.0R   Milestone
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os

log = logging.getLogger(__name__)

# Notify-Service wird einmal gelesen und gecacht
_notify_service: str | None = None


def _get_notify_service() -> str:
    global _notify_service
    if _notify_service is None:
        _notify_service = "notify.notify"
        try:
            with open("/data/options.json") as f:
                options = json.load(f)
                _notify_service = options.get("notify_service") or _notify_service
        except FileNotFoundError:
            pass
    return _notify_service


def _send_ha_notification(title: str, message: str, critical: bool = False):
    """Notification via HA API senden."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Notification (lokal): %s — %s", title, message)
        return

    service = _get_notify_service()
    domain, svc = service.split(".", 1) if "." in service else ("notify", service)

    data = {"title": title, "message": message}
    if critical:
        data["data"] = {"push": {"sound": {"name": "default", "critical": 1}}}

    try:
        import requests
        _headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # Push-Notification ans Handy
        resp = requests.post(
            f"http://supervisor/core/api/services/{domain}/{svc}",
            headers=_headers, json=data, timeout=5,
        )
        if resp.status_code in (200, 201):
            log.info("Notification gesendet: %s", title)
        else:
            log.warning("Notification Fehler %d: %s", resp.status_code, resp.text[:200])

        # Persistente Notification in HA (vollständig lesbar)
        requests.post(
            "http://supervisor/core/api/services/persistent_notification/create",
            headers=_headers, timeout=5,
            json={
                "title": title,
                "message": message,
                "notification_id": f"trading_{title[:30].replace(' ', '_').lower()}",
            },
        )
    except Exception as e:
        log.warning("Notification fehlgeschlagen: %s", e)


def check_and_notify():
    """Pruefe alle offenen Positionen und sende neue Alerts."""
    from db import (get_trades, record_alert, get_alert_time)
    from ko_calc import calc_profit_r

    open_trades = get_trades(status="OPEN")
    if not open_trades:
        return

    # Gruppiere nach Ticker
    positions: dict[str, list[dict]] = {}
    for t in open_trades:
        positions.setdefault(t["ticker"], []).append(t)

    now = dt.datetime.now()

    for ticker, trades in positions.items():
        name = trades[0]["name"]
        suffix = f" ({len(trades)} Trades)" if len(trades) > 1 else ""

        # Profit R fuer jeden Trade berechnen
        r_values = []
        for t in trades:
            r = calc_profit_r(t)
            if r is not None:
                r_values.append(r)

        if not r_values:
            continue

        worst_r = min(r_values)
        best_r = max(r_values)
        avg_r = sum(r_values) / len(r_values)

        # --- SL Alerts (schlechtester Trade) ---
        if worst_r <= -1.0:
            msg = f"{name}{suffix}: {worst_r:+.2f}R — Sofort pruefen!"
            if record_alert(ticker, "sl_breach", worst_r, msg):
                _send_ha_notification("TRADING: SL DURCHBROCHEN", msg, critical=True)

            # Reminder 60 Min nach Breach
            breach_time = get_alert_time(ticker, "sl_breach")
            if breach_time:
                elapsed = (now - dt.datetime.fromisoformat(breach_time)).total_seconds()
                if elapsed >= 3600:
                    msg = f"{name}{suffix}: {worst_r:+.2f}R — Trade immer noch offen!"
                    if record_alert(ticker, "sl_reminder", worst_r, msg):
                        _send_ha_notification(
                            "REMINDER: SL immer noch durchbrochen!", msg, critical=True)

        elif worst_r <= -0.8:
            msg = f"{name}{suffix}: {worst_r:+.2f}R — Stop-Order gesetzt?"
            if record_alert(ticker, "sl_warning", worst_r, msg):
                _send_ha_notification("Trading: Nahe SL", msg)

        # --- Target Milestones (bester Trade) ---
        milestones = [
            ("target_4r", 4.0, "4.0R Meilenstein!"),
            ("target_3r", 3.0, "3.0R Meilenstein!"),
            ("target_25r", 2.5, "2.5R — Teilgewinne?"),
            ("target_2r", 2.0, "Target erreicht — Gewinn mitnehmen?"),
        ]
        for alert_type, threshold, hint in milestones:
            if best_r >= threshold:
                msg = f"{name}{suffix}: {best_r:+.2f}R — {hint}"
                if record_alert(ticker, alert_type, best_r, msg):
                    _send_ha_notification(f"Trading: {hint}", msg)
                break  # Nur hoechsten neuen Milestone senden


def cleanup_closed_alerts():
    """Alerts fuer vollstaendig geschlossene Positionen entfernen."""
    from db import get_alerted_tickers, get_open_tickers, clear_alerts_for_ticker

    alerted = get_alerted_tickers()
    still_open = get_open_tickers()
    for ticker in alerted - still_open:
        clear_alerts_for_ticker(ticker)
        log.info("Alerts fuer %s bereinigt (Position geschlossen)", ticker)


def send_evening_summary():
    """Abend-Zusammenfassung aller offenen Positionen."""
    from db import get_trades
    from ko_calc import calc_profit_r

    open_trades = get_trades(status="OPEN")
    if not open_trades:
        return

    positions: dict[str, list[dict]] = {}
    for t in open_trades:
        positions.setdefault(t["ticker"], []).append(t)

    sl_lines = []       # unter oder nahe SL
    target_lines = []   # ueber Target
    ok_lines = []       # dazwischen

    for ticker, trades in positions.items():
        name = trades[0]["name"]
        suffix = f" ({len(trades)}x)" if len(trades) > 1 else ""

        r_values = [calc_profit_r(t) for t in trades]
        r_values = [r for r in r_values if r is not None]
        if not r_values:
            continue

        worst_r = min(r_values)
        best_r = max(r_values)
        avg_r = sum(r_values) / len(r_values)
        display_r = avg_r if len(r_values) > 1 else r_values[0]

        line = f"  {name}{suffix}: {display_r:+.1f}R"

        if worst_r <= -0.8:
            sl_lines.append(line)
        elif best_r >= 2.0:
            target_lines.append(line)
        else:
            ok_lines.append(line)

    # Nachricht zusammenbauen
    parts = [f"Abend-Zusammenfassung ({len(positions)} Positionen)"]

    if sl_lines:
        parts.append("")
        parts.append("Nahe/Unter SL:")
        parts.extend(sl_lines)

    if target_lines:
        parts.append("")
        parts.append("Ueber Target:")
        parts.extend(target_lines)

    if ok_lines:
        parts.append("")
        parts.append("Laufend:")
        parts.extend(ok_lines)

    message = "\n".join(parts)
    has_critical = bool(sl_lines)

    _send_ha_notification(
        "Trading: Abend-Zusammenfassung",
        message,
        critical=has_critical,
    )
