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

### Test 10: Breakeven-Stop nach Recovery (2026-03-25)

Hypothese: Wenn ein Trade erst ins Minus faellt und dann zurueck ueber Entry kommt,
SL auf Entry setzen (Breakeven). Der Trade hat Schwaeche gezeigt, also absichern.

Trigger: Kurs war X% unter Entry, dann Close zurueck ueber Entry → SL = Entry.

| Konfiguration | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| **Kein Breakeven (Baseline)** | **309** | **46.3%** | **+300%** | **23.6%** | **12.7** |
| Recovery BE +5% | 356 | 41.0% | +272% | 21.8% | 12.5 |
| Recovery BE +10% | 312 | 45.2% | +264% | 23.5% | 11.2 |
| Recovery BE +7% | 329 | 43.8% | +241% | 22.0% | 11.0 |
| Recovery BE +3% | 424 | 33.7% | +164% | 26.3% | 6.2 |
| Recovery BE +2% | 499 | 27.1% | +122% | 26.3% | 4.7 |

+5% hat niedrigsten DD (21.8%), aber -28% weniger Rendite. Trades die zurueckkommen
werden zu oft beim Breakeven ausgestoppt statt das Target zu erreichen.

**Entscheidung:** Verworfen. Trades brauchen den originalen SL um zum Target zu atmen.
Reports: results/2026-03-25_1509_breakeven_test/

### Test 11: Top-1 pro Tag vs. parallele Positionen (2026-03-25)

Frage: Wenn ich nur den besten Trade pro Tag nehme (nach Persistenz-Ranking),
wie performt das vs. mehrere parallele Positionen?

Setup: Pattern Top2, Fix R/R=2.0, SL >= 5%, Risk 2% Cash, max €2.500,
persistence_score (LB10, w=0.2).

| Konfiguration | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| Top-1/Tag, unbegr. Pos. | 421 | 43.0% | +243% | **21.2%** | 11.5 |
| Top-2/Tag, unbegr. Pos. | 590 | 41.9% | +311% | 30.4% | 10.2 |
| **Alle, max 5 Pos.** | **309** | **46.3%** | **+300%** | 23.6% | **12.7** |
| Alle, unbegrenzt | 727 | 42.2% | +376% | 32.5% | 11.6 |

Top-1/Tag hat 565 Signale aber nur 421 Trades (144 wegen Ticker-Duplikat blockiert —
selber Ticker noch im Trade, Haltedauer ~20 Tage).

Top-1 hat niedrigsten DD (21.2%), aber das Positions-Limit bei "max 5" wirkt als
natuerlicher Qualitaetsfilter: hoehere WR (46.3%) und beste Effizienz (12.7).

**Entscheidung:** Max 5 parallele Positionen beibehalten. Positions-Limit > Top-N/Tag.
Reports: results/2026-03-25_1538_top1_per_day/

### Test 12: Scale-In / Gestaffelter Einstieg (2026-03-29)

Hypothese: Gestaffelter Kauf in 3 Tranchen (wie im Boersenbrief) verbessert
den Durchschnitts-Entry und reduziert das Risiko.

**A) Risk-Stufen innerhalb SL** (Entry, Entry-1/3R, Entry-2/3R, SL bleibt):

| Konfiguration | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| **Einmal-Kauf (Baseline)** | **309** | **46.6%** | **+300%** | 23.7% | **12.6** |
| 3x Risk-Stufen | 310 | 46.5% | +135% | 16.7% | 8.1 |

**B) Fixer SL + Scale-In** (SL unabhaengig vom Pattern, z.B. 15% unter Entry):

| Konfiguration | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| 3x je 5%, SL fix 15% | 179 | 58.1% | +44% | 23.2% | 1.9 |
| 3x je 5%, SL fix 12% | 204 | 52.0% | +26% | 19.5% | 1.3 |
| 3x je 3%, SL fix 15% | 179 | 58.1% | +52% | 25.7% | 2.0 |
| 3x je 5%, SL fix 20% | 159 | 60.4% | +11% | 29.4% | 0.4 |

**Ergebnis:** Scale-In verliert in JEDER Variante gegen Einmal-Kauf.
- WR steigt bei weitem SL (58-60%), aber Rendite bricht ein
- Problem: ema50_bounce startet oft direkt in die richtige Richtung
- Nachkauf-Levels werden selten erreicht → nur 1/3 Kapital investiert → kleine Gewinne
- Breiterer SL = groesserer Verlust pro Verliertrade

Hinweis: Erster Test (ohne korrekte Tranchenberechnung) zeigte +1025% — war
fehlerhaft weil P/L auf Avg-Entry statt Gesamtinvestment berechnet wurde.

**Entscheidung:** Verworfen. Einmal-Kauf bleibt optimal fuer unser System.
Scale-In funktioniert vermutlich bei laengerer Haltedauer / fundamentaleren Signalen.
Reports: results/2026-03-29_0010_scale_in_corrected/, results/2026-03-29_0303_scale_in_final/

### Analyse 13: Post-Exit Kursverhalten (2026-03-29)

Frage: Sind Target und SL gut kalibriert? Was passiert nach dem Exit?
Datenbasis: 955 Signale (ema50_bounce + gap_up_continuation), R/R=2.0.

**TARGET-TRADES (401 Trades) — "Verkaufen wir zu frueh?"**

| Nach Exit | Median | Weiter gestiegen | Stark >5% | Gefallen <-5% |
|---|---|---|---|---|
| 5 Tage | +0.0% | 50% | 18% | 18% |
| 10 Tage | +0.9% | 56% | 29% | 21% |
| 20 Tage | +0.6% | 53% | 35% | 27% |
| 50 Tage | +4.6% | 60% | 49% | 28% |

Fazit: Target bei R/R=2.0 ist gut. Kurzfristig (5d) Muenzwurf — kein Geld
liegen gelassen. Langfristig steigt es oft weiter, aber das ist Markt-Drift.

**STOP-TRADES (530 Trades) — "Ist der SL zu eng?"**

| Nach Exit | Zurueck ueber Entry | Haette Target erreicht | Max Erholung Median |
|---|---|---|---|
| 5 Tage | 22% | **1%** | -3.1% |
| 10 Tage | 36% | **4%** | -2.0% |
| 20 Tage | 54% | **12%** | +0.5% |
| 50 Tage | 71% | **29%** | +5.6% |

Fazit: SL ist NICHT zu eng. Nur 1% der SL-Trades haetten kurzfristig (5d)
das Target doch erreicht. Selbst nach 50 Tagen nur 29% — und da ist das
Kapital laengst anderswo investiert.

**Entscheidung:** Target R/R=2.0 und Pattern-SL (min 5%) sind gut kalibriert.
Keine Aenderung noetig.

### Test 14: SL/Target verschieben (2026-03-29)

Frage: Was passiert wenn SL 5-10% tiefer und/oder Target 5-10% hoeher gesetzt wird?

| Konfiguration | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| Target +5% | 262 | 37.8% | **+407%** | 24.0% | **16.9** |
| **Baseline (Original)** | **310** | **46.5%** | **+296%** | **23.7%** | **12.5** |
| Target +10% | 218 | 31.2% | +260% | 25.4% | 10.2 |
| SL -10% | 173 | 59.0% | +99% | 21.6% | 4.6 |
| SL -5% | 218 | 51.8% | +62% | 29.7% | 2.1 |
| SL -5%, Target +10% | 150 | 28.0% | +2% | 43.3% | 0.0 |

Target +5% zeigt bessere Rendite/Effizienz, aber WR sinkt auf 37.8% (nur 1 von 3
Trades gewinnt). SL verschieben verschlechtert alles — mehr Luft bringt keinen Mehrwert.

**Entscheidung:** Verworfen. Target +5% sieht im Backtest gut aus, aber 37.8% WR
bedeutet laengere Verlustserien — psychologisch schwer durchzuhalten. Baseline bleibt.

---

### Test 15: Zeitbasierter Stop (2026-03-29)

Hypothese: Wenn ein Trade nach X Tagen noch X% unter Entry steht, hat das
Pattern versagt → fruehzeitig rausgehen statt auf vollen SL zu warten.

| Config | WR | Target | SL | Time-Stop | Netto | vs Baseline |
|---|---|---|---|---|---|---|
| **Baseline** | **49.4%** | 134 | 137 | 0 | **+1.198** | — |
| 7d -2% | 40.3% | 119 | 83 | 93 | +1.146 | -52 |
| 10d -3% | 41.3% | 119 | 86 | 83 | +1.154 | -44 |
| 3d -2% | 39.9% | 116 | 87 | 88 | +1.117 | -80 |
| 5d -2% | 37.2% | 109 | 87 | 97 | +846 | -352 |

Time-Stop spart SL-Verluste (weniger SL-Hits), aber killt Trades die sich
noch erholt haetten. Verlorene Gewinner kosten mehr als gesparte Verluste.

Zusammenhang mit Analyse 13 (Post-Exit):
- NACH SL-Hit: nur 1% erreichen Target → SL ist am richtigen Punkt
- VOR SL-Hit bei -2%: viele Trades drehen noch um → frueh rausgehen schadet
- Der Pattern-SL (min 5%) markiert exakt die Kipplinie

**Entscheidung:** Verworfen. Konsistente Erkenntnis aus Tests 10, 12, 14, 15:
Nicht am Trade herumpfuschen — SL und Target laufen lassen.

### Test 16: Haltedauer optimieren (2026-04-04)

Frage: Timeout-Trades (100d ohne SL/Target) — bringt laengere Haltedauer mehr?
63% der Timeouts sind im Plus (Median +3.5%), viele fast am Target.

| Haltedauer | Trades | WR | Rendite | DD | Effizienz | Timeouts |
|---|---|---|---|---|---|---|
| **100d (Baseline)** | **308** | 46.8% | **+305%** | 23.7% | **12.9** | 239 |
| 120d | 304 | 47.4% | +288% | 21.8% | 13.2 | 189 |
| 150d | 307 | 46.9% | +279% | 26.2% | 10.6 | 145 |
| 200d | 312 | 47.4% | +290% | 25.6% | 11.3 | 110 |

Laengere Haltedauer rettet einzelne Timeouts, aber gebundenes Kapital fehlt
fuer neue Trades. Netto-Effekt: null bis negativ.

**Entscheidung:** 100d beibehalten. 120d marginal besser bei Effizienz, aber
zu wenig Unterschied fuer eine Aenderung.

### Test 17: Validierung Test 15 + BE-bei-Profit mit vollem Simulator (2026-04-04)

Tests 15 (Time-Stop) und Breakeven-bei-Profit wurden urspruenglich mit
manueller Outcome-Zaehlung gemacht. Hier die Validierung mit vollem
Portfolio-Simulator (max 5 Positionen, Risk 2%, Persistenz-Ranking).

**Time-Stop (voller Simulator):**

| Config | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| **Baseline** | **312** | **47.4%** | **+290%** | 25.6% | **11.3** |
| TS: 10d -3% | 312 | 45.2% | +249% | 25.6% | 9.7 |
| TS: 7d -2% | 312 | 44.2% | +246% | 25.8% | 9.5 |

**Breakeven bei Profit (voller Simulator):**

| Config | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| **Baseline** | **312** | **47.4%** | **+290%** | 25.6% | **11.3** |
| BE +10% Aktie (~200% Prod) | 312 | 42.6% | +244% | 24.4% | 10.0 |
| BE +7.5% Aktie (~150% Prod) | 312 | 38.8% | +192% | 23.1% | 8.3 |

Gleiche Trade-Anzahl (312) — fruehere Exits machen keine Slots frei
fuer zusaetzliche Trades. Ergebnis bestaetigt manuelle Analyse.

**Entscheidung:** Bestaetigt: Baseline gewinnt. Nicht am Trade herumpfuschen.

### Test 18: Trend-Following nach Target (2026-04-04)

Frage: Wenn ein Trade sein Target (2R) erreicht, kann man den Trend weiterreiten
statt hart zu verkaufen? Post-Exit-Analyse (Test 13) zeigte: 60% steigen nach Target
weiter (Median +4.6% nach 50d).

Strategie: Bei Target (2R) nicht verkaufen, sondern SL auf +1R hochziehen (Gewinn
gesichert), dann Trailing-SL (Close - X × ATR) aktivieren.

| Config | Trades | WR | Rendite | DD | Effizienz |
|---|---|---|---|---|---|
| Baseline (hard exit 2R) | 312 | 47.4% | +290% | 25.6% | 11.3 |
| Lock 1R, Target 3R | 312 | 23.7% | +345% | 28.1% | 12.3 |
| Lock 1R, Target 4R | 312 | 18.6% | +575% | 27.3% | 21.1 |
| Lock 1R, Trail 1.5×ATR | 312 | 0.0% | +590% | 27.0% | 21.8 |
| **Lock 1R, Trail 2.0×ATR** | **312** | **0.0%** | **+910%** | **26.2%** | **34.7** |
| Lock 1R, Trail 3.0×ATR | 312 | 0.0% | +1111% | 28.2% | 39.3 |

Validierung Trail 2.0×ATR:
- 372 von 899 Signalen (41%) erreichen Target und gehen in Phase 2
- 70% der Trail-Exits machen WENIGER als hard exit (-5.9% pro Trade)
- 30% machen DEUTLICH MEHR (Top: thyssenkrupp +141%, Schaeffler +80%)
- Die wenigen Big Winner treiben den Gesamtreturn (Avg +14.9% vs +12.9%)
- Min Trail-Exit: +4.9% — kein Trade geht ins Minus (1R gesichert)
- Haltedauer verdoppelt sich: 22d → 44d

Positions-Vergleich (Trail 2×ATR ist auf jeder Stufe 3× besser):

| Positionen | Baseline Return | Trail Return | Faktor |
|---|---|---|---|
| 5 | +290% | +910% | 3.1× |
| 7 | +288% | +903% | 3.1× |
| 10 | +219% | +691% | 3.2× |

**Entscheidung:** UEBERNEHMEN. Lock 1R + Trail 2.0×ATR nach Target-Erreichen.
Verdreifacht den Return bei gleichem Drawdown.
Reports: results/2026-04-04_1129_trend_follow/, results/2026-04-04_1151_trend_follow_positions/

---

## Aktueller bester Stand — Pattern-Signale (2026-04-04)

| Parameter | Wert |
|---|---|
| Patterns | ema50_bounce + gap_up_continuation |
| Target | Fix R/R=2.0 (Entry + 2 × Risk) → Phase 2 Trigger |
| Bei Target | SL auf +1R hochziehen, dann Trailing 2.0×ATR |
| SL | Vom Pattern-Detektor, min 5% Distanz |
| Sizing | Risk 2% freies Cash, max €2.500 Eigenkapital |
| Ranking | persistence_score: combo_score + persistence × 0.2, Lookback 10 Tage |
| Markt-Veto | Keins (Trader entscheidet manuell) |
| Pos-Limit / Einzahlung | Manuell (nicht im System) |

---

## Offene Fragen

- Trend-Following in App einbauen (Phase 2 Logik)
- US-Titel mit eigenem Markt-Kontext testen
- Blocking-Dauer ggf. verkuerzen
- Paper-Trading starten (min. 3 Monate)
