#!/usr/bin/env bash
# Verify bootstrap modes 1–3 (non-interactive). Local proof only — this repo has no GitHub Actions.
#
# Mode 1 generated: full pytest after rename (source-equivalent suite).
# Mode 2 generated: pytest tests/host tests/scripts tests/api (canaries).
# Mode 3 generated: same set, DATABASE_URL unset, sqlalchemy/alembic/psycopg not installed.
#
# Requires: docker, compose v2, GITHUB_TOKEN (private kit/audit/cms-client git deps).
# Does not copy source .env / .secrets into generated trees.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! REPO_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: run from inside b-tree-bfa-host-sample" >&2
  exit 1
fi

BOOTSTRAP="${SCRIPT_DIR}/bootstrap-new-host.sh"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/verify-bootstrap-modes.XXXXXX")"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

GITHUB_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [[ -z "$GITHUB_TOKEN" && -f "${REPO_ROOT}/.env" ]]; then
  # Local verify only: read compose token without rsyncing .env into generated trees.
  GITHUB_TOKEN="$(awk -F= '/^GITHUB_TOKEN=/{print substr($0, index($0,$2)); exit}' "${REPO_ROOT}/.env")"
fi
if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "error: GITHUB_TOKEN (or GH_TOKEN) is required for private git deps in generated mode 3" >&2
  exit 1
fi

if ! docker compose -f "${REPO_ROOT}/docker-compose.yml" --project-directory "${REPO_ROOT}" \
     ps --status running postgres 2>/dev/null | grep -q postgres; then
  echo "Starting source compose postgres..."
  env GITHUB_TOKEN="$GITHUB_TOKEN" GH_TOKEN="$GITHUB_TOKEN" \
    docker compose -f "${REPO_ROOT}/docker-compose.yml" --project-directory "${REPO_ROOT}" up -d postgres
fi

COMPOSE_ENV=(
  "GITHUB_TOKEN=${GITHUB_TOKEN}"
  "GH_TOKEN=${GITHUB_TOKEN}"
)

residue_greps() {
  local root="$1"
  local pizza_ok="${2:-no}"
  if ! grep -R -n "build_aydeo_host" "${root}/backend/src/host/factory.py" >/dev/null; then
    echo "error: ${root}: build_aydeo_host missing" >&2
    return 1
  fi
  if grep -R -n "de-gate-context" "${root}/backend/src" "${root}/backend/tests/host" >/dev/null 2>&1; then
    echo "error: ${root}: de-gate-context present" >&2
    return 1
  fi
  if grep -R -n "config_gate_client" "${root}/backend/src" "${root}/backend/tests/host" >/dev/null 2>&1; then
    echo "error: ${root}: config_gate_client present" >&2
    return 1
  fi
  if [[ "$pizza_ok" != "yes" ]]; then
    local hits
    hits="$(grep -R -i -n pizza \
      "${root}/backend/src" \
      "${root}/backend/tests/host" \
      "${root}/postman" \
      "${root}/README.md" \
      "${root}/POSTMAN_GUIDE.md" \
      2>/dev/null || true)"
    if [[ -n "$hits" ]]; then
      echo "error: ${root}: pizza residue:" >&2
      echo "$hits" >&2
      return 1
    fi
  fi
}

assert_rsync_exclusions() {
  local root="$1"
  local path
  for path in \
    ".knowledge" \
    ".cursor/mcp.json" \
    ".env" \
    ".env.demo" \
    ".env.local" \
    "backend/vendor/agentstepkit" \
    "backend/vendor/aydeo_audit_sdk" \
    "scripts/.demo-last-bfa-host-tag"; do
    if [[ -e "${root}/${path}" ]]; then
      echo "error: rsync leaked ${path} into ${root}" >&2
      return 1
    fi
  done
  if [[ -e "${root}/.secrets" ]]; then
    if find "${root}/.secrets" -mindepth 1 ! -name 'README.md' | grep -q .; then
      echo "error: rsync leaked secrets besides README.md into ${root}/.secrets" >&2
      return 1
    fi
  fi
}

write_generated_env() {
  local root="$1"
  local include_db="${2:-yes}"
  cp "${root}/backend/.env.example" "${root}/.env"
  printf '\nGITHUB_TOKEN=%s\n' "$GITHUB_TOKEN" >> "${root}/.env"
  if [[ "$include_db" != "yes" ]]; then
    # Fail closed: generated mode 3 must not inherit a DATABASE_URL.
    if grep -q '^DATABASE_URL=' "${root}/.env"; then
      echo "error: mode 3 .env still has DATABASE_URL" >&2
      return 1
    fi
  fi
}

bootstrap_mode() {
  local dest="$1"
  shift
  mkdir -p "$dest"
  git -C "$dest" init -q
  "$BOOTSTRAP" --non-interactive --target "$dest" --no-commit "$@"
}

run_generated_pytest_on_source_image() {
  local gen="$1"
  local slug="$2"
  shift 2
  local db_base
  db_base="$(printf '%s' "$slug" | tr '-' '_')"
  env "${COMPOSE_ENV[@]}" docker compose -f "${REPO_ROOT}/docker-compose.yml" --project-directory "${REPO_ROOT}" \
    run --rm \
    -e "BFA_SERVICE_SLUG=${slug}" \
    -e "VERIFY_PYTEST_DB=${db_base}" \
    -v "${gen}/backend:/app/backend" \
    -v "${gen}/scripts:/app/scripts" \
    -v "${gen}/docker-compose.yml:/app/docker-compose.yml:ro" \
    backend bash -c 'raw="${DATABASE_URL:?}"; prefix="${raw%/*}"; export DATABASE_URL="${prefix}/${VERIFY_PYTEST_DB}"; exec pytest "$@"' \
    x "$@"
}

echo "=== Mode 1: demo clone (rename, pizza kept) ==="
MODE1="${WORKDIR}/mode1"
bootstrap_mode "$MODE1" --repo-name b-tree-verify-mode1-bfa --service-slug verify-mode1-bfa
assert_rsync_exclusions "$MODE1"
residue_greps "$MODE1" yes
grep -q "AyDEO verify-mode1-bfa API" "${MODE1}/backend/src/main.py"
grep -q '"name": "AyDEO verify-mode1-bfa"' "${MODE1}/postman/collection.json" \
  || grep -q 'AyDEO verify-mode1-bfa' "${MODE1}/postman/collection.json"
write_generated_env "$MODE1" yes
run_generated_pytest_on_source_image "$MODE1" verify-mode1-bfa

echo "=== Mode 2: clean host + Postgres ==="
MODE2="${WORKDIR}/mode2"
bootstrap_mode "$MODE2" --repo-name b-tree-verify-mode2-bfa --service-slug verify-mode2-bfa --strip-pizza
assert_rsync_exclusions "$MODE2"
residue_greps "$MODE2" no
write_generated_env "$MODE2" yes
run_generated_pytest_on_source_image "$MODE2" verify-mode2-bfa tests/host tests/scripts tests/api

echo "=== Mode 3: clean host, no Postgres ==="
MODE3="${WORKDIR}/mode3"
bootstrap_mode "$MODE3" --repo-name b-tree-verify-mode3-bfa --service-slug verify-mode3-bfa --strip-pizza --strip-postgres
assert_rsync_exclusions "$MODE3"
residue_greps "$MODE3" no
write_generated_env "$MODE3" no
if grep -q 'sqlalchemy>=' "${MODE3}/backend/Dockerfile"; then
  echo "error: mode 3 Dockerfile still installs sqlalchemy" >&2
  exit 1
fi

MODE3_PROJECT="verify-bootstrap-mode3-$$"
env "${COMPOSE_ENV[@]}" docker compose -f "${MODE3}/docker-compose.yml" --project-directory "${MODE3}" \
  -p "$MODE3_PROJECT" build backend
env "${COMPOSE_ENV[@]}" docker compose -f "${MODE3}/docker-compose.yml" --project-directory "${MODE3}" \
  -p "$MODE3_PROJECT" run --no-deps --rm -e DATABASE_URL= backend \
  python -c "import sys
mods = ('sqlalchemy', 'alembic', 'psycopg')
failed = False
for name in mods:
    try:
        __import__(name)
        print(f'error: {name} is installed in mode 3 image', file=sys.stderr)
        failed = True
    except ImportError:
        pass
raise SystemExit(1 if failed else 0)"
env "${COMPOSE_ENV[@]}" docker compose -f "${MODE3}/docker-compose.yml" --project-directory "${MODE3}" \
  -p "$MODE3_PROJECT" run --no-deps --rm -e DATABASE_URL= backend \
  pytest tests/host tests/scripts tests/api
env "${COMPOSE_ENV[@]}" docker compose -f "${MODE3}/docker-compose.yml" --project-directory "${MODE3}" \
  -p "$MODE3_PROJECT" down --rmi local --volumes >/dev/null 2>&1 || true

echo "verify-bootstrap-modes: all modes passed"
