# Trading App — Home Assistant Add-on

Swing-Trading System mit Pattern-Erkennung (ema50_bounce, gap_up_continuation).

## Installation

### Lokales Add-on (empfohlen für Entwicklung)

1. Projekt auf den HA-Host kopieren:
   ```bash
   scp -r /Users/robert.arndt/Projects/trading user@nas:/path/to/
   ```

2. In HA: Settings → Add-ons → Add-on Store → Repositories
   - Lokalen Pfad hinzufügen: `/path/to/trading`

3. Add-on "Trading App" installieren und starten

4. In der HA Sidebar erscheint "Trading" — klicken öffnet die App

### Daten

- Die DB wird persistent in `/data/trading.db` gespeichert (HA addon_config)
- Kursdaten werden beim ersten Start aus dem mitgelieferten Backup übernommen
- Backups über HA Snapshots (inkl. DB)

### Konfiguration

| Option | Default | Beschreibung |
|--------|---------|-------------|
| scan_interval_minutes | 30 | Automatischer Scan alle N Minuten |

## Nächste Schritte

- HA Custom Integration für Sensor-Entities und Notifications
- Automationen für SL/Target Alerts
