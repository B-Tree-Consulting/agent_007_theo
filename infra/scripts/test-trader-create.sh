#!/usr/bin/env bash
# Offline check: trader-create.sh provisions trader-app and leaves other apps alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/infra/scripts/trader-create.sh"
SUB_ID="00000000-0000-4000-8000-000000000001"
APP_ID_VALUE="2b3e51f8-4695-4764-91a8-bd374ad37d4a"
DOMAIN="demo.example.net"
UAI_ID="/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-trader-app"
PRINCIPAL_ID="11111111-1111-4111-8111-111111111111"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1" needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "missing [${needle}]"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    fail "unexpected [${needle}]"
  fi
}

if grep -q 'aydeo-sample-bfa' "$SCRIPT"; then
  fail "trader-create.sh names aydeo-sample-bfa"
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cat >"$tmp/demo.bicepparam" <<EOF
param location = 'westeurope'
param appId = '${APP_ID_VALUE}'
param idpIssuer = 'https://login.microsoftonline.com/tenant/v2.0'
param authProvider = 'azure'
EOF

mkdir -p "$tmp/bin"
cat >"$tmp/bin/az" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${AZ_LOG:?}"
args="$*"
if [[ "$args" == *"keyvault secret show"* && "$args" == *"--query value"* ]]; then
  echo "stub refused secret value query" >&2
  exit 2
fi
if [[ "$args" == "account show" ]]; then
  exit 0
fi
if [[ "$args" == *"account set"* || "$args" == *"account show"* ]]; then
  if [[ "$args" == *"--query name"* ]]; then
    printf '%s\n' "Azure subscription 1"
  fi
  exit 0
fi
if [[ "$args" == *"extension show"* ]]; then
  exit 0
fi
if [[ "$args" == *"containerapp env show"* ]]; then
  printf '%s\n' "${DOMAIN:?}"
  exit 0
fi
if [[ "$args" == *"keyvault secret show"* ]]; then
  if [[ -n "${MISSING_SECRET:-}" && "$args" == *"--name ${MISSING_SECRET}"* ]]; then
    exit 1
  fi
  printf '%s\n' "https://kv-aydeo-demo-weu.vault.azure.net/secrets/name"
  exit 0
fi
if [[ "$args" == *"keyvault show"* ]]; then
  if [[ "$args" == *"properties.vaultUri"* ]]; then
    printf '%s\n' "https://kv-aydeo-demo-weu.vault.azure.net/"
  else
    printf '%s\n' "/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.KeyVault/vaults/kv-aydeo-demo-weu"
  fi
  exit 0
fi
if [[ "$args" == *"identity show"* ]]; then
  if [[ "${IDENTITY_MISSING:-}" == "1" ]] && ! grep -q "identity create" "$AZ_LOG"; then
    exit 1
  fi
  if [[ "$args" == *"--query principalId"* ]]; then
    printf '%s\n' "${PRINCIPAL_ID:?}"
  else
    printf '%s\n' "${UAI_ID:?}"
  fi
  exit 0
fi
if [[ "$args" == *"identity create"* ]]; then
  printf '%s\n' "${UAI_ID:?}"
  exit 0
fi
if [[ "$args" == *"acr show"* ]]; then
  printf '%s\n' "/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.ContainerRegistry/registries/acraydeodemo"
  exit 0
fi
if [[ "$args" == *"role assignment list"* ]]; then
  printf '%s\n' "/subscriptions/${SUB_ID}/providers/Microsoft.Authorization/roleAssignments/existing"
  exit 0
fi
if [[ "$args" == *"containerapp show"* ]]; then
  if [[ "${APP_EXISTS:-}" != "1" && "${APP_STATE:-}" != "Failed" ]]; then
    exit 1
  fi
  if [[ "$args" == *"provisioningState"* ]]; then
    printf '%s\n' "${APP_STATE:-Succeeded}"
    exit 0
  fi
  printf '%s\n' "trader-app"
  exit 0
fi
if [[ "$args" == *"containerapp secret set"* ]]; then
  if [[ -n "${SECRET_FAIL_FILE:-}" && -f "$SECRET_FAIL_FILE" ]]; then
    left="$(cat "$SECRET_FAIL_FILE")"
    if [[ "$left" -gt 0 ]]; then
      printf '%s\n' "$((left - 1))" >"$SECRET_FAIL_FILE"
      echo "Unable to get value using Managed identity" >&2
      exit 1
    fi
  fi
  exit 0
fi
if [[ "$args" == *"containerapp delete"* || "$args" == *"containerapp create"* || "$args" == *"containerapp update"* || "$args" == *"containerapp identity assign"* || "$args" == *"containerapp registry set"* || "$args" == *"containerapp ingress update"* ]]; then
  exit 0
fi
echo "stub: unhandled az: $args" >&2
exit 3
EOF
chmod +x "$tmp/bin/az"

run_script() {
  local log="$1"
  shift
  PATH="$tmp/bin:$PATH" \
    DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID" \
    BICEPPARAM="$tmp/demo.bicepparam" \
    AZ_LOG="$log" \
    SUB_ID="$SUB_ID" \
    DOMAIN="$DOMAIN" \
    UAI_ID="$UAI_ID" \
    PRINCIPAL_ID="$PRINCIPAL_ID" \
    "$@" \
    "$SCRIPT"
}

set +e
missing_output="$(MISSING_SECRET=trader-app-database-url IDENTITY_MISSING=1 APP_EXISTS=0 run_script "$tmp/az-missing.log" 2>&1)"
missing_code=$?
set -e
if [[ "$missing_code" -eq 0 ]]; then
  fail "create ran with a missing database secret"
fi
if [[ "$missing_output" != *"missing: trader-app-database-url"* ]]; then
  printf '%s\n' "$missing_output" >&2
  fail "missing secret was not named"
fi
if [[ -f "$tmp/az-missing.log" ]] && grep -q 'containerapp create' "$tmp/az-missing.log"; then
  fail "container app was created without the database secret"
fi

set +e
create_output="$(IDENTITY_MISSING=1 APP_EXISTS=0 run_script "$tmp/az-create.log" 2>&1)"
create_code=$?
set -e
if [[ "$create_code" -ne 0 ]]; then
  printf '%s\n' "$create_output" >&2
  fail "create exited $create_code"
fi
create_log="$(cat "$tmp/az-create.log")"
create_line="$(grep "containerapp create" "$tmp/az-create.log")"
assert_contains "$create_line" "-n trader-app"
assert_contains "$create_line" "--environment cae-aydeo-demo-weu"
assert_contains "$create_line" "--ingress external"
assert_contains "$create_line" "--target-port 8000"
assert_contains "$create_line" "--min-replicas 0"
assert_contains "$create_line" "--image mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
assert_contains "$create_line" "--user-assigned ${UAI_ID}"
assert_contains "$create_line" "APP_ID=${APP_ID_VALUE}"
assert_contains "$create_line" "IDP_ISSUER=https://login.microsoftonline.com/tenant/v2.0"
assert_contains "$create_line" "BFA_SERVICE_SLUG=agent-007-theo"
assert_not_contains "$create_line" "secretref:"
assert_not_contains "$create_line" "keyvaultref:"
secret_line="$(grep "containerapp secret set" "$tmp/az-create.log" | tail -1)"
env_line="$(grep "containerapp update" "$tmp/az-create.log" | tail -1)"
assert_contains "$secret_line" "trader-app-database-url=keyvaultref:https://kv-aydeo-demo-weu.vault.azure.net/secrets/trader-app-database-url,identityref:${UAI_ID}"
assert_contains "$env_line" "DATABASE_URL=secretref:trader-app-database-url"
assert_contains "$env_line" "T212_API_KEY=secretref:trader-app-t212-api-key"
assert_contains "$env_line" "THEO_SYMBOL_OVERRIDES=secretref:trader-app-theo-symbol-overrides"
assert_not_contains "$create_log" "aydeo-sample-bfa"
assert_not_contains "$create_log" "--query value"
assert_contains "$(grep "identity create" "$tmp/az-create.log")" "-n id-trader-app"
assert_contains "$(grep "identity create" "$tmp/az-create.log")" "--location westeurope"

set +e
update_output="$(IDENTITY_MISSING=0 APP_EXISTS=1 run_script "$tmp/az-update.log" 2>&1)"
update_code=$?
set -e
if [[ "$update_code" -ne 0 ]]; then
  printf '%s\n' "$update_output" >&2
  fail "update exited $update_code"
fi
if grep -q 'containerapp create' "$tmp/az-update.log"; then
  fail "existing app was created again"
fi
update_line="$(grep "containerapp update" "$tmp/az-update.log")"
assert_contains "$update_line" "-n trader-app"
assert_not_contains "$update_line" "containerapps-helloworld"
assert_not_contains "$update_line" "--min-replicas"
assert_contains "$(grep "containerapp secret set" "$tmp/az-update.log")" "trader-app-t212-api-secret=keyvaultref:"

printf '%s\n' "1" >"$tmp/secret-fails"
set +e
retry_output="$(
  IDENTITY_MISSING=1 APP_EXISTS=0 APP_STATE= SECRET_WAIT_SECONDS=0 \
    SECRET_FAIL_FILE="$tmp/secret-fails" \
    run_script "$tmp/az-retry.log" 2>&1
)"
retry_code=$?
set -e
if [[ "$retry_code" -ne 0 ]]; then
  printf '%s\n' "$retry_output" >&2
  fail "secret bind retry exited $retry_code"
fi
if [[ "$(grep -c "containerapp secret set" "$tmp/az-retry.log")" -lt 2 ]]; then
  fail "secret bind was not retried"
fi
if [[ "$retry_output" != *"Waiting for id-trader-app to read Key Vault"* ]]; then
  fail "secret bind wait was not reported"
fi

set +e
failed_output="$(
  IDENTITY_MISSING=0 APP_STATE=Failed SECRET_WAIT_SECONDS=0 \
    run_script "$tmp/az-failed.log" 2>&1
)"
failed_code=$?
set -e
if [[ "$failed_code" -ne 0 ]]; then
  printf '%s\n' "$failed_output" >&2
  fail "failed-app recreate exited $failed_code"
fi
if ! grep -q 'containerapp delete' "$tmp/az-failed.log"; then
  fail "failed app was not deleted"
fi
if ! grep -q 'containerapp create' "$tmp/az-failed.log"; then
  fail "failed app was not created again"
fi
assert_contains "$failed_output" "provisioning state is Failed"

echo "trader-create ok"
