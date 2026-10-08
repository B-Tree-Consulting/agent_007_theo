"""Confirm posts one DE-authored case comment; submit does not."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from aydeo_cms_client.errors import CmsForbiddenError
from fastapi.testclient import TestClient

from src.config import get_settings
from src.samples.domain.actions._steps import render_domain_order_comment
from src.samples.domain.models.order import Payer
from src.samples.domain.schemas.order import (
    OrderdomainForEventInput,
    OrderdomainForMeInput,
    OrderdomainForTeamInput,
)
from src.shared.test_utils import create_de_token
from tests.host.cms_fixtures import default_open_case_id
from tests.host.flow_helpers import (
    assert_confirm_succeeded,
    assert_deferred,
    confirm_order,
    extract_order_ref,
    fetch_menu_ref,
    invoke_tool,
    runtime_headers,
)

domain_ACTION_VERSION = "1.0.0"


def _headers(de_id: str, capability_token: str) -> tuple[dict[str, str], str]:
    token = create_de_token(de_id)
    return runtime_headers(token, capability_token), token


@pytest.mark.parametrize(
    ("tool_name", "quantity", "payer", "deferral", "with_event"),
    [
        ("domain_action_medium", 1, Payer.REQUESTOR, "needs-confirmation", False),
        ("domain_action_high_team", 2, Payer.COMPANY, "needs-superior-defer", False),
        ("domain_action_high_event", 2, Payer.COMPANY, "needs-superior-defer", True),
    ],
)
def test_confirm_posts_one_case_comment(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    recorded_case_comments: list[dict[str, str]],
    tool_name: str,
    quantity: int,
    payer: Payer,
    deferral: str,
    with_event: bool,
) -> None:
    headers, de_token = _headers(de_id, sample_capability_token)
    menu_ref = fetch_menu_ref(client, headers)
    event_date = (date.today() + timedelta(days=7)).isoformat() if with_event else None
    inputs: dict[str, object] = {"menu_ref": menu_ref, "quantity": quantity}
    if event_date is not None:
        inputs["event_date"] = event_date

    submit_body = invoke_tool(
        client,
        headers,
        {
            "tool_name": tool_name,
            "tool_version": domain_ACTION_VERSION,
            "inputs": inputs,
            "correlation_id": f"comment-submit-{tool_name}",
        },
    )
    assert recorded_case_comments == []
    plan_token = assert_deferred(submit_body, deferral)

    confirm_body = confirm_order(
        client,
        headers,
        tool_name=tool_name,
        menu_ref=menu_ref,
        quantity=quantity,
        plan_token=plan_token,
        extra_inputs={"event_date": event_date} if event_date else None,
        correlation_id=f"comment-confirm-{tool_name}",
    )
    assert_confirm_succeeded(confirm_body)
    order_ref = extract_order_ref(confirm_body)
    assert len(recorded_case_comments) == 1
    posted = recorded_case_comments[0]
    assert posted["case_id"] == default_open_case_id()
    assert posted["bearer"] == de_token
    assert posted["bearer"] != (get_settings().aydeo_platform_internal_service_token or "")
    assert posted["body"] == render_domain_order_comment(
        order_ref=order_ref,
        menu_ref=menu_ref,
        quantity=quantity,
        payer=payer,
        event_date=date.fromisoformat(event_date) if event_date else None,
    )


def test_order_inputs_have_no_comment_field() -> None:
    for model in (OrderdomainForMeInput, OrderdomainForTeamInput, OrderdomainForEventInput):
        assert "comment" not in model.model_fields
        assert "body" not in model.model_fields


def test_cms_failure_fails_confirm(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _deny(self: object, *, case_id: str, body: str) -> None:
        del self, case_id, body
        raise CmsForbiddenError("AyDEO CMS forbidden", status_code=403)

    monkeypatch.setattr("src.host.case_comment_client.CaseCommentClient.add_comment", _deny)
    headers, _token = _headers(de_id, sample_capability_token)
    menu_ref = fetch_menu_ref(client, headers)
    submit_body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "domain_action_medium",
            "tool_version": domain_ACTION_VERSION,
            "inputs": {"menu_ref": menu_ref, "quantity": 1},
            "correlation_id": "comment-deny-submit",
        },
    )
    plan_token = assert_deferred(submit_body, "needs-confirmation")
    response_body = confirm_order(
        client,
        headers,
        tool_name="domain_action_medium",
        menu_ref=menu_ref,
        quantity=1,
        plan_token=plan_token,
        correlation_id="comment-deny-confirm",
    )
    assert response_body["status"] == "failed"
