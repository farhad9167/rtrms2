#!/bin/sh
set -e

# Only the "web" service (or a single-process "all" run) seeds the DB on first start.
# owner/superadmin wait for web to be healthy (see docker-compose.yml), so there is no race.
if [ "${SERVICE_ROLE:-all}" = "web" ] || [ "${SERVICE_ROLE:-all}" = "all" ]; then
  if [ ! -f "$DATA_DIR/rtrms_saas.db" ]; then
    echo ">> [${SERVICE_ROLE:-all}] First run: seeding database..."
    python seed.py
  fi
fi

echo ">> Starting service role: ${SERVICE_ROLE:-all}"
# SQLite => 1 worker, several threads.
exec gunicorn 'app:create_app()' \
  --bind 0.0.0.0:5000 \
  --workers 1 --threads 8 --timeout 120 \
  --access-logfile -
