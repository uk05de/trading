FROM python:3.12-slim-bookworm

# Build-Tools fuer native Extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# App-Verzeichnis
WORKDIR /app

# Requirements zuerst (Docker Cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Code kopieren (Build-Context = trading_app/)
COPY . .

# Streamlit Config
RUN mkdir -p /root/.streamlit && \
    cp /app/.streamlit/config.toml /root/.streamlit/config.toml

# Daten-Verzeichnis (persistent via HA addon_config)
RUN mkdir -p /data /app/data
ENV TRADING_DB_PATH=/data/trading.db

# Entrypoint
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
