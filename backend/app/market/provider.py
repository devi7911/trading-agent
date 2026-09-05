"""The market data port.

Every provider - synthetic, Alpaca, a CSV replay - implements this. Nothing
upstream of here knows which one is in use; the adapter is chosen by env var.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    name: str
    sector: str | None
    exchange: str
    is_synthetic: bool
    initial_price: float | None = None
    shares_outstanding: int | None = None
    beta: float | None = None
    annual_vol: float | None = None
    listed_on: date | None = None
    generator_seed: int | None = None
    sim_params: dict | None = None


@dataclass(frozen=True)
class BarSpec:
    symbol: str
    ts: datetime
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class NewsSpec:
    symbol: str | None
    published_at: datetime
    headline: str
    body: str
    category: str
    sentiment: float
    relation: str
    source: str = "SIM WIRE"


@dataclass(frozen=True)
class EventSpec:
    symbol: str
    event_type: str
    occurs_at: datetime
    eps_estimate: float | None = None
    eps_actual: float | None = None
    ratio: float | None = None
    amount: float | None = None
    note: str | None = None


@runtime_checkable
class MarketDataProvider(Protocol):
    """Read-only market data. Implementations must be side-effect free."""

    name: str

    def instruments(self) -> list[InstrumentSpec]: ...

    def bars(self, start: date, end: date, timeframe: str = "1d") -> list[BarSpec]: ...

    def news(self, start: date, end: date) -> list[NewsSpec]: ...

    def corporate_events(self, start: date, end: date) -> list[EventSpec]: ...


__all__ = [
    "BarSpec",
    "EventSpec",
    "InstrumentSpec",
    "MarketDataProvider",
    "NewsSpec",
]
