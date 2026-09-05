"""Backtest metrics, and the point-in-time guarantee.

Lookahead is the way a backtest lies most often and most convincingly, so the
cutoff gets a dedicated test rather than trust.
"""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import select

from app.agent.context import load_series
from app.backtest.metrics import block_bootstrap, evaluate, longest_drawdown
from app.core.db import SessionLocal
from app.models import Bar, Instrument

# --- metrics (pure) ----------------------------------------------------------

def test_total_return_is_first_to_last():
    p = evaluate(np.array([100.0, 110.0, 150.0]))
    assert p.total_return_pct == pytest.approx(50.0)


def test_max_drawdown_finds_the_worst_trough():
    p = evaluate(np.array([100.0, 200.0, 100.0, 180.0]))
    assert p.max_drawdown_pct == pytest.approx(-50.0)


def test_a_monotonic_curve_has_no_drawdown():
    p = evaluate(np.array([100.0, 101.0, 102.0, 103.0]))
    assert p.max_drawdown_pct == pytest.approx(0.0)
    assert p.longest_drawdown_days == 0


def test_longest_drawdown_counts_consecutive_days_below_the_peak():
    equity = np.array([100.0, 90.0, 91.0, 92.0, 105.0, 104.0])
    assert longest_drawdown(equity) == 3


def test_a_flat_curve_has_no_sharpe():
    p = evaluate(np.full(50, 100.0))
    assert p.sharpe is None
    assert p.annualised_vol_pct == pytest.approx(0.0)


def test_sortino_ignores_upside_volatility():
    """A curve that only jumps upward has no downside deviation at all."""
    equity = np.array([100.0, 101.0, 105.0, 106.0, 120.0])
    p = evaluate(equity)
    assert p.sortino is None or p.sortino > (p.sharpe or 0)


def test_win_rate_and_profit_factor_come_from_trade_outcomes():
    p = evaluate(np.array([100.0, 110.0]), trade_returns=[0.1, 0.2, -0.1], trades=3)
    assert p.win_rate_pct == pytest.approx(66.7, abs=0.1)
    assert p.profit_factor == pytest.approx(3.0)


def test_a_single_point_curve_is_rejected():
    with pytest.raises(ValueError, match="two equity points"):
        evaluate(np.array([100.0]))


def test_bootstrap_brackets_the_realised_outcome():
    rng = np.random.default_rng(3)
    equity = 100 * np.cumprod(1 + rng.normal(0.0006, 0.01, 400))
    result = block_bootstrap(equity, samples=200, seed=1)
    assert result["samples"] == 200
    assert result["p05_return_pct"] < result["median_return_pct"] < result["p95_return_pct"]
    assert 0 <= result["probability_of_loss_pct"] <= 100


def test_bootstrap_declines_on_a_short_series():
    assert block_bootstrap(np.array([100.0, 101.0, 102.0]))["samples"] == 0


# --- the point-in-time guarantee --------------------------------------------

@pytest.mark.integration
async def test_load_series_never_returns_data_after_the_cutoff():
    """The whole validity of a backtest rests on this one property."""
    async with SessionLocal() as session:
        instrument = (
            await session.execute(
                select(Instrument).where(Instrument.is_tradable.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if instrument is None:
            pytest.skip("no instruments loaded")

        newest = await session.scalar(
            select(Bar.ts)
            .where(Bar.instrument_id == instrument.id)
            .order_by(Bar.ts.desc())
            .limit(1)
        )
        cutoff = newest - timedelta(days=120)

        full = await load_series(session, instrument.id, lookback=5000)
        limited = await load_series(session, instrument.id, lookback=5000, as_of=cutoff)

        assert full is not None and limited is not None
        assert len(limited) < len(full), "the cutoff had no effect"

        # The last bar before the cutoff must be the last bar in the series.
        expected_close = await session.scalar(
            select(Bar.close)
            .where(Bar.instrument_id == instrument.id, Bar.ts <= cutoff,
                   Bar.timeframe == "1d")
            .order_by(Bar.ts.desc())
            .limit(1)
        )
        assert limited.close[-1] == pytest.approx(float(expected_close))


@pytest.mark.integration
async def test_two_cutoffs_produce_a_strict_prefix():
    """History up to an earlier date must be a prefix of history up to a later
    one - if it is not, something is being recomputed with hindsight."""
    async with SessionLocal() as session:
        instrument = (
            await session.execute(
                select(Instrument).where(Instrument.is_tradable.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if instrument is None:
            pytest.skip("no instruments loaded")

        newest = await session.scalar(
            select(Bar.ts)
            .where(Bar.instrument_id == instrument.id)
            .order_by(Bar.ts.desc())
            .limit(1)
        )
        early = await load_series(
            session, instrument.id, lookback=5000, as_of=newest - timedelta(days=200)
        )
        late = await load_series(
            session, instrument.id, lookback=5000, as_of=newest - timedelta(days=100)
        )
        assert early is not None and late is not None
        assert np.allclose(late.close[: len(early)], early.close)


@pytest.mark.integration
@pytest.mark.slow
async def test_a_backtest_runs_and_reports_against_a_benchmark():
    from datetime import date

    from app.agent.clock import latest_bar_date
    from app.backtest.runner import run_backtest

    async with SessionLocal() as session:
        last = await latest_bar_date(session)
        if last is None:
            pytest.skip("no market data loaded")

        result = await run_backtest(
            session, start=last - timedelta(days=200), end=last,
            universe_size=4, label="test",
        )
        assert result.strategy is not None
        assert result.benchmark is not None
        assert len(result.equity_curve) == len(result.dates)
        assert result.excess_return_pct is not None
        assert isinstance(result.start, date)

        # The account must be gone: a backtest leaves no trace in the live tables.
        from app.models import Account

        leftovers = list(
            (
                await session.execute(
                    select(Account).join(
                        Account.user.property.mapper.class_,
                        Account.user_id == Account.user.property.mapper.class_.id,
                    ).where(
                        Account.user.property.mapper.class_.email.like("backtest-%")
                    )
                )
            ).scalars()
        )
        assert not leftovers, "the backtest left an account behind"
        await session.rollback()


def test_backtest_needs_a_meaningful_window():
    import asyncio
    from datetime import date

    from app.backtest.runner import run_backtest

    async def go():
        async with SessionLocal() as session:
            with pytest.raises(ValueError, match="30 trading days"):
                await run_backtest(session, start=date(2026, 8, 1), end=date(2026, 8, 10))

    asyncio.get_event_loop_policy()
    _ = uuid.uuid4()
    _ = datetime.now(UTC)
    asyncio.run(go())
