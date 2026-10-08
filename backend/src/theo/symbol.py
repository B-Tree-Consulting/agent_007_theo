"""Map Trading 212 tickers to vendor symbols."""

from __future__ import annotations

import re

from src.theo.settings import parse_symbol_overrides

_EQ_SUFFIX = re.compile(r"_[A-Z0-9]+_EQ$")


def vendor_symbol(ticker: str, overrides: dict[str, str] | None = None) -> str:
    mapping = overrides if overrides is not None else parse_symbol_overrides()
    if ticker in mapping:
        return mapping[ticker]
    return _EQ_SUFFIX.sub("", ticker)
