#!/usr/bin/env bash
# Point the existing Container App trader-app at an image built from this repo.
# The process slug is agent-007-theo. Local .env is not copied.
#
# Usage:
#   ./infra/scripts/trader-apply.sh
#   ./infra/scripts/trader-apply.sh <tag>
#   TAG=<tag> ./infra/scripts/trader-apply.sh
#
# Default tag: infra/scripts/.trader-last-image-tag from trader-build-push.sh.
# Sets BFA_SERVICE_SLUG=agent-007-theo, minReplicas=1, and HTTP GET /health
# liveness and readiness probes on port 8000.
#
# Health on the default hostname (custom DNS is not bound here):
#   curl -sS "https://trader-app.<defaultDomain>/health"
#
# Secret values stay in Key Vault. This script prints secret names and
# secretRef names only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=trader-build-lib.sh
source "$SCRIPT_DIR/trader-build-lib.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,19p' "$0"
  exit 0
fi

if [[ $# -ge 1 ]]; then
  TAG="$1"
elif [[ -z "${TAG:-}" ]]; then
  if ! TAG="$(resolve_demo_bfa_host_tag)"; then
    echo "error: no image tag. Run ./infra/scripts/trader-build-push.sh first or pass TAG / first arg." >&2
    exit 1
  fi
fi
if [[ -z "${TAG:-}" ]]; then
  echo "error: no image tag. Run ./infra/scripts/trader-build-push.sh first or pass TAG / first arg." >&2
  exit 1
fi

REVISION_SUFFIX="${REVISION_SUFFIX:-apply$(date -u +%H%M%S)}"
IMAGE="$ACR/$IMAGE_REPOSITORY:$TAG"

require_demo_subscription
export_aca_default_domain
if [[ -z "${ACA_DEFAULT_DOMAIN:-}" ]]; then
  echo "error: ACA default domain is empty for $CAE in $RG" >&2
  exit 1
fi

BE_URL="https://aydeo-be.${ACA_DEFAULT_DOMAIN}"
CHAT_URL="https://aydeo-chat.${ACA_DEFAULT_DOMAIN}"

env_json="$(az containerapp show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" \
  --query "properties.template.containers[0].env" -o json)"

if ! parsed="$(printf '%s' "$env_json" | python3 -c '
import json, sys
env = json.load(sys.stdin) or []

def plain(name):
    for item in env:
        if isinstance(item, dict) and item.get("name") == name and "value" in item:
            return str(item.get("value") or "").strip()
    return ""

app_id = plain("APP_ID")
issuer = plain("IDP_ISSUER")
audience = plain("IDP_AUDIENCE")
if not app_id or not issuer:
    sys.exit(1)
if not audience:
    audience = "api://" + app_id
sys.stdout.write(app_id + "\t" + issuer + "\t" + audience)
')"; then
  echo "error: APP_ID and IDP_ISSUER must already be set on $APP_NAME" >&2
  exit 1
fi
IFS=$'\t' read -r LIVE_APP_ID _LIVE_ISSUER LIVE_AUDIENCE <<<"$parsed"

uai_id="$(az identity show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$UAI_NAME" --query id -o tsv)"
if [[ -z "$uai_id" ]]; then
  echo "error: user-assigned identity not found: $UAI_NAME" >&2
  exit 1
fi

vault_uri="$(az keyvault show "${AZ_SUBSCRIPTION_ARGS[@]}" -n "$KV_NAME" --query properties.vaultUri -o tsv)"
vault_uri="${vault_uri%/}"
if [[ -z "$vault_uri" ]]; then
  echo "error: Key Vault URI is empty: $KV_NAME" >&2
  exit 1
fi

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
  local aca_name="$1"
  local kv_name="$2"
  printf '%s=keyvaultref:%s/secrets/%s,identityref:%s' \
    "$aca_name" "$vault_uri" "$kv_name" "$uai_id"
}

secret_args=()
require_kv_secret "$KV_DATABASE_SECRET"
secret_args+=("$(kv_binding "$ACA_DATABASE_SECRET" "$KV_DATABASE_SECRET")")
require_kv_secret "$KV_CHAT_TOKEN_SECRET"
secret_args+=("$(kv_binding "$ACA_CHAT_TOKEN_SECRET" "$KV_CHAT_TOKEN_SECRET")")
require_kv_secret "$KV_PLATFORM_SECRET"
secret_args+=("$(kv_binding "$ACA_PLATFORM_SECRET" "$KV_PLATFORM_SECRET")")

trading_env=()
for env_name in "${TRADER_SECRET_ENV_NAMES[@]}"; do
  kv_name="trader-app-$(printf '%s' "$env_name" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  require_kv_secret "$kv_name"
  secret_args+=("$(kv_binding "$kv_name" "$kv_name")")
  trading_env+=("${env_name}=secretref:${kv_name}")
done

az containerapp secret set "${AZ_SUBSCRIPTION_ARGS[@]}" \
  -g "$RG" \
  -n "$APP_NAME" \
  --secrets "${secret_args[@]}" \
  -o none

echo "Applying demo image (tag=$TAG, revision-suffix=$REVISION_SUFFIX):"
echo "  $APP_NAME → $IMAGE"

az containerapp update "${AZ_SUBSCRIPTION_ARGS[@]}" \
  -g "$RG" \
  -n "$APP_NAME" \
  --image "$IMAGE" \
  --min-replicas 1 \
  --revision-suffix "$REVISION_SUFFIX" \
  --set-env-vars \
    "BFA_SERVICE_SLUG=${BFA_SERVICE_SLUG}" \
    "AYDEO_MIGRATE_ON_START=1" \
    "AUTH_TEST_MODE=false" \
    "BFA_CONFIRM_TEST_MODE=false" \
    "AYDEO_CHAT_BASE_URL=${CHAT_URL}" \
    "AYDEO_CMS_BASE_URL=${BE_URL}" \
    "AYDEO_UM_BASE_URL=${BE_URL}" \
    "DRIS_CAPABILITY_JWKS_URI=${BE_URL}/.well-known/bfa-capability-jwks.json" \
    "DRIS_CAPABILITY_ISSUER=aydeo-be.dris" \
    "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL=${BE_URL}/.well-known/approval-proof-jwks.json" \
    "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER=aydeo-be.approval-proof" \
    "IDP_AUDIENCE=${LIVE_AUDIENCE}" \
    "DATABASE_URL=secretref:${ACA_DATABASE_SECRET}" \
    "AYDEO_CHAT_INTERNAL_TOKEN=secretref:${ACA_CHAT_TOKEN_SECRET}" \
    "AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN=secretref:${ACA_PLATFORM_SECRET}" \
    "${trading_env[@]}" \
  -o none

container_json="$(az containerapp show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" \
  --query "properties.template.containers[0]" -o json)"

patch_body="$(
  PROBE_IMAGE="$IMAGE" EXPECTED_SLUG="$BFA_SERVICE_SLUG" python3 -c '
import json, os, sys
container = json.load(sys.stdin) or {}
env = container.get("env") or []
slug = ""
for item in env:
    if isinstance(item, dict) and item.get("name") == "BFA_SERVICE_SLUG":
        slug = str(item.get("value") or "")
if slug != os.environ["EXPECTED_SLUG"]:
    sys.stderr.write("error: container env was not updated before probe patch\n")
    sys.exit(1)
probes = [
    {
        "type": "Liveness",
        "httpGet": {"path": "/health", "port": 8000, "scheme": "HTTP"},
        "periodSeconds": 30,
        "failureThreshold": 3,
    },
    {
        "type": "Readiness",
        "httpGet": {"path": "/health", "port": 8000, "scheme": "HTTP"},
        "periodSeconds": 10,
        "failureThreshold": 3,
    },
]
kept = {}
for key in ("name", "command", "args", "env", "resources", "volumeMounts"):
    if key in container and container[key] is not None:
        kept[key] = container[key]
kept["name"] = container.get("name") or "trader-app"
kept["image"] = os.environ["PROBE_IMAGE"]
kept["probes"] = probes
json.dump({"properties": {"template": {"containers": [kept]}}}, sys.stdout)
' <<<"$container_json"
)"

app_id="$(az containerapp show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$APP_NAME" --query id -o tsv)"
if [[ -z "$app_id" ]]; then
  echo "error: container app resource id is empty: $APP_NAME" >&2
  exit 1
fi

az rest --method patch \
  --uri "${app_id}?api-version=${CONTAINER_APP_API_VERSION}" \
  --body "$patch_body" \
  -o none

echo ""
echo "Update submitted for $APP_NAME."
echo "Secret values stay in Key Vault."
echo ""
echo "Logs:"
echo "  az containerapp logs show --subscription \"${AZ_SUBSCRIPTION_ARGS[1]}\" -g $RG -n $APP_NAME --tail 50 --follow"
echo ""
echo "Health:"
echo "  curl -sS \"https://${APP_NAME}.${ACA_DEFAULT_DOMAIN}/health\""
