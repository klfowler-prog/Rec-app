#!/usr/bin/env bash
# Dump the prod (Supabase) database and restore it into the local dev Postgres
# running under docker-compose.dev.yml.
#
# Usage:
#   PROD_DATABASE_URL='postgresql://postgres:PASSWORD@HOST:5432/postgres' \
#     ./scripts/pull_prod_db.sh
#
# Requires: pg_dump on PATH (brew install libpq && brew link --force libpq),
#           docker compose, and the dev stack's db service defined.

set -euo pipefail

: "${PROD_DATABASE_URL:?set PROD_DATABASE_URL to your Supabase connection string}"

COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/docker-compose.dev.yml"
DUMP_FILE="$(cd "$(dirname "$0")/.." && pwd)/prod_dump.pgc"

echo "==> Dumping prod to $DUMP_FILE"
pg_dump "$PROD_DATABASE_URL" \
  --no-owner --no-privileges \
  --clean --if-exists \
  --schema=public \
  --exclude-extension='*' \
  -Fc -f "$DUMP_FILE"

echo "==> Ensuring dev db is up"
docker compose -f "$COMPOSE_FILE" up -d db

echo "==> Waiting for db to accept connections"
for _ in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U postgres -d nextup >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> Restoring into local nextup db"
docker compose -f "$COMPOSE_FILE" exec -T db \
  pg_restore -U postgres -d nextup \
  --no-owner --clean --if-exists \
  < "$DUMP_FILE"

echo "==> Done. Restart the app container to pick up the new data:"
echo "    docker compose -f docker-compose.dev.yml restart app"
