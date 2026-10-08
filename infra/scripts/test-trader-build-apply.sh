#!/usr/bin/env bash
# Offline checks for trader-build-push.sh and trader-apply.sh. No live Azure calls.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

SUB_ID="00000000-0000-4000-8000-000000000001"
APP_ID_VALUE="2b3e51f8-4695-4764-91a8-bd374ad37d4a"
DOMAIN="demo.example.net"
IMAGE_TAG="trader-app-test"
IMAGE="acraydeodemo.azurecr.io/trader-app:${IMAGE_TAG}"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "missing [${needle}]"
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    fail "unexpected [${needle}]"
  fi
}

expect_fail() {
  set +e
  "$@" >/dev/null 2>&1
  local code=$?
  set -e
  if [[ "$code" -eq 0 ]]; then
    fail "expected non-zero exit: $*"
  fi
}

install_stubs() {
  local tmp="$1"
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
if [[ "$args" == *"account set"* || "$args" == *"account show"* ]]; then
  if [[ "$args" == *"--query name"* ]]; then
    printf '%s\n' "Azure subscription 1"
  fi
  exit 0
fi
if [[ "$args" == *"extension show"* ]]; then
  exit 0
fi
if [[ "$args" == *"acr login"* ]]; then
  exit 0
fi
if [[ "$args" == *"containerapp env show"* ]]; then
  printf '%s\n' "${DOMAIN:?}"
  exit 0
fi
if [[ "$args" == *"keyvault secret show"* ]]; then
  if [[ "$args" != *"--query id"* || "$args" == *"--query value"* ]]; then
    echo "stub refused secret query" >&2
    exit 2
  fi
  if [[ "${FAIL_PLATFORM_SECRET:-}" == "1" ]]; then
    exit 1
  fi
  printf '%s\n' "/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.KeyVault/vaults/kv-aydeo-demo-weu/secrets/aydeo-platform-internal-service-token"
  exit 0
fi
if [[ "$args" == *"keyvault show"* ]]; then
  printf '%s\n' "https://kv-aydeo-demo-weu.vault.azure.net/"
  exit 0
fi
if [[ "$args" == *"identity show"* ]]; then
  printf '%s\n' "/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-trader-app"
  exit 0
fi
if [[ "$args" == *"containerapp show"* ]]; then
  updated=0
  if [[ "$args" != *"containerapp update"* ]] && grep -q "containerapp update" "$AZ_LOG"; then
    updated=1
  fi
  if [[ "$args" == *"containers[0].env"* ]]; then
    UPDATED="$updated" python3 - <<'PY'
import json, os, sys
app_id = os.environ["APP_ID_VALUE"]
env = []
if os.environ.get("OMIT_APP_ID") != "1":
    env.append({"name": "APP_ID", "value": app_id})
if os.environ.get("OMIT_ISSUER") != "1":
    env.append({"name": "IDP_ISSUER", "value": "https://login.microsoftonline.com/tenant/v2.0"})
preset = os.environ.get("PRESET_AUDIENCE", "")
if preset:
    env.append({"name": "IDP_AUDIENCE", "value": preset})
env.append({"name": "BFA_SERVICE_SLUG", "value": "agent-007-theo"})
env.append({"name": "DATABASE_URL", "secretRef": "trader-app-database-url"})
json.dump(env, sys.stdout)
PY
    exit 0
  fi
  if [[ "$args" == *"containers[0]"* ]]; then
    python3 - <<'PY'
import json, os, sys
env = [
    {"name": "APP_ID", "value": os.environ["APP_ID_VALUE"]},
    {"name": "IDP_ISSUER", "value": "https://login.microsoftonline.com/tenant/v2.0"},
    {"name": "BFA_SERVICE_SLUG", "value": "agent-007-theo"},
    {"name": "DATABASE_URL", "secretRef": "trader-app-database-url"},
    {"name": "AYDEO_CHAT_INTERNAL_TOKEN", "secretRef": "chat-internal-service-token"},
    {"name": "AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN", "secretRef": "platform-internal-service-token"},
]
json.dump(
    {
        "name": "trader-app",
        "image": "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest",
        "command": ["uvicorn"],
        "env": env,
        "resources": {"cpu": 0.5, "memory": "1Gi"},
        "volumeMounts": [{"volumeName": "keep-me", "mountPath": "/mnt/keep"}],
    },
    sys.stdout,
)
PY
    exit 0
  fi
  if [[ "$args" == *"--query id"* ]]; then
    printf '%s\n' "/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.App/containerApps/trader-app"
    exit 0
  fi
fi
if [[ "$args" == *"containerapp secret set"* || "$args" == *"containerapp update"* || "$args" == "rest "* || "$args" == *" rest "* ]]; then
  exit 0
fi
echo "stub: unhandled az: $args" >&2
exit 3
EOF
  cat >"$tmp/bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${DOCKER_LOG:?}"
EOF
  chmod +x "$tmp/bin/az" "$tmp/bin/docker"
}

begin_case() {
  TMP="$(mktemp -d)"
  AZ_LOG="$TMP/az.log"
  DOCKER_LOG="$TMP/docker.log"
  export AZ_LOG DOCKER_LOG SUB_ID APP_ID_VALUE DOMAIN
  install_stubs "$TMP"
  export PATH="$TMP/bin:${PATH}"
  export GITHUB_TOKEN_FILE="$TMP/github_token"
  printf 'ghp_test\n' >"$GITHUB_TOKEN_FILE"
  export LAST_TAG_FILE="$TMP/last-tag"
  export REVISION_SUFFIX="apply120000"
  unset TAG FAIL_PLATFORM_SECRET OMIT_APP_ID OMIT_ISSUER PRESET_AUDIENCE DEMO_AZURE_SUBSCRIPTION_ID
}

check_dockerfile() {
  python3 - <<'PY'
import pathlib, sys
text = pathlib.Path("backend/Dockerfile").read_text()
if "ARG GH_TOKEN=" not in text:
    sys.exit("ARG GH_TOKEN= missing")
parts = text.split("\nRUN ")
mounted = [part for part in parts if part.startswith("--mount=type=secret,id=github_token,required=false")]
if len(mounted) != 3:
    sys.exit(f"expected 3 secret mounts, got {len(mounted)}")
for part in mounted:
    plus = part.find("set +x")
    git_config = part.find("git config")
    traced = part.find("set -eux")
    if plus < 0 or git_config < 0 or traced < 0:
        sys.exit("token RUN is missing set +x, git config, or set -eux")
    if not (plus < git_config < traced):
        sys.exit("git config is not between set +x and set -eux")
    after = part[traced:]
    for needle in ("${GH_TOKEN", "${token", "/run/secrets/github_token"):
        if needle in after:
            sys.exit(f"token expansion under set -x: {needle}")
print("dockerfile token trace ok")
PY
}

check_sources() {
  local file
  for file in infra/scripts/trader-build-lib.sh infra/scripts/trader-build-push.sh infra/scripts/trader-apply.sh; do
    if grep -E 'license-manager-bfa|bfa-container|aydeo-sample-bfa|(^|[^a-z-])aydeo-bfa([^a-z-]|$)' "$file"; then
      fail "$file names a container app this task must not touch"
    fi
  done
  if grep -q -- '--build-arg' infra/scripts/trader-build-push.sh; then
    fail "trader-build-push.sh passes a build-arg"
  fi
  if grep -q -- '--replace-env-vars' infra/scripts/trader-apply.sh; then
    fail "trader-apply.sh replaces the whole env"
  fi
  if grep -q '/health/ready' infra/scripts/trader-apply.sh; then
    fail "trader-apply.sh probes /health/ready"
  fi
  if ! grep -q 'apply$(date -u +%H%M%S)' infra/scripts/trader-apply.sh; then
    fail "revision suffix is not applyHHMMSS"
  fi
  if ! grep -qx 'infra/scripts/.trader-last-image-tag' .gitignore; then
    fail "gitignore is missing infra/scripts/.trader-last-image-tag"
  fi
  if grep -qx 'scripts/.demo-last-bfa-host-tag' .gitignore; then
    fail "gitignore still ignores scripts/.demo-last-bfa-host-tag"
  fi
}

check_tag_format() {
  local tag
  tag="$(
    # shellcheck source=trader-build-lib.sh
    source infra/scripts/trader-build-lib.sh
    generate_demo_bfa_host_tag
  )"
  if [[ ! "$tag" =~ ^agent-007-theo-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$ ]]; then
    fail "tag format: $tag"
  fi
}

require_subscription() {
  local line="$1"
  assert_contains "$line" "--subscription ${SUB_ID}"
}

test_build_push() {
  begin_case
  TAG="$IMAGE_TAG" infra/scripts/trader-build-push.sh >/dev/null
  local docker_log az_log
  docker_log="$(cat "$DOCKER_LOG")"
  az_log="$(cat "$AZ_LOG")"
  assert_contains "$docker_log" "--platform linux/amd64"
  assert_contains "$docker_log" "-f backend/Dockerfile"
  assert_contains "$docker_log" "--secret id=github_token,src=${GITHUB_TOKEN_FILE}"
  assert_contains "$docker_log" "-t ${IMAGE}"
  assert_contains "$docker_log" "push ${IMAGE}"
  assert_not_contains "$docker_log" "--build-arg"
  assert_not_contains "$docker_log" "GH_TOKEN"
  if [[ "$(cat "$LAST_TAG_FILE")" != "$IMAGE_TAG" ]]; then
    fail "tag file was not recorded"
  fi
  assert_contains "$az_log" "account list"
  require_subscription "$(grep "acr login" "$AZ_LOG")"
  require_subscription "$(grep "containerapp env show" "$AZ_LOG")"
}

test_missing_token_file() {
  begin_case
  export GITHUB_TOKEN_FILE="$TMP/missing-token"
  expect_fail infra/scripts/trader-build-push.sh
  if [[ -f "$DOCKER_LOG" ]]; then
    fail "docker ran without a token file"
  fi
}

test_empty_token_file() {
  begin_case
  : >"$GITHUB_TOKEN_FILE"
  expect_fail infra/scripts/trader-build-push.sh
  if [[ -f "$DOCKER_LOG" ]]; then
    fail "docker ran with an empty token file"
  fi
}

test_apply() {
  begin_case
  export DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID"
  infra/scripts/trader-apply.sh "$IMAGE_TAG" >/dev/null
  local az_log update_line secret_line rest_line
  az_log="$(cat "$AZ_LOG")"
  update_line="$(grep "containerapp update" "$AZ_LOG")"
  secret_line="$(grep "keyvault secret show" "$AZ_LOG")"
  rest_line="$(grep "rest --method patch" "$AZ_LOG")"
  assert_not_contains "$az_log" "license-manager-bfa"
  assert_not_contains "$az_log" "--replace-env-vars"
  assert_not_contains "$az_log" "--max-replicas"
  assert_not_contains "$secret_line" "--query value"
  assert_contains "$secret_line" "--query id"
  require_subscription "$update_line"
  require_subscription "$secret_line"
  require_subscription "$(grep "identity show" "$AZ_LOG")"
  require_subscription "$(grep "containerapp secret set" "$AZ_LOG")"
  assert_contains "$update_line" "-n trader-app"
  assert_contains "$update_line" "--image ${IMAGE}"
  assert_contains "$update_line" "--min-replicas 1"
  assert_contains "$update_line" "--revision-suffix apply120000"
  assert_contains "$update_line" "--set-env-vars"
  assert_contains "$update_line" "BFA_SERVICE_SLUG=agent-007-theo"
  assert_contains "$update_line" "AYDEO_MIGRATE_ON_START=1"
  assert_contains "$update_line" "AUTH_TEST_MODE=false"
  assert_contains "$update_line" "BFA_CONFIRM_TEST_MODE=false"
  assert_contains "$update_line" "AYDEO_CHAT_BASE_URL=https://aydeo-chat.${DOMAIN}"
  assert_contains "$update_line" "AYDEO_CMS_BASE_URL=https://aydeo-be.${DOMAIN}"
  assert_contains "$update_line" "AYDEO_UM_BASE_URL=https://aydeo-be.${DOMAIN}"
  assert_contains "$update_line" "DRIS_CAPABILITY_JWKS_URI=https://aydeo-be.${DOMAIN}/.well-known/bfa-capability-jwks.json"
  assert_contains "$update_line" "DRIS_CAPABILITY_ISSUER=aydeo-be.dris"
  assert_contains "$update_line" "AYDEO_PLATFORM_APPROVAL_PROOF_JWKS_URL=https://aydeo-be.${DOMAIN}/.well-known/approval-proof-jwks.json"
  assert_contains "$update_line" "AYDEO_PLATFORM_APPROVAL_PROOF_ISSUER=aydeo-be.approval-proof"
  assert_contains "$update_line" "IDP_AUDIENCE=api://${APP_ID_VALUE}"
  assert_contains "$update_line" "DATABASE_URL=secretref:trader-app-database-url"
  assert_contains "$update_line" "AYDEO_CHAT_INTERNAL_TOKEN=secretref:chat-internal-service-token"
  assert_contains "$update_line" "AYDEO_PLATFORM_INTERNAL_SERVICE_TOKEN=secretref:platform-internal-service-token"
  assert_contains "$update_line" "T212_API_KEY=secretref:trader-app-t212-api-key"
  assert_contains "$update_line" "T212_API_SECRET=secretref:trader-app-t212-api-secret"
  assert_contains "$update_line" "THEO_WHITELIST=secretref:trader-app-theo-whitelist"
  assert_contains "$update_line" "THEO_WHITELIST_PATH=secretref:trader-app-theo-whitelist-path"
  assert_contains "$update_line" "THEO_SYMBOL_OVERRIDES=secretref:trader-app-theo-symbol-overrides"
  local secret_set identity_ref
  secret_set="$(grep "containerapp secret set" "$AZ_LOG")"
  identity_ref="identityref:/subscriptions/${SUB_ID}/resourceGroups/rg-aydeo-demo-weu/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-trader-app"
  assert_contains "$secret_set" "trader-app-database-url=keyvaultref:https://kv-aydeo-demo-weu.vault.azure.net/secrets/trader-app-database-url,${identity_ref}"
  assert_contains "$secret_set" "chat-internal-service-token=keyvaultref:https://kv-aydeo-demo-weu.vault.azure.net/secrets/aydeo-chat-internal-service-token,${identity_ref}"
  assert_contains "$secret_set" "platform-internal-service-token=keyvaultref:https://kv-aydeo-demo-weu.vault.azure.net/secrets/aydeo-platform-internal-service-token,${identity_ref}"
  assert_contains "$secret_set" "trader-app-t212-api-key=keyvaultref:https://kv-aydeo-demo-weu.vault.azure.net/secrets/trader-app-t212-api-key,${identity_ref}"
  assert_contains "$(grep "identity show" "$AZ_LOG")" "-n id-trader-app"
  assert_contains "$rest_line" "/subscriptions/${SUB_ID}/"
  assert_contains "$rest_line" "api-version=2024-03-01"
  assert_contains "$rest_line" '"path": "/health"'
  assert_not_contains "$rest_line" "/health/ready"
  assert_contains "$rest_line" '"periodSeconds": 30'
  assert_contains "$rest_line" '"periodSeconds": 10'
  assert_contains "$rest_line" "keep-me"
  assert_contains "$rest_line" "uvicorn"
  assert_contains "$rest_line" "${IMAGE}"
  assert_not_contains "$rest_line" "containerapps-helloworld"
  local secret_n update_n rest_n
  secret_n="$(grep -n "containerapp secret set" "$AZ_LOG" | head -1 | cut -d: -f1)"
  update_n="$(grep -n "containerapp update" "$AZ_LOG" | head -1 | cut -d: -f1)"
  rest_n="$(grep -n "rest --method patch" "$AZ_LOG" | head -1 | cut -d: -f1)"
  if [[ "$secret_n" -ge "$update_n" || "$update_n" -ge "$rest_n" ]]; then
    fail "probe patch ran before the env update was submitted"
  fi
}

test_preset_audience() {
  begin_case
  export DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID"
  export PRESET_AUDIENCE="api://kept-audience"
  infra/scripts/trader-apply.sh "$IMAGE_TAG" >/dev/null
  local update_line
  update_line="$(grep "containerapp update" "$AZ_LOG")"
  assert_contains "$update_line" "IDP_AUDIENCE=api://kept-audience"
  assert_not_contains "$update_line" "IDP_AUDIENCE=api://${APP_ID_VALUE}"
}

test_missing_tag() {
  begin_case
  expect_fail infra/scripts/trader-apply.sh
  if [[ -f "$AZ_LOG" ]]; then
    fail "az ran without an image tag"
  fi
}

test_missing_app_id() {
  begin_case
  export DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID"
  export OMIT_APP_ID=1
  expect_fail infra/scripts/trader-apply.sh "$IMAGE_TAG"
  if grep -q "containerapp update" "$AZ_LOG"; then
    fail "update ran without APP_ID"
  fi
}

test_missing_issuer() {
  begin_case
  export DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID"
  export OMIT_ISSUER=1
  expect_fail infra/scripts/trader-apply.sh "$IMAGE_TAG"
  if grep -q "containerapp update" "$AZ_LOG"; then
    fail "update ran without IDP_ISSUER"
  fi
}

test_missing_platform_secret() {
  begin_case
  export DEMO_AZURE_SUBSCRIPTION_ID="$SUB_ID"
  export FAIL_PLATFORM_SECRET=1
  expect_fail infra/scripts/trader-apply.sh "$IMAGE_TAG"
  if grep -q "containerapp update" "$AZ_LOG"; then
    fail "update ran without the platform Key Vault secret"
  fi
  assert_contains "$(grep "keyvault secret show" "$AZ_LOG")" "--query id"
  assert_not_contains "$(grep "keyvault secret show" "$AZ_LOG")" "--query value"
}

check_dockerfile
check_sources
check_tag_format
test_build_push
test_missing_token_file
test_empty_token_file
test_apply
test_preset_audience
test_missing_tag
test_missing_app_id
test_missing_issuer
test_missing_platform_secret
echo "trader build/apply stubs ok"
