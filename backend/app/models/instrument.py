from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, Float, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Instrument(Base, UUIDMixin, TimestampMixin):
    """A tradable symbol. Real (Alpaca) or synthetic (phase 01 generator).

    Synthetic instruments keep their generator seed so any market can be
    reproduced exactly from its seed alone.
    """

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), default="SIM", nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_tradable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # phase 01 - synthetic generator inputs and fundamentals
    generator_seed: Mapped[int | None] = mapped_column()
    initial_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    listed_on: Mapped[date | None] = mapped_column(Date)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)
    beta: Mapped[float | None] = mapped_column(Float)
    annual_vol: Mapped[float | None] = mapped_column(Float)

    # Everything else the generator needs to reproduce this name exactly.
    sim_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = ["Instrument"]
