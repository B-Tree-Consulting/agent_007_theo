"""Assert observed HTTP outcomes against frozen semantic expectations."""

from __future__ import annotations

from typing import Any


def _recovery(body: dict[str, Any]) -> dict[str, Any]:
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    recovery = details.get("recovery") if isinstance(details.get("recovery"), dict) else {}
    return recovery


def assert_semantic_expectation(observed: dict[str, Any], expected: dict[str, Any]) -> None:
    assert observed["http_status"] == expected["http_status"], (
        f"status {observed['http_status']} != {expected['http_status']}: {observed.get('body')}"
    )

    body = observed.get("body") or {}
    shape = expected.get("response_shape")

    if shape == "policy_nested":
        err = body.get("error")
        assert isinstance(err, dict), body
        code = expected.get("error", {}).get("code") or expected.get("error.code")
        if code:
            assert err.get("code") == code, body
        msg = expected.get("error", {}).get("message")
        if msg:
            assert msg in (err.get("message") or ""), body
        recovery = _recovery(body)
        forbidden = expected.get("recovery", {}).get("forbidden_action")
        if forbidden:
            assert recovery.get("action") != forbidden, body
        elif expected.get("recovery", {}).get("absent"):
            assert recovery.get("action") is None
            assert recovery.get("hint") is None
        else:
            action = expected.get("recovery", {}).get("action")
            if action:
                assert recovery.get("action") == action, body
    elif shape == "plain_detail":
        detail = body.get("detail")
        assert detail is not None, body
        msg = expected.get("error", {}).get("message")
        if msg:
            assert msg in str(detail), body
    elif shape == "action_assertion":
        assertion_ids = [a.get("id") for a in body.get("assertions") or []]
        for aid in expected.get("assertion_ids") or []:
            assert aid in assertion_ids, body
        if expected.get("decision") == "deny":
            assert body.get("status") == "failed", body
    elif shape == "invoke_success_body":
        if expected.get("decision") == "allow":
            assert body.get("status") in ("succeeded", "failed"), body

    side = expected.get("side_effects") or {}
    if "case_mutated" in side:
        if "tool_mutated" in observed:
            assert observed["tool_mutated"] == side["case_mutated"], observed
        elif observed.get("case_id"):
            mutated = observed["history_after"] > observed["history_before"]
            assert mutated == side["case_mutated"], observed
    if "grant_verify_count" in side:
        assert observed.get("grant_verify_count") == side["grant_verify_count"], observed
