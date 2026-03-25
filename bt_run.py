"""
Backtest-Framework: Runner.

Zentraler Einstiegspunkt fuer alle Backtests.
Jeder Lauf erzeugt einen Ordner unter results/ mit HTML-Report.

  run(cfg)               -> Einzelner Lauf, gibt BacktestResult zurueck
  compare([cfg1, cfg2])  -> Mehrere Configs mit GLEICHEN Signalen vergleichen
  grid(base, param, values) -> Parameter-Grid (z.B. max_positions=[1,3,5,7,10])

Verwendung:
  python bt_run.py                      # Produktions-Preset
  python bt_run.py --compare            # Alle Presets vergleichen
  python bt_run.py --grid positions     # Positions-Grid
  python bt_run.py --grid sizing        # Sizing-Grid
"""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from itertools import product

import pandas as pd

from bt_config import (
    BacktestConfig,
    preset_baseline, preset_baseline_v1, preset_best,
    preset_production, preset_risk_portfolio,
    preset_conservative, preset_aggressive,
)
try:
    from bt_signals import collect_signals
except ImportError:
    collect_signals = None  # bt_signals.py im Archive, nur fuer alte Funktionen
from bt_simulate import simulate, BacktestResult
from bt_report import generate_report, generate_compare_report, _make_run_dir


SURVIVORSHIP_WARNING = (
    "HINWEIS: Nur aktuelle DAX/MDAX/TecDAX-Mitglieder getestet. "
    "Firmen die abgestiegen oder insolvent sind fehlen (Survivorship-Bias). "
    "Reale Performance ist wahrscheinlich 10-20% niedriger."
)


# ─── Einzelner Lauf ──────────────────────────────────────────────────────

def run(cfg: BacktestConfig | None = None, verbose: bool = True,
        report: bool = True) -> BacktestResult:
    """Einen Backtest-Lauf ausfuehren. Erzeugt HTML-Report in results/."""
    if cfg is None:
        cfg = preset_production()

    if verbose:
        print(f"\n  Sammle Signale: {cfg.label()}")

    signals = collect_signals(cfg, verbose=verbose)
    result = simulate(signals, cfg)

    if verbose:
        print(f"  {result.summary_line()}")

    if report:
        path = generate_report(result)
        if verbose:
            print(f"  Report: {path}")

    return result


# ─── Vergleich mehrerer Configs ──────────────────────────────────────────

def compare(configs: list[BacktestConfig],
            signals: pd.DataFrame | None = None,
            verbose: bool = True,
            report: bool = True) -> list[BacktestResult]:
    """
    Mehrere Konfigurationen vergleichen.

    Wenn signals=None, werden Signale aus der ERSTEN Config gesammelt
    und fuer alle Configs wiederverwendet (fair: gleiche Signale).
    Erzeugt Vergleichs-Report + Einzel-Reports pro Config.
    """
    if not configs:
        return []

    # Signale einmal sammeln
    if signals is None:
        base_cfg = configs[0]
        if verbose:
            print(f"\n  Sammle Signale (Basis: {base_cfg.label()})...")
        signals = collect_signals(base_cfg, verbose=verbose)

    results = []
    if verbose:
        print(f"\n  {'Konfiguration':>35s} | {'Sig':>4s} {'Tr':>4s} {'WR':>6s} | "
              f"{'Ret':>7s} {'DD':>5s} {'Eff':>5s} | {'Endkapital':>10s}")
        print(f"  {'─' * 90}")

    for cfg in configs:
        result = simulate(signals, cfg)
        results.append(result)
        if verbose:
            print(f"  {result.summary_line()}")

    if report and results:
        run_dir = _make_run_dir(BacktestConfig(name="vergleich"))
        # Vergleichs-Report
        path = generate_compare_report(results, run_dir=run_dir)
        # Einzel-Reports fuer jeden (mit Vergleichs-Chart)
        for r in results:
            generate_report(r, run_dir=run_dir, all_results=results)
        if verbose:
            print(f"  Reports: {run_dir}/")

    return results


# ─── Parameter-Grid ──────────────────────────────────────────────────────

def grid(base: BacktestConfig | None = None,
         params: dict[str, list] | None = None,
         signals: pd.DataFrame | None = None,
         verbose: bool = True,
         report: bool = True) -> list[BacktestResult]:
    """
    Parameter-Grid durchlaufen.

    params: z.B. {"max_positions": [1,3,5,7,10], "sizing_pct": [0.10, 0.20]}
    Erzeugt das kartesische Produkt aller Kombinationen.
    """
    if base is None:
        base = preset_production()
    if params is None:
        params = {"max_positions": [1, 3, 5, 7, 10]}

    # Signale einmal sammeln
    if signals is None:
        if verbose:
            print(f"\n  Sammle Signale (Basis: {base.label()})...")
        signals = collect_signals(base, verbose=verbose)

    # Kartesisches Produkt
    param_names = list(params.keys())
    param_values = list(params.values())
    combos = list(product(*param_values))

    configs = []
    for combo in combos:
        overrides = dict(zip(param_names, combo))
        label_parts = [f"{k}={v}" for k, v in overrides.items()]
        cfg = replace(base, name=", ".join(label_parts), **overrides)
        configs.append(cfg)

    return compare(configs, signals=signals, verbose=verbose, report=report)


# ─── Schrittweises Aufbauen (evolve) ─────────────────────────────────────

def evolve(steps: list[tuple[str, dict]],
           base: BacktestConfig | None = None,
           verbose: bool = True,
           report: bool = True) -> list[BacktestResult]:
    """
    Annahmen schrittweise aufbauen und Gesamtbild sehen.

    Jeder Schritt ist ein Tuple: (Name, {param: wert, ...})
    Die Aenderungen sind KUMULATIV — jeder Schritt baut auf dem vorherigen auf.
    Plus: Jede Aenderung wird auch EINZELN auf der Baseline getestet.

    Beispiel:
        evolve([
            ("+ SL Floor 6%",    {"min_sl_dist": 0.06}),
            ("+ SL Ceiling 8%",  {"max_sl_dist": 0.08}),
            ("+ Risk-Sizing",    {"sizing_method": "risk_portfolio", "sizing_pct": 0.05}),
            ("+ 7 Positionen",   {"max_positions": 7}),
            ("+ 100€/Monat",     {"monthly_deposit": 100}),
        ])

    Erzeugt:
        1. Baseline (unveraendert)
        2. Baseline + SL Floor
        3. Baseline + SL Floor + SL Ceiling
        4. Baseline + SL Floor + SL Ceiling + Risk-Sizing
        5. ... usw (kumulativ)
    """
    if base is None:
        base = preset_production()

    # Signale einmal mit minimalsten Filtern sammeln
    signal_cfg = replace(base,
                         min_sl_dist=0.0, max_sl_dist=1.0,
                         min_rr=0.0, only_long=False)
    if verbose:
        print(f"\n  Sammle alle Signale (ohne Filter)...")
    signals = collect_signals(signal_cfg, verbose=verbose)

    # Baseline
    configs = [replace(base, name="0. Baseline")]

    # Kumulativ aufbauen
    current = base
    for i, (name, overrides) in enumerate(steps, 1):
        current = replace(current, name=f"{i}. {name}", **overrides)
        configs.append(current)

    # Simulieren
    results = []
    if verbose:
        print(f"\n  {'#':>3s} {'Konfiguration':>35s} | {'Sig':>4s} {'Tr':>4s} {'WR':>6s} | "
              f"{'Ret':>7s} {'DD':>6s} {'Eff':>5s} | {'Endkap.':>10s} {'Eingez.':>8s}")
        print(f"  {'─' * 100}")

    for cfg in configs:
        r = simulate(signals, cfg)
        results.append(r)
        if verbose:
            dep = f"€{r.total_deposited:,.0f}" if r.total_deposited > cfg.start_capital else ""
            print(f"  {cfg.name:>39s} | {r.n_signals:>4d} {r.n_trades:>4d} {r.win_rate:>5.1f}% | "
                  f"{r.total_return:>+7.1f}% {r.max_drawdown:>5.1f}% {r.efficiency:>5.1f} | "
                  f"€{r.end_capital:>9,.2f} {dep:>8s}")

    if report and results:
        run_dir = _make_run_dir(BacktestConfig(name="evolve"))
        generate_compare_report(results, run_dir=run_dir)
        for r in results:
            generate_report(r, run_dir=run_dir, all_results=results)
        if verbose:
            print(f"\n  Reports: {run_dir}/")
        import subprocess
        subprocess.run(["open", str(run_dir / "report.html")])

    return results


# ─── Trade-Details (Terminal) ────────────────────────────────────────────

def print_trades(result: BacktestResult, n: int = 20) -> None:
    """Die letzten N Trades im Terminal ausgeben."""
    if len(result.trades) == 0:
        print("  Keine Trades.")
        return

    df = result.trades.tail(n)
    print(f"\n  Letzte {len(df)} Trades ({result.config.label()}):")
    print(f"  {'Datum':>12s} {'Ticker':>10s} {'Richtung':>8s} {'Ergebnis':>8s} "
          f"{'P&L%':>7s} {'Invest':>8s} {'P&L Euro':>8s} {'Tage':>5s} {'R/R':>5s}")
    print(f"  {'─' * 85}")

    for _, t in df.iterrows():
        print(f"  {str(t['date'])[:10]:>12s} {t['ticker']:>10s} {t['direction']:>8s} "
              f"{t['outcome']:>8s} {t['pnl_pct']:>+6.1f}% "
              f"€{t['invested']:>7.2f} €{t['pnl_euro']:>+7.2f} "
              f"{t['days_held']:>5d} {t['risk_reward']:>5.1f}")


# ─── Vordefinierte Grids ─────────────────────────────────────────────────

def grid_positions(signals: pd.DataFrame | None = None) -> list[BacktestResult]:
    """Test: Optimale Anzahl Positionen."""
    return grid(
        base=preset_production(),
        params={"max_positions": [1, 3, 5, 7, 10, 999]},
        signals=signals,
    )


def grid_sizing(signals: pd.DataFrame | None = None) -> list[BacktestResult]:
    """Test: Alle Sizing-Varianten."""
    base = preset_production()
    configs = []

    for pct in [0.10, 0.15, 0.20, 0.25, 0.30]:
        configs.append(replace(base,
            name=f"{int(pct*100)}% frei",
            sizing_method="fixed_free", sizing_pct=pct))

    for pct in [0.02, 0.05, 0.10, 0.15]:
        configs.append(replace(base,
            name=f"Risiko {int(pct*100)}% frei",
            sizing_method="risk_free", sizing_pct=pct))

    for pct in [0.02, 0.05, 0.10, 0.15]:
        configs.append(replace(base,
            name=f"Risiko {int(pct*100)}% Portf.",
            sizing_method="risk_portfolio", sizing_pct=pct))

    if signals is None:
        print("\n  Sammle Signale...")
        signals = collect_signals(base)

    return compare(configs, signals=signals)


def grid_market_veto(verbose: bool = True) -> list[BacktestResult]:
    """Test: Markt-Veto an/aus."""
    cfg_on = preset_production()
    cfg_off = replace(cfg_on, name="OHNE Markt-Veto", use_market_veto=False)

    if verbose:
        print("\n  Sammle Signale MIT Markt-Veto...")
    sig_on = collect_signals(cfg_on, verbose=verbose)

    if verbose:
        print("\n  Sammle Signale OHNE Markt-Veto...")
    sig_off = collect_signals(cfg_off, verbose=verbose)

    r_on = simulate(sig_on, cfg_on)
    r_off = simulate(sig_off, cfg_off)

    if verbose:
        print(f"\n  {'Konfiguration':>35s} | {'Sig':>4s} {'Tr':>4s} {'WR':>6s} | "
              f"{'Ret':>7s} {'DD':>5s} {'Eff':>5s} | {'Endkapital':>10s}")
        print(f"  {'─' * 90}")
        print(f"  {r_off.summary_line()}")
        print(f"  {r_on.summary_line()}")

    # Reports
    run_dir = _make_run_dir(BacktestConfig(name="markt_veto_vergleich"))
    generate_compare_report([r_off, r_on], run_dir=run_dir)
    generate_report(r_off, run_dir=run_dir)
    generate_report(r_on, run_dir=run_dir)
    if verbose:
        print(f"  Reports: {run_dir}/")

    return [r_off, r_on]


# ─── Pattern-Vergleich ─────────────────────────────────────────────────────

ALL_PATTERNS = [
    "pullback_ema20",
    "ema50_bounce",
    "support_bounce",
    "breakout_consolidation",
    "bollinger_squeeze_up",
    "gap_up_continuation",
]


def evolve_patterns(verbose: bool = True,
                    report: bool = True) -> list[BacktestResult]:
    """
    Pattern Top2 (ema50_bounce + gap_up_continuation) mit Fix R/R=2.0.

    Getestete und verworfene Varianten (siehe wiki/07_testprotokoll.md Test 6):
      - Chartbasierte Targets: Zu konservativ, Fix R/R=2.0 besser
      - Trailing-SL: Verschlechtert Performance, Trades brauchen Luft
      - pullback_ema20, support_bounce, breakout_consolidation: Unprofitabel
      - bollinger_squeeze_up: Marginal, nicht lohnenswert

    Referenz-Signale (alte Methode) werden gecached in data/signals_old_ref.pkl.
    Pattern-Signale werden gecached in data/signals_patterns_rr2.0.pkl.
    """
    from bt_signals_patterns import collect_pattern_signals
    force = "--rescan" in sys.argv

    WINNER_PATTERNS = ["ema50_bounce", "gap_up_continuation"]
    OLD_SIGNALS_CACHE = "data/signals_old_ref.pkl"

    # ==================================================================
    # Signale laden (gecached)
    # ==================================================================

    # Alte Signale (Referenz)
    if not force and os.path.exists(OLD_SIGNALS_CACHE):
        if verbose:
            print(f"\n  Alte Signale aus Cache: {OLD_SIGNALS_CACHE}")
        old_signals = pd.read_pickle(OLD_SIGNALS_CACHE)
    else:
        ref_base = preset_baseline()
        ref_signal_cfg = replace(ref_base,
                                 min_sl_dist=0.0, max_sl_dist=1.0,
                                 min_rr=0.0, only_long=False)
        if verbose:
            print(f"\n  Sammle alte Signale...")
        old_signals = collect_signals(ref_signal_cfg, verbose=verbose)
        old_signals.to_pickle(OLD_SIGNALS_CACHE)
        if verbose:
            print(f"  -> Cache: {OLD_SIGNALS_CACHE}")

    # Pattern-Signale (Fix R/R=2.0)
    pat_base = preset_baseline_v1()
    if verbose:
        print(f"\n  Lade Pattern-Signale (Fix R/R=2.0)...")
    pat_signals = collect_pattern_signals(pat_base, target_rr=2.0,
                                          force_rescan=force, verbose=verbose)
    if pat_signals.empty:
        print("  Keine Pattern-Signale gefunden!")
        return []

    # ==================================================================
    # Ausgabe-Funktionen
    # ==================================================================
    def _print_header(title: str) -> None:
        if verbose:
            print(f"\n  === {title} ===")
            print(f"  {'Konfiguration':>55s} | {'Sig':>4s} {'Tr':>4s} {'WR':>6s} | "
                  f"{'Ret':>7s} {'DD':>6s} {'Eff':>5s} | {'Endkap.':>10s}")
            print(f"  {'─' * 110}")

    def _print_result(r: BacktestResult) -> None:
        if verbose:
            print(f"  {r.config.name:>55s} | {r.n_signals:>4d} {r.n_trades:>4d} {r.win_rate:>5.1f}% | "
                  f"{r.total_return:>+7.1f}% {r.max_drawdown:>5.1f}% {r.efficiency:>5.1f} | "
                  f"€{r.end_capital:>9,.2f}")

    all_results: list[BacktestResult] = []

    # ==================================================================
    # ==================================================================
    # Finales LONG System: Risk 2% Cash, max €2500
    # ==================================================================
    # SL-Floor ist jetzt im Detektor (min 5%) — kein Filter mehr noetig
    sizing_base = replace(pat_base,
                          min_invest=25.0,
                          sizing_method="risk_free", sizing_pct=0.02,
                          max_invest=2500.0)

    # ==================================================================
    # Signal-Ranking: Welche Trades bei begrenztem Budget?
    # ==================================================================
    _print_header("Signal-Ranking (max 5 Pos)")

    rankings = ["none", "sl_dist_asc", "adx", "combo_score", "random"]

    for max_pos in [3, 5, 7, 10]:
        _print_header(f"Signal-Ranking (max {max_pos} Pos)")
        for ranking in rankings:
            cfg = replace(sizing_base,
                          name=f"{max_pos} Pos, {ranking}",
                          pattern_filter=WINNER_PATTERNS,
                          max_positions=max_pos,
                          signal_ranking=ranking)
            r = simulate(pat_signals, cfg)
            all_results.append(r)
            _print_result(r)

    # ==================================================================
    # Hysterese-Veto: Unter SMA200 → Pause, verschiedene Reset-Level
    # ==================================================================
    from backtest import _download as _dl

    dax_df = _dl("^GDAXI", days=2800)
    dax_close = dax_df["Close"]
    dax_sma200 = dax_close.rolling(200).mean()
    dax_ema50 = dax_close.ewm(span=50, adjust=False).mean()
    dax_ema20 = dax_close.ewm(span=20, adjust=False).mean()

    # Berechne Veto-Status pro Tag (Hysterese: AN wenn unter SMA200, AUS wenn ueber Reset)
    def _hysterese_veto(trigger_series, reset_series) -> pd.Series:
        """Veto AN wenn close < trigger, bleibt AN bis close > reset."""
        veto_on = pd.Series(False, index=dax_df.index)
        active = False
        for date in dax_df.index:
            c = float(dax_close.get(date, 0))
            t = float(trigger_series.get(date, 0))
            r = float(reset_series.get(date, 0))
            if active:
                # Veto ist AN — nur Reset pruefen
                if c > r:
                    active = False
            else:
                # Veto ist AUS — nur Trigger pruefen
                if c < t:
                    active = True
            veto_on[date] = active
        return veto_on

    veto_sma200_sma200 = _hysterese_veto(dax_sma200, dax_sma200)
    veto_sma200_ema50 = _hysterese_veto(dax_sma200, dax_ema50)
    veto_sma200_ema20 = _hysterese_veto(dax_sma200, dax_ema20)

    def _apply_hysterese(signals: pd.DataFrame, veto: pd.Series) -> pd.DataFrame:
        keep = []
        for _, row in signals.iterrows():
            sig_date = pd.Timestamp(row["date"])
            mask = dax_df.index <= sig_date
            if mask.any():
                nearest = dax_df.index[mask][-1]
                keep.append(not veto.get(nearest, False))
            else:
                keep.append(True)
        return signals[keep].copy().reset_index(drop=True)

    # Pattern Top2 filtern
    pat_top2 = pat_signals[
        pat_signals["pattern"].isin(WINNER_PATTERNS)
    ].copy()

    _print_header("Hysterese-Veto: Unter SMA200, verschiedene Reset-Level")

    # Ohne Veto
    cfg_base = replace(sizing_base, name="Ohne Veto",
                       pattern_filter=WINNER_PATTERNS)
    r = simulate(pat_signals, cfg_base)
    all_results.append(r)
    _print_result(r)

    veto_variants = [
        ("Unter SMA200 → ueber SMA200", veto_sma200_sma200),
        ("Unter SMA200 → ueber EMA50",  veto_sma200_ema50),
        ("Unter SMA200 → ueber EMA20",  veto_sma200_ema20),
    ]

    for name, veto in veto_variants:
        filtered = _apply_hysterese(pat_top2, veto)
        n_blocked = len(pat_top2) - len(filtered)
        cfg = replace(sizing_base, name=name)
        r = simulate(filtered, cfg)
        all_results.append(r)
        blocked_pct = n_blocked / len(pat_top2) * 100 if len(pat_top2) > 0 else 0
        if verbose:
            print(f"  {name:>55s} | {r.n_signals:>4d} {r.n_trades:>4d} {r.win_rate:>5.1f}% | "
                  f"{r.total_return:>+7.1f}% {r.max_drawdown:>5.1f}% {r.efficiency:>5.1f} | "
                  f"€{r.end_capital:>9,.2f}  ({n_blocked} geblockt, {blocked_pct:.0f}%)")

    # ==================================================================
    # Report
    # ==================================================================
    if report and all_results:
        run_dir = _make_run_dir(BacktestConfig(name="pattern_vergleich"))
        generate_compare_report(all_results, run_dir=run_dir)
        for r in all_results:
            generate_report(r, run_dir=run_dir, all_results=all_results)
        if verbose:
            print(f"\n  Reports: {run_dir}/")
        import subprocess
        subprocess.run(["open", str(run_dir / "report.html")])

    return all_results


# ─── Pattern-Grid (systematischer Vergleich) ─────────────────────────────

def grid_patterns(verbose: bool = True, report: bool = True) -> list[BacktestResult]:
    """
    Systematisches Grid ueber alle Pattern × R/R × SL-Kombinationen.

    Dimensionen:
      - R/R: 1.5, 2.0, 2.5, 3.0
      - Patterns: jedes einzeln + Top-Kombinationen
      - SL-Bands: kein SL, 4-10%, 6-8%, 6-10%

    Ergebnis: Ranking nach Effizienz. Report in results/.
    """
    from bt_signals_patterns import collect_pattern_signals

    pat_base = preset_baseline_v1()

    rr_values = [1.5, 2.0, 2.5, 3.0]
    sl_bands = [
        ("kein SL",  0.0,  1.0),
        ("SL 4-10%", 0.04, 0.10),
        ("SL 6-8%",  0.06, 0.08),
        ("SL 6-10%", 0.06, 0.10),
    ]

    all_results: list[BacktestResult] = []
    ranking: list[dict] = []

    for rr in rr_values:
        if verbose:
            print(f"\n  ── R/R = {rr} ──────────────────────────────────")

        # Signale fuer diesen R/R-Wert sammeln (Cache pro R/R)
        import os
        cache = f"data/signals_patterns_rr{rr:.1f}.pkl"
        if os.path.exists(cache):
            signals = pd.read_pickle(cache)
            if verbose:
                print(f"  Cache: {cache} ({len(signals)} Signale)")
        else:
            if verbose:
                print(f"  Sammle Signale (R/R={rr})...")
            signals = collect_pattern_signals(
                pat_base, target_rr=rr, force_rescan=True, verbose=verbose)
            if not signals.empty:
                signals.to_pickle(cache)

        if signals.empty:
            continue

        # Pattern-Sets: einzeln + Kombis
        # Erst alle einzeln durchrechnen fuer Ranking
        single_eff: dict[str, float] = {}
        for pat in ALL_PATTERNS:
            sub = signals[signals["pattern"] == pat]
            if len(sub) == 0:
                continue
            cfg = replace(pat_base, name=f"{pat} | R/R={rr} | kein SL",
                          pattern_filter=[pat])
            r = simulate(sub, cfg)
            single_eff[pat] = r.efficiency

        # Top-Patterns nach Effizienz
        ranked_pats = sorted(single_eff.items(), key=lambda x: x[1], reverse=True)
        profitable = [p for p, e in ranked_pats if e > 0]

        pattern_sets: list[tuple[str, list[str]]] = []
        # Einzelne
        for pat in ALL_PATTERNS:
            pattern_sets.append((pat, [pat]))
        # Kombinationen
        if len(profitable) >= 2:
            pattern_sets.append((f"Top2({'+'.join(profitable[:2])})", profitable[:2]))
        if len(profitable) >= 3:
            pattern_sets.append((f"Top3({'+'.join(profitable[:3])})", profitable[:3]))
        if len(profitable) >= 1:
            pattern_sets.append(("Alle profitablen", profitable))
        pattern_sets.append(("Alle Patterns", []))

        # Grid: Pattern × SL-Band
        for pat_name, pat_filter in pattern_sets:
            for sl_name, sl_min, sl_max in sl_bands:
                name = f"{pat_name} | R/R={rr} | {sl_name}"
                cfg = replace(pat_base, name=name,
                              pattern_filter=pat_filter,
                              min_sl_dist=sl_min, max_sl_dist=sl_max)
                r = simulate(signals, cfg)
                all_results.append(r)

                ranking.append({
                    "name": name,
                    "pattern": pat_name,
                    "rr": rr,
                    "sl_band": sl_name,
                    "signals": r.n_signals,
                    "trades": r.n_trades,
                    "win_rate": r.win_rate,
                    "total_return": r.total_return,
                    "max_dd": r.max_drawdown,
                    "efficiency": r.efficiency,
                    "end_capital": r.end_capital,
                })

    # ── Ranking ausgeben ──
    ranking_df = pd.DataFrame(ranking)
    if ranking_df.empty:
        print("  Keine Ergebnisse!")
        return []

    # Nur Configs mit mindestens 20 Trades
    ranking_df = ranking_df[ranking_df["trades"] >= 20]
    ranking_df = ranking_df.sort_values("efficiency", ascending=False)

    if verbose:
        print(f"\n  {'=' * 120}")
        print(f"  TOP 20 KOMBINATIONEN (nach Effizienz, min. 20 Trades)")
        print(f"  {'=' * 120}")
        print(f"  {'#':>3s} {'Konfiguration':>55s} | {'Sig':>4s} {'Tr':>4s} {'WR':>6s} | "
              f"{'Ret':>8s} {'DD':>6s} {'Eff':>5s} | {'Endkap.':>10s}")
        print(f"  {'─' * 115}")

        for i, (_, row) in enumerate(ranking_df.head(20).iterrows()):
            print(f"  {i+1:>3d} {row['name']:>55s} | {row['signals']:>4.0f} {row['trades']:>4.0f} {row['win_rate']:>5.1f}% | "
                  f"{row['total_return']:>+7.1f}% {row['max_dd']:>5.1f}% {row['efficiency']:>5.1f} | "
                  f"€{row['end_capital']:>9,.2f}")

    # ── Report ──
    if report:
        # Nur Top 20 fuer den Report (sonst zu viele)
        top_names = set(ranking_df.head(20)["name"])
        top_results = [r for r in all_results if r.config.name in top_names]

        run_dir = _make_run_dir(BacktestConfig(name="pattern_grid"))
        generate_compare_report(top_results, run_dir=run_dir)
        for r in top_results:
            generate_report(r, run_dir=run_dir, all_results=top_results)

        # Ranking als CSV speichern
        csv_path = run_dir / "ranking.csv"
        ranking_df.to_csv(csv_path, index=False)

        if verbose:
            print(f"\n  Reports: {run_dir}/")
            print(f"  Ranking CSV: {csv_path}")
            print(f"  Gesamt: {len(ranking_df)} Kombinationen getestet")

        import subprocess
        subprocess.run(["open", str(run_dir / "report.html")])

    return all_results


# ─── Persistenz-Test ─────────────────────────────────────────────────────

def test_persistence(verbose: bool = True, report: bool = True) -> list[BacktestResult]:
    """
    Test: Verbessert Signal-Persistenz (Tage × Weight) das Trade-Ranking?

    Vergleicht combo_score (Baseline) gegen persistence_score mit
    verschiedenen Gewichten und Lookback-Fenstern.
    """
    from bt_signals_patterns import collect_pattern_signals

    WINNER_PATTERNS = ["ema50_bounce", "gap_up_continuation"]
    force = "--rescan" in sys.argv

    all_results: list[BacktestResult] = []
    ranking: list[dict] = []

    pat_base = preset_baseline_v1()

    for lookback in [5, 10, 15]:
        if verbose:
            print(f"\n  ── Lookback = {lookback} Tage ──────────────────")

        # Signale mit Persistenz sammeln (Cache pro Lookback)
        cfg_lb = replace(pat_base, persistence_lookback=lookback)
        cache = f"data/signals_patterns_rr2.0_lb{lookback}.pkl"
        if not force and os.path.exists(cache):
            pat_signals = pd.read_pickle(cache)
            if verbose:
                print(f"  Cache: {cache} ({len(pat_signals)} Signale)")
        else:
            if verbose:
                print(f"  Sammle Signale (Lookback={lookback})...")
            pat_signals = collect_pattern_signals(
                cfg_lb, target_rr=2.0, force_rescan=True, verbose=verbose)
            if not pat_signals.empty:
                pat_signals.to_pickle(cache)

        if pat_signals.empty:
            continue

        # Persistenz-Verteilung ausgeben
        if verbose and "persistence" in pat_signals.columns:
            p_dist = pat_signals["persistence"].value_counts().sort_index()
            print(f"  Persistenz-Verteilung: {dict(p_dist)}")

        sizing_base = replace(pat_base,
                              min_invest=25.0,
                              sizing_method="risk_free", sizing_pct=0.02,
                              max_invest=2500.0,
                              pattern_filter=WINNER_PATTERNS,
                              max_positions=5,
                              min_sl_dist=0.05)

        configs = [
            # Baseline: combo_score ohne Persistenz
            replace(sizing_base,
                    name=f"LB{lookback} combo_score (Baseline)",
                    signal_ranking="combo_score"),
        ]

        # Persistenz mit verschiedenen Gewichten
        for w in [0.05, 0.1, 0.2, 0.3, 0.5]:
            configs.append(replace(sizing_base,
                                   name=f"LB{lookback} persist w={w}",
                                   signal_ranking="persistence_score",
                                   persistence_weight=w,
                                   persistence_lookback=lookback))

        results = compare(configs, signals=pat_signals,
                          verbose=verbose, report=False)
        all_results.extend(results)

        for r in results:
            ranking.append({
                "name": r.config.name,
                "lookback": lookback,
                "trades": r.n_trades,
                "win_rate": r.win_rate,
                "total_return": r.total_return,
                "max_dd": r.max_drawdown,
                "efficiency": r.efficiency,
                "end_capital": r.end_capital,
            })

    # Ranking ausgeben
    if verbose and ranking:
        ranking_df = pd.DataFrame(ranking).sort_values("efficiency", ascending=False)
        print(f"\n  {'=' * 100}")
        print(f"  PERSISTENZ-RANKING (nach Effizienz)")
        print(f"  {'=' * 100}")
        print(f"  {'#':>3s} {'Konfiguration':>40s} | {'LB':>3s} {'Tr':>4s} {'WR':>6s} | "
              f"{'Ret':>8s} {'DD':>6s} {'Eff':>5s} | {'Endkap.':>10s}")
        print(f"  {'─' * 95}")

        for i, (_, row) in enumerate(ranking_df.iterrows()):
            print(f"  {i+1:>3d} {row['name']:>40s} | {row['lookback']:>3.0f} {row['trades']:>4.0f} {row['win_rate']:>5.1f}% | "
                  f"{row['total_return']:>+7.1f}% {row['max_dd']:>5.1f}% {row['efficiency']:>5.1f} | "
                  f"€{row['end_capital']:>9,.2f}")

    # Report
    if report and all_results:
        run_dir = _make_run_dir(BacktestConfig(name="persistence_test"))
        generate_compare_report(all_results, run_dir=run_dir)
        for r in all_results:
            generate_report(r, run_dir=run_dir, all_results=all_results)
        if verbose:
            print(f"\n  Reports: {run_dir}/")
        import subprocess
        subprocess.run(["open", str(run_dir / "report.html")])

    return all_results


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'#' * 90}")
    print(f"  BACKTEST-FRAMEWORK")
    print(f"{'#' * 90}")
    print(f"\n  {SURVIVORSHIP_WARNING}\n")

    args = sys.argv[1:]

    if "--compare" in args:
        configs = [
            preset_production(),
            preset_conservative(),
            preset_aggressive(),
            preset_risk_portfolio(0.05),
            preset_risk_portfolio(0.10),
        ]
        compare(configs)

    elif "--grid" in args:
        idx = args.index("--grid")
        grid_name = args[idx + 1] if idx + 1 < len(args) else "positions"

        if grid_name == "positions":
            grid_positions()
        elif grid_name == "sizing":
            grid_sizing()
        elif grid_name == "veto":
            grid_market_veto()
        else:
            print(f"  Unbekanntes Grid: {grid_name}")
            print(f"  Verfuegbar: positions, sizing, veto")
            return

    elif "--pattern-grid" in args:
        grid_patterns()

    elif "--persistence" in args:
        test_persistence()

    elif "--patterns" in args:
        evolve_patterns()

    elif "--trades" in args:
        result = run()
        print_trades(result, n=30)

    else:
        result = run()
        print_trades(result, n=10)

    print()


if __name__ == "__main__":
    main()
