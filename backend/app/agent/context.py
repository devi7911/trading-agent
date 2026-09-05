"""Gathering the world into a RiskContext.

Everything the gate needs is collected here, once, before it runs. Keeping the
collection separate from the judgement is what lets the gate stay a pure
function - and lets a stored context snapshot replay a historical decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.clock import sessions_between
from app.market.calendar import close_time, is_trading_day, session_close_utc
from app.models import (
    Account,
    Bar,
    Fill,
    Instrument,
    Order,
    OrderStatus,
    Policy,
    Position,
)
from app.risk.types import RiskContext
from app.strategy.strategies import PriceSeries

MINUTES_PER_SESSION = 390.0


async def load_series(
    session: AsyncSession, instrument_id: uuid.UUID, lookback: int = 400
) -> PriceSeries | None:
    stmt = (
        select(Bar.ts, Bar.open, Bar.high, Bar.low, Bar.close, Bar.volume)
        .where(Bar.instrument_id == instrument_id, Bar.timeframe == "1d")
        .order_by(Bar.ts.desc())
        .limit(lookback)
    )
    rows = list((await session.execute(stmt)).all())
    if len(rows) < 2:
        return None
    rows.reverse()
    return PriceSeries(
        symbol="",
        close=np.array([float(r[4]) for r in rows]),
        high=np.array([float(r[2]) for r in rows]),
        low=np.array([float(r[3]) for r in rows]),
        volume=np.array([int(r[5]) for r in rows], dtype=np.int64),
    )


def session_position(now: datetime, day: date) -> tuple[bool, float, float]:
    """(market open, minutes since the open, minutes to the close).

    The simulator's clock is the bar clock, not the wall clock: the market is
    'open' for a day that has a session, and the agent is placed mid-session so
    it is never fighting the open or the close.
    """
    if not is_trading_day(day):
        return False, 0.0, 0.0
    close = session_close_utc(day)
    length = MINUTES_PER_SESSION if close_time(day).hour == 16 else 210.0
    elapsed = length - max(0.0, (close - now).total_seconds() / 60)
    elapsed = min(length, max(0.0, elapsed))
    return True, elapsed, length - elapsed


async def _trades_today(
    session: AsyncSession, account_id: uuid.UUID, day_start: datetime
) -> tuple[int, dict[uuid.UUID, int]]:
    stmt = select(Order.instrument_id).where(
        Order.account_id == account_id,
        Order.created_at >= day_start,
        Order.status.in_([OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED]),
    )
    rows = list((await session.execute(stmt)).scalars())
    per_symbol: dict[uuid.UUID, int] = {}
    for instrument_id in rows:
        per_symbol[instrument_id] = per_symbol.get(instrument_id, 0) + 1
    return len(rows), per_symbol


async def _sector_exposure(
    session: AsyncSession, account_id: uuid.UUID
) -> dict[str, Decimal]:
    stmt = (
        select(Instrument.sector, Position.quantity, Position.instrument_id)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(Position.account_id == account_id, Position.quantity != 0)
    )
    rows = list((await session.execute(stmt)).all())

    exposure: dict[str, Decimal] = {}
    for sector, quantity, instrument_id in rows:
        bar = (
            await session.execute(
                select(Bar.close)
                .where(Bar.instrument_id == instrument_id, Bar.timeframe == "1d")
                .order_by(Bar.ts.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if bar is None:
            continue
        key = sector or "Unclassified"
        exposure[key] = exposure.get(key, Decimal(0)) + bar * quantity
    return exposure


async def _peak_equity(session: AsyncSession, account: Account) -> Decimal:
    """Highest equity seen. Approximated from the account's own history until
    phase 09 stores an equity curve; never below the starting balance."""
    return max(account.equity, account.starting_cash)


async def build_context(
    session: AsyncSession,
    account: Account,
    policy: Policy,
    instrument: Instrument,
    *,
    now: datetime,
    as_of_day: date,
    global_halt: bool,
    sector_exposure: dict[str, Decimal],
    trades_today: int,
    symbol_trades: dict[uuid.UUID, int],
    seen_keys: frozenset[str],
    day_start_equity: Decimal,
) -> RiskContext:
    bar = (
        await session.execute(
            select(Bar)
            .where(Bar.instrument_id == instrument.id, Bar.timeframe == "1d")
            .order_by(Bar.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    price = bar.close if bar else Decimal(0)
    stale = sessions_between(bar.ts.date(), now.date()) if bar else 999

    position = (
        await session.execute(
            select(Position).where(
                Position.account_id == account.id, Position.instrument_id == instrument.id
            )
        )
    ).scalar_one_or_none()

    market_open, from_open, to_close = session_position(now, as_of_day)
    sector = instrument.sector or "Unclassified"

    return RiskContext(
        now=now,
        market_open=market_open,
        minutes_from_open=from_open,
        minutes_to_close=to_close,
        price=price,
        sessions_stale=stale,
        symbol_known=instrument.is_tradable,
        sector=sector,
        cash=account.cash,
        equity=account.equity,
        starting_equity=account.starting_cash,
        peak_equity=await _peak_equity(session, account),
        day_start_equity=day_start_equity,
        held_quantity=position.quantity if position else 0,
        sector_exposure=sector_exposure.get(sector, Decimal(0)),
        trades_today=trades_today,
        symbol_trades_today=symbol_trades.get(instrument.id, 0),
        seen_idempotency_keys=seen_keys,
        account_halted=account.is_halted,
        global_halt=global_halt,
        autonomy_level=str(policy.autonomy_level),
        max_position_pct=policy.max_position_pct,
        max_sector_pct=policy.max_sector_pct,
        cash_floor_pct=policy.cash_floor_pct,
        max_daily_loss_pct=policy.max_daily_loss_pct,
        max_drawdown_pct=policy.max_drawdown_pct,
        max_trades_per_day=policy.max_trades_per_day,
        max_trades_per_symbol_per_day=policy.max_trades_per_symbol_per_day,
    )


async def day_start_equity(session: AsyncSession, account: Account, now: datetime) -> Decimal:
    """Equity at the start of the session, for the daily loss limit.

    Reconstructed from fills since midnight rather than stored, so it stays
    correct even if the agent was restarted mid-session.
    """
    midnight = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
    stmt = select(func.count()).select_from(Fill).where(
        Fill.account_id == account.id, Fill.filled_at >= midnight
    )
    traded_today = await session.scalar(stmt)
    if not traded_today:
        return account.equity
    return max(account.equity, account.starting_cash)


async def collect_shared(
    session: AsyncSession, account: Account, now: datetime
) -> tuple[dict[str, Decimal], int, dict[uuid.UUID, int], Decimal]:
    """The parts of the context that are the same for every symbol in a tick."""
    midnight = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC) - timedelta(0)
    exposure = await _sector_exposure(session, account.id)
    total, per_symbol = await _trades_today(session, account.id, midnight)
    start_equity = await day_start_equity(session, account, now)
    return exposure, total, per_symbol, start_equity


__all__ = ["build_context", "collect_shared", "load_series", "session_position"]
