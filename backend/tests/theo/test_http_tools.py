"""HTTP catalog and invoke coverage for Theo tools."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.shared.test_utils import create_de_token
from src.theo.errors import BROKER_REJECTED, TOOL_VERSION, TheoError
from src.theo.schemas import OrderType, Side, TimeValidity
from src.theo.stores import intents as intent_store
from tests.host.cms_fixtures import default_open_case_id
from tests.host.http_helpers import assert_deferred, catalog_tool_by_name, invoke_tool, runtime_headers
from tests.theo.fakes import FakeT212


def _headers(de_id: str, capability_token: str) -> dict[str, str]:
    return runtime_headers(create_de_token(de_id), capability_token)


def test_catalog_exposes_theo_axes(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    tools = catalog_tool_by_name(client, _headers(de_id, sample_capability_token))
    low_names = (
        "place_market_equity_order",
        "place_limit_equity_order",
        "place_stop_equity_order",
        "place_stop_limit_equity_order",
    )
    high_names = (
        "place_large_market_equity_order",
        "place_large_limit_equity_order",
        "place_large_stop_equity_order",
        "place_large_stop_limit_equity_order",
    )
    assert "place_equity_order" not in tools
    assert "place_large_equity_order" not in tools
    for name in low_names:
        assert tools[name]["risk"] == "low"
        assert tools[name]["execute_context"] == "de_autonomous"
        assert tools[name]["tool_kind"] == "action_factory"
        assert tools[name]["case_tool_class"] == "case_effect"
        assert tools[name]["version"] == "1.0.0"
    for name in high_names:
        assert tools[name]["risk"] == "high"
        assert tools[name]["execute_context"] == "de_autonomous"
        assert tools[name]["version"] == "1.0.0"
    market_schema = tools["place_market_equity_order"].get("input_schema") or {}
    market_props = market_schema.get("properties") or {}
    assert "order_type" not in market_props
    assert "limit_price" not in market_props
    assert "comment" not in market_props
    assert "request_id" not in market_props
    limit_required = set((tools["place_limit_equity_order"].get("input_schema") or {}).get("required") or [])
    assert {"ticker", "side", "quantity", "limit_price", "time_validity"} <= limit_required
    for name in (*high_names, "cancel_equity_order"):
        schema = tools[name].get("input_schema") or {}
        assert "request_id" not in schema.get("properties", {})
        assert "order_type" not in schema.get("properties", {})
    catalog = client.get("/api/v1/bfa/catalog", headers=_headers(de_id, sample_capability_token))
    assert "WHAT THIS BFA IS" in catalog.json()["operating_context"]


def test_get_whitelist_and_account_summary(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    white = invoke_tool(
        client,
        headers,
        {"tool_name": "get_whitelist", "tool_version": TOOL_VERSION, "inputs": {}},
    )
    assert white["status"] == "succeeded"
    assert "AAPL_US_EQ" in white["outputs"]["tickers"]
    summary = invoke_tool(
        client,
        headers,
        {"tool_name": "get_account_summary", "tool_version": TOOL_VERSION, "inputs": {}},
    )
    assert summary["status"] == "succeeded", summary
    assert summary["outputs"]["cash_available_czk"] == "125000"


def test_place_small_market_order_executes(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
    recorded_case_comments: list[dict[str, str]],
) -> None:
    headers = _headers(de_id, sample_capability_token)
    body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "place_market_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.buy.value,
                "quantity": "1",
            },
        },
    )
    assert body["status"] == "succeeded", body
    assert fake_t212.placed
    assert recorded_case_comments
    assert "AAPL_US_EQ" in recorded_case_comments[0]["body"]


def test_incomplete_limit_is_field_level_422(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    response = client.post(
        "/api/v1/bfa/invoke",
        headers=headers,
        json={
            "tool_name": "place_limit_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.buy.value,
                "quantity": "1",
            },
            "case_id": default_open_case_id(),
        },
    )
    assert response.status_code == 422, response.text
    assert not fake_t212.placed
    locs = [item["loc"] for item in response.json()["detail"]]
    assert ["limit_price"] in locs
    assert ["time_validity"] in locs


def test_large_order_defers_without_broker_call(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
    recorded_case_comments: list[dict[str, str]],
) -> None:
    headers = _headers(de_id, sample_capability_token)
    body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "place_large_market_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.buy.value,
                "quantity": "30",
                "rationale": "Concentrated add to a core holding after the review.",
            },
        },
    )
    plan_token = assert_deferred(body, "needs-superior-defer")
    assert plan_token
    assert not fake_t212.placed
    assert recorded_case_comments == []


def test_stop_loss_sell_places_stop_order(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    fake_t212.holdings.append(
        {
            "ticker": "AAPL_US_EQ",
            "quantity": Decimal("2"),
            "average_price": Decimal("140"),
            "last_price": Decimal("150"),
            "ppl": Decimal("20"),
        }
    )
    headers = _headers(de_id, sample_capability_token)
    body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "place_stop_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.sell.value,
                "quantity": "1",
                "stop_price": "140",
                "time_validity": TimeValidity.GOOD_TILL_CANCEL.value,
            },
        },
    )
    assert body["status"] == "succeeded", body
    assert fake_t212.placed[0].order_type == OrderType.stop
    assert fake_t212.placed[0].side == Side.sell


def test_limit_buy_places_limit_order(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "place_limit_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.buy.value,
                "quantity": "1",
                "limit_price": "148",
                "time_validity": TimeValidity.DAY.value,
            },
        },
    )
    assert body["status"] == "succeeded", body
    assert fake_t212.placed[0].order_type == OrderType.limit
    assert fake_t212.placed[0].limit_price == Decimal("148")


def test_stop_limit_buy_places_stop_limit_order(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    body = invoke_tool(
        client,
        headers,
        {
            "tool_name": "place_stop_limit_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": Side.buy.value,
                "quantity": "1",
                "stop_price": "155",
                "limit_price": "156",
                "time_validity": TimeValidity.DAY.value,
            },
        },
    )
    assert body["status"] == "succeeded", body
    assert fake_t212.placed[0].order_type == OrderType.stop_limit
    assert fake_t212.placed[0].stop_price == Decimal("155")
    assert fake_t212.placed[0].limit_price == Decimal("156")


def _market_buy(quantity: str, **extra: str) -> dict:
    payload = {
        "ticker": "AAPL_US_EQ",
        "side": Side.buy.value,
        "quantity": quantity,
    }
    payload.update(extra)
    return payload


def _invoke_order(
    client,
    headers,
    tool_name: str,
    inputs: dict,
    *,
    correlation_id: str | None,
    phase: str = "execute",
    plan_token: str | None = None,
    approval_record_id: str | None = None,
):
    body = {
        "tool_name": tool_name,
        "tool_version": TOOL_VERSION,
        "invoke_phase": phase,
        "inputs": inputs,
        "case_id": default_open_case_id(),
    }
    if correlation_id is not None:
        body["correlation_id"] = correlation_id
    if plan_token is not None:
        body["plan_token"] = plan_token
    if approval_record_id is not None:
        body["approval_record_id"] = approval_record_id
    return invoke_tool(client, headers, body)


def test_zero_prices_are_field_level_422(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    response = client.post(
        "/api/v1/bfa/invoke",
        headers=headers,
        json={
            "tool_name": "place_stop_limit_equity_order",
            "tool_version": TOOL_VERSION,
            "inputs": {
                "ticker": "AAPL_US_EQ",
                "side": "buy",
                "quantity": "1",
                "limit_price": 0,
                "stop_price": 0,
                "time_validity": "DAY",
            },
            "case_id": default_open_case_id(),
        },
    )
    assert response.status_code == 422, response.text
    locs = [item["loc"] for item in response.json()["detail"]]
    assert ["limit_price"] in locs
    assert ["stop_price"] in locs
    assert all("request_id" not in loc for loc in locs)


def test_same_correlation_posts_once_and_stores_server_uuid(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    inputs = _market_buy("1")
    first = _invoke_order(client, headers, "place_market_equity_order", inputs, correlation_id="cid-replay")
    second = _invoke_order(client, headers, "place_market_equity_order", inputs, correlation_id="cid-replay")
    assert first["status"] == "succeeded", first
    assert second["status"] == "succeeded", second
    assert len(fake_t212.placed) == 1
    rows = [
        row
        for row in intent_store.list_for_case(default_open_case_id(), limit=50)
        if row.correlation_id == "cid-replay"
    ]
    assert len(rows) == 1
    assert rows[0].request_id is not None
    assert rows[0].tool_name == "place_market_equity_order"


def test_blank_correlation_posts_twice(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    inputs = _market_buy("1")
    first = _invoke_order(client, headers, "place_market_equity_order", inputs, correlation_id=None)
    second = _invoke_order(client, headers, "place_market_equity_order", inputs, correlation_id="   ")
    assert first["status"] == "succeeded", first
    assert second["status"] == "succeeded", second
    assert len(fake_t212.placed) == 2


def test_changed_awaiting_order_gets_a_new_uuid(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    rationale = "Concentrated add to a core holding after the review."
    _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        _market_buy("30", rationale=rationale),
        correlation_id="cid-correct",
    )
    original = [
        row
        for row in intent_store.list_for_case(default_open_case_id(), limit=50)
        if row.correlation_id == "cid-correct"
    ]
    assert len(original) == 1
    assert original[0].status == "awaiting_approval"
    second = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        _market_buy("35", rationale=rationale),
        correlation_id="cid-correct",
    )
    assert_deferred(second, "needs-superior-defer")
    assert not fake_t212.placed
    rows = intent_store.list_for_case(default_open_case_id(), limit=50)
    abandoned = [row for row in rows if row.status == "abandoned" and row.tool_name == "place_large_market_equity_order"]
    awaiting = [row for row in rows if row.correlation_id == "cid-correct"]
    assert any(row.request_id == original[0].request_id for row in abandoned)
    assert len(awaiting) == 1
    assert awaiting[0].request_id != original[0].request_id
    assert awaiting[0].status == "awaiting_approval"


def test_other_tool_does_not_abandon_a_proposal(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    rationale = "Concentrated add to a core holding after the review."
    _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        _market_buy("30", rationale=rationale),
        correlation_id="cid-cross",
    )
    placed = _invoke_order(
        client,
        headers,
        "place_market_equity_order",
        _market_buy("1"),
        correlation_id="cid-cross",
    )
    assert placed["status"] == "failed", placed
    ids = {item.get("id") for item in placed.get("assertions") or []}
    assert "large_proposal_pending" in ids
    assert not fake_t212.placed
    rows = intent_store.list_for_case(default_open_case_id(), limit=50)
    assert any(
        row.correlation_id == "cid-cross"
        and row.tool_name == "place_large_market_equity_order"
        and row.status == "awaiting_approval"
        for row in rows
    )
    assert not any(row.tool_name == "place_market_equity_order" and row.correlation_id == "cid-cross" for row in rows)


def test_executed_order_rejects_a_different_payload(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    _invoke_order(client, headers, "place_market_equity_order", _market_buy("1"), correlation_id="cid-exec")
    second = _invoke_order(client, headers, "place_market_equity_order", _market_buy("2"), correlation_id="cid-exec")
    assert second["status"] == "failed", second
    ids = {item.get("id") for item in second.get("assertions") or []}
    assert "request_id_reused" in ids
    assert len(fake_t212.placed) == 1
    row = next(row for row in intent_store.list_for_case(default_open_case_id(), limit=50) if row.correlation_id == "cid-exec")
    assert row.status == "executed"


def test_dispatching_order_rejects_a_different_payload(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    _invoke_order(client, headers, "place_market_equity_order", _market_buy("1"), correlation_id="cid-dispatch")
    row = next(row for row in intent_store.list_for_case(default_open_case_id(), limit=50) if row.correlation_id == "cid-dispatch")
    intent_store.mark_status(row.id, "dispatching")
    second = _invoke_order(client, headers, "place_market_equity_order", _market_buy("2"), correlation_id="cid-dispatch")
    assert second["status"] == "failed", second
    assert len(fake_t212.placed) == 1
    refreshed = next(item for item in intent_store.list_for_case(default_open_case_id(), limit=50) if item.id == row.id)
    assert refreshed.status == "dispatching"


def test_confirm_places_once_and_unknown_correlation_does_not(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    rationale = "Concentrated add to a core holding after the review."
    inputs = _market_buy("30", rationale=rationale)
    submitted = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-confirm",
    )
    plan_token = assert_deferred(submitted, "needs-superior-defer")
    confirmed = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-confirm",
        phase="confirm",
        plan_token=plan_token,
    )
    assert confirmed["status"] == "succeeded", confirmed
    assert len(fake_t212.placed) == 1
    again = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-confirm",
        phase="confirm",
        plan_token=plan_token,
    )
    assert again["status"] == "succeeded", again
    assert len(fake_t212.placed) == 1
    missed = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-unknown",
        phase="confirm",
        plan_token="missing-token",
    )
    assert missed["status"] == "failed", missed
    assert len(fake_t212.placed) == 1


def test_second_cancel_does_not_delete_again(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    headers = _headers(de_id, sample_capability_token)
    placed = _invoke_order(client, headers, "place_market_equity_order", _market_buy("1"), correlation_id="cid-cancel")
    assert placed["status"] == "succeeded", placed
    row = next(row for row in intent_store.list_for_case(default_open_case_id(), limit=50) if row.correlation_id == "cid-cancel")
    cancel_body = {
        "tool_name": "cancel_equity_order",
        "tool_version": TOOL_VERSION,
        "inputs": {"t212_order_id": row.t212_order_id},
        "case_id": default_open_case_id(),
    }
    first = invoke_tool(client, headers, cancel_body)
    second = invoke_tool(client, headers, cancel_body)
    assert first["status"] == "succeeded", first
    assert second["status"] == "succeeded", second
    assert fake_t212.cancelled == [row.t212_order_id]


def _allow_lane_b_confirm() -> None:
    from bfa.aydeo_host.blueprint import VerifiedInvokeContext

    from src.host.factory import get_host_blueprint

    class _Allow:
        async def verify_invoke(self, request, **kwargs):
            del request, kwargs
            return VerifiedInvokeContext()

    blueprint = get_host_blueprint()
    for policy in blueprint._pre_invoke_policies:
        if type(policy).__name__ == "LaneBConfirmGrantPolicy":
            policy._lane_b_confirm_verifier = _Allow()


def test_confirm_stores_approval_record_id(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
    recorded_case_comments: list[dict[str, str]],
) -> None:
    _allow_lane_b_confirm()
    headers = _headers(de_id, sample_capability_token)
    rationale = "Concentrated add to a core holding after the review."
    inputs = _market_buy("30", rationale=rationale)
    submitted = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-approval",
    )
    plan_token = assert_deferred(submitted, "needs-superior-defer")
    confirmed = _invoke_order(
        client,
        headers,
        "place_large_market_equity_order",
        inputs,
        correlation_id="cid-approval",
        phase="confirm",
        plan_token=plan_token,
        approval_record_id="apr-record-1",
    )
    assert confirmed["status"] == "succeeded", confirmed
    assert len(fake_t212.placed) == 1
    assert any("apr-record-1" in comment["body"] for comment in recorded_case_comments)
    row = next(
        row
        for row in intent_store.list_for_case(default_open_case_id(), limit=50)
        if row.correlation_id == "cid-approval"
    )
    assert row.approval_record_id == "apr-record-1"


def test_missing_fx_fails_account_summary_invoke(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _down():
        raise RuntimeError("cnb down")

    monkeypatch.setattr("src.theo.snapshot.load_usd_fixing", _down)
    body = invoke_tool(
        client,
        _headers(de_id, sample_capability_token),
        {"tool_name": "get_account_summary", "tool_version": TOOL_VERSION, "inputs": {}},
    )
    assert body["status"] == "failed", body
    ids = {item.get("id") for item in body.get("assertions") or []}
    assert "fx_unavailable" in ids


def test_off_whitelist_research_fails_invoke(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
) -> None:
    body = invoke_tool(
        client,
        _headers(de_id, sample_capability_token),
        {
            "tool_name": "get_title_research",
            "tool_version": TOOL_VERSION,
            "inputs": {"ticker": "ZZ_US_EQ"},
        },
    )
    assert body["status"] == "failed", body
    ids = {item.get("id") for item in body.get("assertions") or []}
    assert "whitelist_rejected" in ids


def test_correlation_unique_race_replays_or_conflicts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import IntegrityError

    from src.theo.schemas import OrderInput
    from src.theo.stores import intents as intent_store

    del client
    case_id = default_open_case_id()
    inputs = OrderInput(
        ticker="AAPL_US_EQ",
        side=Side.buy,
        quantity=Decimal("1"),
        order_type=OrderType.market,
    )
    common = dict(
        case_id=case_id,
        inputs=inputs,
        status="dispatching",
        tool_name="place_market_equity_order",
        notional_price=Decimal("150"),
        notional_czk=Decimal("3000"),
        quote_source="yahoo",
        fx_czk_per_unit=Decimal("23"),
        fx_date=None,
        fx_source="CNB",
    )
    first = intent_store.upsert_intent(**common, correlation_id="cid-race")

    def _boom(*_args, **_kwargs):
        raise IntegrityError("duplicate key", {}, Exception("duplicate key"))

    monkeypatch.setattr(intent_store, "_apply_write", _boom)
    replay = intent_store.upsert_intent(**common, correlation_id="cid-race")
    assert replay.conflict is False
    assert replay.row.id == first.row.id

    changed = inputs.model_copy(update={"quantity": Decimal("2")})
    conflict = intent_store.upsert_intent(**{**common, "inputs": changed}, correlation_id="cid-race")
    assert conflict.conflict is True
    assert conflict.row.id == first.row.id

    with pytest.raises(IntegrityError):
        intent_store.upsert_intent(**common, correlation_id=None)
    with pytest.raises(IntegrityError):
        intent_store.upsert_intent(**common, correlation_id="cid-race-missing")


def test_review_portfolio_reads_account_cash_once(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
) -> None:
    calls = 0
    original = fake_t212.account_cash

    async def counted():
        nonlocal calls
        calls += 1
        return await original()

    fake_t212.account_cash = counted
    body = invoke_tool(
        client,
        _headers(de_id, sample_capability_token),
        {
            "tool_name": "review_portfolio",
            "tool_version": TOOL_VERSION,
            "inputs": {"include_research": False},
        },
    )
    assert body["status"] == "succeeded", body
    assert calls == 1


def test_review_portfolio_broker_rate_limit_fails_invoke(
    client: TestClient,
    de_id: str,
    sample_capability_token: str,
    fake_t212: FakeT212,
    recorded_case_comments: list[dict[str, str]],
) -> None:
    async def limited():
        raise TheoError(BROKER_REJECTED, "Too Many Requests")

    fake_t212.account_cash = limited
    body = invoke_tool(
        client,
        _headers(de_id, sample_capability_token),
        {
            "tool_name": "review_portfolio",
            "tool_version": TOOL_VERSION,
            "inputs": {"include_research": False},
        },
    )
    assert body["status"] == "failed", body
    ids = {item.get("id") for item in body.get("assertions") or []}
    assert "broker_rejected" in ids
    assert recorded_case_comments == []
