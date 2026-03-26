# Money Management & Position-Sizing

## Philosophie

Die Simulation zeigt: **Wie viel** investiert wird, ist genauso wichtig wie **wann**.
Alle Methoden wurden realistisch mit Cash-Tracking getestet — freies Cash, gebundenes Cash,
und tatsächliche Verfügbarkeit bei jedem Trade.

## Empfohlene Methodik: 20% freies Cash

**Regel: Investiere 20% deines FREIEN Cash pro Trade, max. 5 Positionen.**

### So funktioniert's

1. Schau auf dein freies Cash (Kontostand minus offene Positionen)
2. Kaufe KO-Zertifikate für 20% davon
3. Maximal 5 Positionen gleichzeitig
4. Nur LONG, nur wenn DAX über EMA50+200, nur bei VIX < 25

### Beispiel mit €1.000

```
Trade 1: 20% von €1.000 frei = €200 investiert → €800 frei
Trade 2: 20% von €800 frei  = €160 investiert → €640 frei
Trade 3: 20% von €640 frei  = €128 investiert → €512 frei
Trade 4: 20% von €512 frei  = €102 investiert → €410 frei
Trade 5: 20% von €410 frei  = €82 investiert  → €328 frei (Reserve!)
```

→ Nach 5 Trades: €672 gebunden, €328 als Reserve
→ Du bist NIE zu 100% investiert
→ Jeder weitere Trade ist automatisch kleiner (Selbstschutz)

### Warum diese Methode?

- **Kein Cash-Engpass**: 0 übersprungene Trades wegen Geldmangel im Backtest
- **Einfach**: Keine Formel nötig, nur 20% vom verfügbaren Betrag
- **Selbstregulierend**: Bei Verlusten werden Positionen automatisch kleiner
- **+299% Rendite** bei €1.000 Start, 33% max. Drawdown

## Alternatives: Risiko-basiertes Sizing

Für erfahrene Trader die mehr Rendite wollen und die Formel akzeptieren:

### Formel

```
Risikobetrag = Portfolio-Wert × 10%          (max. Verlust bei SL)
Notional     = Risikobetrag / SL-Abstand%    (Gesamtposition)
Investiert   = Notional / Hebel              (tatsächlicher Einsatz)
Cap:           Investiert ≤ 80% des freien Cash
```

### Ergebnis

+1.060% Rendite (vs. +299% bei 20%-Methode), bei nur 36% max. Drawdown.
Effizienz 29.5 (vs. 9.1).

**Nachteil**: Positionsgrößen schwanken stark je nach SL-Abstand. Bei engem SL
kann eine einzelne Position sehr groß werden.

## Vergleich aller Methoden (realistisch mit Cash-Tracking)

| Methode | Rendite | MaxDD | Effizienz | Trades übersprungen |
|---|---|---|---|---|
| 10% freies Cash, 5 Pos | +153% | 18% | 8.4 | 0 |
| **20% freies Cash, 5 Pos** | **+299%** | **33%** | **9.1** | **0** |
| 30% freies Cash, 5 Pos | +372% | 45% | 8.2 | 0 |
| 40% freies Cash, 5 Pos | +384% | 55% | 6.9 | 0 |
| 10% Portfolio, 5 Pos | +246% | 19% | 13.2 | 0 |
| 20% Portfolio, 5 Pos | +615% | 35% | 17.8 | 32 (Cash!) |
| Risiko 5% frei, 5 Pos | +266% | 19% | 14.0 | 0 |
| Risiko 10% frei, 5 Pos | +513% | 34% | 15.0 | 0 |
| **Risiko 10% Portfolio, 5 Pos** | **+1.060%** | **36%** | **29.5** | **0** |

## Cash-Tracking: Warum es wichtig ist

Frühere Simulationen rechneten mit "Kapital" ohne zu prüfen, ob das Geld tatsächlich
frei war. In der Realität:

- **Freies Cash** = Was auf dem Konto liegt (nicht in Positionen gebunden)
- **Gebundenes Cash** = In KO-Zertifikaten investiertes Geld
- **Portfolio-Wert** = Freies Cash + Gebundenes Cash

Wenn du ein KO kaufst, sinkt dein freies Cash. Wenn du es verkaufst,
bekommst du Kaufbetrag ± P&L zurück.

**Problem ohne Cash-Check**: Simulation mit "20% vom Portfolio" (€615% Rendite)
musste 32 Trades überspringen weil nicht genug freies Cash da war.
"20% vom freien Cash" hat dieses Problem nie.

## Unterschied zur alten +2.016% Simulation

Die alte Simulation (analyze_detailed_equity.py) verwendete Risiko 10% vom
Gesamtkapital OHNE zu prüfen ob genug Cash frei war. Die realistische Version
derselben Methode ergibt +1.060% — immer noch hervorragend, aber realistischer.

| | Ohne Cash-Check | Mit Cash-Check |
|---|---|---|
| Risiko 10% Portfolio | +2.016% | +1.060% |
| Differenz | — | Positionen manchmal kleiner weil Cash gebunden |

## Buchungssystem im Dashboard

### Konto-Seite

Die Seite **Konto** zeigt alle Geldbewegungen als Buchungshistorie:

| Buchungstyp | Automatisch? | Beispiel |
|---|---|---|
| **Einzahlung** | Manuell | Überweisung von Girokonto |
| **Auszahlung** | Manuell | Gewinn-Entnahme |
| **Kauf** | Automatisch bei Trade-Eröffnung | Kauf LONG Siemens (50 Stk. × €3.20) |
| **Verkauf** | Automatisch bei Trade-Schließung | Verkauf LONG Siemens (50 Stk. × €4.10) |
| **Korrektur** | Manuell | Abweichung zwischen System und echtem Konto |

Der **Kontostand** (= freies Cash) ergibt sich aus der Summe aller Buchungen.
Keine manuelle Pflege nötig — Käufe und Verkäufe werden automatisch gebucht.

### Workflow für einen Trade

1. **Konto**: Einzahlung buchen (einmalig am Anfang)
2. **Empfehlungen**: Signal anklicken → KO-Produkt per ISIN laden
3. System zeigt: **"Empfehlung: X Stück kaufen (€Y)"**
4. Stückzahl ist vorausgefüllt → "Trade eröffnen"
5. Kauf wird automatisch als Buchung verbucht
6. Beim Schließen: Verkauf wird automatisch verbucht (inkl. P&L)

### Bei Abweichungen

Wenn das System-Guthaben nicht mit dem echten Kontostand übereinstimmt
(z.B. durch Rundungen, Spread, Dividenden), einfach eine **Korrektur-Buchung**
auf der Konto-Seite anlegen.
