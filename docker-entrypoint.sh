#!/bin/sh
set -eu

mkdir -p /app/data /app/reports /app/logs /app/exports /app/config
alembic upgrade head
exec uvicorn audio_salvage_hunter.web.app:app --host 0.0.0.0 --port 8080
