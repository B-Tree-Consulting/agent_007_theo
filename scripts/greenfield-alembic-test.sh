#!/usr/bin/env bash
# Empty database → alembic upgrade head (merge-ready gate for backend/migrations changes).
# Uses an isolated DB name so dev data in `bfa-host-sample` is untouched.
#
# Requires: Docker Compose postgres (+ backend image for alembic). From repo root:
#   ./scripts/greenfield-alembic-test.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! REPO_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: must run from inside the b-tree-bfa-host-sample git repository" >&2
  exit 1
fi

cd "$REPO_ROOT"

_read_env_var() {
  local key="$1"
  local default="$2"
  if [[ -f .env ]]; then
    local line
    line="$(grep -E "^${key}=" .env | tail -1 || true)"
    if [[ -n "$line" ]]; then
      local value="${line#*=}"
      value="${value%\"}"
      value="${value#\"}"
      value="${value%\'}"
      value="${value#\'}"
      printf '%s' "$value"
      return 0
    fi
  fi
  printf '%s' "$default"
}

PG_USER="$(_read_env_var POSTGRES_USER bfa-host-sample)"
PG_PASSWORD="$(_read_env_var POSTGRES_PASSWORD changeme)"
GREENFIELD_DB="${GREENFIELD_DB:-bfa_host_sample_greenfield_test}"
DATABASE_URL="postgresql+psycopg://${PG_USER}:${PG_PASSWORD}@postgres:5432/${GREENFIELD_DB}"

echo "Starting postgres (if needed)..."
docker compose up -d postgres
docker compose exec -T postgres pg_isready -U "$PG_USER" >/dev/null

echo "Recreating database: $GREENFIELD_DB"
docker compose exec -T postgres psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = '${GREENFIELD_DB}' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS ${GREENFIELD_DB};
CREATE DATABASE ${GREENFIELD_DB};
SQL

echo "Running alembic upgrade head on empty database..."
docker compose run --rm --no-deps \
  -e DATABASE_URL="$DATABASE_URL" \
  backend alembic upgrade head

HEAD="$(docker compose run --rm --no-deps -e DATABASE_URL="$DATABASE_URL" backend alembic heads 2>/dev/null | awk '{print $1}' | tail -1)"
CURRENT="$(docker compose run --rm --no-deps -e DATABASE_URL="$DATABASE_URL" backend alembic current 2>/dev/null | awk '{print $1}' | tail -1)"

if [[ -z "$HEAD" || -z "$CURRENT" || "$CURRENT" != "$HEAD" ]]; then
  echo "error: greenfield migration did not reach head (current=${CURRENT:-?}, head=${HEAD:-?})" >&2
  exit 1
fi

echo "Greenfield alembic test passed (revision $CURRENT)."
