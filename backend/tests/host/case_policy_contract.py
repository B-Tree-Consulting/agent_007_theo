"""Contract loaders for sample case/hold parity harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "case_policy_parity"
CONTRACTS_ROOT = Path(__file__).resolve().parent.parent.parent / "contracts" / "bfa_case_policy_parity_v1"

SHARED_ENGINE_VECTOR_IDS = [
    "scope_headless_open_query_allow",
    "scope_interactive_missing_case_thread_not_bound",
    "scope_headless_missing_case_thread_not_bound",
    "scope_headless_closed_case_not_active",
    "hold_headless_held_case_on_hold",
    "scope_headless_hold_no_capture_recovery",
    "ordering_scope_deny_no_mutation",
    "hold_headless_cms_unavailable",
    "grant_lane_a_turn_missing",
    "grant_lane_a_turn_invalid",
    "grant_lane_a_tool_mismatch",
    "grant_lane_a_turn_replay",
]


def load_role_mappings() -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / "role_mappings.json").read_text(encoding="utf-8"))


def mapping_for_role_id(role_id: str) -> dict[str, Any]:
    for entry in load_role_mappings()["mappings"]:
        if entry["role_id"] == role_id:
            return entry
    raise KeyError(f"unknown role_id: {role_id}")


def load_vector(vector_id: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_ROOT / "vectors" / f"{vector_id}.json").read_text(encoding="utf-8"))


def load_expected(vector_id: str) -> dict[str, Any]:
    return json.loads(
        (CONTRACTS_ROOT / "fixtures" / "expected" / f"{vector_id}.json").read_text(encoding="utf-8")
    )
