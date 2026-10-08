"""Smoke tests for pinned BFA kit (agentstepkit) dependency."""

from importlib.metadata import version

from bfa.aydeo_host import AydeoHostBlueprint


def test_agentstepkit_pinned_at_v0_2_27() -> None:
    assert version("agentstepkit") == "0.2.27"


def test_aydeo_audit_sdk_pinned_at_0_1_2() -> None:
    assert version("aydeo-audit-sdk") == "0.1.2"


def test_aydeo_host_blueprint_importable() -> None:
    assert AydeoHostBlueprint.__name__ == "AydeoHostBlueprint"
