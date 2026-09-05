"""The agent loop and its clock.

The properties that matter for leaving it running unattended: it never trades
through a halt, dry-run places nothing, one bad symbol does not abandon the
tick, and every decision is recorded with a reason whether or not it acted.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agent.clock import market_clock, sessions_between
from app.agent.loop import _target_quantity, run_tick
from app.agent.worker import HALT_KEY, singleton_lock
from app.core.db import SessionLocal
from app.models import (
    Account,
    AgentDecision,
    AgentRun,
    AutonomyLevel,
    Instrument,
    Order,
    Policy,
    RunStatus,
    RunTrigger,
    User,
    Watchlist,
    WatchlistItem,
)
from app.services.users import create_user

# --- the clock (pure) --------------------------------------------------------

def test_sessions_between_skips_weekends():
    # Friday 4 Sep 2026 to Monday 7 Sep... which is Labor Day, so Tuesday.
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 5)) == 0
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 7)) == 0
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 8)) == 1


def test_sessions_between_is_zero_for_the_same_day():
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 4)) == 0


def test_sessions_between_is_signed():
    assert sessions_between(date(2026, 9, 8), date(2026, 9, 4)) == -1


def test_a_friday_close_is_not_stale_on_a_saturday():
    """The bug this replaced: measuring staleness in seconds made a Friday close
    look 25 hours old on Saturday, and the agent refused to act on good data."""
    assert sessions_between(date(2026, 9, 4), date(2026, 9, 5)) == 0


# --- sizing (pure) -----------------------------------------------------------

def test_target_quantity_scales_with_conviction():
    low = _target_quantity(Decimal("100000"), Decimal("100"), Decimal("10"), 0.3, 1.0)
    high = _target_quantity(Decimal("100000"), Decimal("100"), Decimal("10"), 0.9, 1.0)
    assert high > low


def test_target_quantity_respects_the_conviction_tier():
    full = _target_quantity(Decimal("100000"), Decimal("100"), Decimal("10"), 0.8, 1.0)
    half = _target_quantity(Decimal("100000"), Decimal("100"), Decimal("10"), 0.8, 0.5)
    assert half < full


def test_target_quantity_is_zero_without_a_price():
    assert _target_quantity(Decimal("100000"), Decimal(0), Decimal("10"), 1.0, 1.0) == 0


def test_target_quantity_never_exceeds_the_position_budget():
    quantity = _target_quantity(Decimal("100000"), Decimal("50"), Decimal("10"), 1.0, 1.0)
    assert quantity * 50 <= 100_000 * 0.10


# --- integration -------------------------------------------------------------

pytestmark_integration = pytest.mark.integration


@pytest.fixture
async def agent_user():
    """A user with a populated watchlist and full autonomy."""
    async with SessionLocal() as session:
        user = await create_user(
            session,
            email=f"agent-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()

        instruments = list(
            (
                await session.execute(
                    select(Instrument).where(Instrument.is_tradable.is_(True)).limit(6)
                )
            ).scalars()
        )
        if not instruments:
            pytest.skip("no instruments loaded - run the market seed first")

        watchlist = (
            await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))
        ).scalar_one()
        for instrument in instruments:
            session.add(
                WatchlistItem(watchlist_id=watchlist.id, instrument_id=instrument.id,
                              conviction=3)
            )

        policy = (
            await session.execute(select(Policy).where(Policy.user_id == user.id))
        ).scalar_one()
        policy.autonomy_level = AutonomyLevel.FULL_AUTO
        await session.flush()

        yield session, user, len(instruments)
        await session.rollback()


@pytest.mark.integration
async def test_a_tick_records_a_run_and_a_decision_for_every_symbol(agent_user):
    session, user, count = agent_user
    clock = await market_clock(session)
    run = await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock)

    assert run.status == RunStatus.COMPLETED
    assert run.symbols_examined == count
    assert run.duration_ms is not None

    decisions = list(
        (
            await session.execute(
                select(AgentDecision).where(AgentDecision.run_id == run.id)
            )
        ).scalars()
    )
    assert len(decisions) == count
    for decision in decisions:
        assert decision.rationale, "every decision must say why, including holds"


@pytest.mark.integration
async def test_a_halt_stops_every_order(agent_user):
    session, user, _ = agent_user
    clock = await market_clock(session)
    run = await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock,
                         global_halt=True)

    assert run.orders_placed == 0
    denials = {
        d.denial
        for d in (
            await session.execute(
                select(AgentDecision).where(
                    AgentDecision.run_id == run.id, AgentDecision.denial.is_not(None)
                )
            )
        ).scalars()
    }
    assert denials <= {"global_halt"}


@pytest.mark.integration
async def test_dry_run_evaluates_everything_and_places_nothing(agent_user):
    session, user, _ = agent_user
    clock = await market_clock(session)

    before = len(list((await session.execute(select(Order))).scalars()))
    run = await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock, dry_run=True)
    after = len(list((await session.execute(select(Order))).scalars()))

    assert run.orders_placed == 0
    assert after == before, "a dry run placed an order"
    assert run.summary["dry_run"] is True


@pytest.mark.integration
async def test_observe_autonomy_denies_every_intent(agent_user):
    session, user, _ = agent_user
    policy = (
        await session.execute(select(Policy).where(Policy.user_id == user.id))
    ).scalar_one()
    policy.autonomy_level = AutonomyLevel.OBSERVE
    await session.flush()

    clock = await market_clock(session)
    run = await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock)
    assert run.orders_placed == 0

    denials = {
        d.denial
        for d in (
            await session.execute(
                select(AgentDecision).where(
                    AgentDecision.run_id == run.id, AgentDecision.denial.is_not(None)
                )
            )
        ).scalars()
    }
    assert denials <= {"observe_only"}


@pytest.mark.integration
async def test_a_tick_never_breaches_the_daily_trade_limit(agent_user):
    session, user, _ = agent_user
    policy = (
        await session.execute(select(Policy).where(Policy.user_id == user.id))
    ).scalar_one()
    policy.max_trades_per_day = 2
    await session.flush()

    clock = await market_clock(session)
    run = await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock)
    assert run.orders_placed <= 2


@pytest.mark.integration
async def test_the_ledger_still_reconciles_after_the_agent_trades(agent_user):
    """The agent is just another order source. It must not be able to corrupt
    what the exchange guarantees."""
    from app.execution import service as execution

    session, user, _ = agent_user
    clock = await market_clock(session)
    await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock)

    account = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalar_one()
    expected = await execution.cash_from_fills(session, account)
    assert abs(account.cash - expected) < Decimal("0.01")


@pytest.mark.integration
async def test_a_user_without_a_policy_is_skipped_not_crashed():
    async with SessionLocal() as session:
        user = User(email=f"nopolicy-{uuid.uuid4().hex[:8]}@example.com",
                    password_hash="x", is_active=True)
        session.add(user)
        await session.flush()

        run = await run_tick(session, user, trigger=RunTrigger.MANUAL,
                             now=datetime.now(UTC))
        assert run.status == RunStatus.SKIPPED
        assert run.error
        await session.rollback()


@pytest.mark.integration
async def test_runs_are_recorded_even_when_nothing_happens(agent_user):
    session, user, _ = agent_user
    clock = await market_clock(session)
    await run_tick(session, user, trigger=RunTrigger.MANUAL, now=clock, global_halt=True)

    runs = list(
        (await session.execute(select(AgentRun).where(AgentRun.user_id == user.id))).scalars()
    )
    assert len(runs) == 1
    assert runs[0].finished_at is not None


# --- the singleton lock ------------------------------------------------------

@pytest.mark.integration
async def test_only_one_worker_can_hold_the_tick_lock():
    from redis.asyncio import Redis

    from app.core.config import settings

    redis = Redis.from_url(settings.redis_url)
    key = f"test:lock:{uuid.uuid4().hex[:8]}"
    try:
        async with singleton_lock(redis, key) as first:
            assert first is True
            async with singleton_lock(redis, key) as second:
                assert second is False, "two workers held the lock at once"
        # Released on exit, so the next holder gets it.
        async with singleton_lock(redis, key) as third:
            assert third is True
    finally:
        await redis.delete(key)
        await redis.aclose()


@pytest.mark.integration
async def test_the_halt_flag_is_readable_from_redis():
    from redis.asyncio import Redis

    from app.agent.worker import is_halted
    from app.core.config import settings

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.delete(HALT_KEY)
        assert await is_halted(redis) is False
        await redis.set(HALT_KEY, "test")
        assert await is_halted(redis) is True
    finally:
        await redis.delete(HALT_KEY)
        await redis.aclose()
