#!/usr/bin/env bash
# Stage a local b-tree-aydeo-audit SDK checkout for Docker builds without GITHUB_TOKEN.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_REPO="${AUDIT_SDK_REPO:-$ROOT/../b-tree-aydeo-audit}"
SDK="${AUDIT_SDK_PATH:-$AUDIT_REPO/packages/aydeo_audit_sdk}"
VENDOR="$ROOT/backend/vendor/aydeo_audit_sdk"

mkdir -p "$ROOT/backend/vendor"

if [[ -f "$SDK/pyproject.toml" ]]; then
  rm -rf "$VENDOR"
  cp -R "$SDK" "$VENDOR"
  echo "Prepared aydeo-audit-sdk vendor from: $SDK"
else
  rm -rf "$VENDOR"
  echo "No audit SDK at $SDK — Docker build requires GITHUB_TOKEN or vendor checkout" >&2
  exit 1
fi
