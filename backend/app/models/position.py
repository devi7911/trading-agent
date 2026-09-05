import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Position(Base, UUIDMixin, TimestampMixin):
    """Derived state: what the account holds, computed from fills.

    Never edited by hand and never written outside the execution service. If a
    position disagrees with the fills that produced it, the fills are right.
    """

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_positions_instrument"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="RESTRICT"), index=True
    )

    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    realised_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    total_commission: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, nullable=False)

    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_open(self) -> bool:
        return self.quantity != 0

    @property
    def cost_basis(self) -> Decimal:
        return self.quantity * self.avg_cost


__all__ = ["Position"]
