"""Locks for verify-bootstrap-modes.sh (no pytest subset hatch)."""

from __future__ import annotations

from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify-bootstrap-modes.sh"


def test_verify_script_exists() -> None:
    assert _SCRIPT.is_file()


def test_verify_script_runs_full_generated_pytest_sets() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "pytest tests/host tests/scripts tests/api" in text
    assert "Mode 1" in text or "mode 1" in text.lower()
    assert "strip-postgres" in text
    assert "de-gate-context" in text
    assert "config_gate_client" in text
    assert "documented subset" not in text.lower()
    assert "pytest tests/host/test_health.py" not in text
    assert "GH_TOKEN" in text or "GITHUB_TOKEN" in text
    assert "BFA_SERVICE_SLUG" in text
    assert "VERIFY_PYTEST_DB" in text
    assert "backend/vendor/agentstepkit" in text
    assert "backend/vendor/aydeo_audit_sdk" in text
