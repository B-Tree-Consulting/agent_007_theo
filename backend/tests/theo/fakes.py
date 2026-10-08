"""In-memory Trading 212 and market-data doubles."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from src.theo.book import signed_quantity
from src.theo.schemas import OrderInput


class FakeT212:
    def __init__(self) -> None:
        self.cash = {
            "free": Decimal("125000"),
            "invested": Decimal("0"),
            "total": Decimal("125000"),
        }
        self.holdings: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.placed: list[OrderInput] = []
        self.cancelled: list[str] = []
        self._n = 100

    async def account_cash(self) -> dict[str, Decimal]:
        return dict(self.cash)

    async def positions(self) -> list[dict[str, Any]]:
        return list(self.holdings)

    async def open_orders(self) -> list[dict[str, Any]]:
        return list(self.orders)

    async def historical_orders(self) -> list[dict[str, Any]]:
        return []

    async def place_order(self, inputs: OrderInput) -> str:
        self._n += 1
        order_id = str(self._n)
        self.placed.append(inputs)
        qty = signed_quantity(inputs.side, inputs.quantity)
        self.orders.append(
            {
                "t212_order_id": order_id,
                "ticker": inputs.ticker,
                "side": inputs.side,
                "order_type": inputs.order_type,
                "quantity": inputs.quantity,
                "signed_quantity": qty,
                "limit_price": inputs.limit_price,
                "stop_price": inputs.stop_price,
                "time_validity": inputs.time_validity,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return order_id

    async def cancel_order(self, t212_order_id: str) -> None:
        self.cancelled.append(t212_order_id)
        self.orders = [row for row in self.orders if row["t212_order_id"] != t212_order_id]


class FakeMarket:
    def __init__(self, price: Decimal = Decimal("150")) -> None:
        self.price = price

    async def last_price(self, ticker: str, *, position_mark: Decimal | None = None):
        del ticker
        if self.price is None:
            if position_mark is not None:
                return position_mark, "t212"
            return None
        return self.price, "yahoo"

    async def research(self, ticker: str, *, position_mark: Decimal | None = None):
        from src.theo.schemas import SourcedValue, TitleResearchOutput

        last = await self.last_price(ticker, position_mark=position_mark)
        quote = None
        if last is not None:
            quote = SourcedValue(source=last[1], data={"last_price": str(last[0])})
        return TitleResearchOutput(ticker=ticker, quote=quote)


def fake_fx() -> SimpleNamespace:
    return SimpleNamespace(
        czk_per_unit=Decimal("23"),
        fixing_date=date(2026, 10, 6),
        source="CNB",
    )
