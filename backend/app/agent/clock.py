"""The agent's clock.

Two clocks matter and conflating them is a bug:

* Wall time - what `datetime.now()` says.
* Market time - which session the data belongs to.

With daily bars these differ by up to three days over a weekend. Measuring
freshness in seconds meant a Friday close looked "25 hours stale" on a Saturday
and the agent refused to act on perfectly good data; and running against wall
time meant it was permanently outside a session.

In simulation the market clock is authoritative: the agent is placed mid-session
on the day of the most recent bar. That is what a replay is.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market.calendar import is_trading_day, session_close_utc
from app.models import Bar

# Placed deliberately away from both edges of the session.
MID_SESSION = time(14, 30)


async def latest_bar_date(session: AsyncSession) -> date | None:
    ts = await session.scalar(
        select(Bar.ts).where(Bar.timeframe == "1d").order_by(Bar.ts.desc()).limit(1)
    )
    return ts.date() if ts else None


async def market_clock(session: AsyncSession, *, fallback: datetime | None = None) -> datetime:
    """Mid-session on the day of the most recent bar."""
    day = await latest_bar_date(session)
    if day is None:
        return fallback or datetime.now(UTC)
    # session_close_utc handles the Eastern offset; mid-session is 90 minutes before.
    return session_close_utc(day) - timedelta(minutes=90)


def sessions_between(earlier: date, later: date) -> int:
    """Trading days from `earlier` to `later`. Negative if the order is reversed."""
    if later < earlier:
        return -sessions_between(later, earlier)
    count = 0
    day = earlier
    while day < later:
        day += timedelta(days=1)
        if is_trading_day(day):
            count += 1
    return count


__all__ = ["MID_SESSION", "latest_bar_date", "market_clock", "sessions_between"]
