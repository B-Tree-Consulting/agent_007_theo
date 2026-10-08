#!/usr/bin/env bash
# Stage a local b-tree-aydeo-bfa checkout for Docker builds without GITHUB_TOKEN.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIT="${BFA_KIT_PATH:-$ROOT/../bfa_kit}"
VENDOR="$ROOT/backend/vendor/agentstepkit"

mkdir -p "$ROOT/backend/vendor"

if [[ -f "$KIT/pyproject.toml" ]]; then
  rm -rf "$VENDOR"
  cp -R "$KIT" "$VENDOR"
  echo "Prepared agentstepkit vendor from: $KIT"
else
  rm -rf "$VENDOR"
  echo "No local kit at $KIT — Docker build requires GITHUB_TOKEN" >&2
  exit 1
fi
