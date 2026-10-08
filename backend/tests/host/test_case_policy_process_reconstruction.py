"""Process reconstruction: fresh subprocess still enforces case/hold on host assembly."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.conftest import subprocess_env_without_coverage

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def test_fresh_subprocess_runs_case_policy_deny_vector() -> None:
    script = """
import asyncio
from tests.host.case_policy_contract import load_vector, load_expected
from tests.host.case_policy_harness import run_shared_engine_vector
from tests.host.case_policy_assertions import assert_semantic_expectation

async def main():
    vector_id = "scope_headless_missing_case_thread_not_bound"
    vector = load_vector(vector_id)
    expected = load_expected(vector_id)
    observed = await run_shared_engine_vector(vector)
    assert_semantic_expectation(observed, expected)

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=subprocess_env_without_coverage(),
    )
    assert result.returncode == 0, result.stderr or result.stdout
