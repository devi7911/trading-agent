"""The calendar is rule-based, so it must be right for years nobody checked by hand."""

from datetime import date

from app.market import calendar as cal


def test_weekends_are_closed():
    assert not cal.is_trading_day(date(2026, 9, 5))   # Saturday
    assert not cal.is_trading_day(date(2026, 9, 6))   # Sunday
    assert cal.is_trading_day(date(2026, 9, 8))       # Tuesday


def test_known_holidays_2026():
    closed = [
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Day, 3rd Monday
        date(2026, 2, 16),   # Presidents' Day, 3rd Monday
        date(2026, 4, 3),    # Good Friday
        date(2026, 5, 25),   # Memorial Day, last Monday
        date(2026, 6, 19),   # Juneteenth
        date(2026, 7, 3),    # July 4th falls Saturday, observed Friday
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    ]
    for d in closed:
        assert not cal.is_trading_day(d), f"{d} should be closed"


def test_good_friday_tracks_easter():
    # Easter Sunday 2027 is 28 March, so Good Friday is the 26th.
    assert date(2027, 3, 26) in cal.holidays(2027)


def test_holiday_observance_shifts_off_the_weekend():
    # 4 July 2026 is a Saturday - observed on Friday the 3rd, not the 4th.
    assert date(2026, 7, 3) in cal.holidays(2026)
    assert date(2026, 7, 4) not in cal.holidays(2026)


def test_early_closes():
    assert date(2026, 11, 27) in cal.early_closes(2026)  # day after Thanksgiving
    assert cal.close_time(date(2026, 11, 27)).hour == 13
    assert cal.close_time(date(2026, 11, 30)).hour == 16


def test_trading_day_count_is_realistic():
    for year in (2024, 2025, 2026, 2027):
        n = len(cal.trading_days(date(year, 1, 1), date(year, 12, 31)))
        assert 248 <= n <= 254, f"{year} produced {n} trading days"


def test_session_close_respects_daylight_saving():
    # January: Eastern is UTC-5, so a 16:00 close is 21:00 UTC.
    assert cal.session_close_utc(date(2026, 1, 15)).hour == 21
    # July: Eastern is UTC-4, so a 16:00 close is 20:00 UTC.
    assert cal.session_close_utc(date(2026, 7, 15)).hour == 20


def test_navigation_skips_closures():
    # Friday 2026-11-27 is a half day but open; Thursday the 26th is Thanksgiving.
    assert cal.previous_trading_day(date(2026, 11, 27)) == date(2026, 11, 25)
    assert cal.next_trading_day(date(2026, 12, 24)) == date(2026, 12, 28)
