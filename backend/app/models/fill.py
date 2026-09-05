import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.order import Order


class Fill(Base, UUIDMixin, TimestampMixin):
    """An execution. Fills are the only thing that moves cash or position.

    Nothing else writes to positions - they are derived from this table, which
    is what makes the ledger reconcilable.
    """

    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence", name="uq_fills_order_sequence"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )

    # A database-assigned total order over every fill in the system. Wall-clock
    # timestamps cannot do this job: simulated acknowledgement latency jitters by
    # a couple of hundred milliseconds, so two orders placed together can have
    # their fills timestamped out of sequence. Replaying the ledger in the wrong
    # order drove a position negative and then divided by zero.
    ledger_seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), unique=True, nullable=False
    )

    # Position of this fill within its own order (1, 2, ... for a split fill).
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    commission: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # How far the fill landed from the reference price, in basis points.
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="fills")

    @property
    def gross_value(self) -> Decimal:
        return self.quantity * self.price


__all__ = ["Fill"]
