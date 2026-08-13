#!/usr/bin/env bash
# Start/stop/restart the API against the local Postgres, for development and
# the smoke tests. Uses a pidfile so stopping never signals the calling shell.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="${TMPDIR:-/tmp}/gisportfolio-api.pid"
LOGFILE="${TMPDIR:-/tmp}/gisportfolio-api.log"
PORT="${API_PORT:-8099}"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://gis:gis@127.0.0.1:5432/gisportfolio}"
export SECRET_KEY="${SECRET_KEY:-dev-only-insecure-change-me-in-production}"

stop() {
    if [[ -f "$PIDFILE" ]]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null || true
        rm -f "$PIDFILE"
        sleep 1
    fi
}

start() {
    cd "$ROOT/backend"
    nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
        --log-level warning > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 30); do
        if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
            echo "API up on http://127.0.0.1:$PORT (pid $(cat "$PIDFILE"))"
            return 0
        fi
        sleep 0.5
    done
    echo "API failed to start; last log lines:" >&2
    tail -25 "$LOGFILE" >&2
    return 1
}

case "${1:-restart}" in
    start)   start ;;
    stop)    stop; echo "stopped" ;;
    restart) stop; start ;;
    log)     tail -n "${2:-40}" "$LOGFILE" ;;
    *)       echo "usage: $0 {start|stop|restart|log}" >&2; exit 2 ;;
esac
