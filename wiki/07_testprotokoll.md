# Testprotokoll

Dokumentiert jeden Test, die Fragestellung, die gedrehte Stellschraube und das Ergebnis.
So koennen wir nachvollziehen was funktioniert hat und was zurueckgedreht werden sollte.

---

## Baseline (Stand 19.03.2026)

| Parameter | Wert |
|---|---|
| Richtung | Nur LONG |
| Markt-Veto | Aktiv (DAX > EMA50+200, VIX < 25) |
| MACD-Veto | Aktiv |
| Max. Gegenstimmen | 1 |
| R/R Minimum | 1.5 |
| SL-Berechnung | 2.5x ATR (fix) |
| SL-Band | keins (alles erlaubt) |
| Target | Nur bestaetigte S/R-Cluster |
| Max. Haltedauer | 100 Tage |
| Max. Positionen | 5 |
| Sizing | 20% vom freien Cash |
| Hebel | 5x |
| Gebuehren | 2 EUR/Trade |
| Startkapital | 1.000 EUR |
| Monatl. Einzahlung | 0 EUR |
| Universum | DE (DAX + MDAX + TecDAX, 104 Titel) |

**Baseline-Ergebnis:** 149 Signale, 107 Trades, 38.3% WR, +31% Rendite, 52% DD, 0.6 Effizienz

---

## Tests

### Test 1: SL-Band (Floor + Ceiling)

| | |
|---|---|
| **Frage** | Viele Trades werden mit engem SL (<6%) ausgestoppt. 5% Bewegung passiert bei normaler Wochenvolatilitaet. Hilft ein SL-Mindestabstand? Und: hochvolatile Aktien (SL >10%) haben schlechte WR — hilft ein Ceiling? |
| **Stellschraube** | `min_sl_dist`: 0% -> 6%, `max_sl_dist`: 100% -> 8% |
| **Hypothese** | Enge SLs werden zu schnell ausgestoppt, zu weite SLs deuten auf zu volatile Aktien mit unklarer Richtung |
| **Ergebnis** | 27 Trades, **51.9% WR** (vorher 38.3%), **+95% Rendite**, 44% DD, **Eff 2.2** |
| **Bewertung** | Starke Verbesserung bei WR und Effizienz. Aber: Nur 27 Trades in 5 Jahren (0.5/Monat) — zu wenig. |
| **Entscheidung** | **Beibehalten.** Band 6-8% bestaetigt. Problem "zu wenig Trades" separat loesen. |

---

### Test 2: Risk-basiertes Sizing (auf SL-Band 6-8%)

| | |
|---|---|
| **Frage** | Fixed 20% frei investiert gleich viel egal wie riskant der Trade ist. Ist risiko-basiertes Sizing besser? |
| **Stellschraube** | `sizing_method`: fixed_free -> risk_portfolio, `sizing_pct`: 20% -> 5% |
| **Hypothese** | Position an SL-Distanz anpassen = gleichmaessigeres Risiko pro Trade |
| **Ergebnis** | 27 Trades, 51.9% WR, +73% Rendite (statt +95%), **37% DD** (statt 44%), Eff 1.9 |
| **Bewertung** | Weniger Rendite aber deutlich weniger Drawdown. Effizienz sinkt leicht (2.2 -> 1.9). |
| **Entscheidung** | **Noch offen.** Fixed-Sizing hat hoehere Rendite, Risk-Sizing hat niedrigeren DD. Haengt von Risikobereitschaft ab. |

---

### Test 3: Monatliche Einzahlung (realistisches Szenario)

| | |
|---|---|
| **Frage** | Realistisch: 1000 EUR Start + 100 EUR/Monat. Wie veraendert sich das Bild? |
| **Stellschraube** | `monthly_deposit`: 0 -> 100 EUR |
| **Hypothese** | Mehr Cash = weniger Cash-Engpaesse, groessere Positionen ueber Zeit |
| **Ergebnis** | Eingezahlt: 7.100 EUR -> Endkapital: 11.509 EUR (+62%), DD nur **20%**, **Eff 3.2** |
| **Bewertung** | Realistisches Szenario sieht gut aus. DD massiv gesenkt weil staendig frisches Cash reinkommt. |
| **Entscheidung** | **Beibehalten.** Entspricht dem realen Plan. |

---

### Test 4: R/R Minimum senken (1.5 -> 1.0)

| | |
|---|---|
| **Frage** | R/R >= 1.5 filtert 675 auf 300 Signale (mehr als die Haelfte raus). Sind Trades mit R/R 1.0-1.5 im SL-Band 6-8% trotzdem profitabel? |
| **Stellschraube** | `min_rr`: 1.5 -> 1.0 (kumulativ auf SL 6-8% + Risk-Sizing + 100 EUR/Monat) |
| **Hypothese** | Im SL-Band 6-8% ist die Volatilitaet "richtig" — auch niedrigere R/R-Trades koennten funktionieren |
| **Ergebnis** | **92 Trades** (statt 27), **52.2% WR**, +90% Rendite, 31% DD, Eff 2.9, Endkapital **13.852 EUR** |
| **Bewertung** | Mehr als 3x so viele Trades bei GLEICHER Win-Rate! Rendite und Effizienz steigen. Bester Gesamtlauf bisher. |
| **Entscheidung** | **Beibehalten.** R/R 1.0 funktioniert im SL-Band 6-8%. Trades steigen von 0.5 auf 1.5/Monat. |

---

### Test 5: US-Titel aktivieren

| | |
|---|---|
| **Frage** | US-Titel wurden entfernt weil DAX als Markt-Kontext nicht passt. Mit S&P als Kontext und korrigiertem Backtest — funktionieren sie? |
| **Stellschraube** | Universum: DE -> DE + US (mit S&P-Kontext fuer US) |
| **Hypothese** | Doppelt so viele Titel = doppelt so viele Gelegenheiten. US-Markt hat andere Dynamik, koennte diversifizieren. |
| **Ergebnis** | *Noch nicht getestet* |
| **Bewertung** | — |
| **Entscheidung** | — |

---

## Aktueller bester Stand (kumulativ)

Baseline + SL 6-8% + Risk 5% Portfolio + 7 Positionen + 100 EUR/Monat + R/R >= 1.0

| Kennzahl | Wert |
|---|---|
| Signale | 97 |
| Trades | 92 |
| Win-Rate | 52.2% |
| Rendite (auf Einzahlungen) | +90% |
| Max. Drawdown | 31% |
| Effizienz | 2.9 |
| Endkapital | 13.852 EUR |
| Eingezahlt | 7.300 EUR |
| Trades/Monat | ~1.5 |
| **Ziel Trades/Monat** | **5-10** |

### Test 6: Pattern-Detektoren als Signalquelle (2026-03-20)

6 Chart-Pattern-Detektoren in `patterns.py` als Alternative zu `analyze_stock()`.
Patterns: pullback_ema20, ema50_bounce, support_bounce, breakout_consolidation, bollinger_squeeze_up, gap_up_continuation.

**6a: Einzelne Patterns (chartbasiertes Target, preset_baseline_v1)**

| Pattern | Trades | WR | Rendite | DD | Eff | Ø PnL |
|---|---|---|---|---|---|---|
| ema50_bounce | 1136 | 43.5% | **+142%** | 45% | 3.1 | +0.9% |
| gap_up_continuation | 94 | 54.3% | +26% | 21% | 1.2 | +1.5% |
| bollinger_squeeze_up | 346 | 40.5% | +26% | 41% | 0.6 | +0.6% |
| pullback_ema20 | 1564 | 36.3% | -27% | 44% | -0.6 | +0.2% |
| support_bounce | 590 | 34.2% | -24% | 36% | -0.7 | +0.1% |
| breakout_consolidation | 318 | 59.1% | -59% | 74% | -0.8 | -0.3% |

**Entscheidung:** Nur ema50_bounce und gap_up_continuation sind profitabel genug (>= +100% Rendite bei ema50, bester Ø PnL bei gap_up).

---

**6b: Target-Methode (Fix R/R vs. chartbasiert)**

| Config | Methode | Trades | WR | Rendite | DD | Eff |
|---|---|---|---|---|---|---|
| ema50_bounce | chartbasiert | 1136 | 43.5% | +142% | 45% | 3.1 |
| ema50_bounce | **fix R/R=2.0** | 878 | 37.0% | **+383%** | 48% | **8.0** |
| Top2 (ema50+gap_up) | chartbasiert | 1259 | 44.3% | +273% | 46% | 5.9 |
| Top2 (ema50+gap_up) | **fix R/R=2.0** | 1107 | 37.9% | **+738%** | 50% | **14.9** |

**Erkenntnis:** Fix R/R=2.0 schlaegt chartbasiert deutlich. Chartbasierte Targets sind zu konservativ (Median R/R=1.6). Fix R/R=2.0 laesst Gewinner weiter laufen.
**Entscheidung:** Fix R/R=2.0 verwenden.

---

**6c: Trailing-SL (Fix R/R=2.0 + Trailing)**

| Config | Methode | WR | Rendite | DD | Eff |
|---|---|---|---|---|---|
| Top2 | Fix2.0 (statisch) | **37.9%** | **+738%** | 50% | **14.9** |
| Top2 | Fix2.0 + Trail ab 2R | 34.8% | +411% | 52% | 8.0 |
| Top2 | Fix2.0 + Trail ab 1R | 24.0% | +325% | 64% | 5.0 |

**Erkenntnis:** Trailing verschlechtert die Performance. Der SL wird nachgezogen, aber der Kurs macht Ruecksetzer und stoppt den Trade bevor er das Target erreicht. Bei R/R=2.0 ist das Target nah genug dass die meisten Gewinner es sauber erreichen.
**Entscheidung:** Kein Trailing bei Fix R/R=2.0.

---

**6d: R/R-Grid (pattern_grid, 148 Kombinationen)**

Systematisch getestet: 4 R/R-Werte × 6 Patterns × 4 SL-Baender.
Report: `results/2026-03-20_1851_pattern_grid/ranking.csv`

Top 3 (nach Effizienz, min. 20 Trades):
1. Top2 (ema50+gap_up) | R/R=2.0 | kein SL → Eff 14.9
2. Top2 | R/R=1.5 | kein SL → Eff 13.8
3. Top2 | R/R=2.5 | kein SL → Eff 13.5

**Entscheidung:** R/R=2.0 ist Sweet Spot (beste Effizienz). R/R=1.5 hat hoehere WR aber weniger Rendite.

---

**6e: SL-Mindestabstand (2026-03-21)**

33% der Pattern-Signale haben SL < 4% — das ist reines Rauschen. Bei Risk-Sizing
werden diese zu uebergrossen Positionen die scharfe Equity-Dips verursachen.

| SL-Floor | Trades | WR | Rendite | DD | Eff |
|---|---|---|---|---|---|
| kein | 1107 | 37.9% | +738% | 50% | 14.9 |
| >= 3% | 853 | 38.3% | +587% | 53% | 11.2 |
| >= 4% | 735 | 37.6% | +507% | 54% | 9.4 |
| **>= 5%** | **559** | **38.8%** | **+627%** | **43%** | **14.7** |
| >= 6% | 397 | 39.3% | +480% | 43% | 11.1 |

**Entscheidung:** SL >= 5%. Fast gleiche Effizienz, DD sinkt von 50% auf 43%.

---

**6f: Sizing-Modelle (2026-03-21)**

Getestet auf ×3 Projektion (18 Jahre) fuer Langzeit-Vergleich.

| Modell | 18J Endkapital | DD |
|---|---|---|
| Fixed 10% Cash | €8.1 Mio | 47% |
| Risk 2% Cash | €519k | 37% |
| **Risk 2% Cash, max €2500** | **€265k** | **36%** |
| Risk 2% Cash, max €500 | €88k | 29% |

Fixed X% Cash = exponentielles Wachstum, unkontrolliertes Risiko bei grossem Konto.
Risk 2% Cash = kontrolliert, Risiko bleibt bei 2% pro Trade.
Max €2500 = Cap verhindert uebergrosse Positionen bei wachsendem Konto.

**Entscheidung:** Risk 2% freies Cash, max €2.500 Eigenkapital pro Position.

---

**6g: Markt-Veto (2026-03-21)**

| Veto | Geblockt | Rendite | DD | Eff |
|---|---|---|---|---|
| Ohne | 0% | +627% | 43% | 14.7 |
| DC (SMA50<SMA200) | 29% | +160% | 34% | 4.7 |
| Preis < SMA200 | 27% | +213% | 35% | 6.1 |
| EMA-DC (EMA20<EMA50) | 26% | +240% | 34% | 7.0 |
| VIX > 25 | 26% | +187% | 35% | 5.4 |

**Entscheidung:** Kein automatisches Veto. Trader entscheidet manuell basierend auf Marktlage.

---

**6h: Trailing-SL revisited (2026-03-21)**

Auch konservatives Trailing (ab 2R, weiter ATR) verschlechtert Performance.
Bei R/R=2.0 erreichen die meisten Gewinner das Target sauber.
Trailing stoppt sie vorher aus bei normalen Ruecksetzern.

**Entscheidung:** Kein Trailing.

---

## Aktueller bester Stand — Alte Signale (2026-03-19)

Baseline + SL 6-8% + Risk 5% Portfolio + 7 Positionen + 100 EUR/Monat + R/R >= 1.0

| Kennzahl | Wert |
|---|---|
| Trades | 92 |
| Win-Rate | 52.2% |
| Rendite | +90% |
| Max. Drawdown | 31% |
| Effizienz | 2.9 |
| Endkapital | 13.852 EUR |

## Neuer bester Stand — Pattern-Signale (2026-03-21)

Pattern Top2 (ema50_bounce + gap_up_continuation) + Fix R/R=2.0 + SL >= 5% + Risk 2% Cash + max €2.500

| Parameter | Wert |
|---|---|
| Patterns | ema50_bounce + gap_up_continuation |
| Target | Fix R/R=2.0 |
| SL | Vom Pattern-Detektor, min 5% Distanz |
| Sizing | Risk 2% freies Cash, max €2.500 |
| Trailing | Nein |
| Markt-Veto | Keins (manuell) |
| Pos-Limit | Keins (manuell) |
| Einzahlung | Manuell |

Backtest-Ergebnis (×3 Projektion, 18 Jahre, 1.500 EUR Start):

| Kennzahl | Wert |
|---|---|
| Trades | 1.763 (~8/Monat) |
| Win-Rate | 39.1% |
| Rendite | +2.047% |
| Max. Drawdown | 36% |
| Effizienz | 56.5 |
| Endkapital | 265.129 EUR |

### Test 7: SHORT-Pattern-Detektoren (2026-03-21)

6 eigenstaendige SHORT-Patterns entwickelt (nicht einfach umgekehrte LONG-Patterns):

| Pattern | Logik | Trades | WR | Rendite | DD |
|---|---|---|---|---|---|
| bearish_engulfing | Grosse rote Kerze verschluckt Vortag nach Rally, hohes Vol | 142 | 30.3% | -24% | 19% |
| failed_rally | Abwaertstrend, Rally bis EMA20 scheitert, Lower High | 813 | 28.3% | -68% | 52% |
| breakdown_support | Bruch unter 20-Tage-Low mit Volumen im Abwaertstrend | 785 | 32.7% | -45% | 62% |
| death_cross_sell | EMA20 kreuzt EMA50 nach unten, Kurs unter beiden EMAs | 412 | 22.3% | -47% | 48% |
| resistance_rejection | Abprall an Widerstand, langer oberer Docht, Close unten | 86 | 36.0% | -2% | 15% |
| gap_down_continuation | Gap nach unten >1.5% mit Volumen im Abwaertstrend | 80 | 21.2% | -27% | 16% |

**Ergebnis:** Kein einziges SHORT-Pattern ist profitabel. Alle WR unter 34% (Breakeven bei R/R=2.0).

**Gruende:**
- **Survivorship Bias**: Nur aktuelle Index-Mitglieder getestet — die sind langfristig Gewinner. Shorts gegen Gewinner verlieren systematisch.
- **Bullisher Zeitraum**: DAX 2020-2026 von 9.000 auf 23.000. Shorts gegen den Trend sind Gift.
- **Technische SHORT-Patterns funktionieren anders**: Professionelle Short-Seller nutzen Fundamentaldaten (Earnings, Guidance), nicht nur Charttechnik.
- resistance_rejection war fast breakeven (-2%, 86 Trades) — zu wenig Signale fuer Vertrauen.

**Entscheidung:** SHORT-Patterns verworfen. SHORT-Trades manuell basierend auf Marktlage und Fundamentaldaten. System bleibt rein LONG.

---

### Test 8: SL-Floor im Detektor (2026-03-21)

Statt SL-Mindestabstand als Filter: SL-Floor direkt in `_make()` in patterns.py eingebaut.
`MIN_SL_DIST_PCT = 0.05` — wenn Pattern-SL enger als 5% ist, wird er auf 5% gesetzt.

| Methode | Signale | WR | Rendite | DD |
|---|---|---|---|---|
| SL >= 5% Filter (vorher) | 588 | 38.8% | +627% | 43% |
| **SL-Floor im Detektor** | 993 | **42.0%** | +391% | 41% |

Floor behaelt alle Signale (993 statt 588) und setzt zu enge SLs weiter nach unten.
WR steigt auf 42% weil die vorher zu engen SLs jetzt mehr Luft haben.

**Entscheidung:** SL-Floor im Detektor beibehalten (MIN_SL_DIST_PCT = 0.05).

### Test 9: Signal-Persistenz im Ranking (2026-03-25)

Hypothese: Signale die an mehreren aufeinanderfolgenden Tagen erscheinen sind robuster
und fuehren zu besseren Trades als "Wackelkandidaten" die nur einmal aufblitzen.

**Persistenz** = Anzahl verschiedener Kalendertage an denen dasselbe Ticker+Pattern
im Lookback-Fenster erkannt wurde (vor Blocking).

**Rang = combo_score + (persistence × weight)**

Setup: Pattern Top2, Fix R/R=2.0, SL >= 5%, Risk 2% Cash, max €2.500, 5 Positionen.

| Konfiguration | Trades | WR | Rendite | DD | Effizienz | Endkapital |
|---|---|---|---|---|---|---|
| combo_score Baseline | 314 | 44.6% | +214% | 28.3% | 7.6 | €16.029 |
| LB5, w=0.2 | 319 | 44.8% | +234% | 28.2% | 8.3 | €17.019 |
| LB10, w=0.1 | 316 | 45.3% | +245% | 28.5% | 8.6 | €17.609 |
| **LB10, w=0.2** | **309** | **46.3%** | **+300%** | **23.6%** | **12.7** | **€20.401** |
| LB10, w=0.3 | 309 | 46.3% | +301% | 23.6% | 12.7 | €20.423 |
| LB15, w=0.2 | 309 | 46.0% | +281% | 23.6% | 11.9 | €19.422 |

Persistenz-Verteilung (LB10): 4182× 1d, 594× 2d, 195× 3d, 72× 4d, 19× 5d

**Ergebnis:** Persistenz verbessert alle Metriken deutlich:
- +86% mehr Rendite (300% vs 214%)
- Weniger Drawdown (23.6% vs 28.3%)
- Hoehere Win Rate (46.3% vs 44.6%)
- 67% bessere Effizienz (12.7 vs 7.6)

Ab w=0.2 flacht der Effekt ab (0.3/0.5 kaum besser). Lookback 10 > 15 > 5.

**Entscheidung:** Signal-Persistenz mit LB=10, w=0.2 ins Ranking aufnehmen.
Reports: results/2026-03-25_1213_persistence_test/

---

## Aktueller bester Stand — Pattern-Signale (2026-03-25)

| Parameter | Wert |
|---|---|
| Patterns | ema50_bounce + gap_up_continuation |
| Target | Fix R/R=2.0 (Entry + 2 × Risk) |
| SL | Vom Pattern-Detektor, min 5% Distanz |
| Sizing | Risk 2% freies Cash, max €2.500 Eigenkapital |
| Ranking | persistence_score: combo_score + persistence × 0.2, Lookback 10 Tage |
| Trailing | Nein (verschlechtert Performance) |
| Markt-Veto | Keins (Trader entscheidet manuell) |
| Pos-Limit / Einzahlung | Manuell (nicht im System) |

---

## Offene Fragen

- US-Titel mit eigenem Markt-Kontext testen
- Blocking-Dauer ggf. verkuerzen
- Paper-Trading starten (min. 3 Monate)
