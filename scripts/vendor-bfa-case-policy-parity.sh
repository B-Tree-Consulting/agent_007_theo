#!/usr/bin/env bash
# Vendor bfa_case_policy_parity_v1 contract from b-tree-aydeo_be (sample#23).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT="${ROOT}/backend/contracts/bfa_case_policy_parity_v1"
TAG="bfa-case-policy-parity-v1.0.0"
EXPECTED_COMMIT="950126cd7f89e694ddeb23e3b8914351f0a62c5c"
EXPECTED_PAYLOAD_SHA256="5a376f502d35b2cdf3796c0d7f5b3683252ba6904e28265f702111e16d85e31f"
REPO_URL="https://github.com/B-Tree-Consulting/b-tree-aydeo_be.git"
SOURCE_SUBPATH="backend/contracts/bfa_case_policy_parity_v1"
BE_REPO="${BE_REPO:-${ROOT}/../aydeo-be}"
CHECK_ONLY=false

if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=true
fi

verify_payload() {
  python3 - <<'PY'
import json
import sys
from pathlib import Path

root = Path("backend/contracts/bfa_case_policy_parity_v1")
sys.path.insert(0, str(Path("backend/tests/fixtures/case_policy_parity").resolve()))
from hash_utils import compute_payload_sha256

expected = "5a376f502d35b2cdf3796c0d7f5b3683252ba6904e28265f702111e16d85e31f"
actual = compute_payload_sha256(root)
if actual != expected:
    print(f"payload_sha256 mismatch: {actual} != {expected}", file=sys.stderr)
    sys.exit(1)
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("payload_sha256") != expected:
    print("manifest payload_sha256 drift", file=sys.stderr)
    sys.exit(1)
print(actual)
PY
}

copy_from_path() {
  local src="${1}/${SOURCE_SUBPATH}"
  if [[ ! -f "${src}/manifest.json" ]]; then
    echo "vendor failed: ${src}/manifest.json missing" >&2
    exit 1
  fi
  rm -rf "${EXPORT}"
  mkdir -p "${EXPORT}/vectors" "${EXPORT}/fixtures/expected"
  cp "${src}/manifest.json" "${EXPORT}/"
  cp "${src}/semantic_schema.json" "${EXPORT}/"
  cp "${src}/vectors/"*.json "${EXPORT}/vectors/"
  cp "${src}/fixtures/expected/"*.json "${EXPORT}/fixtures/expected/"
}

fetch_contract() {
  if [[ -f "${BE_REPO}/${SOURCE_SUBPATH}/manifest.json" ]]; then
    copy_from_path "${BE_REPO}"
    return
  fi
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "${tmp}"' RETURN
  git clone --depth 1 --branch "${TAG}" "${REPO_URL}" "${tmp}/repo" >/dev/null 2>&1
  local resolved
  resolved="$(git -C "${tmp}/repo" rev-parse HEAD)"
  if [[ "${resolved}" != "${EXPECTED_COMMIT}" ]]; then
    echo "vendor failed: tag ${TAG} resolved to ${resolved}, expected ${EXPECTED_COMMIT}" >&2
    exit 1
  fi
  copy_from_path "${tmp}/repo"
}

cd "${ROOT}"

if [[ "${CHECK_ONLY}" == "true" ]]; then
  if [[ ! -d "${EXPORT}" ]]; then
    echo "vendor check failed: ${EXPORT} missing; run without --check first" >&2
    exit 1
  fi
  verify_payload
  echo "vendor check ok"
  exit 0
fi

fetch_contract
verify_payload
echo "vendored to ${EXPORT}"
