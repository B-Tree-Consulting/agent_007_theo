#!/usr/bin/env bash
# Offline check: Trading App Configuration is stored, later sections are not.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/infra/scripts/trader-sync-trading-kv-secrets.sh"
SUB_ID="00000000-0000-4000-8000-000000000001"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/.env" <<'EOF'
# before
GITHUB_TOKEN=must-not-upload-early
# =============================================================================
# Trading App Configuration
# =============================================================================
T212_API_KEY=key-value
T212_API_SECRET=secret-value
THEO_WHITELIST=AAPL_US_EQ,MSFT_US_EQ
THEO_WHITELIST_PATH=config/theo_whitelist.txt
THEO_SYMBOL_OVERRIDES=IVV_EQ:IVV
EMPTY_KEY=
# =============================================================================
# Build docker image
# =============================================================================
GITHUB_TOKEN=must-not-upload-late
EOF

mkdir -p "$tmp/bin"
cat >"$tmp/bin/az" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${AZ_LOG:?}"
args="$*"
if [[ "$args" == "account show" ]]; then
  exit 0
fi
if [[ "$args" == *"account list"* ]]; then
  printf '%s\n' "${SUB_ID:?}"
  exit 0
fi
if [[ "$args" == *"account set"* || "$args" == *"account show --subscription"* ]]; then
  if [[ "$args" == *"--query name"* ]]; then
    printf '%s\n' "Azure subscription 1"
  fi
  exit 0
fi
if [[ "$args" == *"keyvault secret set"* ]]; then
  if [[ "$args" == *"--value"* ]]; then
    echo "secret value was passed on the command line" >&2
    exit 2
  fi
  prev=""
  for arg in "$@"; do
    if [[ "$prev" == "--file" && -n "${AZ_FILE_LOG:-}" && -f "$arg" ]]; then
      cat "$arg" >> "$AZ_FILE_LOG"
      printf '\n' >> "$AZ_FILE_LOG"
    fi
    prev="$arg"
  done
  exit 0
fi
exit 0
EOF
chmod +x "$tmp/bin/az"

AZ_LOG="$tmp/az.log"
export AZ_LOG SUB_ID
set +e
output="$(
  PATH="$tmp/bin:$PATH" \
    ENV_FILE="$tmp/.env" \
    DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID" \
    "$SCRIPT" 2>&1
)"
code=$?
set -e
if [[ "$code" -ne 0 ]]; then
  printf '%s\n' "$output" >&2
  fail "script exited $code"
fi

for name in \
  trader-app-t212-api-key \
  trader-app-t212-api-secret \
  trader-app-theo-whitelist \
  trader-app-theo-whitelist-path \
  trader-app-theo-symbol-overrides
do
  if [[ "$output" != *"as kv-aydeo-demo-weu/$name"* ]]; then
    fail "missing store line for $name"
  fi
  if ! grep -q -- "--name $name" "$AZ_LOG"; then
    fail "az was not called for $name"
  fi
done

if grep -q 'must-not-upload' <<<"$output$AZ_LOG"; then
  fail "a token from outside the Trading App section was uploaded or printed"
fi
if grep -q 'key-value\|secret-value\|AAPL_US_EQ' <<<"$output"; then
  fail "a secret value was printed"
fi
if grep -q 'trader-app-empty-key' "$AZ_LOG"; then
  fail "empty key was stored"
fi
if [[ "$output" != *"skip empty EMPTY_KEY"* ]]; then
  fail "empty key was not reported"
fi
if grep -q 'trader-app-github-token' "$AZ_LOG"; then
  fail "github token was stored"
fi

run_script() {
  local env_file="$1"
  local log="$2"
  local file_log="$3"
  PATH="$tmp/bin:$PATH" \
    ENV_FILE="$env_file" \
    DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID" \
    AZ_LOG="$log" \
    AZ_FILE_LOG="$file_log" \
    "$SCRIPT" 2>&1
}

cat >"$tmp/.env-local-db" <<'EOF'
# =============================================================================
# DB Setup
# =============================================================================
DATABASE_URL=postgresql://trader:local-only-password@postgres:5432/trader_app
# =============================================================================
# Trading App Configuration
# =============================================================================
T212_API_KEY=key-value
# =============================================================================
# Build docker image
# =============================================================================
GITHUB_TOKEN=must-not-upload-late
EOF

set +e
local_output="$(run_script "$tmp/.env-local-db" "$tmp/az-local.log" "$tmp/az-local-files.log")"
local_code=$?
set -e
if [[ "$local_code" -eq 0 ]]; then
  fail "local Compose DATABASE_URL was accepted"
fi
if [[ "$local_output" != *"host is 'postgres'"* ]]; then
  printf '%s\n' "$local_output" >&2
  fail "local host was not named in the error"
fi
if [[ "$local_output" == *"local-only-password"* ]]; then
  fail "local database password was printed"
fi
if [[ -f "$tmp/az-local.log" ]] && grep -q 'keyvault secret set' "$tmp/az-local.log"; then
  fail "secrets were stored when the database host is local"
fi

cat >"$tmp/.env-demo-db" <<'EOF'
# =============================================================================
# DB Setup
# =============================================================================
DATABASE_URL=postgresql://trader:local-only-password@postgres:5432/trader_app
DEMO_DATABASE_URL=postgresql://trader:demo-db-secret@psql-aydeo-demo-weu.postgres.database.azure.com:5432/trader_app
# =============================================================================
# Trading App Configuration
# =============================================================================
T212_API_KEY=key-value
# =============================================================================
# Build docker image
# =============================================================================
GITHUB_TOKEN=must-not-upload-late
EOF

set +e
demo_output="$(run_script "$tmp/.env-demo-db" "$tmp/az-demo.log" "$tmp/az-demo-files.log")"
demo_code=$?
set -e
if [[ "$demo_code" -ne 0 ]]; then
  printf '%s\n' "$demo_output" >&2
  fail "demo database URL was rejected"
fi
if [[ "$demo_output" != *"as kv-aydeo-demo-weu/trader-app-database-url"* ]]; then
  fail "database secret was not stored"
fi
if [[ "$demo_output" == *"local-only-password"* || "$demo_output" == *"demo-db-secret"* ]]; then
  fail "a database password was printed"
fi
if ! grep -q 'sslmode=require' "$tmp/az-demo-files.log"; then
  fail "Azure database URL was stored without sslmode=require"
fi
if grep -q 'local-only-password' "$tmp/az-demo-files.log"; then
  fail "Compose DATABASE_URL was stored"
fi
if ! grep -q 'demo-db-secret' "$tmp/az-demo-files.log"; then
  fail "demo database URL was not passed to Key Vault"
fi

echo "trader-sync-trading-kv-secrets ok"
