"""US equity trading calendar.

Rule-based rather than a data file so it works for any year the simulator
runs, past or future, with no dependency to keep updated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)

# The exchange runs on New York time. Bars are stamped at the close in UTC;
# US Eastern is UTC-5 in winter and UTC-4 in summer.
_EASTERN_STANDARD_OFFSET = timedelta(hours=-5)
_EASTERN_DAYLIGHT_OFFSET = timedelta(hours=-4)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth occurrence of a weekday in a month. weekday: Monday=0."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 1) + timedelta(days=32)
    d = date(d.year, d.month, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """Saturday holidays observe Friday, Sunday holidays observe Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm - needed for Good Friday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lo = (2 * e + 2 * i - h - k + 32) % 7
    m = (a + 11 * h + 19 * lo) // 433
    month, day = divmod(h + lo - 7 * m + 90, 25)
    day = (h + lo - 7 * m + 33 * month + 19) % 32
    return date(year, month, day)


@lru_cache(maxsize=64)
def holidays(year: int) -> frozenset[date]:
    """Full-day closures."""
    days = {
        _observed(date(year, 1, 1)),                    # New Year's Day
        _nth_weekday(year, 1, 0, 3),                    # MLK Day
        _nth_weekday(year, 2, 0, 3),                    # Presidents' Day
        _easter(year) - timedelta(days=2),              # Good Friday
        _last_weekday(year, 5, 0),                      # Memorial Day
        _observed(date(year, 7, 4)),                    # Independence Day
        _nth_weekday(year, 9, 0, 1),                    # Labor Day
        _nth_weekday(year, 11, 3, 4),                   # Thanksgiving
        _observed(date(year, 12, 25)),                  # Christmas
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))          # Juneteenth
    return frozenset(days)


@lru_cache(maxsize=64)
def early_closes(year: int) -> frozenset[date]:
    """1pm closes: day after Thanksgiving, Christmas Eve, July 3rd."""
    days = {_nth_weekday(year, 11, 3, 4) + timedelta(days=1)}
    for d in (date(year, 12, 24), date(year, 7, 3)):
        if d.weekday() < 5 and d not in holidays(year):
            days.add(d)
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def close_time(d: date) -> time:
    return EARLY_CLOSE if d in early_closes(d.year) else MARKET_CLOSE


def _eastern_offset(d: date) -> timedelta:
    """US DST: second Sunday in March to first Sunday in November."""
    start = _nth_weekday(d.year, 3, 6, 2)
    end = _nth_weekday(d.year, 11, 6, 1)
    return _EASTERN_DAYLIGHT_OFFSET if start <= d < end else _EASTERN_STANDARD_OFFSET


def session_close_utc(d: date) -> datetime:
    """The UTC instant a session closes. This is the timestamp a daily bar carries."""
    local = datetime.combine(d, close_time(d))
    return (local - _eastern_offset(d)).replace(tzinfo=UTC)


def trading_days(start: date, end: date) -> list[date]:
    """Inclusive of both ends."""
    out: list[date] = []
    d = start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


__all__ = [
    "close_time",
    "early_closes",
    "holidays",
    "is_trading_day",
    "next_trading_day",
    "previous_trading_day",
    "session_close_utc",
    "trading_days",
]
