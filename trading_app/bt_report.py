"""
Backtest-Framework: HTML-Report.

Erzeugt pro Lauf einen Ordner unter results/ mit:
  - report.html  (vollständiger interaktiver Report)
  - equity.png   (Equity-Chart)

Der Report enthält:
  - Konfigurations-Zusammenfassung
  - Kennzahlen (Rendite, DD, Effizienz, Win-Rate, ...)
  - Equity-Chart (Cash + gebundenes Kapital)
  - Vollständige Trade-Tabelle mit allen Details
  - Signal-Statistiken (warum gehandelt/nicht gehandelt)
"""

from __future__ import annotations

import base64
import io
import os
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

from bt_config import BacktestConfig
from bt_simulate import BacktestResult


RESULTS_DIR = Path(__file__).parent / "results"


def _make_run_dir(cfg: BacktestConfig) -> Path:
    """Erstelle Lauf-Verzeichnis: results/YYYY-MM-DD_HHmm_name/"""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    slug = cfg.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    slug = slug.replace(",", "").replace("%", "pct").replace("/", "-")
    slug = slug[:40]
    run_dir = RESULTS_DIR / f"{ts}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _render_equity_chart(result: BacktestResult, run_dir: Path) -> str:
    """Equity-Chart als PNG speichern und als Base64 zurückgeben."""
    if len(result.equity) == 0:
        return ""

    eq = result.equity.copy()
    fig, ax = plt.subplots(figsize=(14, 5))

    # Kumulierte Einzahlungen als Bezugslinie berechnen
    cfg = result.config
    if cfg.monthly_deposit > 0:
        start_date = eq["date"].iloc[0]
        months_elapsed = ((eq["date"] - start_date).dt.days / 30.44).astype(int)
        deposited = cfg.start_capital + months_elapsed * cfg.monthly_deposit
        ax.plot(eq["date"], deposited, color="#9E9E9E",
                linewidth=1.5, linestyle="--", label=f"Eingezahlt ({result.total_deposited:,.0f})")

    ax.fill_between(eq["date"], 0, eq["free_cash"],
                    color="#4CAF50", alpha=0.3, label="Freies Cash")
    ax.fill_between(eq["date"], eq["free_cash"],
                    eq["free_cash"] + eq["locked"],
                    color="#FF9800", alpha=0.3, label="Gebunden in Positionen")
    ax.plot(eq["date"], eq["portfolio"], color="#1565C0",
            linewidth=2, label=f"Portfolio ({result.total_return:+.1f}% auf Einzahlungen)")

    ax.set_ylabel("Euro")
    ax.set_title(f"Portfolio-Entwicklung: {result.config.label()}", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()

    # PNG speichern
    png_path = run_dir / "equity.png"
    fig.savefig(png_path, dpi=150, bbox_inches="tight")

    # Base64 für HTML-Embedding
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _render_positions_chart(result: BacktestResult) -> str:
    """Chart: Anzahl paralleler Positionen ueber Zeit."""
    if len(result.trades) == 0:
        return ""

    trades = result.trades.copy()
    trades["date"] = pd.to_datetime(trades["date"])
    trades["exit_date"] = pd.to_datetime(trades["exit_date"])

    # Zeitreihe: fuer jeden Tag die Anzahl offener Positionen
    min_date = trades["date"].min()
    max_date = trades["exit_date"].max()
    all_days = pd.date_range(min_date, max_date, freq="B")  # Handelstage

    open_count = []
    for day in all_days:
        n_open = ((trades["date"] <= day) & (trades["exit_date"] > day)).sum()
        open_count.append(n_open)

    fig, ax = plt.subplots(figsize=(14, 3))
    ax.fill_between(all_days, 0, open_count, color="#FF9800", alpha=0.4)
    ax.plot(all_days, open_count, color="#E65100", linewidth=1)

    max_pos = max(open_count) if open_count else 0
    avg_pos = sum(open_count) / len(open_count) if open_count else 0
    ax.axhline(y=avg_pos, color="#1565C0", linestyle="--", linewidth=1,
               label=f"Ø {avg_pos:.1f} Positionen")
    ax.axhline(y=max_pos, color="#D32F2F", linestyle=":", linewidth=1,
               label=f"Max {max_pos}")

    ax.set_ylabel("Offene Positionen")
    ax.set_title("Parallele Positionen", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def _render_compare_chart(current: BacktestResult,
                          all_results: list[BacktestResult]) -> str:
    """Vergleichs-Chart: Alle Varianten, aktuelle hervorgehoben."""
    if not all_results or len(current.equity) == 0:
        return ""

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = ["#1565C0", "#4CAF50", "#FF9800", "#9C27B0", "#E91E63",
              "#00BCD4", "#795548", "#607D8B", "#F44336", "#3F51B5"]

    for i, r in enumerate(all_results):
        if len(r.equity) == 0:
            continue
        eq = r.equity.copy()
        is_current = (r.config.name == current.config.name)
        lw = 2.5 if is_current else 1.0
        alpha = 1.0 if is_current else 0.4
        color = colors[i % len(colors)]
        label = f"{r.config.label()} ({r.total_return:+.0f}%)"
        if is_current:
            label = f">>> {label} <<<"
        ax.plot(eq["date"], eq["portfolio"], color=color,
                linewidth=lw, alpha=alpha, label=label)

    ax.set_ylabel("Portfolio (Euro)")
    ax.set_title("Vergleich aller Varianten (aktuelle hervorgehoben)", fontweight="bold")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"


def _render_drawdown_chart(result: BacktestResult) -> str:
    """Drawdown-Chart als Base64."""
    if len(result.equity) == 0:
        return ""

    eq = result.equity.copy()
    eq["peak"] = eq["portfolio"].cummax()
    eq["dd_pct"] = (eq["peak"] - eq["portfolio"]) / eq["peak"] * 100

    fig, ax = plt.subplots(figsize=(14, 3))
    ax.fill_between(eq["date"], 0, -eq["dd_pct"], color="#F44336", alpha=0.4)
    ax.plot(eq["date"], -eq["dd_pct"], color="#D32F2F", linewidth=1)
    ax.set_ylabel("Drawdown (%)")
    ax.set_title("Drawdown", fontweight="bold")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _format_euro(val) -> str:
    if val >= 0:
        return f"{val:,.2f}"
    return f"<span style='color:#D32F2F'>{val:,.2f}</span>"


def _format_pct(val, color=True) -> str:
    if not color:
        return f"{val:+.1f}%"
    if val > 0:
        return f"<span style='color:#2E7D32'>{val:+.1f}%</span>"
    elif val < 0:
        return f"<span style='color:#D32F2F'>{val:+.1f}%</span>"
    return f"{val:+.1f}%"


def _outcome_badge(outcome: str) -> str:
    colors = {
        "TARGET": ("background:#E8F5E9; color:#2E7D32", "TARGET"),
        "STOP": ("background:#FFEBEE; color:#C62828", "STOP"),
        "TIMEOUT": ("background:#FFF3E0; color:#E65100", "TIMEOUT"),
    }
    style, label = colors.get(outcome, ("", outcome))
    return f"<span style='{style}; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:600'>{label}</span>"


def generate_report(result: BacktestResult,
                    run_dir: Path | None = None,
                    all_results: list[BacktestResult] | None = None) -> Path:
    """
    Vollständigen HTML-Report generieren.

    Args:
        all_results: Alle Ergebnisse aus dem Vergleich — für den
                     übergreifenden Equity-Chart in jedem Einzel-Report.

    Returns: Pfad zur report.html
    """
    cfg = result.config
    if run_dir is None:
        run_dir = _make_run_dir(cfg)

    # Charts rendern
    equity_b64 = _render_equity_chart(result, run_dir)
    dd_b64 = _render_drawdown_chart(result)
    positions_b64 = _render_positions_chart(result)
    compare_b64 = _render_compare_chart(result, all_results) if all_results else ""

    # Trade-Tabelle aufbauen
    trades_html = _build_trades_table(result)

    # Cashflow-Tabelle aufbauen
    cashflow_html = _build_cashflow_table(result)

    # HTML zusammenbauen
    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest: {cfg.label()}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f5; color: #333; line-height: 1.5; padding: 20px; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  h2 {{ font-size: 18px; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #1565C0; }}
  .subtitle {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
  .warning {{ background: #FFF3E0; border-left: 4px solid #FF9800; padding: 10px 16px;
              margin-bottom: 20px; font-size: 13px; border-radius: 0 4px 4px 0; }}

  /* KPI-Karten */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
               gap: 12px; margin-bottom: 20px; }}
  .kpi {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .kpi-label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
  .kpi-value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  .kpi-value.positive {{ color: #2E7D32; }}
  .kpi-value.negative {{ color: #D32F2F; }}

  /* Config-Tabelle */
  .config-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; background: white;
                   border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .config-table td {{ padding: 6px 12px; border-bottom: 1px solid #f0f0f0; font-size: 13px; }}
  .config-table td:first-child {{ font-weight: 600; width: 200px; color: #555; }}

  /* Charts */
  .chart-container {{ background: white; border-radius: 8px; padding: 12px;
                      box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }}
  .chart-container img {{ width: 100%; height: auto; }}

  /* Tabellen */
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: white;
                 border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .data-table th {{ background: #1565C0; color: white; padding: 8px 10px; text-align: right;
                    font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px;
                    position: sticky; top: 0; z-index: 10; }}
  .data-table th:nth-child(-n+5) {{ text-align: left; }}
  .data-table td {{ padding: 6px 10px; border-bottom: 1px solid #f0f0f0; text-align: right;
                    font-variant-numeric: tabular-nums; }}
  .data-table td:nth-child(-n+5) {{ text-align: left; }}
  .data-table tr:hover {{ background: #f8f9fa; }}
  .data-table tr.win {{ background: #f1f8e9; }}
  .data-table tr.loss {{ background: #fce4ec; }}
  .data-table tr.win:hover {{ background: #e8f5e9; }}
  .data-table tr.loss:hover {{ background: #ffebee; }}

  /* Scroll-Container */
  .table-scroll {{ max-height: 800px; overflow-y: auto; border-radius: 8px;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); position: relative; }}

  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding: 20px; }}

  /* Filter */
  .filter-bar {{ display: flex; gap: 12px; margin-bottom: 12px; align-items: center; }}
  .filter-bar select, .filter-bar input {{ padding: 6px 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 13px; }}
  .filter-bar label {{ font-size: 13px; font-weight: 500; }}

  @media print {{
    .table-scroll {{ max-height: none; overflow: visible; }}
    .data-table th {{ position: static; }}
  }}
</style>
</head>
<body>
<div class="container">

<p style="margin-bottom:12px"><a href="report.html" style="color:#1565C0;text-decoration:none;font-size:14px">&larr; Zurueck zur Uebersicht</a></p>

<h1>Backtest-Report: {cfg.label()}</h1>
<div class="subtitle">Erstellt: {datetime.now().strftime("%d.%m.%Y %H:%M")} |
  Zeitraum: {_get_date_range(result)} |
  {result.n_signals} Signale, {result.n_trades} Trades</div>

<div class="warning">
  Survivorship-Bias: Nur aktuelle DAX/MDAX/TecDAX-Mitglieder getestet.
  Firmen die abgestiegen oder insolvent gingen fehlen. Reale Performance wahrscheinlich 10-20% niedriger.
</div>

<!-- KPI-Karten -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-label">Rendite</div>
    <div class="kpi-value {'positive' if result.total_return > 0 else 'negative'}">{result.total_return:+.1f}%</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Endkapital</div>
    <div class="kpi-value">{result.end_capital:,.2f}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Max. Drawdown</div>
    <div class="kpi-value negative">{result.max_drawdown:.1f}%</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Effizienz</div>
    <div class="kpi-value">{result.efficiency:.1f}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Win-Rate</div>
    <div class="kpi-value">{result.win_rate:.1f}%</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Trades</div>
    <div class="kpi-value">{result.n_trades}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Gewinner</div>
    <div class="kpi-value positive">{result.n_wins}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Verlierer</div>
    <div class="kpi-value negative">{result.n_trades - result.n_wins}</div>
  </div>
</div>

<!-- Konfiguration -->
<h2>Konfiguration</h2>
<table class="config-table">
  {f'<tr><td>Pattern-Filter</td><td>{", ".join(cfg.pattern_filter)}</td></tr>' if cfg.pattern_filter else ''}
  <tr><td>Richtung</td><td>{'Nur LONG' if cfg.only_long else 'LONG + SHORT'}{' (nur LONG-Patterns)' if cfg.pattern_filter and not cfg.only_long else ''}</td></tr>
  <tr><td>Target</td><td>Fix R/R=2.0 (Entry + 2 × Risk)</td></tr>
  <tr><td>SL</td><td>Vom Pattern-Detektor, Floor 5%</td></tr>
  <tr><td>Sizing-Methode</td><td>{cfg.sizing_method} ({cfg.sizing_pct*100:.0f}%)</td></tr>
  {f'<tr><td>Max. Invest pro Position</td><td>{cfg.max_invest:,.0f} EUR</td></tr>' if cfg.max_invest > 0 else ''}
  <tr><td>Max. Positionen</td><td>{cfg.max_positions if cfg.max_positions < 999 else 'unbegrenzt'}</td></tr>
  <tr><td>Hebel</td><td>{cfg.leverage}x</td></tr>
  <tr><td>Startkapital</td><td>{cfg.start_capital:,.2f} EUR</td></tr>
  <tr><td>Gebuehren</td><td>{cfg.fees:.2f} EUR pro Trade</td></tr>
  {f'<tr><td>Monatl. Einzahlung</td><td>{cfg.monthly_deposit:,.0f} EUR</td></tr>' if cfg.monthly_deposit > 0 else ''}
  <tr><td>Min. Risk/Reward</td><td>{f'{cfg.min_rr:.1f}' if cfg.min_rr > 0 else 'keins (fix R/R=2.0)'}</td></tr>
  {f'<tr><td>SL-Band</td><td>{cfg.min_sl_dist*100:.0f}% - {cfg.max_sl_dist*100:.0f}%</td></tr>' if cfg.min_sl_dist > 0 or cfg.max_sl_dist < 1.0 else ''}
  <tr><td>Max. Haltedauer</td><td>{cfg.max_hold_days} Tage</td></tr>
  <tr><td>Markt-Veto</td><td>{'Aktiv' if cfg.use_market_veto else 'Keins (manuell)'}</td></tr>
  <tr><td>Signale verfuegbar</td><td>{result.n_signals}</td></tr>
  <tr><td>Uebersprungen (Cash)</td><td>{result.skipped_cash}</td></tr>
  <tr><td>Uebersprungen (Pos.-Limit)</td><td>{result.skipped_pos}</td></tr>
  <tr><td>Uebersprungen (Ticker offen)</td><td>{result.skipped_ticker}</td></tr>
</table>

<!-- Equity-Chart -->
<h2>Portfolio-Entwicklung</h2>
<div class="chart-container">
  {f'<img src="{equity_b64}" alt="Equity">' if equity_b64 else '<p>Keine Daten</p>'}
</div>

<!-- Drawdown-Chart -->
<h2>Drawdown</h2>
<div class="chart-container">
  {f'<img src="{dd_b64}" alt="Drawdown">' if dd_b64 else '<p>Keine Daten</p>'}
</div>

{f"""<!-- Parallele Positionen -->
<h2>Parallele Positionen</h2>
<div class="chart-container">
  <img src="{positions_b64}" alt="Parallele Positionen">
</div>""" if positions_b64 else ""}

{f"""<!-- Vergleichs-Chart -->
<h2>Vergleich aller Varianten</h2>
<div class="chart-container">
  <img src="{compare_b64}" alt="Vergleich">
</div>""" if compare_b64 else ""}

<!-- Trade-Tabelle -->
<h2>Alle Trades ({result.n_trades})</h2>
{trades_html}

<!-- Cashflow-Tabelle -->
<h2>Cashflow-Verlauf</h2>
{cashflow_html}

<div class="footer">
  Backtest-Framework | Alle Angaben ohne Gewaehr | Survivorship-Bias nicht korrigiert
</div>

</div>

<script>
// Multi-Filter: Alle aktiven Filter gleichzeitig anwenden
function applyFilters() {{
  const selects = document.querySelectorAll('.filter-select');
  const table = document.querySelector('.table-scroll');
  if (!table) return;
  const rows = table.querySelectorAll('tbody tr');

  // Aktive Filter sammeln
  const filters = [];
  selects.forEach(sel => {{
    if (sel.value !== 'all') {{
      filters.push({{ col: parseInt(sel.dataset.col), val: sel.value }});
    }}
  }});

  // Statistik
  let shown = 0, wins = 0, totalPnl = 0;

  rows.forEach(row => {{
    let visible = true;
    for (const f of filters) {{
      const cell = row.cells[f.col];
      if (!cell || cell.textContent.trim() !== f.val) {{
        visible = false;
        break;
      }}
    }}
    row.style.display = visible ? '' : 'none';
    if (visible) {{
      shown++;
      if (row.classList.contains('win')) wins++;
    }}
  }});

  // Filter-Info anzeigen
  let info = document.getElementById('filter-info');
  if (!info) {{
    info = document.createElement('div');
    info.id = 'filter-info';
    info.style.cssText = 'font-size:13px; color:#666; margin-top:8px;';
    document.querySelector('.filter-bar').appendChild(info);
  }}
  if (filters.length > 0) {{
    const wr = shown > 0 ? (wins / shown * 100).toFixed(1) : '0.0';
    info.textContent = shown + ' Trades angezeigt, ' + wins + ' Wins (' + wr + '% WR)';
  }} else {{
    info.textContent = '';
  }}
}}

document.querySelectorAll('.filter-select').forEach(sel => {{
  sel.addEventListener('change', applyFilters);
}});
</script>

</body>
</html>"""

    # Eindeutiger Dateiname wenn run_dir schon existiert (z.B. bei compare)
    slug = cfg.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
    slug = slug.replace(",", "").replace("%", "pct").replace("/", "-").replace(".", "")[:30]
    report_name = f"report_{slug}.html" if (run_dir / "report.html").exists() else "report.html"
    report_path = run_dir / report_name
    report_path.write_text(html, encoding="utf-8")
    return report_path


def _get_date_range(result: BacktestResult) -> str:
    if len(result.trades) == 0:
        return "keine Trades"
    first = str(result.trades["date"].iloc[0])[:10]
    last = str(result.trades["exit_date"].iloc[-1])[:10]
    return f"{first} bis {last}"


def _build_trades_table(result: BacktestResult) -> str:
    """Vollstaendige Trade-Tabelle mit allen Details."""
    if len(result.trades) == 0:
        return "<p>Keine Trades.</p>"

    cfg = result.config
    trades = result.trades.copy()

    # Laufendes Kapital berechnen
    free_cash = cfg.start_capital
    running_capital = []
    running_portfolio = []

    # Simulation nochmal durchlaufen fuer laufende Werte
    open_pos = []
    for idx, t in trades.iterrows():
        # Positionen schliessen
        closed = [p for p in open_pos if p["exit_date"] <= t["date"]]
        for p in closed:
            returned = max(0, p["invested"] + p["pnl_euro"])
            free_cash += returned
            open_pos.remove(p)

        running_capital.append(free_cash)
        locked = sum(p["invested"] for p in open_pos)
        running_portfolio.append(free_cash + locked)

        free_cash -= t["invested"]
        open_pos.append({
            "exit_date": t["exit_date"],
            "invested": t["invested"],
            "pnl_euro": t["pnl_euro"],
        })

    trades["cash_before"] = running_capital
    trades["portfolio_before"] = running_portfolio
    trades["notional"] = trades["invested"] * cfg.leverage

    # Filter-Optionen sammeln
    tickers = sorted(trades["ticker"].unique())
    outcomes = sorted(trades["outcome"].unique())
    indices = sorted(trades["index"].unique()) if "index" in trades.columns else []
    directions = sorted(trades["direction"].unique()) if "direction" in trades.columns else []

    html = f"""
<div class="filter-bar">
  <label>Filter:</label>
  {f'''<select class="filter-select" data-col="2">
    <option value="all">Alle Indizes</option>
    {"".join(f'<option value="{ix}">{ix}</option>' for ix in indices)}
  </select>''' if indices else ''}
  <select class="filter-select" data-col="3">
    <option value="all">Alle Ticker</option>
    {''.join(f'<option value="{t}">{t}</option>' for t in tickers)}
  </select>
  <select class="filter-select" data-col="4">
    <option value="all">Alle Richtungen</option>
    {''.join(f'<option value="{d}">{d}</option>' for d in directions)}
  </select>
  <select class="filter-select" data-col="5">
    <option value="all">Alle Ergebnisse</option>
    {''.join(f'<option value="{o}">{o}</option>' for o in outcomes)}
  </select>
</div>
<div class="table-scroll">
<table class="data-table">
<thead>
<tr>
  <th>#</th>
  <th>Datum</th>
  <th>Index</th>
  <th>Ticker</th>
  <th>Richtung</th>
  <th>Ergebnis</th>
  <th>Tage</th>
  <th>Exit-Datum</th>
  <th>Einstieg</th>
  <th>Ziel</th>
  <th>Stop-Loss</th>
  <th>SL-Dist.</th>
  <th>R/R</th>
  <th>Investiert</th>
  <th>Hebel-Vol.</th>
  <th>P&amp;L %</th>
  <th>P&amp;L Euro</th>
  <th>Cash vorher</th>
  <th>Portfolio</th>
</tr>
</thead>
<tbody>
"""

    cumulative_pnl = 0.0
    for i, (_, t) in enumerate(trades.iterrows(), 1):
        cumulative_pnl += t["pnl_euro"]
        row_class = "win" if t["outcome"] == "TARGET" else "loss" if t["outcome"] == "STOP" else ""

        idx_val = t.get('index', '') if 'index' in trades.columns else ''
        dir_val = t.get('direction', '')

        html += f"""<tr class="{row_class}">
  <td>{i}</td>
  <td>{str(t['date'])[:10]}</td>
  <td>{idx_val}</td>
  <td><strong>{t['ticker']}</strong></td>
  <td>{dir_val}</td>
  <td>{_outcome_badge(t['outcome'])}</td>
  <td>{t['days_held']}</td>
  <td>{str(t['exit_date'])[:10]}</td>
  <td>{t.get('entry', '-')}</td>
  <td>{t.get('target', '-')}</td>
  <td>{t.get('stop_loss', '-')}</td>
  <td>{t['sl_dist_pct']:.1f}%</td>
  <td>{t['risk_reward']:.1f}</td>
  <td>{_format_euro(t['invested'])}</td>
  <td>{_format_euro(t['notional'])}</td>
  <td>{_format_pct(t['pnl_pct'])}</td>
  <td>{_format_euro(t['pnl_euro'])}</td>
  <td>{_format_euro(t['cash_before'])}</td>
  <td>{_format_euro(t['portfolio_before'])}</td>
</tr>
"""

    html += """</tbody>
</table>
</div>"""
    return html


def _build_cashflow_table(result: BacktestResult) -> str:
    """Cashflow-Tabelle: Jede Portfolio-Aenderung."""
    if len(result.equity) == 0:
        return "<p>Keine Daten.</p>"

    eq = result.equity.copy()
    eq["peak"] = eq["portfolio"].cummax()
    eq["dd_pct"] = ((eq["peak"] - eq["portfolio"]) / eq["peak"] * 100).round(1)
    eq["ret_pct"] = ((eq["portfolio"] / result.config.start_capital - 1) * 100).round(1)

    html = """
<div class="table-scroll" style="max-height:500px">
<table class="data-table">
<thead>
<tr>
  <th>Datum</th>
  <th>Freies Cash</th>
  <th>Gebunden</th>
  <th>Portfolio</th>
  <th>Rendite</th>
  <th>Drawdown</th>
</tr>
</thead>
<tbody>
"""
    for _, row in eq.iterrows():
        html += f"""<tr>
  <td>{str(row['date'])[:10]}</td>
  <td>{_format_euro(row['free_cash'])}</td>
  <td>{_format_euro(row['locked'])}</td>
  <td><strong>{_format_euro(row['portfolio'])}</strong></td>
  <td>{_format_pct(row['ret_pct'])}</td>
  <td>{'-' + str(row['dd_pct']) + '%' if row['dd_pct'] > 0 else '-'}</td>
</tr>
"""

    html += """</tbody>
</table>
</div>"""
    return html


def generate_compare_report(results: list[BacktestResult],
                            run_dir: Path | None = None) -> Path:
    """Vergleichs-Report fuer mehrere Konfigurationen."""
    if not results:
        return Path()

    if run_dir is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        run_dir = RESULTS_DIR / f"{ts}_vergleich"
        run_dir.mkdir(parents=True, exist_ok=True)

    # Equity-Charts aller Configs
    fig, ax = plt.subplots(figsize=(14, 6))
    for r in results:
        if len(r.equity) > 0:
            eq = r.equity
            ret_pct = (eq["portfolio"] / r.config.start_capital - 1) * 100
            ax.plot(eq["date"], ret_pct,
                    label=f"{r.config.label()} ({r.total_return:+.0f}%)", linewidth=1.5)
    ax.axhline(y=0, color="gray", linestyle="--", alpha=0.3)
    ax.set_ylabel("Rendite (%)")
    ax.set_title("Vergleich: Portfolio-Entwicklung", fontweight="bold")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    fig.savefig(run_dir / "compare_equity.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    equity_b64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode()}"

    # Vergleichs-Tabelle mit Links zu Einzel-Reports
    rows_html = ""
    for r in sorted(results, key=lambda x: x.efficiency, reverse=True):
        ret_class = "positive" if r.total_return > 0 else "negative"
        # Einzel-Report Dateiname (gleiche Slug-Logik wie in generate_report)
        slug = r.config.name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        slug = slug.replace(",", "").replace("%", "pct").replace("/", "-").replace(".", "")[:30]
        report_file = f"report_{slug}.html"
        rows_html += f"""<tr>
  <td><strong><a href="{report_file}" style="color:#1565C0;text-decoration:none">{r.config.label()}</a></strong></td>
  <td>{r.n_signals}</td>
  <td>{r.n_trades}</td>
  <td>{r.win_rate:.1f}%</td>
  <td class="{ret_class}">{r.total_return:+.1f}%</td>
  <td>{r.max_drawdown:.1f}%</td>
  <td><strong>{r.efficiency:.1f}</strong></td>
  <td>{_format_euro(r.end_capital)}</td>
  <td>{r.skipped_cash}</td>
  <td>{r.skipped_pos}</td>
</tr>
"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtest-Vergleich</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f5f5f5; color: #333; line-height: 1.5; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  h2 {{ font-size: 18px; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #1565C0; }}
  .subtitle {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
  .warning {{ background: #FFF3E0; border-left: 4px solid #FF9800; padding: 10px 16px;
              margin-bottom: 20px; font-size: 13px; border-radius: 0 4px 4px 0; }}
  .chart-container {{ background: white; border-radius: 8px; padding: 12px;
                      box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }}
  .chart-container img {{ width: 100%; height: auto; }}
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; background: white;
                 border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .data-table th {{ background: #1565C0; color: white; padding: 10px 12px; text-align: right;
                    font-weight: 600; font-size: 12px; }}
  .data-table th:first-child {{ text-align: left; }}
  .data-table td {{ padding: 8px 12px; border-bottom: 1px solid #f0f0f0; text-align: right;
                    font-variant-numeric: tabular-nums; }}
  .data-table td:first-child {{ text-align: left; }}
  .data-table tr:hover {{ background: #f8f9fa; }}
  .positive {{ color: #2E7D32; }}
  .negative {{ color: #D32F2F; }}
  .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 30px; padding: 20px; }}
</style>
</head>
<body>
<div class="container">

<h1>Backtest-Vergleich</h1>
<div class="subtitle">Erstellt: {datetime.now().strftime("%d.%m.%Y %H:%M")} |
  {len(results)} Konfigurationen verglichen</div>

<div class="warning">
  Survivorship-Bias: Nur aktuelle Index-Mitglieder getestet. Reale Performance wahrscheinlich 10-20% niedriger.
</div>

<h2>Equity-Vergleich</h2>
<div class="chart-container">
  <img src="{equity_b64}" alt="Vergleich">
</div>

<h2>Kennzahlen (sortiert nach Effizienz)</h2>
<table class="data-table">
<thead>
<tr>
  <th>Konfiguration</th>
  <th>Signale</th>
  <th>Trades</th>
  <th>Win-Rate</th>
  <th>Rendite</th>
  <th>Max DD</th>
  <th>Effizienz</th>
  <th>Endkapital</th>
  <th>Skip Cash</th>
  <th>Skip Pos</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>

<div class="footer">
  Backtest-Framework | Sortiert nach Effizienz (Rendite / Max. Drawdown)
</div>

</div>
</body>
</html>"""

    report_path = run_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
