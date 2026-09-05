import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Severity(StrEnum):
    IMMEDIATE = "immediate"   # send now
    DIGEST = "digest"         # batch into the daily summary
    SILENT = "silent"         # recorded, never pushed


class Channel(StrEnum):
    TELEGRAM = "telegram"
    IN_APP = "in_app"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"   # deduplicated against a recent identical message


class Notification(Base, UUIDMixin, TimestampMixin):
    """What was sent, when, and on which channel.

    Stored even when delivery is suppressed or fails, so "why didn't I hear
    about this?" always has an answer.
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(String(12), nullable=False, index=True)
    channel: Mapped[Channel] = mapped_column(String(12), nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        String(12), default=DeliveryStatus.PENDING, nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Identical (user, event, dedupe_key) inside the window is suppressed.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


__all__ = ["Channel", "DeliveryStatus", "Notification", "Severity"]
