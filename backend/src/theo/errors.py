"""Stable domain error codes for Theo tools."""

from __future__ import annotations


class TheoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


VALIDATION_ERROR = "validation_error"
REQUEST_ID_REUSED = "request_id_reused"
APPROVAL_REQUIRED = "approval_required"
BELOW_APPROVAL_THRESHOLD = "below_approval_threshold"
WHITELIST_REJECTED = "whitelist_rejected"
WHITELIST_EMPTY = "whitelist_empty"
POSITION_CAP = "position_cap"
INSUFFICIENT_CASH = "insufficient_cash"
SHORT_REJECTED = "short_rejected"
QUOTE_UNAVAILABLE = "quote_unavailable"
FX_UNAVAILABLE = "fx_unavailable"
STOP_PRICE_INVALID = "stop_price_invalid"
DUPLICATE_PENDING_TICKER = "duplicate_pending_ticker"
LARGE_PROPOSAL_PENDING = "large_proposal_pending"
RESEARCH_NOT_PERMITTED = "research_not_permitted"
INSTRUMENT_NOT_FOUND = "instrument_not_found"
BROKER_REJECTED = "broker_rejected"
BROKER_AMBIGUOUS = "broker_ambiguous"
ORDER_NOT_TRACKED = "order_not_tracked"
COMPENSATION_PARTIAL = "compensation_partial"

TOOL_VERSION = "1.0.0"
