# Das Setup — Zusammenfassung

Alle Parameter wurden in Backtests (2020–2026, DAX/MDAX/TecDAX) validiert.
Haltedauer 100 Tage. Alle Erkenntnisse basieren konsistent auf dieser Einstellung.

## Regeln auf einen Blick

| # | Parameter | Wert | Begründung |
|---|---|---|---|
| 1 | **Richtung** | Nur LONG | SHORT funktioniert in keinem Marktumfeld (14% WR) |
| 2 | **Markt: DAX-Trend** | Nur im Bullenmarkt (DAX > EMA50 UND EMA200) | Bull: 43% WR, Bear: 15% WR |
| 3 | **Markt: VIX** | Kein Trade bei VIX ≥ 25 | High VIX: 25% WR, -1.4% Ø P&L |
| 4 | **MACD-Veto** | MACD muss Richtung bestätigen | Ohne MACD: 38% WR → mit: 64% WR |
| 5 | **Gegen-Stimmen** | Max. 1 erlaubt (≥2 = Veto) | 1 Gegen-Stimme = beste Trades (65% WR) |
| 6 | **Confidence** | Kein Minimum (= 0) | Niedrige Conf + Veto-frei + hohes R/R = beste Trades |
| 7 | **Target** | Nur bestätigte S/R-Cluster | ATR-Fallback: 50% WR aber -0.28% Ø P&L |
| 8 | **Stop-Loss** | 2.5× ATR, kein S/R-Anker | Sweet Spot: +1.56% Ø P&L, S/R-Anker schadet |
| 9 | **Max. Haltedauer** | 100 Tage | 99.4% treffen SL/Target vorher; Wert kaum relevant |
| 10 | **Max. Positionen** | 5 gleichzeitig | Bester Kompromiss Rendite/Risiko (Eff. 9.1) |
| 11 | **Position-Sizing** | 20% vom freien Cash | Einfach, kein Cash-Engpass, selbstregulierend |
| 12 | **Universum** | Nur DE (DAX, MDAX, TecDAX) | US-Titel: DAX als Kontext passt nicht |
| 13 | **index_trend Vote** | Deaktiviert (Gewicht = 0) | Schadet: Trades bei weit gelaufenem Trend |

## Backtest-Ergebnis

| Kennzahl | Wert |
|---|---|
| **Rendite** | +299% (€1.000 → €3.991) |
| **Max. Drawdown** | 33% |
| **Effizienz** (Rendite/DD) | 9.1 |
| **Win-Rate** | 47% |
| **Trades** | 93 (in ~5 Jahren) |
| **Ø Haltedauer** | 32 Tage |
| **Übersprungene Trades** | 0 (kein Cash-Engpass) |

## Position-Sizing im Detail

```
Freies Cash = Kontostand − in Positionen gebundenes Geld
Investiere  = 20% vom freien Cash
Max.        = 5 Positionen gleichzeitig
```

Beispiel mit €1.000 Start:

```
Trade 1: 20% von €1.000 = €200 → €800 frei
Trade 2: 20% von €800  = €160 → €640 frei
Trade 3: 20% von €640  = €128 → €512 frei
Trade 4: 20% von €512  = €102 → €410 frei
Trade 5: 20% von €410  = €82  → €328 Reserve
```

Nach 5 Trades: ~67% investiert, ~33% Reserve. Nie zu 100% investiert.

## Was NICHT funktioniert hat

| Idee | Ergebnis |
|---|---|
| Gewichtungs-Optimierung | Verschlechtert (Overfitting) |
| SHORT-Trading | 14% Win-Rate, in keinem Regime profitabel |
| Hohe Confidence bevorzugen | Schadet — Trend schon zu weit gelaufen |
| Sektor-Trend als Veto | Kein robuster Effekt, dreht sich je nach Filter |
| S/R-Anker im Stop-Loss | Zieht SL zu nah, häufiger ausgestoppt |
| Dynamische Exits (MACD-Flip, Score-Verfall etc.) | Frühzeitiges Aussteigen schadet — Schwankungen aussitzen ist besser |
| US-Aktien im DE-System | DAX-Kontext passt nicht für US-Titel |

## Detaillierte Dokumentation

- [01 Systemüberblick](01_system_ueberblick.md)
- [02 Veto-Regeln](02_veto_regeln.md)
- [03 Backtest-Prozess](03_backtest_prozess.md)
- [04 Erkenntnisse](04_erkenntnisse.md)
- [05 Indikatoren](05_indikatoren.md)
- [06 Money Management](06_money_management.md)
- [07 Testprotokoll](07_testprotokoll.md) — Alle Tests, Stellschrauben und Ergebnisse
