#!/usr/bin/env bash
set -e

# DB-Pfad: persistent in /data (gemappt auf HA addon_config)
export TRADING_DB_PATH="/data/trading.db"

# Prices aus Backup kopieren wenn DB noch nicht existiert
if [ ! -f "$TRADING_DB_PATH" ]; then
    echo "Erste Ausfuehrung — initialisiere DB..."
    if [ -f /app/data/trading.db ]; then
        cp /app/data/trading.db "$TRADING_DB_PATH"
    fi
fi

# Symlink damit der App-Code die DB findet
ln -sf "$TRADING_DB_PATH" /app/data/trading.db 2>/dev/null || true

# Ingress-Pfad von HA Supervisor abfragen
INGRESS_PATH=""
if [ -n "$SUPERVISOR_TOKEN" ]; then
    echo "HA Supervisor erkannt — frage Ingress-Pfad ab..."
    INGRESS_ENTRY=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
        http://supervisor/addons/self/info 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('ingress_entry',''))" 2>/dev/null || echo "")

    if [ -n "$INGRESS_ENTRY" ]; then
        # Ingress URL: /api/hassio_ingress/<token>
        INGRESS_TOKEN=$(curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
            http://supervisor/addons/self/info 2>/dev/null | \
            python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('ingress_url','').split('/')[-1])" 2>/dev/null || echo "")
        if [ -n "$INGRESS_TOKEN" ]; then
            INGRESS_PATH="/api/hassio_ingress/${INGRESS_TOKEN}"
            echo "Ingress-Pfad: ${INGRESS_PATH}"
        fi
    fi
fi

echo "Starte Trading App..."
cd /app

# Streamlit mit Ingress-Settings starten
exec python3 -m streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.baseUrlPath="${INGRESS_PATH}" \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.enableWebsocketCompression=false \
    --browser.gatherUsageStats=false \
    --server.headless=true
