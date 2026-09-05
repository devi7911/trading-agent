from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.order import OrderType, Side, TimeInForce


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(max_length=16)
    side: Side
    quantity: int = Field(gt=0, le=1_000_000)
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: TimeInForce = TimeInForce.DAY
    client_order_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def check_prices(self) -> "PlaceOrderRequest":
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError("limit_price is required for limit and stop-limit orders")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError("stop_price is required for stop and stop-limit orders")
        return self


class FillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    quantity: int
    price: Decimal
    commission: Decimal
    slippage_bps: Decimal
    filled_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_order_id: str
    symbol: str | None = None
    side: Side
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: int
    limit_price: Decimal | None
    stop_price: Decimal | None
    status: str
    filled_quantity: int
    avg_fill_price: Decimal | None
    commission: Decimal
    reject_reason: str | None
    note: str | None
    submitted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime


class OrderDetail(OrderOut):
    fills: list[FillOut] = []


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    symbol: str | None = None
    quantity: int
    avg_cost: Decimal
    realised_pnl: Decimal
    total_commission: Decimal
    opened_at: datetime | None

    # Filled in by the endpoint from the latest bar.
    last_price: Decimal | None = None
    market_value: Decimal | None = None
    unrealised_pnl: Decimal | None = None
    unrealised_pct: float | None = None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    broker: str
    currency: str
    starting_cash: Decimal
    cash: Decimal
    equity: Decimal
    is_halted: bool
    halt_reason: str | None

    total_return_pct: float | None = None
    open_positions: int = 0


class ReconciliationOut(BaseModel):
    """Does stored state agree with what the fills imply?"""

    reconciled: bool
    cash_stored: Decimal
    cash_from_fills: Decimal
    cash_difference: Decimal
    position_mismatches: list[dict] = []
