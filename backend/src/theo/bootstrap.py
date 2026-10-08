"""Idempotent registration of Theo tools onto a host class."""

from __future__ import annotations

import inspect
from typing import Any

from bfa import ExecuteContext, ScopedResolver

from src.theo.actions import PLACE_ACTION_SPECS, PLACE_ACTIONS, CancelEquityOrder, ReviewPortfolio
from src.theo.errors import TOOL_VERSION
from src.theo.queries import register as register_queries

_FLAG = "_theo_tools_registered"

PLACE_DESCRIPTIONS = {
    "place_market_equity_order": (
        "Place a market equity order on Trading 212 now at whatever the market gives, for a whitelisted "
        "ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, and share "
        "count. Do not use this for a priced order. If the user has not said market, ask; do not default "
        "to it. Convert crowns to shares with get_account_summary. The order is sent immediately and "
        "recorded as a case comment. It refuses an order worth more than the threshold (use "
        "place_large_market_equity_order), a buy off the whitelist or short of cash, a sell larger than "
        "the position, and a missing ticker, side, or quantity: ask rather than guessing."
    ),
    "place_limit_equity_order": (
        "Place a limit equity order on Trading 212 that trades only at limit_price or better, for a "
        "whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, "
        "share count, limit price per share, and DAY or GOOD_TILL_CANCEL. Ask for any of those; do not "
        "invent a price. The order is sent immediately and recorded as a case comment. Over the threshold "
        "use place_large_limit_equity_order. It refuses a buy off the whitelist or short of cash, and a "
        "sell larger than the position."
    ),
    "place_stop_equity_order": (
        "Place a stop equity order on Trading 212 that becomes a market order once stop_price is reached, "
        "for a whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or "
        "sell, share count, trigger price, and DAY or GOOD_TILL_CANCEL. A sell stop-loss trigger must sit "
        "below the last price; a buy stop above it. Ask rather than inventing. The order is sent immediately. "
        "Over the threshold use place_large_stop_equity_order."
    ),
    "place_stop_limit_equity_order": (
        "Place a stop-limit equity order on Trading 212 that becomes a limit order at limit_price once "
        "stop_price is reached, for a whitelisted ticker at a CZK value at or under the approval threshold. "
        "Need ticker, buy or sell, share count, both prices, and DAY or GOOD_TILL_CANCEL. Ask rather than "
        "inventing. The order is sent immediately. Over the threshold use place_large_stop_limit_equity_order."
    ),
    "place_large_market_equity_order": (
        "Propose a market equity order worth more than the approval threshold and send it to your manager "
        "for approval. Need ticker, buy or sell, share count, and a rationale of at least 20 characters. "
        "Nothing reaches the broker when you call this. Tell the user their order is waiting for the manager, "
        "not that it is done. Do not watch for the approval or call anything again to complete it. At or "
        "under the threshold use place_market_equity_order instead."
    ),
    "place_large_limit_equity_order": (
        "Propose a limit equity order worth more than the approval threshold and send it to your manager "
        "for approval. Need ticker, buy or sell, share count, limit price, DAY or GOOD_TILL_CANCEL, and a "
        "rationale of at least 20 characters. Nothing reaches the broker. Tell the user it is waiting for "
        "the manager. At or under the threshold use place_limit_equity_order instead."
    ),
    "place_large_stop_equity_order": (
        "Propose a stop equity order worth more than the approval threshold and send it to your manager "
        "for approval. Need ticker, buy or sell, share count, trigger price, DAY or GOOD_TILL_CANCEL, and a "
        "rationale of at least 20 characters. Nothing reaches the broker. Tell the user it is waiting for "
        "the manager. At or under the threshold use place_stop_equity_order instead."
    ),
    "place_large_stop_limit_equity_order": (
        "Propose a stop-limit equity order worth more than the approval threshold and send it to your "
        "manager for approval. Need ticker, buy or sell, share count, stop price, limit price, DAY or "
        "GOOD_TILL_CANCEL, and a rationale of at least 20 characters. Nothing reaches the broker. Tell the "
        "user it is waiting for the manager. At or under the threshold use place_stop_limit_equity_order instead."
    ),
}
CANCEL_DESC = (
    "Cancel one order that is still working at the broker and was placed through this BFA, and "
    "record the cancellation as a case comment. Use this to withdraw an order the user changed "
    "their mind about or that is no longer wanted. It cannot cancel an order placed in the "
    "Trading 212 app, cannot touch an order that already filled, and cancelling does not re-place "
    "anything."
)
REVIEW_DESC = (
    "Produce one combined review pack for the account: holdings with current marks, working orders, "
    "open proposals, the whitelist, the CZK rate, and research per name, then record the review as "
    "a case comment. Use this at the start of a portfolio review instead of calling the individual "
    "read tools one by one. It gathers facts and leaves an audit trail; it does not analyse, "
    "recommend, or place anything."
)


def _factory(action_cls: type) -> Any:
    def factory(sres: ScopedResolver):
        return action_cls(comments=sres.get("case_comments"))

    return factory


def _action_kwargs(name: str, description: str, action_cls: type, risk: str, case_tool_class: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "description": description,
        "name": name,
        "action_cls": action_cls,
        "factory": _factory(action_cls),
        "version": TOOL_VERSION,
        "risk": risk,
        "execute_context": ExecuteContext.DE_AUTONOMOUS,
    }
    return kwargs


def register_theo_tools(host_cls: type) -> bool:
    if getattr(host_cls, _FLAG, False):
        return False
    register_queries(host_cls)
    actions: list[tuple[str, str, type, str, str]] = [
        (name, PLACE_DESCRIPTIONS[name], PLACE_ACTIONS[name], gate, "case_effect")
        for name, _model, gate in PLACE_ACTION_SPECS
    ]
    actions.extend(
        [
            ("cancel_equity_order", CANCEL_DESC, CancelEquityOrder, "low", "case_effect"),
            ("review_portfolio", REVIEW_DESC, ReviewPortfolio, "low", "case_support"),
        ]
    )
    deco = host_cls.action_factory
    for name, description, action_cls, risk, case_class in actions:
        kwargs = _action_kwargs(name, description, action_cls, risk, case_class)
        if "case_tool_class" in inspect.signature(deco).parameters:
            kwargs["case_tool_class"] = case_class
        marker_name = f"_marker_{name}"

        def _marker(self: object) -> None:
            return None

        _marker.__name__ = marker_name
        deco(**kwargs)(_marker)
        setattr(host_cls, marker_name, _marker)
    setattr(host_cls, _FLAG, True)
    return True
