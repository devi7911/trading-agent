from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketSnapshot(Base):
    """One row per trading day: the index level and market breadth.

    Derived entirely from `bars`, so it can be rebuilt from scratch at any time.
    Stored rather than computed on request because every dashboard view needs it
    and recomputing 1500 days of breadth per page load would be absurd.
    """

    __tablename__ = "market_snapshots"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    index_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    index_return: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)

    advancers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decliners: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    new_highs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_lows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pct_above_50dma: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=0)

    total_volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    regime: Mapped[str | None] = mapped_column(String(8))

    @property
    def breadth_ratio(self) -> float:
        total = self.advancers + self.decliners
        return (self.advancers / total) if total else 0.5


__all__ = ["MarketSnapshot"]
