# Die 13 Bedingungen im Detail

## Übersicht: Wofür wird was verwendet?

### Cluster 1: Richtungsfindung (LONG oder SHORT)
Alle 13 Bedingungen stimmen ab. Die Summe bestimmt die Richtung:
- Summe positiv → LONG
- Summe negativ → SHORT

### Cluster 2: Veto-Regeln (Trade ja/nein)
- **MACD**: Wenn gegen Signalrichtung → Veto
- **Alle Votes**: Wenn ≥2 gegen Signalrichtung → Veto

### Cluster 3: Target & Stop-Loss Berechnung
Verwendet **keine** der 13 Bedingungen. Nur Kursdaten:
- **ATR**: Stop-Loss Abstand (volatilitätsangepasst)
- **Support/Resistance**: Multi-Timeframe Zonen
- **Fibonacci**: Retracement-Level
- **Swing-Highs/Lows**: Historische Wendepunkte

---

## Die 13 Bedingungen

### Technisch (7 Bedingungen)

| # | Bedingung | Was sie misst | Vote-Bereich | Wann positiv | Wann negativ |
|---|---|---|---|---|---|
| 1 | `ema50_trend` | Mittelfristiger Trend | ±2.0 | EMA50 steigt >0.5% | EMA50 fällt <-0.5% |
| 2 | `macd_signal` | Momentum-Richtung | ±1.5 | MACD > Signal-Linie | MACD < Signal-Linie |
| 3 | `adx_trend` | Trendstärke | -0.5 bis +1.0 | ADX > 25 (starker Trend) | ADX < 15 (kein Trend) |
| 4 | `bollinger_squeeze` | Ausbruchserkennung | ±1.5 | Squeeze + nahe unterem Band | Squeeze + nahe oberem Band |
| 5 | `volume_surge` | Volumen-Bestätigung | 0 bis +1.0 | Vol > 1.5× Durchschnitt | Nie negativ (nur 0) |
| 6 | `support_near` | Nähe zu Support | 0 bis +1.5 | Kurs < 2% über Support | Nie negativ |
| 7 | `resistance_near` | Nähe zu Resistance | -1.0 bis 0 | — | Kurs < 2% unter Resistance |

**Besonderheiten:**
- **EMA50** und **MACD** sind die stärksten Votes (±2.0 / ±1.5) — sie dominieren die Richtungsentscheidung
- **ADX** ist asymmetrisch: starker Trend = +1.0, kein Trend = -0.5 (verstärkt vs. dämpft)
- **Volume** ist nur positiv oder neutral — kein negatives Signal
- **Support/Resistance** sind einseitig: Support = bullish, Resistance = bearish

### Relative Stärke (1 Bedingung)

| # | Bedingung | Was sie misst | Vote-Bereich | Wann positiv | Wann negativ |
|---|---|---|---|---|---|
| 8 | `relative_strength` | Performance vs. DAX | ±1.5 | ROC10 > DAX +3% | ROC10 < DAX -3% |

### Fundamental (1 Bedingung)

| # | Bedingung | Was sie misst | Vote-Bereich | Hinweis |
|---|---|---|---|---|
| 9 | `earnings_proximity` | Nähe zu Earnings | variabel | Im Backtest immer 0 (keine hist. Daten) |

### Markt-Kontext (3 Bedingungen)

| # | Bedingung | Was sie misst | Vote-Bereich | Wann positiv | Wann negativ |
|---|---|---|---|---|---|
| 10 | `index_trend` | DAX-Richtung | **0 (deaktiviert)** | — | — |
| 11 | `vix_regime` | Angst-Level | -1.0 bis +0.5 | VIX < 15 | VIX > 25 |
| 12 | `sector_trend` | Sektor-Momentum | ±1.5 | Sektor-Score > 30 | Sektor-Score < -30 |

**Hinweis:** Im Backtest sind Sektor (=0) und News (=0) immer neutral.

### News (1 Bedingung)

| # | Bedingung | Was sie misst | Vote-Bereich | Hinweis |
|---|---|---|---|---|
| 13 | `news_sentiment` | Nachrichten-Stimmung | variabel | Im Backtest immer 0 |

---

## Indikatoren für Targets (nicht Teil der 13 Bedingungen)

Diese Indikatoren werden **nur** in `targets.py` für Stop-Loss und Kursziel verwendet:

| Indikator | Verwendung |
|---|---|
| **ATR (14)** | Stop-Loss Abstand (fester 2.5× Multiplikator), Mindest-Target-Abstand |
| **ATR%** | Nur noch Info (vorher: Volatilitäts-Regime für variablen Multiplikator) |
| **Support/Resistance** | Multi-TF Zonen für **Targets** (nicht mehr für SL) |
| **Fibonacci** | Retracement-Level aus 50-Tage Swing (für Targets) |
| **Swing-Highs/Lows** | Historische Wendepunkte 120 Tage (für Targets) |

---

## Berechnete aber nicht genutzte Indikatoren

Diese werden in `indicators.py` berechnet, aber nirgends in den 13 Bedingungen verwendet:

| Indikator | Berechnet | Verwendet in |
|---|---|---|
| **RSI (14)** | Ja | Nur Dashboard-Anzeige |
| **Stochastic %K/%D** | Ja | Nirgends |
| **ROC 5d** | Ja | Nirgends |
| **Higher Lows / Lower Highs** | Ja | Nirgends |
| **Gap Detection** | Ja | Nirgends |
| **EMA20** | Ja | Nirgends direkt |
| **EMA200** | Ja | Nur für Warmup-Konvergenz |

---

## Trefferquote pro Bedingung

### Ranking nach Prognosewert (Leave-One-Out, März 2026)

**Wichtig (Entfernung schadet dem System):**
1. `macd_signal` — Δ -0.55% (wichtigster Filter + Veto-Regel)
2. `relative_strength` — Δ -0.55%
3. `ema50_trend` — Δ -0.18%
4. `vix_regime` — Δ -0.17%
5. `resistance_near` — Δ -0.10%

**Neutral:** `bollinger_squeeze`, `volume_surge`, `support_near`

**Schädlich (Entfernung verbessert das System):**
- `index_trend` — Δ +0.46% → **deaktiviert**

**Nicht testbar im Backtest:** `earnings_proximity`, `sector_trend`, `news_sentiment`


**von mir (nicht löschen)**

R/R = Reward / Risk                                                                                                                                                                
      = |Target - Entry| / |Entry - Stop-Loss|                                                                                                                                       
                                                                                                                                                                                     
  Beispiel:                                                                                                                                                                          
  - Entry: 100€                                                                                                                                                                      
  - Target: 115€ → Reward = 15€                                                                                                                                                      
  - Stop-Loss: 90€ → Risk = 10€                                                                                                                                                      
  - R/R = 15 / 10 = 1.5

  Das heißt: Für jeden Euro den du riskierst, kannst du 1,50€ gewinnen.

  │ R/R │          Bedeutung          │ Break-Even WR │
  │ 1.0 │ Gewinn = Verlust            │ 50%           │
  │ 1.5 │ 50% mehr Gewinn als Verlust │ 40%           │
  │ 2.0 │ Doppelt so viel Gewinn      │ 33%           │
  │ 3.0 │ Dreifach                    │ 25%           │

  Entry, Target und Stop-Loss kommen aus compute_targets() in targets.py — die werden technisch berechnet (Support/Resistance, ATR etc.).

  Bei R/R >= 1.5 brauchen wir nur 40% Trefferquote um profitabel zu sein. Unsere aktuelle WR liegt bei ~36% — das ist knapp. Bei R/R >= 1.0 reichen die 36% aber locker.

  Soll ich jetzt das R/R Grid testen (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)?

**Death Cross**

Der Death Cross ist ein klassisches charttechnisches Signal:                                                                                                                       
                                                                                                                                                                                   
  SMA50 kreuzt unter SMA200 = Death Cross                                                                                                                                            
                                                            
  - SMA50: Durchschnittskurs der letzten 50 Handelstage (kurzfristiger Trend)                                                                                                        
  - SMA200: Durchschnittskurs der letzten 200 Handelstage (langfristiger Trend)

  Wenn der kurzfristige Trend unter den langfristigen fällt, signalisiert das: Der Markt dreht in einen Abwärtstrend.

  Das Gegenstück heißt Golden Cross (SMA50 kreuzt über SMA200 = Aufwärtstrend beginnt).

  Beispiel am DAX 2022:
  1. DAX fällt ab Januar von ~16.000 auf ~12.500
  2. SMA50 sinkt schneller als SMA200 (reagiert auf aktuelle Kurse)
  3. Irgendwann kreuzt SMA50 unter SMA200 → Death Cross
  4. Ab jetzt: Veto aktiv, keine Longs auf DAX-Aktien
  5. DAX erholt sich, SMA50 steigt wieder über SMA200 → Golden Cross
  6. Veto aufgehoben, Longs wieder erlaubt

  Warum funktioniert das als Veto?
  - Es ist langsam (SMA200 braucht Monate zum Drehen) → greift nur bei echten Bärenmärkten, nicht bei kurzen Korrekturen
  - Nachteil: Es reagiert spät — der Abwärtstrend hat schon begonnen wenn das Signal kommt, und die Erholung läuft schon wenn es endet

  Bei uns: Death Cross auf dem Index (DAX/TecDAX), nicht auf der einzelnen Aktie. MDAX bleibt offen weil dort der Death Cross fast dauerhaft aktiv ist.
