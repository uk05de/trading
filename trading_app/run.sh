#!/usr/bin/env bash
set -e

# DB-Pfad: persistent in /data (gemappt auf HA addon_config)
export TRADING_DB_PATH="/data/trading.db"

# DB initialisieren wenn noetig
if [ ! -f "$TRADING_DB_PATH" ]; then
    echo "Erste Ausfuehrung — initialisiere DB..."
    if [ -f /app/data/trading.db ]; then
        cp /app/data/trading.db "$TRADING_DB_PATH"
    fi
fi

# Symlink damit der App-Code die DB findet
ln -sf "$TRADING_DB_PATH" /app/data/trading.db 2>/dev/null || true

echo "Starte Trading App..."
cd /app

# Streamlit starten — Ingress-kompatibel
exec python3 -m streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.enableWebsocketCompression=false \
    --browser.gatherUsageStats=false \
    --server.headless=true
