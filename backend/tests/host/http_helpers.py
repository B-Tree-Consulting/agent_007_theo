"""Host-neutral HTTP helpers for BFA catalog/invoke tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.shared.bfa_capability_contract import CAPABILITY_HEADER


def runtime_headers(de_token: str, capability_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {de_token}",
        CAPABILITY_HEADER: capability_token,
    }


def invoke_tool(
    client: TestClient,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    expected_status: int = 200,
    case_id: str | None = None,
) -> dict[str, Any]:
    from tests.host.cms_fixtures import default_open_case_id

    body = dict(payload)
    if case_id is not None:
        body["case_id"] = case_id
    elif "case_id" not in body:
        body["case_id"] = default_open_case_id()
    response = client.post("/api/v1/bfa/invoke", headers=headers, json=body)
    assert response.status_code == expected_status, response.text
    return response.json()


def assert_deferred(body: dict[str, Any], assertion_id: str) -> str:
    assert body["status"] == "failed"
    plan_token = body.get("outputs", {}).get("plan_token")
    assert plan_token, "expected plan_token in deferral outputs"
    assertion_ids = {item.get("id") for item in body.get("assertions") or []}
    assert assertion_id in assertion_ids, f"expected assertion {assertion_id!r}, got {assertion_ids}"
    return str(plan_token)


def catalog_tool_by_name(client: TestClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    response = client.get("/api/v1/bfa/catalog", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    return {str(tool["name"]): tool for tool in body.get("tools") or []}
