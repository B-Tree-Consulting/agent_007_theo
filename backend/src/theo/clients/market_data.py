"""Free-tier quote and research cascade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from src.config import get_settings
from src.theo.clients.rate_limit import cooldown_seconds
from src.theo.schemas import SourcedValue, TitleResearchOutput
from src.theo.stores import replies as reply_store
from src.theo.symbol import vendor_symbol

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
STOOQ_CSV = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
TIINGO_EOD = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"


@dataclass(frozen=True)
class _Hit:
    source: str
    data: Any
    fetched_at: datetime | None
    stored: bool

    def block(self) -> SourcedValue:
        return SourcedValue(
            source=self.source,
            data=self.data,
            fetched_at=self.fetched_at,
            stored=self.stored,
        )


class MarketDataClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(timeout=15.0, transport=transport, headers={"User-Agent": "theo-bfa/1.0"})

    async def last_price(
        self,
        ticker: str,
        *,
        position_mark: Decimal | None = None,
    ) -> tuple[Decimal, str] | None:
        found = await self._priced(ticker, position_mark=position_mark)
        if found is None:
            return None
        return found[0], found[1].source

    async def _priced(
        self,
        ticker: str,
        *,
        position_mark: Decimal | None = None,
    ) -> tuple[Decimal, _Hit] | None:
        settings = get_settings()
        symbol = vendor_symbol(ticker)
        if settings.theo_finnhub_api_key:
            quoted = await self._finnhub_quote(symbol, settings.theo_finnhub_api_key)
            price = _finnhub_price(quoted)
            if quoted is not None and price is not None:
                return price, quoted
        yahoo = await self._yahoo_chart(symbol)
        price = _yahoo_price(yahoo.data if yahoo else None)
        if yahoo is not None and price is not None:
            return price, yahoo
        stooq = await self._stooq(symbol)
        price = _stooq_price(stooq.data if stooq else None)
        if stooq is not None and price is not None:
            return price, stooq
        if position_mark is not None:
            return position_mark, _Hit(source="t212", data={"last_price": str(position_mark)}, fetched_at=None, stored=False)
        return None

    async def research(self, ticker: str, *, position_mark: Decimal | None = None) -> TitleResearchOutput:
        settings = get_settings()
        symbol = vendor_symbol(ticker)
        quote = None
        found = await self._priced(ticker, position_mark=position_mark)
        if found is not None:
            quote = found[1].block().model_copy(update={"data": {"last_price": str(found[0])}})
        history: list[SourcedValue] = []
        hist = await self._history(symbol)
        if hist is not None:
            history.append(hist)
        profile = metrics = None
        news: list[SourcedValue] = []
        earnings: list[SourcedValue] = []
        macro: list[SourcedValue] = []
        filings: list[SourcedValue] = []
        if settings.theo_finnhub_api_key:
            profile, metrics, news, earnings = await self._finnhub_research(
                symbol, settings.theo_finnhub_api_key
            )
        if settings.theo_alpha_vantage_api_key:
            av = await self._alpha_news(symbol, settings.theo_alpha_vantage_api_key)
            if av is not None:
                news.append(av)
        if settings.theo_fred_api_key:
            series = await self._fred(settings.theo_fred_api_key)
            if series is not None:
                macro.append(series)
        if settings.theo_sec_user_agent:
            filing = await self._sec(symbol, settings.theo_sec_user_agent)
            if filing is not None:
                filings.append(filing)
        return TitleResearchOutput(
            ticker=ticker,
            quote=quote,
            history=history,
            profile=profile,
            metrics=metrics,
            news=news,
            earnings=earnings,
            macro=macro,
            filings=filings,
        )

    async def _history(self, symbol: str) -> SourcedValue | None:
        settings = get_settings()
        if settings.theo_tiingo_api_key:
            hit = await self._stored_get(
                "tiingo",
                "eod",
                symbol.lower(),
                lambda: self._client.get(
                    TIINGO_EOD.format(symbol=symbol.lower()),
                    headers={"Authorization": f"Token {settings.theo_tiingo_api_key}"},
                ),
            )
            if hit is not None and hit.data:
                return hit.block()
        yahoo = await self._yahoo_chart(symbol)
        if yahoo is not None:
            return yahoo.block()
        stooq = await self._stooq(symbol)
        price = _stooq_price(stooq.data if stooq else None)
        if stooq is not None and price is not None:
            return stooq.block().model_copy(update={"data": {"last_price": str(price)}})
        return None

    async def _finnhub_quote(self, symbol: str, key: str) -> _Hit | None:
        return await self._stored_get(
            "finnhub",
            "quote",
            symbol,
            lambda: self._client.get(FINNHUB_QUOTE, params={"symbol": symbol, "token": key}),
        )

    async def _yahoo_chart(self, symbol: str) -> _Hit | None:
        return await self._stored_get(
            "yahoo",
            "chart",
            symbol,
            lambda: self._client.get(YAHOO_CHART.format(symbol=symbol)),
        )

    async def _stooq(self, symbol: str) -> _Hit | None:
        return await self._stored_get(
            "stooq",
            "last",
            symbol.lower(),
            lambda: self._client.get(STOOQ_CSV.format(symbol=symbol.lower())),
            as_text=True,
        )

    async def _finnhub_research(
        self, symbol: str, key: str
    ) -> tuple[SourcedValue | None, SourcedValue | None, list[SourcedValue], list[SourcedValue]]:
        news: list[SourcedValue] = []
        earnings: list[SourcedValue] = []
        profile_hit = await self._stored_get(
            "finnhub",
            "profile2",
            symbol,
            lambda: self._client.get(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": symbol, "token": key},
            ),
        )
        profile = profile_hit.block() if profile_hit is not None and profile_hit.data else None
        metrics_hit = await self._stored_get(
            "finnhub",
            "metric",
            symbol,
            lambda: self._client.get(
                "https://finnhub.io/api/v1/stock/metric",
                params={"symbol": symbol, "metric": "all", "token": key},
            ),
        )
        metrics = metrics_hit.block() if metrics_hit is not None and metrics_hit.data else None
        return profile, metrics, news, earnings

    async def _alpha_news(self, symbol: str, key: str) -> SourcedValue | None:
        hit = await self._stored_get(
            "alpha_vantage",
            "NEWS_SENTIMENT",
            symbol,
            lambda: self._client.get(
                "https://www.alphavantage.co/query",
                params={"function": "NEWS_SENTIMENT", "tickers": symbol, "apikey": key},
            ),
        )
        return None if hit is None else hit.block()

    async def _fred(self, key: str) -> SourcedValue | None:
        hit = await self._stored_get(
            "fred",
            "FEDFUNDS",
            "",
            lambda: self._client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": "FEDFUNDS", "api_key": key, "file_type": "json", "limit": 1, "sort_order": "desc"},
            ),
        )
        return None if hit is None else hit.block()

    async def _sec(self, symbol: str, user_agent: str) -> SourcedValue | None:
        hit = await self._stored_get(
            "sec_edgar",
            "search-index",
            symbol,
            lambda: self._client.get(
                f"https://efts.sec.gov/LATEST/search-index?q={symbol}&dateRange=custom&startdt=2020-01-01",
                headers={"User-Agent": user_agent},
            ),
        )
        return None if hit is None else hit.block()

    async def _stored_get(self, provider: str, route: str, subject: str, send, *, as_text: bool = False) -> _Hit | None:
        blocked = reply_store.blocking_reply(provider, route, subject)
        if blocked is not None:
            if blocked.payload is None:
                return None
            return _Hit(source=provider, data=blocked.payload, fetched_at=blocked.fetched_at, stored=True)
        try:
            response = await send()
        except httpx.HTTPError:
            return _hit_from_row(provider, reply_store.get_reply(provider, route, subject))
        if response.status_code == 429:
            reply_store.remember_cooldown(provider, route, subject, cooldown_seconds(response.headers))
            return _hit_from_row(provider, reply_store.get_reply(provider, route, subject))
        if response.status_code >= 400:
            return _hit_from_row(provider, reply_store.get_reply(provider, route, subject))
        payload: Any = {"text": response.text} if as_text else response.json()
        saved = reply_store.remember_success(provider, route, subject, payload)
        return _Hit(source=provider, data=payload, fetched_at=saved.fetched_at, stored=False)


def _hit_from_row(provider: str, row) -> _Hit | None:
    if row is None or row.payload is None:
        return None
    return _Hit(source=provider, data=row.payload, fetched_at=row.fetched_at, stored=True)


def _finnhub_price(hit: _Hit | None) -> Decimal | None:
    if hit is None or not isinstance(hit.data, dict):
        return None
    last = hit.data.get("c")
    if last in (None, 0, 0.0):
        return None
    try:
        return Decimal(str(last))
    except (ValueError, TypeError, ArithmeticError):
        return None


def _yahoo_price(chart: Any) -> Decimal | None:
    if not isinstance(chart, dict):
        return None
    try:
        result = chart["chart"]["result"][0]
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
            price = next((item for item in reversed(closes) if item is not None), None)
        return Decimal(str(price)) if price is not None else None
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError):
        return None


def _stooq_price(payload: Any) -> Decimal | None:
    text = payload.get("text") if isinstance(payload, dict) else None
    if not text:
        return None
    try:
        lines = str(text).strip().splitlines()
        if len(lines) < 2:
            return None
        cols = lines[1].split(",")
        close = cols[6] if len(cols) > 6 else None
        if close in (None, "N/D", ""):
            return None
        return Decimal(close)
    except (ValueError, IndexError, ArithmeticError):
        return None


_MARKET: MarketDataClient | None = None


def get_market_data_client() -> MarketDataClient:
    global _MARKET
    if _MARKET is None:
        _MARKET = MarketDataClient()
    return _MARKET


def reset_market_data_client() -> None:
    global _MARKET
    _MARKET = None
