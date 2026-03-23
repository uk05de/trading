# System-Überblick

## Was macht das System?

Swing-Trading-Screener für **104 deutsche Aktien** (DAX + TecDAX + MDAX). Scannt täglich alle Titel, bewertet sie anhand von 13 technischen/fundamentalen Bedingungen und gibt Kauf-/Verkaufssignale mit Kursziel und Stop-Loss.

## Architektur

1. **Scanner** (`scanner.py`): Lädt Kursdaten, berechnet Indikatoren, ruft Analyzer auf
2. **Analyzer** (`analyzer.py`): 13 Bedingungen stimmen ab → Score → Richtung (LONG/SHORT) + Veto-Prüfung
3. **Targets** (`targets.py`): Berechnet Entry, Target, Stop-Loss basierend auf ATR und S/R-Levels
4. **Dashboard** (`app.py`): Streamlit-UI mit Empfehlungen, Trades, Historie, Lernmodul, Wiki

## Die 13 Bedingungen

| # | Bedingung | Was sie misst |
|---|---|---|
| 1 | `ema50_trend` | Mittelfristiger Trend (EMA50 Steigung) |
| 2 | `macd_signal` | Momentum (MACD vs. Signal-Linie) |
| 3 | `adx_trend` | Trendstärke (ADX-Level) |
| 4 | `bollinger_squeeze` | Volatilitäts-Ausbruch (BB-Breite + Position) |
| 5 | `volume_surge` | Volumen-Bestätigung (vs. 20-Tage-Ø) |
| 6 | `support_near` | Nähe zu Support-Level |
| 7 | `resistance_near` | Nähe zu Resistance-Level |
| 8 | `relative_strength` | Relative Stärke vs. DAX |
| 9 | `earnings_proximity` | Nähe zu Earnings-Termin |
| 10 | `index_trend` | DAX-Trend (bull/bear/neutral) |
| 11 | `vix_regime` | Volatilitäts-Regime (VIX-Level) |
| 12 | `sector_trend` | Sektor-Momentum |
| 13 | `news_sentiment` | Nachrichten-Stimmung |

## Gewichtungen

**Alle Gewichte = 1.0** (Standard v1). Gewichts-Optimierung hat in allen Tests die Ergebnisse verschlechtert. Der Hebel liegt in den **Veto-Regeln und Filtern**, nicht in den Gewichten.
