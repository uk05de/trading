# Erkenntnisse aus Backtests

## März 2026 — Erste umfassende Analyse

### Gewichtungs-Optimierung funktioniert nicht
Alle Versuche, die 13 Bedingungsgewichte zu optimieren, haben die Ergebnisse **verschlechtert** gegenüber Standard v1 (alle = 1.0). Das liegt vermutlich an Overfitting auf historische Daten.

### MACD ist der wichtigste Einzelfilter
MACD-Bestätigung allein bringt +6pp Win-Rate. Kein anderer Einzelindikator hat einen vergleichbaren Filtereffekt.

### 1 Gegen-Stimme ist optimal
Trades mit exakt einer Gegen-Stimme performen am besten (65.4% WR). Komplett einstimmige Signale sind etwas schwächer. Erklärung: Leichter Widerstand deutet auf realistische Einschätzung hin.

### US-Markt braucht eigene Regeln
Das System ist auf den deutschen Markt kalibriert:
- DAX als Markt-Kontext funktioniert nicht für US-Aktien
- US-LONG: 49.1% WR, Ø -1.34% (schlecht)
- US-SHORT: 77.5% WR (gut, aber andere Dynamik)
- → US-Titel deaktiviert, bräuchten eigenen S&P-Kontext und eigene Veto-Regeln

### Kosten beachten
Bei kleinen Summen mit Hebelprodukten (x5) und €2 Gebühren pro Trade sind marginale Trades (+0.70%) nach Kosten unprofitabel. Nur klare Signale mit hohem R/R lohnen sich.

### R/R-Filter verschiebt sich
- 1-Jahres-Backtest: R/R ≥ 1.0 optimal
- 2-Jahres-Backtest: R/R ≥ 1.5 optimal
- Längere Zeiträume → strengerer Filter nötig

### Sektor-Trend ist kein Filterkriterium (März 2026)

Getestet: Sektor-Trend entgegen Aktien-Signal → kein Trade?

**Ergebnis:** Kein zuverlässiger Filtereffekt in beide Richtungen.

| Bei R/R ≥ 1.5 | Trades | Win% | Ø P&L |
|---|---|---|---|
| Sektor bestätigt Signal | 148 | 37.8% | +1.37% |
| Sektor neutral | 32 | 46.9% | +2.91% |
| Sektor GEGEN Signal | 50 | 42.0% | +0.94% |

- Ohne R/R-Filter: "Sektor dagegen" performt sogar besser (relative Stärke)
- Mit R/R ≥ 1.5: "Sektor bestätigt" performt besser
- Ergebnis dreht sich je nach Filter-Level → **kein robuster Effekt**
- Sektor-Trend bleibt als eine der 13 Bedingungen, aber **nicht als Veto-Regel**

### Confidence-Filter schadet — abgeschafft (März 2026)

Getestet: Alle Signale ohne Confidence-Mindestgrenze (vorher: Score ≥ 25).

**Ergebnis:** Niedrige Confidence + kein Veto + hohes R/R = die besten Trades.

#### LONG (entscheidend, da Großteil der Trades)

| Filter | Trades | Win% | Ø P&L |
|---|---|---|---|
| Conf < 25, kein Veto, R/R ≥ 1.0 | 195 | 47.7% | **+1.37%** |
| Conf < 25, kein Veto, R/R ≥ 1.5 | 79 | 38.0% | **+2.33%** |
| Conf < 25, kein Veto, R/R ≥ 2.0 | 39 | 41.0% | **+3.22%** |
| Alter Filter: Conf ≥ 25, R/R ≥ 1.5 | 87 | 42.5% | +0.95% |

Ab Confidence 30 bricht LONG-Performance ein (39% → 32% → 17% WR).

#### Warum?

- Knappes Score-Ergebnis + gutes R/R + MACD bestätigt = Setup das der Markt noch nicht eingepreist hat
- "Alle sind sich einig" (hohe Confidence) = Trend ist vermutlich schon weit gelaufen
- **Veto-Regeln sind der entscheidende Filter**, nicht die Confidence

#### Konsequenz

- MIN_CONFIDENCE von 25 auf **0** gesetzt
- Dashboard Trust-Filter Default auf **0**
- Filterlogik: nur noch **Veto + R/R + bestätigtes Target**

#### Bestätigtes Target bleibt wichtig

| Target-Typ | Trades | Win% | Ø P&L |
|---|---|---|---|
| Bestätigtes Target (S/R-Cluster) | 2342 | 45.3% | +0.33% |
| ATR-Fallback (kein Cluster) | 1066 | 50.2% | -0.28% |

→ Target-Bestätigung behalten, kein Fallback.

### Veto-Regeln: ODER ist besser als UND (März 2026)

Getestet: Soll Veto nur greifen wenn MACD dagegen **und** ≥2 Gegen-Stimmen (statt oder)?

**Ergebnis bei R/R ≥ 1.5:**

| Veto-Variante | Trades | Win% | Ø P&L | Δ vs Veto |
|---|---|---|---|---|
| Kein Veto | 1283 | 29.5% | +0.37% | — |
| **MACD ODER ≥2 (aktuell)** | **231** | **36.8%** | **+0.94%** | **+0.70%** |
| MACD UND ≥2 | 544 | 32.2% | +0.50% | +0.23% |
| MACD UND ≥3 | 1219 | 29.7% | +0.39% | +0.39% |

- ODER-Regel filtert schärfer (231 statt 544 Trades), aber die Qualität ist deutlich besser
- Besonders bei SHORT: aktuelle Regel 53.8% WR vs. kombinierte 34.8%
- **Aktuelle Regeln beibehalten**

#### Veto-Muster

56% aller Signale werden vetoed. Aufschlüsselung:
- Nur MACD-Veto (kein anderer Zweifler): 283 Trades — 51.9% WR, +0.44% (an sich okay)
- Nur ≥2 Gegen-Stimmen (MACD bestätigt): 1275 Trades — 49.3% WR, -0.26%
- **Beides (MACD + ≥2 dagegen): 1161 Trades — 36.3% WR** (die wirklich schlechten)

Häufigste Gegen-Stimmen bei Vetos: MACD (53%), Relative Strength (44%), ADX (32%), Index-Trend (31%).

Bei 1 Gegen-Stimme (erlaubt): index_trend dagegen = beste Trades (74.1% WR, +2.04%).

SHORT wird 77% der Zeit vetoed → erklärt die wenigen SHORT-Trades.

### Leave-One-Out: index_trend entfernt (März 2026)

Jede der 10 testbaren Bedingungen einzeln abgeschaltet und Auswirkung gemessen (R/R ≥ 1.5, ohne Veto).

**Baseline:** 236 Trades | 36.0% WR | Ø +0.99%

| Ohne Bedingung | Trades | Win% | Ø P&L | Δ Ø P&L | Fazit |
|---|---|---|---|---|---|
| **index_trend** | **296** | **37.8%** | **+1.45%** | **+0.46%** | **ENTFERNT** |
| adx_trend | 252 | 37.3% | +1.09% | +0.10% | knapp besser ohne |
| bollinger_squeeze | 241 | 36.5% | +1.02% | +0.03% | egal |
| volume_surge | 239 | 36.0% | +1.00% | +0.01% | egal |
| support_near | 237 | 35.9% | +0.95% | -0.04% | egal |
| resistance_near | 301 | 35.9% | +0.89% | -0.10% | behalten |
| vix_regime | 247 | 34.8% | +0.82% | -0.17% | behalten |
| ema50_trend | 495 | 31.9% | +0.81% | -0.18% | behalten |
| macd_signal | 1120 | 30.4% | +0.44% | -0.55% | **wichtigster Filter** |
| relative_strength | 382 | 29.6% | +0.44% | -0.55% | behalten |

**Warum schadet index_trend?** Wenn der DAX bullisch ist, macht das System mehr LONG-Trades — aber zu Zeitpunkten wo der Trend schon weit gelaufen ist. Ähnlich wie hohe Confidence = zu spät.

**Konsequenz:** `index_trend` Vote auf 0 gesetzt (nur noch als Info im Dashboard sichtbar). System hat jetzt effektiv 12 Bedingungen, davon 9 aktiv im Scoring.

### Stop-Loss Optimierung (März 2026)

Getestet: Verschiedene ATR-Multiplikatoren und Einfluss des S/R-Ankers auf den Stop-Loss.

#### ATR-Multiplikator Vergleich (R/R ≥ 1.5, ohne Veto)

| Variante | Trades | Win% | Ø P&L | Ø SL% |
|---|---|---|---|---|
| 0.50× ATR | 115 | 27.0% | -0.55% | 0.8% |
| 0.75× ATR | 148 | 29.1% | -0.09% | 1.2% |
| 1.00× ATR | 182 | 34.1% | +0.56% | 1.6% |
| 1.25× ATR | 212 | 35.4% | +0.98% | 2.0% |
| 1.50× ATR | 233 | 37.3% | +1.29% | 2.4% |
| 1.75× ATR | 248 | 36.3% | +1.24% | 2.8% |
| 2.00× ATR | 264 | 37.5% | +1.40% | 3.2% |
| **2.50× ATR** | **286** | **38.1%** | **+1.56%** | **4.0%** |
| 3.00× ATR | 292 | 37.3% | +1.33% | 4.8% |
| 3.50× ATR | 293 | 36.9% | +1.17% | 5.6% |
| 4.00× ATR | 297 | 37.0% | +1.14% | 6.4% |
| Standard (v-adj+SR) | 286 | 38.1% | +1.23% | 3.5% |

**Erkenntnis:**
- Zu enger SL (< 1.5× ATR): wird zu oft ausgestoppt, negative Ø P&L
- **Sweet Spot bei 2.5× ATR**: höchste Ø P&L (+1.56%), gute Win-Rate (38.1%)
- Ab 3.0× wird der SL zu weit → weniger R/R-qualifizierte Trades, schlechtere P&L
- Volatilitätsangepasste Multiplikatoren (1.5/2.0/2.5) liegen knapp darunter (+1.23%)

#### S/R-Anker Vergleich

| Variante | Trades | Win% | Ø P&L |
|---|---|---|---|
| Mit S/R-Anker (alt) | 286 | 38.1% | +1.23% |
| Ohne S/R-Anker (nur ATR) | 295 | 37.6% | +1.50% |
| **Δ** | +9 | -0.5% | **+0.27%** |

Der S/R-Anker (`max(stop_atr, stop_support)`) zieht den Stop manchmal näher an den Kurs als der ATR allein vorsieht → wird häufiger unnötig ausgestoppt.

#### Konsequenz

- ATR-Multiplikator auf **festen 2.5×** gesetzt (statt volatilitätsangepasst 1.5/2.0/2.5)
- **S/R-Anker aus Stop-Loss entfernt** (S/R wird weiterhin für Targets verwendet)
- Erwartete Verbesserung: +0.33% Ø P&L pro Trade

### Marktumfeld-Veto: Der wichtigste Filter (März 2026)

**Kernfrage:** Hängt der Erfolg einer Empfehlung vom Marktumfeld ab?

**Antwort: JA — das Marktumfeld ist DER entscheidende Faktor.**

#### Win-Rate nach DAX-Trend

| DAX-Trend | Trades | Win% | Ø P&L |
|---|---|---|---|
| **Bull** (über EMA50+200) | 150 | **43.3%** | **+2.12%** |
| Neutral (dazwischen) | 38 | 18.4% | -3.13% |
| Bear (unter EMA50+200) | 26 | 15.4% | -2.34% |

→ Faktor 3 zwischen Bull und Bear/Neutral!

#### Win-Rate nach VIX-Regime

| VIX | Trades | Win% | Ø P&L |
|---|---|---|---|
| Low (< 15) | 44 | **47.7%** | **+2.94%** |
| Normal (15-25) | 154 | 33.1% | +0.20% |
| High (25-35) | 16 | 25.0% | -1.41% |

#### Das Problem: System erzeugt LONG im Crash

Im Bärenmarkt gibt es 3.035 SHORT-Signale (80%), aber **nur 7 kommen durch alle Filter** (0.2%). Gründe:
- 59% werden durch Veto-Regel 2 (≥2 Gegen-Stimmen) gefiltert — weil "Nahe Support" (+1.5) als Gegen-Stimme gegen SHORT zählt
- 20% haben kein Target
- 21% haben R/R < 1.5

Die wenigen Signale die durchkommen sind überwiegend LONG (73%) — das System interpretiert Crash-Signale (Oversold, nahe Support, Panik-Volumen) als Kaufgelegenheiten. Diese haben nur 15.8% Win-Rate.

**Strukturelle LONG-Bias-Quellen:**
- `Volume Surge`: nur +1.0 oder 0 (nie negativ) → Panik-Volumen = bullish
- `Nahe Support`: +1.5 wenn Aktie zu Support crasht → "Kaufchance"
- `Bollinger BB%`: 74% der Bear-Signale unter 30% → "überverkauft" = LONG

#### Lösung: Marktumfeld-Veto (Stufe 5)

Getestet: 7 Filter-Stufen von "kein Filter" bis "nur LONG im Bull + VIX < 25".

| Filter | Signale | Win% | Ø P&L |
|---|---|---|---|
| Kein Filter | 214 | 35.5% | +0.65% |
| Kein Gegen-Trend | 176 | 38.1% | +1.15% |
| Nur LONG im Bull | 131 | 45.0% | +2.61% |
| **Nur LONG/Bull + VIX < 25** | **129** | **45.7%** | **+2.84%** |

Equity-Ergebnis (10%, 5 Pos, €1.000 Start):

| | Kein Filter | Stufe 5 |
|---|---|---|
| Rendite | +282% | **+2016%** |
| Max DD | 78.7% | **35.9%** |
| Effizienz | 3.6 | **56.2** |

2022 komplett entschärft: vorher 50 Trades mit 16% Win → nachher 12 Trades mit 42% Win.

#### Implementierte Regeln

- **Regel 3**: SHORT komplett deaktiviert (keine zuverlässige Performance in keinem Marktumfeld)
- **Regel 3b**: LONG nur im Bullenmarkt (DAX über EMA50 UND EMA200)
- **Regel 4**: Kein Trade bei VIX ≥ 25 (high/extreme Regime)

#### Konsequenz für Positionslimits

Durch das Marktumfeld-Veto ist das Korrelationsrisiko eliminiert (im Crash wird nicht gehandelt). Dadurch verschiebt sich das optimale Positionslimit:

| | Ohne Markt-Veto | Mit Markt-Veto |
|---|---|---|
| Optimal | 3 Positionen | **5-6 Positionen** |
| Mehr = schlecht? | Ja, ab 5 Verluste | Nein, mehr = besser |
| Unbegrenzt | -97% (Pleite) | +3249% |

Sweet Spot: **5-6 Positionen** bei 10% Risiko, Effizienz 56-75.

### Money Management (März 2026)

→ Ausführliche Dokumentation: [06_money_management.md](06_money_management.md)

#### Empfohlene Methodik: 20% freies Cash

**Regel: Investiere 20% deines FREIEN Cash pro Trade, max. 5 Positionen.**

Realistische Simulation mit Cash-Tracking (freies vs. gebundenes Cash):

| Methode | Rendite | MaxDD | Effizienz | Cash-Engpass |
|---|---|---|---|---|
| **20% freies Cash, 5 Pos** | **+299%** | **33%** | **9.1** | **Nie** |
| Risiko 10% Portfolio, 5 Pos | +1.060% | 36% | 29.5 | Nie (Betrag wird reduziert) |

Vorher (ohne Cash-Check): Risiko 10% Portfolio ergab +2.016%.
Mit Cash-Check: +1.060% — immer noch gut, aber realistischer.

#### Warum 20% vom freien Cash?

- Kein Cash-Engpass — 0 übersprungene Trades im Backtest
- Einfach — keine Formel, nur "20% vom verfügbaren Betrag"
- Selbstregulierend — bei 5 Positionen sind ~67% gebunden, ~33% Reserve
- Im Dashboard integriert: Kontostand eingeben → Stückzahl wird berechnet

#### Risiko-basiert für Fortgeschrittene

```
Risikobetrag = Portfolio-Wert × 10%
Notional     = Risikobetrag / SL-Abstand%
Investiert   = Notional / Hebel (max. 80% von frei)
```

+1.060% Rendite bei 36% Drawdown, Effizienz 29.5. Aber Positionsgrößen schwanken
stark und die Berechnung ist bei jedem Trade anders.

## Offene Ideen

- **Sektor-spezifische Gewichte**: Verschiedene Branchen könnten unterschiedlich auf die 13 Bedingungen reagieren (noch nicht getestet)
- **KI-Batch über Nacht**: Alle Ticker nachts durch KI laufen lassen für Konsens-Filter
- **SHORT-System separat entwickeln**: Eigene Indikatoren/Targets für Bärenmärkte
