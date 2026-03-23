# Trading-System — Kontext fuer Claude

Sprache: Deutsch. Der User tradet Hebelprodukte (KO-Zertifikate), nicht direkt Aktien.

## Umgebung

- Python: `.venv/bin/python3` verwenden (nicht system-python, hat keine Pakete)

## Backtest-Framework

Architektur (alle unter Projektroot):
- `bt_config.py` — BacktestConfig Dataclass, Presets
- `bt_signals.py` — Signal-Sammlung (ein Code-Pfad, alle Bug-Fixes)
- `bt_simulate.py` — Portfolio-Simulation (Cash-Tracking, Drawdown, monatl. Einzahlungen, SL-Filter)
- `bt_run.py` — run(), compare(), grid(), **evolve()** (schrittweises Aufbauen)
- `bt_report.py` — HTML-Reports unter results/

### evolve() — Zentrale Testmethode
Signale einmal sammeln (ohne Filter), dann pro Config filtern in simulate().
Schritte sind kumulativ — jeder baut auf dem vorherigen auf.
So sieht man das Gesamtbild und kann Stellschrauben zurueckdrehen.

### Ergebnisse
- `results/` — Pro Lauf ein Ordner mit HTML-Report, Equity-Chart, Trade-Details
- `archive/` — 33 alte analyze_*.py (ersetzt durch Framework, nicht loeschen)

## Testprotokoll

**WICHTIG: `wiki/07_testprotokoll.md` nach jedem Test aktualisieren!**
Dort stehen alle Tests mit Frage, Stellschraube, Ergebnis, Entscheidung.
Auch "Aktueller bester Stand" und "Offene Fragen" dort pflegen.

## Aktueller bester Stand — Pattern-Signale (2026-03-21)

System: Pattern Top2 (ema50_bounce + gap_up_continuation) + Fix R/R=2.0 + SL >= 5% + Risk 2% Cash + max €2.500

| Parameter | Wert |
|---|---|
| Patterns | ema50_bounce + gap_up_continuation |
| Target | Fix R/R=2.0 (Entry + 2 × Risk) |
| SL | Vom Pattern-Detektor, min 5% Distanz |
| Sizing | Risk 2% freies Cash, max €2.500 Eigenkapital |
| Trailing | Nein (verschlechtert Performance) |
| Markt-Veto | Keins (Trader entscheidet manuell) |
| Pos-Limit / Einzahlung | Manuell (nicht im System) |

Backtest-Ergebnis (×3 Projektion, 18 Jahre):
- Trades: ~8/Monat, WR 39.1%, Rendite +2.047%, DD 36%, Eff 56.5
- Endkapital: 265.129 EUR (von 1.500 EUR Start)

### Fruehere beste Config (alte Signale, 2026-03-19)
Baseline + SL 6-8% + Risk 5% Portfolio + 7 Pos + 100 EUR/Monat + R/R >= 1.0
→ 92 Trades, 52.2% WR, +90% Rendite, 31% DD, Eff 2.9

## Wichtigste Erkenntnisse

- **Pattern-Detektoren** (ema50_bounce, gap_up_continuation) schlagen alte Signale (analyze_stock) deutlich
- **Fix R/R=2.0** schlaegt chartbasierte Targets (compute_targets zu konservativ, Median R/R=1.6)
- **SL >= 5% Mindestabstand** eliminiert Rausch-Trades (33% der Signale hatten SL < 4%)
- **Risk 2% Cash** mit max €2.500 Cap ist professionelles Sizing — kontrolliertes Wachstum
- **Trailing verschlechtert** bei R/R=2.0 — Trades brauchen Luft zum Atmen
- **Kein automatisches Markt-Veto** — alle Varianten kosten zu viel Rendite, Trader entscheidet manuell
- Verworfene LONG-Patterns: pullback_ema20, support_bounce, breakout_consolidation, bollinger_squeeze_up
- **SHORT-Patterns komplett verworfen** (Test 7): Alle 6 unprofitabel wegen Survivorship Bias + bullisher Zeitraum. SHORT manuell.

## Offene naechste Schritte

- Trading-App auf Pattern-System umstellen:
  - Signal-Empfehlung: Entry, SL, Target, KO-Schwelle, Stueckzahl, Risk
  - Markt-Info: DAX unter SMA200 → "Achtung Schwaechephase", DAX ueber EMA20 → "Moegliche Erholung"
- US-Titel mit S&P-Markt-Kontext testen
- Blocking-Dauer ggf. verkuerzen
- Trade-Ranking: Entscheidungshilfe wenn mehrere Signale am gleichen Tag (welchen Trade eingehen?)
- Paper-Trading starten (min. 3 Monate)

## Regeln

- **JEDER Backtest MUSS ueber bt_run.py laufen** (run/compare/grid/evolve/evolve_patterns)
  - NIEMALS ad-hoc Python-Snippets fuer Backtests ausfuehren
  - NIEMALS simulate() oder collect_signals() direkt in Einzeilern aufrufen
  - Jedes Ergebnis muss als HTML-Report in results/ landen
  - Reports in results/ sind die einzige Quelle der Wahrheit fuer Vergleiche
- Keine Gewichtungs-Optimierung (bringt nichts, Overfitting)
- Testprotokoll pflegen (wiki/07_testprotokoll.md)
- Immer evolve() mit Report nutzen fuer Tests
- SL-Aenderungen nur im Backtester, nicht in der App (bis validiert)
- HTML-Reports: Tabellenheader muessen sticky sein (position: sticky, top: 0 auf thead th, .table-scroll braucht position: relative)
