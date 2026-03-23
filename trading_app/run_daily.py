#!/usr/bin/env python3
"""
run_daily.py – Standalone daily scan without Streamlit.

Usage:
    .venv/bin/python run_daily.py          # Full scan
    .venv/bin/python run_daily.py --quiet   # Less output

Can be run via cron or macOS LaunchAgent.
"""

import sys
import types
import logging
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Stub out streamlit before any project module imports it.
# This allows scanner.py / market_context.py to load without streamlit.
# ---------------------------------------------------------------------------
_st = types.ModuleType("streamlit")
_st.cache_data = lambda **kw: (lambda f: f)       # no-op decorator
_st.cache_resource = lambda **kw: (lambda f: f)
_st.spinner = lambda msg: type("_ctx", (), {"__enter__": lambda s: None, "__exit__": lambda s, *a: None})()
sys.modules["streamlit"] = _st

# Now safe to import project modules
os_dir = Path(__file__).parent
sys.path.insert(0, str(os_dir))

from scanner import run_scan, run_ai_for_top_signals
# learner.py entfernt — Post-Exit Tracking laeuft im Scanner


LOCK_FILE = os_dir / "data" / ".scan_today"


def _already_ran_today() -> bool:
    """Check if scan already completed successfully today."""
    if not LOCK_FILE.exists():
        return False
    import datetime
    content = LOCK_FILE.read_text().strip()
    return content == datetime.date.today().isoformat()


def _mark_done():
    """Mark today's scan as completed."""
    import datetime
    LOCK_FILE.write_text(datetime.date.today().isoformat())


def main():
    parser = argparse.ArgumentParser(description="DAX 40 Daily Scan")
    parser.add_argument("--quiet", action="store_true", help="Nur Fehler ausgeben")
    parser.add_argument("--force", action="store_true", help="Auch wenn heute schon gelaufen")
    args = parser.parse_args()

    # Logging
    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os_dir / "data" / "daily_scan.log"),
        ],
    )
    log = logging.getLogger("run_daily")

    # Ensure data dir exists
    (os_dir / "data").mkdir(exist_ok=True)

    # Skip if already ran today (unless --force)
    if _already_ran_today() and not args.force:
        log.info("Scan heute bereits gelaufen – überspringe.")
        sys.exit(0)  # exit 0 = success → launchd startet nicht erneut

    log.info("=== Täglicher Scan gestartet ===")

    try:
        result = run_scan()
        if isinstance(result, tuple) and len(result) == 4:
            results_df, trades_df, market, failed = result
        elif isinstance(result, tuple) and len(result) == 3:
            results_df, trades_df, market = result
            failed = []
        elif isinstance(result, tuple) and len(result) == 2:
            results_df, market = result
            trades_df = None
            failed = []
        else:
            results_df = None
            trades_df = None
            market = {}
            failed = []

        # Summary
        if results_df is not None and not results_df.empty:
            n_long = (results_df["Richtung"] == "LONG").sum()
            n_short = (results_df["Richtung"] == "SHORT").sum()
            log.info(
                "Scan fertig: %d Werte — %d LONG, %d SHORT",
                len(results_df), n_long, n_short,
            )

            # Top picks
            for _, row in results_df.head(5).iterrows():
                log.info(
                    "  %s %s (%s) Score=%+.1f Ziel=%s Stop=%s",
                    row["Richtung"], row["Name"], row["Ticker"],
                    row["Score"],
                    f"{row['Ziel']:.2f}" if row.get("Ziel") else "–",
                    f"{row['Stop-Loss']:.2f}" if row.get("Stop-Loss") else "–",
                )
            # ── KI-Batch für Top-Signale ──
            log.info("=== KI-Bewertung für Top-Signale (|Score| >= 40) ===")
            try:
                results_df = run_ai_for_top_signals(results_df, threshold=40.0)
                if "Konsens" in results_df.columns:
                    n_k = (results_df["Konsens"] == "\u2605\u2605\u2605").sum()
                    n_w = (results_df["Konsens"] == "\u26a0").sum()
                    log.info("KI-Ergebnis: %d Konsens, %d Widerspruch", n_k, n_w)

                    # Konsens-Signale loggen
                    konsens = results_df[results_df["Konsens"] == "\u2605\u2605\u2605"]
                    for _, r in konsens.iterrows():
                        log.info(
                            "  KONSENS: %s %s (%s) Tech=%+.1f KI=%+.0f",
                            r["Richtung"], r["Name"], r["Ticker"],
                            r["Score"], r.get("KI-Score", 0) or 0,
                        )
            except Exception as e:
                log.error("KI-Batch fehlgeschlagen: %s", e, exc_info=True)

        else:
            log.warning("Scan lieferte keine Ergebnisse.")

        # Trade updates
        if trades_df is not None and not trades_df.empty:
            log.info("Trade-Updates: %d aktive Positionen aktualisiert", len(trades_df))
            for _, tr in trades_df.iterrows():
                _bid_str = f" Bid={tr['Produkt Bid']:.2f}€" if tr.get("Produkt Bid") else ""
                _isin_str = f" [{tr['ISIN']}]" if tr.get("ISIN") else ""
                log.info(
                    "  %s %s P/L=%+.1f%% Stop=%.2f Ziel=%.2f%s%s %s",
                    tr["Richtung"], tr["Name"],
                    tr.get("P/L %", 0),
                    tr.get("Stop", 0),
                    tr.get("Ziel", 0),
                    _bid_str, _isin_str,
                    tr.get("Hinweis", ""),
                )

    except Exception as e:
        log.error("Scan fehlgeschlagen: %s", e, exc_info=True)
        sys.exit(1)  # exit 1 → launchd versucht es nach 5 Min. erneut

    _mark_done()
    log.info("=== Scan abgeschlossen ===")


if __name__ == "__main__":
    main()
