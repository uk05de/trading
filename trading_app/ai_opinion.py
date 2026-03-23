"""
ai_opinion.py – KI-Bewertung einzelner Aktien via Claude CLI.

Ruft `claude -p` im nicht-interaktiven Modus auf und übergibt
Kursdaten, Indikatoren, News und Kontext. Ergebnis ist eine
strukturierte Bewertung (Richtung, Ziel, Stop, Begründung).

Der Prompt ist in PROMPT_TEMPLATE dokumentiert und kann angepasst werden.
"""

from __future__ import annotations

import json
import logging
import subprocess
import shutil
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "claude"

# ─────────────────────────────────────────────────────────────────────
# PROMPT TEMPLATE
# ─────────────────────────────────────────────────────────────────────
# Dieser Prompt wird an Claude CLI übergeben.
# Variablen werden per .format() ersetzt.
# Änderungen hier wirken sich direkt auf die KI-Bewertung aus.
# ─────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """\
Du bist ein erfahrener Swing-Trading-Analyst mit tiefem Wissen über \
Unternehmen, Branchen und Märkte. Du sollst eine EIGENSTÄNDIGE Bewertung \
abgeben, die über reine technische Indikatoren hinausgeht.

## Aktie: {name} ({ticker})
Index: {index} | Sektor: {sector}

## Kursverlauf (letzte 20 Handelstage, OHLCV)
{ohlcv_table}

Aktueller Kurs: {close:.2f} {currency}
52W-Hoch: {high_52w:.2f} | 52W-Tief: {low_52w:.2f}
ATR (Tagesvolatilität): {atr:.2f} ({atr_pct:.1f}%)

## Fundamentaldaten
- Nächster Earnings-Termin: {earnings_date}
- Analysten-Konsens: {analyst_rating}
- Analysten-Kursziel: {analyst_target}

## Technische System-Bewertung (unser automatisches System, zum Vergleich)
Richtung: {tech_direction} | Score: {tech_score:+.1f} | Trust: {tech_trust:.0f}%
Sektor-Score: {sector_score:+.0f}
Nachrichten-Sentiment: {news_score:+.1f} ({news_count} Artikel)

## Deine Aufgabe

Gib eine EIGENE, differenzierte Swing-Trading-Bewertung ab (Haltedauer: \
Tage bis wenige Wochen). Nutze dafür DEIN WISSEN, nicht nur die obigen Zahlen:

1. **Unternehmen**: Was macht {name}? Wie ist die Wettbewerbsposition? \
Gibt es aktuelle strategische Entwicklungen, Übernahmen, Produktlaunches?
2. **Branche & Makro**: Wie steht der Sektor ({sector}) aktuell da? \
Gibt es regulatorische Risiken, Zinseinflüsse, Konjunkturabhängigkeiten?
3. **Chartmuster**: Erkennst du im Kursverlauf Formationen (Doppelboden, \
Schulter-Kopf-Schulter, Dreiecke, Kanäle, Ausbrüche)? Wo sind wichtige \
charttechnische Marken?
4. **Risiken**: Was könnte gegen den Trade sprechen? Earnings-Risiko, \
Branchenrotation, politische Faktoren?
5. **Timing**: Ist jetzt ein guter Einstiegszeitpunkt oder sollte man warten?

WICHTIG:
- Bewerte AUSSCHLIESSLICH die Aktie {name} ({ticker}). Erwähne KEINE anderen \
Unternehmen oder Ticker in deiner Begründung, es sei denn als kurzer Vergleich.
- Bewerte EIGENSTÄNDIG. Du darfst dem technischen System widersprechen, \
wenn dein Gesamtbild ein anderes ergibt. Begründe insbesondere, wo und warum \
du anders bewertest.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt (kein Markdown, kein Text davor/danach):
{{
  "direction": "LONG" oder "SHORT",
  "score": <float -100 bis +100, wobei nahe 0 = unsicher, nahe +-100 = sehr überzeugt>,
  "entry": <float Einstiegspreis>,
  "target": <float Kursziel>,
  "stop_loss": <float Stop-Loss>,
  "risk_reward": <float R/R-Verhältnis>,
  "reasoning": "<Ausführliche Begründung auf Deutsch, 5-8 Sätze. Gehe auf Unternehmen, Branche, Chartbild, Risiken und Timing ein. Erkläre wo du dem technischen System zustimmst oder widersprichst und warum.>"
}}
"""


def _build_prompt(ticker: str, name: str, df: pd.DataFrame,
                  fundamentals: dict, news_score: float,
                  news_count: int, sector: str, sector_score: float,
                  index: str, tech_analysis: dict) -> str:
    """Prompt aus Daten zusammenbauen."""
    last = df.iloc[-1]

    # OHLCV der letzten 20 Tage als kompakte Tabelle
    recent = df.tail(20)[["Open", "High", "Low", "Close", "Volume"]].copy()
    recent.index = recent.index.strftime("%Y-%m-%d")
    ohlcv_table = recent.to_string()

    # 52-Wochen Hoch/Tief
    lookback_252 = min(252, len(df))
    _yearly = df.tail(lookback_252)
    high_52w = _yearly["High"].max()
    low_52w = _yearly["Low"].min()

    # Währung ableiten
    currency = "$" if not ticker.endswith((".DE", ".PA", ".L")) else "€"

    return PROMPT_TEMPLATE.format(
        ticker=ticker,
        name=name,
        index=index,
        sector=sector,
        sector_score=sector_score,
        ohlcv_table=ohlcv_table,
        close=last["Close"],
        currency=currency,
        high_52w=high_52w,
        low_52w=low_52w,
        atr=last.get("ATR", 0),
        atr_pct=last.get("ATR_pct", 0),
        earnings_date=fundamentals.get("earnings_date", "–"),
        analyst_rating=fundamentals.get("analyst_rating", "–"),
        analyst_target=fundamentals.get("analyst_target", "–"),
        news_score=news_score,
        news_count=news_count,
        tech_direction=tech_analysis.get("direction", "–"),
        tech_score=tech_analysis.get("score", 0),
        tech_trust=tech_analysis.get("confidence", 0),
    )


def get_ai_opinion(ticker: str, name: str, df: pd.DataFrame,
                   fundamentals: dict, news_score: float,
                   news_count: int, sector: str, sector_score: float,
                   index: str, tech_analysis: dict,
                   model: str = "sonnet") -> dict:
    """
    Hole eine KI-Bewertung für einen Ticker via Claude CLI.

    Args:
        ticker: Yahoo Finance Ticker
        name: Unternehmensname
        df: DataFrame mit allen Indikatoren
        fundamentals: Fundamentaldaten
        news_score: Nachrichten-Sentiment (-2..+2)
        news_count: Anzahl Artikel
        sector: Sektorname
        sector_score: Sektor-Score (-100..+100)
        index: Indexname (DAX, Dow, etc.)
        tech_analysis: dict aus analyze_stock() (zum Vergleich)
        model: Claude-Modell (default: sonnet)

    Returns:
        dict mit: direction, score, entry, target, stop_loss,
                  risk_reward, reasoning, prompt, model, error
    """
    prompt = _build_prompt(
        ticker, name, df, fundamentals, news_score,
        news_count, sector, sector_score, index, tech_analysis,
    )

    result = {
        "ticker": ticker,
        "prompt": prompt,
        "model": model,
        "direction": None,
        "score": None,
        "entry": None,
        "target": None,
        "stop_loss": None,
        "risk_reward": None,
        "reasoning": None,
        "error": None,
    }

    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", "--output-format", "json", "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            result["error"] = f"claude CLI Fehler (exit {proc.returncode}): {proc.stderr[:500]}"
            log.error("claude CLI Fehler: %s", proc.stderr[:500])
            return result

        # Parse CLI JSON output
        cli_output = json.loads(proc.stdout)
        raw_text = cli_output.get("result", "")

        # Extract JSON from response (may be wrapped in ```json ... ```)
        json_str = raw_text.strip()
        if json_str.startswith("```"):
            # Remove markdown code fences
            lines = json_str.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            json_str = "\n".join(lines)

        ai_data = json.loads(json_str)

        result["direction"] = ai_data.get("direction")
        result["score"] = ai_data.get("score")
        result["entry"] = ai_data.get("entry")
        result["target"] = ai_data.get("target")
        result["stop_loss"] = ai_data.get("stop_loss")
        result["risk_reward"] = ai_data.get("risk_reward")
        result["reasoning"] = ai_data.get("reasoning")

        # Validierung
        if result["direction"] not in ("LONG", "SHORT"):
            result["error"] = f"Ungültige Richtung: {result['direction']}"

        # Prüfe ob Reasoning zur richtigen Aktie gehört
        _reasoning = (result.get("reasoning") or "").lower()
        _name_parts = name.lower().split()
        _name_found = any(p in _reasoning for p in _name_parts if len(p) > 3)
        _ticker_found = ticker.lower().rstrip(".de").rstrip(".f") in _reasoning
        if _reasoning and not _name_found and not _ticker_found:
            log.warning("KI-Reasoning für %s erwähnt weder Name noch Ticker – "
                        "mögliche Halluzination", ticker)
            result["error"] = (result.get("error") or "") + \
                " [WARNUNG: Reasoning erwähnt nicht den angefragten Wert]"

        log.info("KI-Bewertung %s: %s (Score %.1f)",
                 ticker, result["direction"], result.get("score", 0))

    except subprocess.TimeoutExpired:
        result["error"] = "Timeout (120s)"
        log.error("claude CLI Timeout für %s", ticker)
    except json.JSONDecodeError as e:
        result["error"] = f"JSON-Parse-Fehler: {e}"
        log.error("JSON-Fehler für %s: %s", ticker, e)
    except Exception as e:
        result["error"] = f"Unerwarteter Fehler: {e}"
        log.error("Fehler bei KI-Bewertung %s: %s", ticker, e, exc_info=True)

    return result


def run_ai_batch(candidates: list[dict], max_workers: int = 5,
                 model: str = "sonnet",
                 progress_callback=None) -> dict[str, dict]:
    """
    KI-Bewertung für mehrere Ticker parallel.

    Args:
        candidates: Liste von dicts mit Keys:
            ticker, name, df, fundamentals, news_score, news_count,
            sector, sector_score, index, tech_analysis
        max_workers: Anzahl paralleler Claude-Aufrufe
        model: Claude-Modell
        progress_callback: Optional callable(done, total) für Fortschritt

    Returns:
        dict {ticker: ai_result}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    total = len(candidates)
    done = 0

    def _process(cand):
        return cand["ticker"], get_ai_opinion(
            ticker=cand["ticker"],
            name=cand["name"],
            df=cand["df"],
            fundamentals=cand["fundamentals"],
            news_score=cand["news_score"],
            news_count=cand["news_count"],
            sector=cand["sector"],
            sector_score=cand["sector_score"],
            index=cand["index"],
            tech_analysis=cand["tech_analysis"],
            model=model,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, c): c["ticker"] for c in candidates}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                t, ai_result = future.result()
                results[t] = ai_result
            except Exception as e:
                log.error("AI-Batch Fehler %s: %s", ticker, e)
                results[ticker] = {"error": str(e), "direction": None, "score": None}
            done += 1
            if progress_callback:
                progress_callback(done, total)

    log.info("AI-Batch: %d/%d erfolgreich",
             sum(1 for r in results.values() if not r.get("error")), total)
    return results
