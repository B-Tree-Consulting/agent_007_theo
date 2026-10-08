"""Offline vendor integrity for frozen parity contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.conftest import subprocess_env_without_coverage
from tests.fixtures.case_policy_parity.hash_utils import compute_payload_sha256

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTRACT_ROOT = REPO_ROOT / "backend" / "contracts" / "bfa_case_policy_parity_v1"
EXPECTED_SHA = "5a376f502d35b2cdf3796c0d7f5b3683252ba6904e28265f702111e16d85e31f"


def test_vendored_payload_sha256_matches_manifest() -> None:
    assert compute_payload_sha256(CONTRACT_ROOT) == EXPECTED_SHA


def test_vendor_script_check_mode_passes_offline() -> None:
    script = REPO_ROOT / "scripts" / "vendor-bfa-case-policy-parity.sh"
    result = subprocess.run(
        [str(script), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=subprocess_env_without_coverage(),
    )
    assert result.returncode == 0, result.stderr or result.stdout
