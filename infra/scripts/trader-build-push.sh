#!/usr/bin/env bash
# Build this repository's backend/Dockerfile and push linux/amd64 to demo ACR.
# The image is published for the existing Container App trader-app.
# This does not create a Container App and does not update any other app.
#
# Usage:
#   ./infra/scripts/trader-build-push.sh
#   TAG=agent-007-theo-manual ./infra/scripts/trader-build-push.sh
#
# Image: acraydeodemo.azurecr.io/trader-app:<tag>
# Tag default: agent-007-theo-YYYYMMDD-HHMMSS-<gitsha> (UTC, this repo's HEAD).
# The GitHub token is read from $HOME/.config/aydeo-demo/github_token and passed
# only as a BuildKit secret. It is not a build-arg, and it is not printed.
# Secret values stay in that file or in Key Vault.
#
# Then roll the Container App:
#   ./infra/scripts/trader-apply.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=trader-build-lib.sh
source "$SCRIPT_DIR/trader-build-lib.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,18p' "$0"
  exit 0
fi

warn_if_github_token_env_set
require_github_token_file
require_demo_subscription
acr_login
export_aca_default_domain

TAG="${TAG:-$(generate_demo_bfa_host_tag)}"

cd "$REPO_ROOT"

IMAGE="$ACR/$IMAGE_REPOSITORY:$TAG"

echo "Building $IMAGE (platform linux/amd64 for ACA)..."
DOCKER_BUILDKIT=1 docker build \
  --platform linux/amd64 \
  -f backend/Dockerfile \
  --secret "id=github_token,src=$GITHUB_TOKEN_FILE" \
  -t "$IMAGE" \
  .

echo "Pushing $IMAGE..."
docker push "$IMAGE"

write_last_bfa_host_tag "$TAG"

echo ""
echo "Done. Image pushed:"
echo "  $IMAGE"
echo ""
echo "Apply to Container App $APP_NAME:"
echo "  ./infra/scripts/trader-apply.sh"
echo "  # or: ./infra/scripts/trader-apply.sh $TAG"
if [[ -n "${ACA_DEFAULT_DOMAIN:-}" ]]; then
  echo ""
  echo "ACA default domain: $ACA_DEFAULT_DOMAIN"
  echo "Health after apply:"
  echo "  curl -sS \"https://${APP_NAME}.${ACA_DEFAULT_DOMAIN}/health\""
fi
echo ""
echo "Verify tag:"
echo "  az acr repository show-tags --subscription \"\${DEMO_AZURE_SUBSCRIPTION_ID}\" -n $ACR_NAME --repository $IMAGE_REPOSITORY --orderby time_desc --top 3 -o table"
