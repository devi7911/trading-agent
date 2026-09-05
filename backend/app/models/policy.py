import uuid
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class AutonomyLevel(StrEnum):
    OBSERVE = "observe"        # log intent, place nothing
    APPROVE = "approve"        # every trade needs a Telegram tap
    AUTO_CAPPED = "auto_capped"  # small trades auto, large ones ask
    FULL_AUTO = "full_auto"


class RiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class Policy(Base, UUIDMixin, TimestampMixin):
    """The user's standing instructions to the agent.

    Versioned and never edited in place: an edit writes a new row and marks
    the previous one inactive, so every decision can name the exact policy
    version that governed it.
    """

    __tablename__ = "policies"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    risk_profile: Mapped[RiskProfile] = mapped_column(
        String(16), default=RiskProfile.BALANCED, nullable=False
    )
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(
        String(16), default=AutonomyLevel.OBSERVE, nullable=False
    )

    # --- sizing ---
    max_position_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"))
    max_sector_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("30.00"))
    cash_floor_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("10.00"))

    # --- loss control ---
    stop_loss_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("8.00"))
    take_profit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    max_daily_loss_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("3.00"))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("15.00"))

    # --- frequency ---
    max_trades_per_day: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_trades_per_symbol_per_day: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # --- approval threshold for AUTO_CAPPED ---
    auto_approve_below: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("500.0000")
    )

    # --- hard rules ---
    avoid_earnings: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_shorting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="policies")


# System ceilings. A user's policy may be stricter than these, never looser.
# The risk gate (phase 04) clamps against these before it looks at anything else.
SYSTEM_CEILINGS = {
    "max_position_pct": Decimal("25.00"),
    "max_sector_pct": Decimal("50.00"),
    "max_daily_loss_pct": Decimal("10.00"),
    "max_drawdown_pct": Decimal("30.00"),
    "max_trades_per_day": 50,
}

__all__ = ["SYSTEM_CEILINGS", "AutonomyLevel", "Policy", "RiskProfile"]
