"""
Backtest-Framework: Konfiguration.

Alle Parameter für Signal-Sammlung und Portfolio-Simulation
in einer einzigen Dataclass. Preset-Funktionen für häufige Konfigurationen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BacktestConfig:
    """Vollständige Konfiguration eines Backtest-Laufs."""

    # ── Identifikation ──
    name: str = "default"

    # ── Signal-Filter ──
    use_market_veto: bool = True       # DAX > EMA50+200, VIX < 25
    ignore_vetos: bool = False         # True = ALLE Vetos ignorieren (MACD, Gegenstimmen, Markt)
    min_rr: float = 1.5                # Minimum Risk/Reward
    only_long: bool = True             # Nur LONG-Signale
    min_sl_dist: float = 0.0           # Min SL-Distanz in % (0.06 = 6%)
    max_sl_dist: float = 1.0           # Max SL-Distanz in % (0.10 = 10%)
    exclude_indices: list[str] = field(default_factory=list)  # Indizes ausschließen (z.B. ["MDAX"])

    # ── Portfolio-Simulation ──
    start_capital: float = 1000.0
    leverage: int = 5
    fees: float = 2.0                  # Euro pro Trade (Kauf+Verkauf)
    max_positions: int = 5
    sizing_method: str = "fixed_free"  # "fixed_free", "risk_free", "risk_portfolio", "risk_tiered"
    sizing_pct: float = 0.20

    # ── Gestaffeltes Risiko-Sizing (risk_tiered) ──
    # Liste von (Schwellenwert, Risiko-%). Aufsteigend sortiert.
    # Beispiel: [(5000, 0.05), (20000, 0.03), (inf, 0.02)]
    #   Portfolio < 5k  → 5% Risiko
    #   5k–20k          → 3% Risiko
    #   > 20k           → 2% Risiko
    sizing_tiers: list[tuple[float, float]] = field(default_factory=list)

    # ── Caps für risiko-basiertes Sizing ──
    risk_free_cap: float = 0.50        # Max % vom freien Cash (risk_free)
    risk_portfolio_cap: float = 0.80   # Max % vom freien Cash (risk_portfolio)

    # ── Daten ──
    download_days: int = 2500          # Handelstage Kurshistorie
    download_days_idx: int = 2800      # Handelstage Indexhistorie
    warmup_bars: int = 200             # EMA200 braucht ~200 Bars
    max_hold_days: int = 100           # Timeout nach N Handelstagen

    # ── Investitions-Grenzen ──
    min_invest: float = 25.0           # Unter diesem Betrag kein Trade
    max_invest: float = 0.0            # Max Euro pro Position (0 = unbegrenzt)
    min_cash_reserve: float = 10.0     # Mindestens X Euro Cash behalten

    # ── Monatliche Einzahlung ──
    monthly_deposit: float = 0.0       # Euro pro Monat (0 = deaktiviert)

    # ── Pause-Regel (nach Verlustserien) ──
    pause_after_losses: int = 0        # Nach N Verlusten in Folge pausieren (0 = aus)
    pause_signals: int = 5             # Anzahl Signale die übersprungen werden
    pause_rolling_wr: float = 0.0      # Pause wenn Rolling WR < X (z.B. 0.20 = 20%) (0 = aus)
    pause_rolling_window: int = 10     # Fenster für Rolling WR
    pause_indices: list[str] = field(default_factory=list)  # Pause nur für diese Indizes (leer = alle)

    # ── Pattern-Filter (fuer Pattern-basierte Signale) ──
    # Leere Liste = alle Patterns erlaubt
    # z.B. ["pullback_ema20", "ema50_bounce"] = nur diese beiden
    pattern_filter: list[str] = field(default_factory=list)

    # ── Signal-Ranking (bei Positionslimit: welche Trades zuerst?) ──
    # "none" = Reihenfolge wie im DataFrame
    # "sl_dist_asc" = engster SL zuerst (praezisestes Setup)
    # "sl_dist_desc" = weitester SL zuerst (mehr Luft)
    # "vol_ratio" = hoechstes Volumen zuerst
    # "random" = zufaellig (Baseline)
    signal_ranking: str = "none"

    # ── Benutzerdefinierter Veto-Filter (optional) ──
    # Callable: (signal_dict) -> bool  (True = vetoed, wird übersprungen)
    custom_veto: Callable | None = None

    def label(self) -> str:
        """Kurz-Label für Ausgabe-Tabellen."""
        if self.name != "default":
            return self.name
        method_short = {
            "fixed_free": f"{int(self.sizing_pct*100)}% frei",
            "risk_free": f"Risk {int(self.sizing_pct*100)}% frei",
            "risk_portfolio": f"Risk {int(self.sizing_pct*100)}% Portf.",
            "risk_tiered": "Risk gestaffelt",
        }
        return f"{method_short.get(self.sizing_method, self.sizing_method)}, {self.max_positions}P"


# ─── Presets ──────────────────────────────────────────────────────────────

def preset_baseline_v1() -> BacktestConfig:
    """Alte Baseline v1: Alles offen, keine Filter, realistisches Kapital."""
    return BacktestConfig(
        name="BASELINE v1 (alles offen)",
        # Kapital
        start_capital=1500.0,
        monthly_deposit=50.0,
        fees=2.0,              # 1 EUR Kauf + 1 EUR Verkauf
        leverage=5,
        # Sizing: max 10% vom freien Cash, min 100 EUR
        sizing_method="fixed_free",
        sizing_pct=0.10,
        min_invest=100.0,
        # Keine Filter
        use_market_veto=False,
        ignore_vetos=True,
        min_rr=0.0,
        only_long=False,
        min_sl_dist=0.0,
        max_sl_dist=1.0,
        # Unbegrenzt
        max_positions=999,
        max_hold_days=100,     # technisch durch _evaluate_trade begrenzt
    )


def preset_baseline() -> BacktestConfig:
    """Baseline v2: Realistisches Kapital + Death Cross Veto auf DAX+TecDAX.

    Death Cross Veto (SMA50 < SMA200 auf dem Index) wird per vetoed-Spalte
    in bt_run.py angewandt, nicht hier — da es Index-Kursdaten braucht.
    Alle anderen Filter (R/R, nur LONG, SL-Band etc.) sind OFFEN und
    werden schrittweise per evolve() getestet.
    """
    return BacktestConfig(
        name="BASELINE v2 (DC-Veto DAX+TecDAX)",
        # Kapital
        start_capital=1500.0,
        monthly_deposit=50.0,
        fees=2.0,              # 1 EUR Kauf + 1 EUR Verkauf
        leverage=5,
        # Sizing: max 10% vom freien Cash, min 100 EUR
        sizing_method="fixed_free",
        sizing_pct=0.10,
        min_invest=100.0,
        # Filter
        use_market_veto=False,     # Altes Market-Veto deaktiviert
        ignore_vetos=False,        # Death Cross Veto über vetoed-Spalte
        min_rr=1.5,               # Getestet: Sweet Spot (Return + Effizienz)
        only_long=False,           # Offen — wird per evolve() getestet
        min_sl_dist=0.0,
        max_sl_dist=1.0,
        # Unbegrenzt
        max_positions=999,
        max_hold_days=100,
    )


def preset_best() -> BacktestConfig:
    """Aktueller bester Stand (2026-03-19).

    Kumulativ: Baseline + SL 6-8% + Risk 5% Portfolio + 7 Pos + 100 EUR/Monat + R/R >= 1.0
    """
    return BacktestConfig(
        name="BEST (SL6-8, R5%, 7P, 100€/M, RR1.0)",
        # Kapital
        start_capital=1500.0,
        monthly_deposit=100.0,
        fees=2.0,
        leverage=5,
        # Sizing: Risk 5% Portfolio
        sizing_method="risk_portfolio",
        sizing_pct=0.05,
        min_invest=25.0,
        # Filter
        use_market_veto=False,
        ignore_vetos=False,        # Death Cross Veto über vetoed-Spalte
        min_rr=1.0,
        only_long=False,
        min_sl_dist=0.06,
        max_sl_dist=0.08,
        exclude_indices=["MDAX"],  # MDAX bringt kaum Ertrag bei mehr Risiko
        # Positionen
        max_positions=7,
        max_hold_days=100,
    )


def preset_production() -> BacktestConfig:
    """Produktions-Setup: 20% frei, 5 Pos, alle Vetos aktiv."""
    return BacktestConfig(
        name="PRODUKTION (20% frei, 5P)",
        sizing_method="fixed_free",
        sizing_pct=0.20,
        max_positions=5,
    )


def preset_risk_portfolio(pct: float = 0.05) -> BacktestConfig:
    """Risiko-basiert auf Portfolio-Wert."""
    return BacktestConfig(
        name=f"Risiko {int(pct*100)}% Portfolio",
        sizing_method="risk_portfolio",
        sizing_pct=pct,
        max_positions=5,
    )


def preset_conservative() -> BacktestConfig:
    """Konservativ: niedrigere Positionsgröße, weniger Positionen."""
    return BacktestConfig(
        name="KONSERVATIV",
        sizing_method="fixed_free",
        sizing_pct=0.10,
        max_positions=3,
    )


def preset_aggressive() -> BacktestConfig:
    """Aggressiv: höheres Risiko-Sizing, mehr Positionen."""
    return BacktestConfig(
        name="AGGRESSIV",
        sizing_method="risk_portfolio",
        sizing_pct=0.10,
        max_positions=7,
    )
