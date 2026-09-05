"""Replay the agent over history.

The agent is not re-implemented here. The backtest drives the *same* loop, the
same gate and the same exchange, one simulated session at a time, with `as_of`
pinned to that day. If the backtest and live behaviour ever diverge, one of them
is wrong - and with a re-implementation you would never find out which.

The benchmark is equal-weight buy-and-hold of the same symbols over the same
window. It is the only comparison that matters: a strategy that underperforms
buying the list and doing nothing is a worse version of doing nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run_tick
from app.backtest.metrics import Performance, block_bootstrap, evaluate
from app.core.logging import get_logger
from app.market.calendar import session_close_utc, trading_days
from app.models import (
    Account,
    AgentDecision,
    AgentRun,
    AutonomyLevel,
    Bar,
    Fill,
    Instrument,
    Order,
    Policy,
    Position,
    RunTrigger,
    User,
    Watchlist,
    WatchlistItem,
)
from app.services.users import create_user

log = get_logger(__name__)

MID_SESSION_OFFSET = timedelta(minutes=-90)


@dataclass
class BacktestResult:
    label: str
    start: date
    end: date
    symbols: list[str]
    equity_curve: list[float] = field(default_factory=list)
    benchmark_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    strategy: Performance | None = None
    benchmark: Performance | None = None
    bootstrap: dict = field(default_factory=dict)
    orders_placed: int = 0
    denials: int = 0
    denial_breakdown: dict = field(default_factory=dict)
    capital_deployed_pct: float = 0.0

    @property
    def excess_return_pct(self) -> float | None:
        if self.strategy is None or self.benchmark is None:
            return None
        return round(self.strategy.total_return_pct - self.benchmark.total_return_pct, 2)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "symbols": self.symbols,
            "dates": self.dates,
            "equity_curve": self.equity_curve,
            "benchmark_curve": self.benchmark_curve,
            "strategy": self.strategy.to_dict() if self.strategy else None,
            "benchmark": self.benchmark.to_dict() if self.benchmark else None,
            "excess_return_pct": self.excess_return_pct,
            "bootstrap": self.bootstrap,
            "orders_placed": self.orders_placed,
            "denials": self.denials,
            "denial_breakdown": self.denial_breakdown,
            "capital_deployed_pct": self.capital_deployed_pct,
            "beat_benchmark": (self.excess_return_pct or 0) > 0,
        }


async def _benchmark_curve(
    session: AsyncSession, instruments: list[Instrument], days: list[date],
    starting_cash: Decimal,
) -> list[float]:
    """Equal-weight buy-and-hold, bought at the first session and never touched."""
    per_name = float(starting_cash) / len(instruments)
    curve: list[float] = []
    holdings: dict[uuid.UUID, float] = {}

    for i, day in enumerate(days):
        ts = session_close_utc(day)
        total = 0.0
        for instrument in instruments:
            price = await session.scalar(
                select(Bar.close)
                .where(Bar.instrument_id == instrument.id, Bar.timeframe == "1d",
                       Bar.ts <= ts)
                .order_by(Bar.ts.desc())
                .limit(1)
            )
            if price is None:
                continue
            if i == 0:
                holdings[instrument.id] = per_name / float(price)
            total += holdings.get(instrument.id, 0.0) * float(price)
        curve.append(round(total, 2))
    return curve


async def _teardown(session: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """Backtests leave no trace in the live tables."""
    await session.execute(delete(AgentDecision).where(AgentDecision.account_id == account_id))
    await session.execute(delete(AgentRun).where(AgentRun.user_id == user_id))
    await session.execute(delete(Fill).where(Fill.account_id == account_id))
    await session.execute(delete(Order).where(Order.account_id == account_id))
    await session.execute(delete(Position).where(Position.account_id == account_id))
    await session.execute(delete(WatchlistItem).where(
        WatchlistItem.watchlist_id.in_(
            select(Watchlist.id).where(Watchlist.user_id == user_id)
        )
    ))
    await session.execute(delete(Watchlist).where(Watchlist.user_id == user_id))
    await session.execute(delete(Policy).where(Policy.user_id == user_id))
    await session.execute(delete(Account).where(Account.id == account_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.flush()


async def run_backtest(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    symbols: list[str] | None = None,
    universe_size: int = 12,
    starting_cash: Decimal = Decimal("100000.00"),
    policy_overrides: dict | None = None,
    label: str = "backtest",
    keep_account: bool = False,
    use_reviewer: bool = False,
) -> BacktestResult:
    """Drive the live agent loop across a historical window."""
    days = trading_days(start, end)
    if len(days) < 30:
        raise ValueError("a backtest needs at least 30 trading days")

    stmt = select(Instrument).where(Instrument.is_tradable.is_(True))
    if symbols:
        stmt = stmt.where(Instrument.symbol.in_([s.upper() for s in symbols]))
    else:
        stmt = stmt.order_by(Instrument.sector, Instrument.symbol).limit(universe_size)
    instruments = list((await session.execute(stmt)).scalars())
    if not instruments:
        raise ValueError("no instruments matched the requested universe")

    # An ephemeral account, torn down afterwards.
    user = await create_user(
        session,
        email=f"backtest-{uuid.uuid4().hex[:12]}@backtest.local",
        password=uuid.uuid4().hex + "aA1!",
        display_name=label,
    )
    await session.flush()
    account = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalar_one()
    account.starting_cash = starting_cash
    account.cash = starting_cash
    account.equity = starting_cash

    watchlist = (
        await session.execute(select(Watchlist).where(Watchlist.user_id == user.id))
    ).scalar_one()
    for i, instrument in enumerate(instruments):
        session.add(WatchlistItem(watchlist_id=watchlist.id, instrument_id=instrument.id,
                                  conviction=(i % 3) + 1))

    policy = (
        await session.execute(select(Policy).where(Policy.user_id == user.id))
    ).scalar_one()
    policy.autonomy_level = AutonomyLevel.FULL_AUTO
    for key, value in (policy_overrides or {}).items():
        setattr(policy, key, value)
    await session.flush()

    equity_curve: list[float] = []
    dates: list[str] = []
    orders = denials = 0

    for day in days:
        clock = session_close_utc(day) + MID_SESSION_OFFSET
        run = await run_tick(
            session, user, trigger=RunTrigger.BACKTEST, now=clock,
            use_reviewer=use_reviewer,
        )
        orders += run.orders_placed
        denials += run.denials
        equity_curve.append(float(account.equity))
        dates.append(day.isoformat())

    # Why did it not act? Without this the answer to "it underperformed" is a
    # shrug; with it, the blocking constraint is named.
    breakdown_rows = (
        await session.execute(
            select(AgentDecision.denial, func.count())
            .join(AgentRun, AgentRun.id == AgentDecision.run_id)
            .where(AgentRun.user_id == user.id, AgentDecision.denial.is_not(None))
            .group_by(AgentDecision.denial)
            .order_by(func.count().desc())
        )
    ).all()
    breakdown = {reason: count for reason, count in breakdown_rows}

    holdings_value = float(account.equity) - float(account.cash)
    deployed = (
        round(holdings_value / float(account.equity) * 100, 1)
        if account.equity > 0 else 0.0
    )

    benchmark_curve = await _benchmark_curve(session, instruments, days, starting_cash)

    # Realised trade outcomes, for hit rate and profit factor.
    positions = list(
        (await session.execute(select(Position).where(Position.account_id == account.id))).scalars()
    )
    trade_returns = [
        float(p.realised_pnl) / float(starting_cash)
        for p in positions
        if p.realised_pnl != 0
    ]

    result = BacktestResult(
        label=label, start=start, end=end,
        symbols=[i.symbol for i in instruments],
        equity_curve=equity_curve, benchmark_curve=benchmark_curve, dates=dates,
        strategy=evaluate(np.array(equity_curve), trade_returns=trade_returns,
                          trades=orders),
        benchmark=evaluate(np.array(benchmark_curve)),
        bootstrap=block_bootstrap(np.array(equity_curve)),
        orders_placed=orders, denials=denials,
        denial_breakdown=breakdown, capital_deployed_pct=deployed,
    )

    if not keep_account:
        await _teardown(session, user.id, account.id)

    log.info(
        "backtest_complete", label=label, days=len(days), orders=orders,
        strategy_return=result.strategy.total_return_pct,
        benchmark_return=result.benchmark.total_return_pct,
    )
    return result


async def walk_forward(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    split: float = 0.6,
    **kwargs,
) -> dict:
    """Split the window, run both halves, and compare.

    A strategy that shines in-sample and collapses out-of-sample was fitted to
    the past, not to the market. This is the check that catches it.
    """
    days = trading_days(start, end)
    if len(days) < 120:
        raise ValueError("walk-forward needs at least 120 trading days")
    boundary = days[int(len(days) * split)]

    in_sample = await run_backtest(
        session, start=start, end=boundary, label="in-sample", **kwargs
    )
    out_of_sample = await run_backtest(
        session, start=boundary, end=end, label="out-of-sample", **kwargs
    )

    decay = None
    if in_sample.strategy and out_of_sample.strategy:
        decay = round(
            out_of_sample.strategy.annualised_return_pct
            - in_sample.strategy.annualised_return_pct,
            2,
        )

    return {
        "boundary": boundary.isoformat(),
        "in_sample": in_sample.to_dict(),
        "out_of_sample": out_of_sample.to_dict(),
        "annualised_return_decay_pct": decay,
        "held_up_out_of_sample": bool(
            out_of_sample.strategy and out_of_sample.strategy.total_return_pct > 0
        ),
    }


async def ab_compare(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    **kwargs,
) -> dict:
    """Run the same window twice: rules only, then rules plus the reviewer.

    This is the question phase 08 exists to answer, and the answer is allowed to
    be "the model made it worse". It is slow - a local model costs seconds per
    symbol per session - so keep the window short and the universe small.
    """
    rules_only = await run_backtest(
        session, start=start, end=end, label="rules-only", use_reviewer=False, **kwargs
    )
    reviewed = await run_backtest(
        session, start=start, end=end, label="with-reviewer", use_reviewer=True, **kwargs
    )

    verdict = "no measurable difference"
    if reviewed.strategy and rules_only.strategy:
        delta = reviewed.strategy.total_return_pct - rules_only.strategy.total_return_pct
        if delta > 0.5:
            verdict = "the reviewer helped"
        elif delta < -0.5:
            verdict = "the reviewer hurt"

    return {
        "rules_only": rules_only.to_dict(),
        "with_reviewer": reviewed.to_dict(),
        "verdict": verdict,
        "return_delta_pct": (
            round(reviewed.strategy.total_return_pct - rules_only.strategy.total_return_pct, 2)
            if reviewed.strategy and rules_only.strategy else None
        ),
    }


__all__ = ["BacktestResult", "ab_compare", "run_backtest", "walk_forward"]
