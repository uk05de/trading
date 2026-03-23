ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.3.3
FROM ${BUILD_FROM}

# Python + Build-Tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# App-Verzeichnis
WORKDIR /app

# Requirements zuerst (Docker Cache)
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# App-Code kopieren
COPY . .

# Streamlit Config (kein Browser oeffnen, Ingress-kompatibel)
RUN mkdir -p /root/.streamlit
COPY ha-addon/.streamlit/config.toml /root/.streamlit/config.toml

# Daten-Verzeichnis (persistent via HA config map)
RUN mkdir -p /data
ENV TRADING_DB_PATH=/data/trading.db

# Entrypoint
COPY ha-addon/run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
