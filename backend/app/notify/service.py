"""Notification routing.

Three severities, and the distinction is the whole point of the feature:

* IMMEDIATE - something happened that you might need to act on.
* DIGEST    - batched into one message at the close.
* SILENT    - recorded for the record, never pushed.

Everything is written to the database whether or not it is delivered, so
"why didn't I hear about this?" always has an answer. Duplicate messages inside
a short window are suppressed rather than sent twice: an agent that pages you
five times about the same stop loss trains you to ignore it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Channel, DeliveryStatus, Notification, Severity, User
from app.notify.telegram import TelegramClient

log = get_logger(__name__)

DEDUPE_WINDOW = timedelta(minutes=30)

# Which events page you and which wait for the digest.
SEVERITY_BY_EVENT: dict[str, Severity] = {
    "trade.executed": Severity.IMMEDIATE,
    "target.hit": Severity.IMMEDIATE,
    "stop.triggered": Severity.IMMEDIATE,
    "circuit_breaker": Severity.IMMEDIATE,
    "approval.requested": Severity.IMMEDIATE,
    "agent.error": Severity.IMMEDIATE,
    "reconciliation.failed": Severity.IMMEDIATE,
    "order.rejected": Severity.DIGEST,
    "agent.tick": Severity.SILENT,
    "digest.daily": Severity.IMMEDIATE,
    "weekly.review": Severity.IMMEDIATE,
}


async def _recently_sent(
    session: AsyncSession, user_id: uuid.UUID, event: str, dedupe_key: str, now: datetime
) -> bool:
    stmt = select(Notification).where(
        Notification.user_id == user_id,
        Notification.event == event,
        Notification.dedupe_key == dedupe_key,
        Notification.created_at >= now - DEDUPE_WINDOW,
        Notification.status == DeliveryStatus.SENT,
    ).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def notify(
    session: AsyncSession,
    user: User,
    *,
    event: str,
    title: str,
    body: str,
    dedupe_key: str | None = None,
    payload: dict | None = None,
    buttons: list[list[dict]] | None = None,
    client: TelegramClient | None = None,
    now: datetime | None = None,
) -> Notification:
    """Record and, if the severity and configuration allow, deliver."""
    now = now or datetime.now(UTC)
    severity = SEVERITY_BY_EVENT.get(event, Severity.DIGEST)

    notification = Notification(
        user_id=user.id, event=event, severity=severity,
        channel=Channel.TELEGRAM if user.telegram_chat_id else Channel.IN_APP,
        title=title[:160], body=body, dedupe_key=dedupe_key,
        payload=payload or {},
    )

    if severity is Severity.SILENT:
        notification.status = DeliveryStatus.SUPPRESSED
        session.add(notification)
        return notification

    if dedupe_key and await _recently_sent(session, user.id, event, dedupe_key, now):
        notification.status = DeliveryStatus.SUPPRESSED
        notification.error = "duplicate within the dedupe window"
        session.add(notification)
        return notification

    if severity is Severity.DIGEST or not user.telegram_chat_id:
        notification.status = DeliveryStatus.PENDING
        session.add(notification)
        return notification

    client = client or TelegramClient()
    result = await client.send(user.telegram_chat_id, f"{title}\n\n{body}", buttons=buttons)
    if result.ok:
        notification.status = DeliveryStatus.SENT
        notification.sent_at = now
    else:
        notification.status = DeliveryStatus.FAILED
        notification.error = result.error
    session.add(notification)
    # structlog reserves `event` for the message itself, so the field is named
    # event_type - passing event= here raised TypeError on every delivery.
    log.info("notification", event_type=event, status=str(notification.status))
    return notification


async def pending_digest(session: AsyncSession, user: User) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.user_id == user.id,
        Notification.severity == Severity.DIGEST,
        Notification.status == DeliveryStatus.PENDING,
    ).order_by(Notification.created_at)
    return list((await session.execute(stmt)).scalars())


async def flush_digest(
    session: AsyncSession, user: User, header: str, *, client: TelegramClient | None = None
) -> int:
    """Send everything batched since the last flush as one message."""
    items = await pending_digest(session, user)
    if not user.telegram_chat_id:
        return 0

    lines = [header]
    if items:
        lines.append("")
        for item in items:
            lines.append(f"• {item.title}")

    client = client or TelegramClient()
    result = await client.send(user.telegram_chat_id, "\n".join(lines))
    now = datetime.now(UTC)
    for item in items:
        item.status = DeliveryStatus.SENT if result.ok else DeliveryStatus.FAILED
        item.sent_at = now if result.ok else None
        if not result.ok:
            item.error = result.error

    # autoflush is off session-wide, so without this a caller that re-queries
    # immediately still sees these rows as pending.
    await session.flush()
    return len(items)


def link_token() -> str:
    return uuid.uuid4().hex[:16]


__all__ = [
    "DEDUPE_WINDOW",
    "SEVERITY_BY_EVENT",
    "flush_digest",
    "link_token",
    "notify",
    "pending_digest",
]
