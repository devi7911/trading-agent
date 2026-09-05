import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class NewsItem(Base, UUIDMixin, TimestampMixin):
    """A headline about an instrument.

    In synthetic mode these are causally linked to price moves - some published
    before the move (leading), some after (lagging), some pure noise. That mix
    is what gives a news-reading agent something real to be right or wrong about.
    """

    __tablename__ = "news_items"

    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("instruments.id", ondelete="CASCADE"), index=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    headline: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="SIM WIRE", nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # -1.0 strongly negative .. +1.0 strongly positive
    sentiment: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # "leading" | "lagging" | "noise" - ground truth, useful for scoring the agent
    relation: Mapped[str] = mapped_column(String(16), default="noise", nullable=False)


__all__ = ["NewsItem"]
