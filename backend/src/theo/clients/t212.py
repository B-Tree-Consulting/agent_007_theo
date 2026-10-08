"""Trading 212 Public API v0 adapter."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from src.config import get_settings
from src.theo.book import signed_quantity
from src.theo.errors import BROKER_REJECTED, TheoError
from src.theo.schemas import OrderInput, OrderType, Side, TimeValidity
from src.theo.settings import t212_base_url, t212_environment

log = logging.getLogger("theo.t212")

_TYPE_MAP = {
    "MARKET": OrderType.market,
    "LIMIT": OrderType.limit,
    "STOP": OrderType.stop,
    "STOP_LIMIT": OrderType.stop_limit,
    "STOPLIMIT": OrderType.stop_limit,
}


class T212Client:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (api_key, api_secret)
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=self._auth,
            timeout=20.0,
            transport=transport,
        )

    @property
    def environment(self) -> str:
        return "live" if "live.trading212.com" in self.base_url else "demo"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, disclose_body: bool = False, **kwargs: Any) -> httpx.Response:
        optional = path.split("?", 1)[0].startswith("/equity/metadata/")
        max_attempts = 1 if optional else 4
        async with self._lock:
            attempt = 0
            while True:
                attempt += 1
                response = await self._client.request(method, path, **kwargs)
                if response.status_code != 429 or attempt >= max_attempts:
                    break
                wait = _retry_wait_seconds(response)
                if wait > 0:
                    await asyncio.sleep(wait)
        if response.status_code >= 400:
            log.warning("t212 %s %s -> %s", method, path, response.status_code)
            message = _full_broker_message(response) if disclose_body else _safe_broker_message(response)
            raise TheoError(BROKER_REJECTED, message)
        return response

    async def _get_json(self, path: str) -> Any:
        return (await self._request("GET", path)).json()

    async def account_cash(self) -> dict[str, Decimal]:
        data = await self._get_json("/equity/account/cash")
        return {
            "free": Decimal(str(data.get("free") or 0)),
            "invested": Decimal(str(data.get("invested") or 0)),
            "total": Decimal(str(data.get("total") or 0)),
        }

    async def positions(self) -> list[dict[str, Any]]:
        data = await self._get_json("/equity/portfolio")
        rows = data if isinstance(data, list) else data.get("items") or []
        out = []
        for row in rows:
            instrument = row.get("instrument") or {}
            out.append(
                {
                    "ticker": row.get("ticker"),
                    "quantity": Decimal(str(row.get("quantity") or 0)),
                    "average_price": _opt_dec(row.get("averagePrice")),
                    "last_price": _opt_dec(row.get("currentPrice")),
                    "ppl": _opt_dec(row.get("ppl")),
                    "currency": instrument.get("currency") or row.get("currency"),
                }
            )
        return out

    async def open_orders(self) -> list[dict[str, Any]]:
        return await self._paginate("/equity/orders")

    async def historical_orders(self) -> list[dict[str, Any]]:
        try:
            return await self._paginate("/equity/history/orders")
        except TheoError:
            return []

    async def _paginate(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        while next_path:
            payload = await self._get_json(next_path)
            if isinstance(payload, list):
                items.extend(payload)
                break
            items.extend(payload.get("items") or [])
            next_path = payload.get("nextPagePath")
        return [_map_order(row) for row in items]

    async def metadata_instruments(self) -> list[dict[str, Any]]:
        data = await self._get_json("/equity/metadata/instruments")
        rows = data if isinstance(data, list) else data.get("items") or []
        return [_map_instrument(row) for row in rows if isinstance(row, dict)]

    async def metadata_exchanges(self) -> list[dict[str, Any]]:
        data = await self._get_json("/equity/metadata/exchanges")
        rows = data if isinstance(data, list) else data.get("items") or []
        return [_map_exchange(row) for row in rows if isinstance(row, dict)]

    async def place_order(self, inputs: OrderInput) -> str:
        body = _order_body(inputs)
        endpoint = {
            OrderType.market: "/equity/orders/market",
            OrderType.limit: "/equity/orders/limit",
            OrderType.stop: "/equity/orders/stop",
            OrderType.stop_limit: "/equity/orders/stop_limit",
        }[inputs.order_type]
        data = (await self._request("POST", endpoint, json=body, disclose_body=True)).json()
        order_id = data.get("id") or data.get("orderId")
        if order_id is None:
            raise TheoError(BROKER_REJECTED, "Broker accepted the order but returned no id")
        return str(order_id)

    async def cancel_order(self, t212_order_id: str) -> None:
        await self._request("DELETE", f"/equity/orders/{t212_order_id}")

    async def get_order(self, t212_order_id: str) -> dict[str, Any] | None:
        try:
            data = await self._get_json(f"/equity/orders/{t212_order_id}")
        except TheoError:
            return None
        return _map_order(data)


def _quantity_step(row: dict[str, Any]) -> Decimal:
    raw = row.get("minTradeQuantity") or row.get("quantityStep")
    if raw not in (None, "", 0, "0"):
        step = Decimal(str(raw))
        if step > 0:
            return step
    return Decimal("0.0001")


def _map_instrument(row: dict[str, Any]) -> dict[str, Any]:
    currency = row.get("currency") or row.get("currencyCode") or ""
    schedule = row.get("workingScheduleId")
    return {
        "ticker": str(row.get("ticker") or ""),
        "name": row.get("name") or row.get("shortName"),
        "isin": row.get("isin"),
        "type": row.get("type"),
        "currency": str(currency or ""),
        "extended_hours": bool(row.get("extendedHours")),
        "max_open_quantity": _opt_dec(row.get("maxOpenQuantity")),
        "quantity_step": _quantity_step(row),
        "working_schedule_id": None if schedule is None else str(schedule),
    }


def _map_exchange(row: dict[str, Any]) -> dict[str, Any]:
    schedule_id = row.get("id") or row.get("workingScheduleId")
    events = row.get("timeEvents") or row.get("workingSchedules") or row.get("events") or []
    return {
        "working_schedule_id": None if schedule_id is None else str(schedule_id),
        "name": row.get("name"),
        "timezone": row.get("timeZone") or row.get("timezone"),
        "events": events if isinstance(events, list) else [],
    }


def _order_body(inputs: OrderInput) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ticker": inputs.ticker,
        "quantity": float(signed_quantity(inputs.side, inputs.quantity)),
    }
    if inputs.extended_hours:
        body["extendedHours"] = True
    if inputs.limit_price is not None:
        body["limitPrice"] = float(inputs.limit_price)
    if inputs.stop_price is not None:
        body["stopPrice"] = float(inputs.stop_price)
    if inputs.time_validity is not None:
        body["timeValidity"] = inputs.time_validity.value
    return body


def _map_order(row: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(row.get("type") or row.get("orderType") or "MARKET").upper()
    qty = Decimal(str(row.get("quantity") or 0))
    side = Side.sell if qty < 0 else Side.buy
    created = row.get("creationTime") or row.get("createdAt")
    created_at = None
    if isinstance(created, str):
        try:
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            created_at = None
    validity_raw = row.get("timeValidity")
    validity = None
    if validity_raw in {item.value for item in TimeValidity}:
        validity = TimeValidity(validity_raw)
    return {
        "t212_order_id": str(row.get("id") or row.get("orderId") or ""),
        "ticker": row.get("ticker"),
        "side": side,
        "order_type": _TYPE_MAP.get(raw_type, OrderType.market),
        "quantity": abs(qty),
        "signed_quantity": qty,
        "limit_price": _opt_dec(row.get("limitPrice")),
        "stop_price": _opt_dec(row.get("stopPrice")),
        "time_validity": validity,
        "created_at": created_at or datetime.now(timezone.utc),
        "status": row.get("status"),
        "raw": row,
    }


def _opt_dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _retry_wait_seconds(response: httpx.Response) -> float:
    reset = response.headers.get("x-ratelimit-reset")
    if reset:
        try:
            wait = float(reset) - time.time()
            if wait > 0:
                return min(wait + 0.1, 8.0)
            return 0.0
        except ValueError:
            pass
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 8.0)
        except ValueError:
            pass
    return 1.0


def _full_broker_message(response: httpx.Response) -> str:
    text = (response.text or "").strip()
    if text:
        return text[:4000]
    return _safe_broker_message(response)


def _safe_broker_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or response.reason_phrase)
    except Exception:
        pass
    return f"HTTP {response.status_code}"


_CLIENT: T212Client | None = None


def get_t212_client() -> T212Client:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    settings = get_settings()
    if not settings.t212_api_key or not settings.t212_api_secret:
        raise TheoError(BROKER_REJECTED, "T212_API_KEY and T212_API_SECRET are required")
    _CLIENT = T212Client(
        base_url=t212_base_url(settings),
        api_key=settings.t212_api_key,
        api_secret=settings.t212_api_secret,
    )
    return _CLIENT


def reset_t212_client() -> None:
    global _CLIENT
    _CLIENT = None


def current_t212_environment() -> str:
    return t212_environment()
