# Backtest-Prozess

## Konfiguration

| Parameter | Wert | Begründung |
|---|---|---|
| Warmup | 200 Bars | EMA200-Konvergenz sicherstellen |
| Min. Confidence | 0 | Kein Vorfilter — Veto + R/R filtern besser |
| Max. Haltezeit | 250 Tage | Exit nur via Target oder Stop-Loss |
| Datenlänge | ~1400 Tage | 2 Jahre Backtest + 200 Warmup |

## Ablauf

1. **Marktdaten laden**: DAX und VIX für Markt-Kontext (1700 Tage)
2. **Pro Ticker**: Kursdaten laden, Indikatoren berechnen
3. **Walk-Forward**: Ab Bar 200 jeden Tag prüfen:
   - Analyzer: Score + Richtung + Veto-Prüfung
   - Targets: Entry, Target, Stop-Loss berechnen
   - Trade evaluieren: Target/Stop/Timeout
4. **Auswertung**: Getrennt nach Empfohlen vs. Veto

## R/R-Filter

Der optimale Risk/Reward-Filter verschiebt sich mit der Datenlänge:
- **1 Jahr**: R/R ≥ 1.0 optimal
- **2 Jahre**: R/R ≥ 1.5 optimal

Standard-Filter im Dashboard: **R/R ≥ 1.5**

## Quartals-Prozess

Alle 3 Monate:
1. 2-Jahres-Backtest laufen lassen (`run_2y_backtest.py`)
2. Prüfen ob Veto-Regeln noch bestätigt werden
3. R/R-Sweep analysieren — hat sich der Sweet Spot verschoben?
4. Ggf. neue Veto-Regeln testen und validieren
5. Ergebnisse hier im Wiki dokumentieren

## Wichtig: Keine Gewichts-Optimierung

Alle Gewichte bleiben bei **1.0** (Standard v1). Jeder Versuch, Gewichte zu optimieren, hat die Ergebnisse verschlechtert. Der Hebel liegt in den **Veto-Regeln und Filtern**.
