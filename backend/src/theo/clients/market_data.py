"""Free-tier quote and research cascade."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from src.config import get_settings
from src.theo.schemas import SourcedValue, TitleResearchOutput
from src.theo.symbol import vendor_symbol

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
STOOQ_CSV = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
TIINGO_EOD = "https://api.tiingo.com/tiingo/daily/{symbol}/prices"


class MarketDataClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(timeout=15.0, transport=transport, headers={"User-Agent": "theo-bfa/1.0"})

    async def last_price(
        self,
        ticker: str,
        *,
        position_mark: Decimal | None = None,
    ) -> tuple[Decimal, str] | None:
        settings = get_settings()
        symbol = vendor_symbol(ticker)
        if settings.theo_finnhub_api_key:
            quoted = await self._finnhub_quote(symbol, settings.theo_finnhub_api_key)
            if quoted is not None:
                return quoted, "finnhub"
        yahoo = await self._yahoo_last(symbol)
        if yahoo is not None:
            return yahoo, "yahoo"
        stooq = await self._stooq_last(symbol)
        if stooq is not None:
            return stooq, "stooq"
        if position_mark is not None:
            return position_mark, "t212"
        return None

    async def research(self, ticker: str, *, position_mark: Decimal | None = None) -> TitleResearchOutput:
        settings = get_settings()
        symbol = vendor_symbol(ticker)
        quote = None
        last = await self.last_price(ticker, position_mark=position_mark)
        if last is not None:
            quote = SourcedValue(source=last[1], data={"last_price": str(last[0])})
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
            try:
                response = await self._client.get(
                    TIINGO_EOD.format(symbol=symbol.lower()),
                    headers={"Authorization": f"Token {settings.theo_tiingo_api_key}"},
                )
                if response.status_code == 200:
                    return SourcedValue(source="tiingo", data=response.json())
            except httpx.HTTPError:
                pass
        yahoo = await self._yahoo_chart(symbol)
        if yahoo is not None:
            return SourcedValue(source="yahoo", data=yahoo)
        stooq = await self._stooq_last(symbol)
        if stooq is not None:
            return SourcedValue(source="stooq", data={"last_price": str(stooq)})
        return None

    async def _finnhub_quote(self, symbol: str, key: str) -> Decimal | None:
        try:
            response = await self._client.get(FINNHUB_QUOTE, params={"symbol": symbol, "token": key})
            if response.status_code != 200:
                return None
            data = response.json()
            last = data.get("c")
            if last in (None, 0, 0.0):
                return None
            return Decimal(str(last))
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def _yahoo_last(self, symbol: str) -> Decimal | None:
        chart = await self._yahoo_chart(symbol)
        if not chart:
            return None
        try:
            result = chart["chart"]["result"][0]
            meta = result.get("meta") or {}
            price = meta.get("regularMarketPrice")
            if price is None:
                closes = (result.get("indicators") or {}).get("quote", [{}])[0].get("close") or []
                price = next((item for item in reversed(closes) if item is not None), None)
            return Decimal(str(price)) if price is not None else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    async def _yahoo_chart(self, symbol: str) -> dict[str, Any] | None:
        try:
            response = await self._client.get(YAHOO_CHART.format(symbol=symbol))
            if response.status_code != 200:
                return None
            return response.json()
        except httpx.HTTPError:
            return None

    async def _stooq_last(self, symbol: str) -> Decimal | None:
        try:
            response = await self._client.get(STOOQ_CSV.format(symbol=symbol.lower()))
            if response.status_code != 200:
                return None
            lines = response.text.strip().splitlines()
            if len(lines) < 2:
                return None
            cols = lines[1].split(",")
            close = cols[6] if len(cols) > 6 else None
            if close in (None, "N/D", ""):
                return None
            return Decimal(close)
        except (httpx.HTTPError, ValueError, IndexError):
            return None

    async def _finnhub_research(
        self, symbol: str, key: str
    ) -> tuple[SourcedValue | None, SourcedValue | None, list[SourcedValue], list[SourcedValue]]:
        profile = metrics = None
        news: list[SourcedValue] = []
        earnings: list[SourcedValue] = []
        try:
            p = await self._client.get(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": symbol, "token": key},
            )
            if p.status_code == 200 and p.json():
                profile = SourcedValue(source="finnhub", data=p.json())
        except httpx.HTTPError:
            pass
        try:
            m = await self._client.get(
                "https://finnhub.io/api/v1/stock/metric",
                params={"symbol": symbol, "metric": "all", "token": key},
            )
            if m.status_code == 200 and m.json():
                metrics = SourcedValue(source="finnhub", data=m.json())
        except httpx.HTTPError:
            pass
        return profile, metrics, news, earnings

    async def _alpha_news(self, symbol: str, key: str) -> SourcedValue | None:
        try:
            response = await self._client.get(
                "https://www.alphavantage.co/query",
                params={"function": "NEWS_SENTIMENT", "tickers": symbol, "apikey": key},
            )
            if response.status_code != 200:
                return None
            return SourcedValue(source="alpha_vantage", data=response.json())
        except httpx.HTTPError:
            return None

    async def _fred(self, key: str) -> SourcedValue | None:
        try:
            response = await self._client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": "FEDFUNDS", "api_key": key, "file_type": "json", "limit": 1, "sort_order": "desc"},
            )
            if response.status_code != 200:
                return None
            return SourcedValue(source="fred", data=response.json())
        except httpx.HTTPError:
            return None

    async def _sec(self, symbol: str, user_agent: str) -> SourcedValue | None:
        try:
            response = await self._client.get(
                f"https://efts.sec.gov/LATEST/search-index?q={symbol}&dateRange=custom&startdt=2020-01-01",
                headers={"User-Agent": user_agent},
            )
            if response.status_code != 200:
                return None
            return SourcedValue(source="sec_edgar", data=response.json())
        except httpx.HTTPError:
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
