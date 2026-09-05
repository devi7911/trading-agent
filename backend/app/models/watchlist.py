import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.instrument import Instrument
    from app.models.user import User


class Watchlist(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "watchlists"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="My list", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="watchlists")
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )


class WatchlistItem(Base, UUIDMixin, TimestampMixin):
    """Conviction tier drives position sizing and stop width in phase 04."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "instrument_id", name="uq_watchlist_items_instrument"),
    )

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )

    is_favourite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conviction: Mapped[int] = mapped_column(Integer, default=2, nullable=False)  # 1 low - 3 high
    notes: Mapped[str | None] = mapped_column(String(500))

    watchlist: Mapped["Watchlist"] = relationship(back_populates="items")
    instrument: Mapped["Instrument"] = relationship()


__all__ = ["Watchlist", "WatchlistItem"]
