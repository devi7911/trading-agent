"""The broker port.

One interface, three intended adapters: the simulated exchange (now), Alpaca
paper (phase 10), and a live adapter that this repository will not ship. Nothing
above this layer knows which is in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.models.order import OrderType, RejectReason, Side, TimeInForce


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: str | None = None
    note: str | None = None

    # Optional bracket legs, attached to the entry when it fills.
    take_profit_price: Decimal | None = None
    stop_loss_price: Decimal | None = None


@dataclass(frozen=True)
class FillEvent:
    sequence: int
    quantity: int
    price: Decimal
    commission: Decimal
    slippage_bps: Decimal
    filled_at: datetime


@dataclass(frozen=True)
class ExecutionResult:
    """What the venue did with an order."""

    accepted: bool
    fills: list[FillEvent] = field(default_factory=list)
    reject_reason: RejectReason | None = None
    message: str | None = None
    resting: bool = False        # accepted, unfilled, still live at the venue

    @property
    def filled_quantity(self) -> int:
        return sum(f.quantity for f in self.fills)

    @property
    def average_price(self) -> Decimal | None:
        if not self.fills:
            return None
        notional = sum(f.price * f.quantity for f in self.fills)
        return (notional / self.filled_quantity).quantize(Decimal("0.0001"))

    @property
    def total_commission(self) -> Decimal:
        return sum((f.commission for f in self.fills), Decimal(0))


@runtime_checkable
class BrokerPort(Protocol):
    """Adapters must be pure with respect to the database: they decide what the
    venue does, they never write to it. Persistence is the service's job."""

    name: str
    supports_live_trading: bool

    async def submit(self, request: OrderRequest, *, as_of: datetime) -> ExecutionResult: ...

    async def cancel(self, client_order_id: str) -> bool: ...


__all__ = ["BrokerPort", "ExecutionResult", "FillEvent", "OrderRequest"]
