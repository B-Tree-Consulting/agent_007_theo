"""Czech National Bank daily FX fixing."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from src.config import get_settings
from src.db.session import SessionLocal, get_engine
from src.theo.errors import FX_UNAVAILABLE, TheoError
from src.theo.models import CnbFxFixing

CNB_SOURCE = "CNB"


def parse_denni_kurz(text: str, *, currency: str = "USD") -> tuple[Decimal, date]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise TheoError(FX_UNAVAILABLE, "CNB fixing file was empty")
    header = lines[0]
    fixing_date = _parse_header_date(header)
    code = currency.upper()
    for line in lines[2:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        if parts[3].strip().upper() != code:
            continue
        amount = Decimal(parts[2].strip().replace(",", ".") or "1")
        rate = Decimal(parts[4].strip().replace(",", "."))
        if amount == 0:
            raise TheoError(FX_UNAVAILABLE, f"CNB amount for {code} was zero")
        return (rate / amount), fixing_date
    raise TheoError(FX_UNAVAILABLE, f"CNB fixing has no row for {code}")


def _parse_header_date(header: str) -> date:
    token = header.split("#", 1)[0].strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return date.today()


class CnbClient:
    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url
        self._client = httpx.AsyncClient(timeout=15.0, transport=transport)

    async def fetch_text(self) -> str:
        response = await self._client.get(self.url)
        response.raise_for_status()
        return response.text


def _session():
    return SessionLocal(bind=get_engine())


def read_cached_fixing(currency: str = "USD") -> CnbFxFixing | None:
    session = _session()
    try:
        return session.get(CnbFxFixing, currency.upper())
    finally:
        session.close()


def store_fixing(currency: str, czk_per_unit: Decimal, fixing_date: date, source: str = CNB_SOURCE) -> CnbFxFixing:
    session = _session()
    try:
        row = session.get(CnbFxFixing, currency.upper())
        if row is None:
            row = CnbFxFixing(
                currency_code=currency.upper(),
                czk_per_unit=czk_per_unit,
                fixing_date=fixing_date,
                source=source,
                fetched_at=datetime.now(timezone.utc),
            )
            session.add(row)
        else:
            row.czk_per_unit = czk_per_unit
            row.fixing_date = fixing_date
            row.source = source
            row.fetched_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(row)
        return row
    finally:
        session.close()


async def load_fixing(currency: str = "USD") -> CnbFxFixing:
    code = currency.upper()
    if code == "CZK":
        return store_fixing("CZK", Decimal("1"), date.today(), source="account")
    settings = get_settings()
    client = CnbClient(settings.theo_cnb_fixing_url)
    try:
        text = await client.fetch_text()
        rate, fixing_date = parse_denni_kurz(text, currency=code)
        return store_fixing(code, rate, fixing_date)
    except Exception:
        cached = read_cached_fixing(code)
        if cached is None:
            raise TheoError(FX_UNAVAILABLE, f"No CNB fixing is available for {code}") from None
        return cached


async def load_usd_fixing() -> CnbFxFixing:
    return await load_fixing("USD")
