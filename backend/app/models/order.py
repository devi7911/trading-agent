import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.fill import Fill


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"


class OrderStatus(StrEnum):
    """The state machine. Terminal states are FILLED, CANCELLED, REJECTED, EXPIRED."""

    NEW = "new"                        # accepted locally, not yet sent
    SUBMITTED = "submitted"            # live at the venue
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"                # DAY order that outlived its session


TERMINAL_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)

# Every legal transition. Anything not listed here is a bug, and the service
# refuses it rather than quietly corrupting the ledger.
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED,
                                OrderStatus.CANCELLED}),
    OrderStatus.SUBMITTED: frozenset({OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                                      OrderStatus.CANCELLED, OrderStatus.REJECTED,
                                      OrderStatus.EXPIRED}),
    OrderStatus.PARTIALLY_FILLED: frozenset({OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                                             OrderStatus.CANCELLED, OrderStatus.EXPIRED}),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


class RejectReason(StrEnum):
    INSUFFICIENT_BUYING_POWER = "insufficient_buying_power"
    INSUFFICIENT_POSITION = "insufficient_position"
    MARKET_CLOSED = "market_closed"
    SYMBOL_HALTED = "symbol_halted"
    SYMBOL_NOT_TRADABLE = "symbol_not_tradable"
    INVALID_QUANTITY = "invalid_quantity"
    INVALID_PRICE = "invalid_price"
    ACCOUNT_HALTED = "account_halted"
    NO_MARKET_DATA = "no_market_data"
    DUPLICATE_CLIENT_ORDER_ID = "duplicate_client_order_id"


class BracketRole(StrEnum):
    ENTRY = "entry"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"


class Order(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("account_id", "client_order_id", name="uq_orders_client_order_id"),
        Index("ix_orders_account_status", "account_id", "status"),
        Index("ix_orders_instrument_ts", "instrument_id", "created_at"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )

    # Caller-supplied idempotency key. A retry with the same key returns the
    # original order instead of placing a second one.
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)

    side: Mapped[Side] = mapped_column(String(8), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(String(12), nullable=False)
    time_in_force: Mapped[TimeInForce] = mapped_column(
        String(8), default=TimeInForce.DAY, nullable=False
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    status: Mapped[OrderStatus] = mapped_column(
        String(20), default=OrderStatus.NEW, nullable=False, index=True
    )
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    commission: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, nullable=False)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[RejectReason | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(255))

    # Bracket linkage: the two exit legs point back at their entry.
    parent_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    bracket_role: Mapped[BracketRole | None] = mapped_column(String(16))

    fills: Mapped[list["Fill"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="Fill.sequence"
    )

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.quantity - self.filled_quantity)

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL_STATUSES

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.side} {self.quantity} status={self.status}>"


__all__ = [
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "BracketRole",
    "Order",
    "OrderStatus",
    "OrderType",
    "RejectReason",
    "Side",
    "TimeInForce",
]
