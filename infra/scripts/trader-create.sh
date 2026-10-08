#!/usr/bin/env bash
# Provision or update the existing Container App trader-app (external ingress on 8000).
# Idempotent. Does not modify any other Container App. Demo already has this app.
#
# Usage:
#   ./infra/scripts/trader-create.sh
#
# Prerequisites:
#   - az login
#   - az extension add --name containerapp
#   - Demo subscription (Azure subscription 1, or DEMO_AZURE_SUBSCRIPTION_ID)
#   - Key Vault secrets already stored (names only; values are not printed):
#       trader-app-database-url
#       trader-app-t212-api-key
#       trader-app-t212-api-secret
#       trader-app-theo-whitelist
#       trader-app-theo-whitelist-path
#       trader-app-theo-symbol-overrides
#       aydeo-chat-internal-service-token
#       aydeo-platform-internal-service-token
#   - Sibling demo parameters, or BICEPPARAM=/path/to/demo.bicepparam
#     Default search: ../aydeo-be and ../b-tree-aydeo_be
#
# First create uses a placeholder image, minReplicas=0, and no secret refs.
# A Failed app is deleted and created again. Secret refs are bound afterwards
# and retried until the identity can read Key Vault. Then roll the image with
# trader-build-push.sh and trader-apply.sh. Idle and boost stay in aydeo-be.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=trader-build-lib.sh
source "$SCRIPT_DIR/trader-build-lib.sh"

PLACEHOLDER_IMAGE="${PLACEHOLDER_IMAGE:-mcr.microsoft.com/azuredocs/containerapps-helloworld:latest}"
CONTAINER_PORT=8000
ACR_PULL_ROLE_ID="7f951dda-4ed3-4680-a7ca-43fe172d538d"
KV_SECRETS_USER_ROLE_ID="4633458b-17de-408a-b874-0445c86b69e6"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,28p' "$0"
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "error: unknown argument: $1" >&2
  exit 1
fi

resolve_bicepparam() {
  if [[ -n "${BICEPPARAM:-}" ]]; then
    printf '%s' "$BICEPPARAM"
    return 0
  fi
  local candidate
  for candidate in \
    "$REPO_ROOT/../aydeo-be/infra/bicep/parameters/demo.bicepparam" \
    "$REPO_ROOT/../b-tree-aydeo_be/infra/bicep/parameters/demo.bicepparam"
  do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

read_bicep_param() {
  local key="$1"
  sed -n "s/^param ${key} = '\\([^']*\\)'.*/\\1/p" "$BICEPPARAM" | head -1
}

require_bicep_param() {
  local key="$1" value
  value="$(read_bicep_param "$key")"
  if [[ -z "$value" ]]; then
    echo "error: demo.bicepparam param is empty: $key" >&2
    exit 1
  fi
  printf '%s' "$value"
}

require_kv_secret() {
  local secret_name="$1"
  if ! az keyvault secret show "${AZ_SUBSCRIPTION_ARGS[@]}" \
    --vault-name "$KV_NAME" \
    --name "$secret_name" \
    --query id \
    -o tsv >/dev/null; then
    echo "error: required Key Vault secret is missing: $secret_name" >&2
    exit 1
  fi
}

kv_binding() {
  local aca_name="$1" kv_name="$2"
  printf '%s=keyvaultref:%s/secrets/%s,identityref:%s' \
    "$aca_name" "$vault_uri" "$kv_name" "$uai_id"
}

ensure_role_assignment() {
  local principal_id="$1" role_id="$2" scope="$3" existing
  existing="$(az role assignment list "${AZ_SUBSCRIPTION_ARGS[@]}" \
    --assignee-object-id "$principal_id" \
    --scope "$scope" \
    --role "$role_id" \
    --query "[0].id" -o tsv)"
  if [[ -n "$existing" ]]; then
    return 0
  fi
  az role assignment create "${AZ_SUBSCRIPTION_ARGS[@]}" \
    --assignee-object-id "$principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "$role_id" \
    --scope "$scope" \
    -o none
}

require_demo_subscription
require_containerapp_extension

if ! BICEPPARAM="$(resolve_bicepparam)"; then
  echo "error: demo.bicepparam not found. Set BICEPPARAM to the aydeo-be parameters file." >&2
  exit 1
fi

LOCATION="$(require_bicep_param location)"
APP_ID="$(require_bicep_param appId)"
IDP_ISSUER="$(require_bicep_param idpIssuer)"
AUTH_PROVIDER="$(require_bicep_param authProvider)"

export_aca_default_domain
if [[ -z "${ACA_DEFAULT_DOMAIN:-}" ]]; then
  echo "error: ACA default domain is empty for $CAE in $RG" >&2
  exit 1
fi

BE_URL="https://aydeo-be.${ACA_DEFAULT_DOMAIN}"
CHAT_URL="https://aydeo-chat.${ACA_DEFAULT_DOMAIN}"

require_kv_secret "$KV_DATABASE_SECRET"
require_kv_secret "$KV_CHAT_TOKEN_SECRET"
require_kv_secret "$KV_PLATFORM_SECRET"
trading_kv_names=()
for env_name in "${TRADER_SECRET_ENV_NAMES[@]}"; do
  kv_name="trader-app-$(printf '%s' "$env_name" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  require_kv_secret "$kv_name"
  trading_kv_names+=("$kv_name")
done

if ! uai_id="$(az identity show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$UAI_NAME" --query id -o tsv 2>/dev/null)"; then
  echo "Creating user-assigned identity $UAI_NAME"
  uai_id="$(az identity create "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$UAI_NAME" \
    --location "$LOCATION" --query id -o tsv)"
fi
if [[ -z "$uai_id" ]]; then
  echo "error: user-assigned identity id is empty: $UAI_NAME" >&2
  exit 1
fi

principal_id=""
attempt=0
while [[ "$attempt" -lt 6 ]]; do
  principal_id="$(az identity show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$UAI_NAME" --query principalId -o tsv)"
  if [[ -n "$principal_id" ]]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done
if [[ -z "$principal_id" ]]; then
  echo "error: principal id is empty for $UAI_NAME" >&2
  exit 1
fi

acr_id="$(az acr show "${AZ_SUBSCRIPTION_ARGS[@]}" -n "$ACR_NAME" --query id -o tsv)"
kv_id="$(az keyvault show "${AZ_SUBSCRIPTION_ARGS[@]}" -n "$KV_NAME" --query id -o tsv)"
vault_uri="$(az keyvault show "${AZ_SUBSCRIPTION_ARGS[@]}" -n "$KV_NAME" --query properties.vaultUri -o tsv)"
vault_uri="${vault_uri%/}"
if [[ -z "$acr_id" || -z "$kv_id" || -z "$vault_uri" ]]; then
  echo "error: ACR id, Key Vault id, or Key Vault URI is empty" >&2
  exit 1
fi

ensure_role_assignment "$principal_id" "$ACR_PULL_ROLE_ID" "$acr_id"
ensure_role_assignment "$principal_id" "$KV_SECRETS_USER_ROLE_ID" "$kv_id"

secret_args=(
  "$(kv_binding "$ACA_DATABASE_SECRET" "$KV_DATABASE_SECRET")"
  "$(kv_binding "$ACA_CHAT_TOKEN_SECRET" "$KV_CHAT_TOKEN_SECRET")"
  "$(kv_binding "$ACA_PLATFORM_SECRET" "$KV_PLATFORM_SECRET")"
)
plain_env_args=(
  "APP_ID=${APP_ID}"
  "IDP_ISSUER=${IDP_ISSUER}"
  "IDP_AUDIENCE=api://${APP_ID}"
  "AUTH_PROVIDER=${AUTH_PROVIDER}"
  "BFA_SERVICE_SLUG=${BFA_SERVICE_SLUG}"
  "AYDEO_MIGRATE_ON_START=1"
  "AUTH_TEST_MODE=false"
  "BFA_CONFIRM_TEST_MODE=false"
  "AYDEO_CHAT_BASE_URL=${CHAT_URL}"
  "AYDEO_CMS_BASE_URL=${BE_URL}"
  "AYDEO_UM_BASE_URL=${BE_URL}"
  "DRIS_CAPABILITY_JWKS_URI=${BE_URL}/.well-known/bfa-capability-jwks.json"
  "DRIS_CAPABILITY_ISSUER=aydeo-be.dris"
  "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL=${BE_URL}/.well-known/approval-proof-jwks.json"
  "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER=aydeo-be.approval-proof"
)
env_args=("${plain_env_args[@]}")
env_args+=(
  "DATABASE_URL=secretref:${ACA_DATABASE_SECRET}"
  "AYDEO_CHAT_INTERNAL_TOKEN=secretref:${ACA_CHAT_TOKEN_SECRET}"
  "AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN=secretref:${ACA_PLATFORM_SECRET}"
)
for kv_name in "${trading_kv_names[@]}"; do
  env_name="$(printf '%s' "${kv_name#trader-app-}" | tr '[:lower:]' '[:upper:]' | tr '-' '_')"
  secret_args+=("$(kv_binding "$kv_name" "$kv_name")")
  env_args+=("${env_name}=secretref:${kv_name}")
done

bind_secrets() {
  local attempt=0
  local max_attempts=30
  local wait_seconds="${SECRET_WAIT_SECONDS:-10}"
  while [[ "$attempt" -lt "$max_attempts" ]]; do
    if az containerapp secret set "${AZ_SUBSCRIPTION_ARGS[@]}" \
      -g "$RG" \
      -n "$APP_NAME" \
      --secrets "${secret_args[@]}" \
      -o none; then
      return 0
    fi
    attempt=$((attempt + 1))
    echo "Waiting for $UAI_NAME to read Key Vault ($attempt/$max_attempts)..."
    sleep "$wait_seconds"
  done
  echo "error: $UAI_NAME cannot read Key Vault secrets yet. Re-run this script." >&2
  exit 1
}

app_exists=0
provisioning_state=""
if az containerapp show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" --query name -o tsv >/dev/null 2>&1; then
  app_exists=1
  provisioning_state="$(az containerapp show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" --query properties.provisioningState -o tsv)"
fi

if [[ "$app_exists" -eq 1 && "$provisioning_state" == "Failed" ]]; then
  echo "Deleting Container App $APP_NAME because provisioning state is Failed"
  az containerapp delete "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" --yes -o none
  app_exists=0
fi

if [[ "$app_exists" -eq 0 ]]; then
  echo "Creating Container App $APP_NAME"
  az containerapp create "${AZ_SUBSCRIPTION_ARGS[@]}" \
    -g "$RG" \
    -n "$APP_NAME" \
    --environment "$CAE" \
    --image "$PLACEHOLDER_IMAGE" \
    --ingress external \
    --target-port "$CONTAINER_PORT" \
    --min-replicas 0 \
    --max-replicas 1 \
    --user-assigned "$uai_id" \
    --registry-server "$ACR" \
    --registry-identity "$uai_id" \
    --env-vars "${plain_env_args[@]}" \
    -o none
else
  echo "Updating Container App $APP_NAME"
  az containerapp identity assign "${AZ_SUBSCRIPTION_ARGS[@]}" \
    -g "$RG" -n "$APP_NAME" \
    --user-assigned "$uai_id" \
    -o none
  az containerapp registry set "${AZ_SUBSCRIPTION_ARGS[@]}" \
    -g "$RG" -n "$APP_NAME" \
    --server "$ACR" \
    --identity "$uai_id" \
    -o none
  az containerapp ingress update "${AZ_SUBSCRIPTION_ARGS[@]}" \
    -g "$RG" -n "$APP_NAME" \
    --type external \
    --target-port "$CONTAINER_PORT" \
    -o none
fi

echo "Binding Key Vault secrets onto $APP_NAME"
bind_secrets
az containerapp update "${AZ_SUBSCRIPTION_ARGS[@]}" \
  -g "$RG" \
  -n "$APP_NAME" \
  --set-env-vars "${env_args[@]}" \
  -o none

echo ""
echo "Container App $APP_NAME is configured in $CAE."
echo "Identity: $UAI_NAME"
echo "Placeholder image does not serve /health. Next:"
echo "  ./infra/scripts/trader-build-push.sh"
echo "  ./infra/scripts/trader-apply.sh"
echo "Idle, boost, and stop are unchanged until b-tree-aydeo_be lists $APP_NAME."
