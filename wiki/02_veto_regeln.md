# Veto-Regeln

## Philosophie

Gewichtungs-Optimierung hat in allen Tests die Ergebnisse **verschlechtert**. Stattdessen setzen wir auf **binäre Filterregeln**: Wenn bestimmte Bedingungen zutreffen → **kein Trade**. Das ist robuster als Feintuning von Gewichten.

## Aktive Regeln

### Regel 1: MACD-Veto

**Wenn MACD gegen die Signalrichtung stimmt → kein Trade.**

- LONG-Signal aber MACD bearish → Veto
- SHORT-Signal aber MACD bullish → Veto

**Warum?** Backtest-Ergebnis:
- MACD bestätigt Signal: **64.2% Win-Rate**, Ø +2.11%
- MACD gegen Signal: **38.1% Win-Rate**, Ø +0.70%
- Verbesserung: **+6 Prozentpunkte** Win-Rate

### Regel 2: Zu viele Gegen-Stimmen

**Wenn ≥ 2 der 13 Bedingungen gegen die Signalrichtung stimmen → kein Trade.**

Interessante Erkenntnis:
- 0 Gegen-Stimmen: Solide Trades
- **1 Gegen-Stimme: BESTE Trades** (65.4% WR) — leichter Widerstand = gesund
- ≥ 2 Gegen-Stimmen: **35.7% WR** — zu viel Gegenwind

### Regel 3: Marktumfeld-Veto (SHORT + Bear/Neutral)

**Nur LONG im Bullenmarkt handeln. SHORT ist deaktiviert.**

- SHORT-Signal → Veto (keine zuverlässige Performance)
- LONG aber DAX nicht bullisch (neutral oder bear) → Veto

**Warum?**
- LONG im Bull: **45.0% Win, +2.61%**
- LONG im Neutral: 16.7% Win, -3.39%
- LONG im Bear: 15.8% Win, -2.10%
- SHORT funktioniert in keinem Marktumfeld zuverlässig (7 von 3.035 Signalen kommen durch Filter, 14.3% Win)

**Bullenmarkt** = DAX über EMA50 UND über EMA200.

### Regel 4: VIX-Veto

**Kein Trade bei VIX ≥ 25 (high oder extreme Regime).**

- VIX < 15 (low): 47.7% Win, +2.94%
- VIX 15-25 (normal): 33.1% Win, +0.20%
- VIX 25-35 (high): **25.0% Win, -1.41%** → Veto
- VIX ≥ 35 (extreme): → Veto

Bei hoher Volatilität werden Stops häufiger gerissen und die Win-Rate bricht ein.

## Veto im Dashboard

- Veto-Signale werden **angezeigt** (nicht versteckt)
- Qualitätsscore = **0** bei Veto
- Bewertung = "Meiden"
- Veto-Grund wird in separater Spalte gezeigt

## Veto im Backtest

Veto-Trades werden **mitgeführt** (nicht übersprungen), damit wir die Regeln kontinuierlich validieren können:
- Empfohlene Trades: Separate Statistik
- Veto-Trades: Separate Statistik
- Vergleich zeigt ob Veto-Regeln noch funktionieren

**2-Jahres-Validierung:**
- Empfohlen: Ø +1.47% bei R/R ≥ 1.5
- Veto: Ø +0.08% bei R/R ≥ 1.5
- → Regeln **bestätigt**
