from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str
    name: str
    sector: str | None
    exchange: str
    is_synthetic: bool
    is_tradable: bool
    beta: float | None
    annual_vol: float | None
    shares_outstanding: int | None
    listed_on: date | None


class BarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class QuoteOut(BaseModel):
    symbol: str
    last: Decimal
    ts: datetime


class NewsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    published_at: datetime
    headline: str
    category: str
    sentiment: float
    source: str


class CorporateEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    occurs_at: datetime
    eps_estimate: Decimal | None
    eps_actual: Decimal | None
    amount: Decimal | None
    note: str | None
