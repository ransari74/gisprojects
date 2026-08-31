#!/usr/bin/env bash
# Apply migrations and load data into the remote (Aiven) database.
#
#   ./scripts/deploy/migrate.sh              # generate --real fields/parcels/roads/canals/buildings + synthetic rest
#   ./scripts/deploy/migrate.sh --generate    # fully synthetic instead
#
# Runs the same backend/etl images used by docker-compose, just pointed at
# $pg_uri instead of the local db service -- nothing here is Lambda-specific.
# Safe to re-run: migrations are idempotent, and --truncate only affects the
# ETL step's own tables.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require pg_uri

LOAD_MODE="${1:---real}"

echo "==> Building backend image (for alembic)..."
docker build -q -t gis-portfolio-backend-migrate "$REPO_ROOT/backend" >/dev/null

echo "==> Applying migrations to $(echo "$pg_uri" | sed -E 's#(://[^:]+:)[^@]+#\1***#')..."
docker run --rm \
    --entrypoint alembic \
    -e DATABASE_URL="$pg_uri" \
    gis-portfolio-backend-migrate \
    upgrade head

echo "==> Building etl image..."
docker build -q -t gis-portfolio-etl -f "$REPO_ROOT/etl/Dockerfile" "$REPO_ROOT" >/dev/null

echo "==> Loading data ($LOAD_MODE --truncate)..."
docker run --rm \
    -e DATABASE_URL="$pg_uri" \
    gis-portfolio-etl \
    python -m etl.load "$LOAD_MODE" --truncate

echo "==> Done. Row counts:"
docker run --rm -e DATABASE_URL="$pg_uri" gis-portfolio-etl python -m etl.load --stats
