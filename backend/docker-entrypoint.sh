#!/usr/bin/env bash
set -euo pipefail

if [ "${AYDEO_MIGRATE_ON_START:-}" = "1" ]; then
  echo "Running Alembic migrations (AYDEO_MIGRATE_ON_START=1)..."
  alembic upgrade head
fi

# Honour LOG_LEVEL for ACA / image CMD when uvicorn has no explicit --log-level.
if [ "${1:-}" = "uvicorn" ]; then
  has_log_level=0
  for arg in "$@"; do
    if [ "$arg" = "--log-level" ]; then
      has_log_level=1
      break
    fi
  done
  if [ "$has_log_level" -eq 0 ]; then
    set -- "$@" --log-level "${LOG_LEVEL:-info}"
  fi
fi

exec "$@"
