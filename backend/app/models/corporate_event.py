import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class CorporateEvent(Base, UUIDMixin, TimestampMixin):
    """Earnings, splits, dividends, halts.

    The agent's policy can say 'never hold through earnings', so it needs to
    know these are coming, not just that they happened.
    """

    __tablename__ = "corporate_events"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    occurs_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # earnings
    eps_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    # splits (2.0 = 2-for-1) and dividends (per share)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))

    note: Mapped[str | None] = mapped_column(String(255))


__all__ = ["CorporateEvent"]
