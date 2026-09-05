import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class Account(Base, UUIDMixin, TimestampMixin):
    """A simulated trading account. One per user per broker adapter."""

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    broker: Mapped[str] = mapped_column(String(32), default="sim", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    starting_cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)

    # Honoured by the risk gate from phase 04. True = no new entries.
    is_halted: Mapped[bool] = mapped_column(default=False, nullable=False)
    halt_reason: Mapped[str | None] = mapped_column(String(255))

    user: Mapped["User"] = relationship(back_populates="accounts")


__all__ = ["Account"]
