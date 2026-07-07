FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASH_DATA_DIR=/app/data \
    ASH_DB_PATH=/app/data/audio_salvage_hunter.sqlite3 \
    DATABASE_URL=sqlite:////app/data/audio_salvage_hunter.sqlite3

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt pyproject.toml README.md alembic.ini ./
COPY audio_salvage_hunter ./audio_salvage_hunter
COPY tests ./tests
COPY config.yaml donor_database.csv ./
COPY docker-entrypoint.sh /usr/local/bin/audio-salvage-hunter-entrypoint

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && chmod 755 /usr/local/bin/audio-salvage-hunter-entrypoint \
    && mkdir -p /app/data /app/reports /app/logs /app/exports /app/config \
    && chown -R app:app /app

USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3).read()"

ENTRYPOINT ["audio-salvage-hunter-entrypoint"]
