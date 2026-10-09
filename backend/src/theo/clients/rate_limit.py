"""Shared reading of optional rate-limit headers. No fixed quota."""

from __future__ import annotations

import time
from typing import Mapping

ACCOUNT_BUDGET_SECONDS = 30.0


def positive_header_wait(headers: Mapping[str, str], *, now: float | None = None) -> float | None:
    """Return a positive wait from the response, or None when the header is missing, zero, or already past.

    ``x-ratelimit-reset`` wins over ``Retry-After``. A zero or past value is not a wait.
    """
    current = time.time() if now is None else now
    reset = headers.get("x-ratelimit-reset")
    if reset is not None and str(reset).strip() != "":
        try:
            wait = float(reset) - current
        except ValueError:
            wait = None
        else:
            if wait > 0:
                return wait + 0.1
            return None
    retry_after = headers.get("Retry-After")
    if retry_after is not None and str(retry_after).strip() != "":
        try:
            value = float(retry_after)
        except ValueError:
            return None
        if value > 0:
            return value
        return None
    return None


def cooldown_seconds(headers: Mapping[str, str], *, now: float | None = None) -> float:
    """How long a stored reply should refuse another call after a 429. At least one second."""
    wait = positive_header_wait(headers, now=now)
    if wait is None:
        return 1.0
    return wait
