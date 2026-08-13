#!/usr/bin/env sh
# Container entrypoint: bring the schema up to head, then serve.
#
# Running migrations here rather than in a separate job keeps the free-tier
# deployment to a single service. It is safe for one instance; if you ever scale
# the API past one replica, move this to a release/pre-deploy step so two
# instances cannot race the same migration.
set -e

echo "Waiting for the database..."
ATTEMPTS=0
until python -c "
import asyncio, sys
from sqlalchemy import text
from app.core.db import SessionLocal

async def check():
    async with SessionLocal() as db:
        await db.execute(text('SELECT 1'))

try:
    asyncio.run(check())
except Exception as exc:
    print(f'  not ready: {type(exc).__name__}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ATTEMPTS" -ge 30 ]; then
        echo "Database did not become reachable after 30 attempts" >&2
        exit 1
    fi
    sleep 2
done
echo "Database is up."

echo "Applying migrations..."
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
