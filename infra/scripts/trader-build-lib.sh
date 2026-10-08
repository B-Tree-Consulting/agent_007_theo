#!/usr/bin/env bash
# Shared helpers for building this repository and applying that image to the
# existing demo Container App trader-app. Spoke-local. Do not source scripts
# from ../trader_app or any other repository.
#
# GitHub token file (not committed): $HOME/.config/aydeo-demo/github_token
# See b-tree-aydeo_be/infra/scripts/github_token.example. Secret values stay in
# Key Vault or that token file, never in git, tags, or logs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  echo "error: must run from inside the agent_007_theo git repository" >&2
  exit 1
fi

GITHUB_TOKEN_FILE="${GITHUB_TOKEN_FILE:-$HOME/.config/aydeo-demo/github_token}"
ACR="${ACR:-acraydeodemo.azurecr.io}"
ACR_NAME="${ACR_NAME:-acraydeodemo}"
RG="${RG:-rg-aydeo-demo-weu}"
CAE="${CAE:-cae-aydeo-demo-weu}"
KV_NAME="${KV_NAME:-kv-aydeo-demo-weu}"
APP_NAME="trader-app"
IMAGE_REPOSITORY="trader-app"
# Azure app name stays trader-app. The process identity is this repository.
BFA_SERVICE_SLUG="agent-007-theo"
UAI_NAME="id-${APP_NAME}"
LAST_TAG_FILE="${LAST_TAG_FILE:-$SCRIPT_DIR/.trader-last-image-tag}"
CONTAINER_APP_API_VERSION="2024-03-01"
KV_PLATFORM_SECRET="aydeo-platform-internal-service-token"
ACA_PLATFORM_SECRET="platform-internal-service-token"
KV_CHAT_TOKEN_SECRET="aydeo-chat-internal-service-token"
ACA_CHAT_TOKEN_SECRET="chat-internal-service-token"
KV_DATABASE_SECRET="trader-app-database-url"
ACA_DATABASE_SECRET="trader-app-database-url"
# Key Vault name equals the Container App secret name. Env var is the uppercase form.
TRADER_SECRET_ENV_NAMES=(
  T212_API_KEY
  T212_API_SECRET
  THEO_WHITELIST
  THEO_WHITELIST_PATH
  THEO_SYMBOL_OVERRIDES
)

AZ_SUBSCRIPTION_ARGS=()

# Unique tag per build (agent-007-theo-YYYYMMDD-HHMMSS-<gitsha>). Override with TAG=.
# The git sha is from this repository. The image repository stays trader-app,
# which is what Container App trader-app already pulls.
generate_demo_bfa_host_tag() {
  local sha
  sha="$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo nosha)"
  date -u "+agent-007-theo-%Y%m%d-%H%M%S-${sha}"
}

resolve_demo_bfa_host_tag() {
  if [[ -n "${TAG:-}" ]]; then
    printf '%s' "$TAG"
    return 0
  fi
  if [[ -f "$LAST_TAG_FILE" ]]; then
    cat "$LAST_TAG_FILE"
    return 0
  fi
  return 1
}

write_last_bfa_host_tag() {
  local tag="$1"
  printf '%s' "$tag" >"$LAST_TAG_FILE"
  echo "Recorded tag for trader-apply.sh: $LAST_TAG_FILE"
}

require_github_token_file() {
  if [[ ! -f "$GITHUB_TOKEN_FILE" ]]; then
    echo "error: GitHub token file not found: $GITHUB_TOKEN_FILE" >&2
    echo "See b-tree-aydeo_be/infra/scripts/github_token.example for setup." >&2
    exit 1
  fi
  if [[ ! -s "$GITHUB_TOKEN_FILE" ]]; then
    echo "error: GitHub token file is empty: $GITHUB_TOKEN_FILE" >&2
    echo "See b-tree-aydeo_be/infra/scripts/github_token.example for setup." >&2
    exit 1
  fi
}

warn_if_github_token_env_set() {
  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    echo "warning: GITHUB_TOKEN is set in the environment; demo scripts use the token file only." >&2
    echo "         See b-tree-aydeo_be/infra/scripts/github_token.example" >&2
  fi
}

require_az_login() {
  if ! az account show >/dev/null 2>&1; then
    echo "error: Azure CLI is not logged in. Run: az login" >&2
    exit 1
  fi
}

require_containerapp_extension() {
  if ! az extension show --name containerapp >/dev/null 2>&1; then
    echo "error: Azure Container Apps CLI extension required." >&2
    echo "       Install with: az extension add --name containerapp" >&2
    exit 1
  fi
}

# az account list is the lookup that discovers the subscription. Later az calls
# pass --subscription. az extension is local and does not take a subscription.
require_demo_subscription() {
  require_az_login
  local sub_id="${DEMO_AZURE_SUBSCRIPTION_ID:-}"
  if [[ -z "$sub_id" ]]; then
    sub_id="$(az account list --query "[?name=='Azure subscription 1'].id | [0]" -o tsv)"
  fi
  if [[ -z "$sub_id" || "$sub_id" == "None" ]]; then
    echo "error: could not resolve demo Azure subscription (set DEMO_AZURE_SUBSCRIPTION_ID)" >&2
    exit 1
  fi
  AZ_SUBSCRIPTION_ARGS=(--subscription "$sub_id")
  az account set "${AZ_SUBSCRIPTION_ARGS[@]}" >/dev/null
  echo "Using Azure subscription: $(az account show "${AZ_SUBSCRIPTION_ARGS[@]}" --query name -o tsv) ($sub_id)"
}

acr_login() {
  echo "Logging in to ACR: $ACR_NAME"
  az acr login "${AZ_SUBSCRIPTION_ARGS[@]}" --name "$ACR_NAME"
}

export_aca_default_domain() {
  if ! az extension show --name containerapp >/dev/null 2>&1; then
    echo "warning: Azure Container Apps CLI extension not installed; skipping ACA_DEFAULT_DOMAIN lookup." >&2
    echo "         Install with: az extension add --name containerapp" >&2
    return 0
  fi

  local domain
  if ! domain="$(az containerapp env show "${AZ_SUBSCRIPTION_ARGS[@]}" -g "$RG" -n "$CAE" --query properties.defaultDomain -o tsv 2>/dev/null)"; then
    echo "warning: could not read ACA default domain from $CAE in $RG; skipping." >&2
    return 0
  fi

  if [[ -z "$domain" ]]; then
    echo "warning: ACA default domain is empty; skipping export." >&2
    return 0
  fi

  export ACA_DEFAULT_DOMAIN="$domain"
}
