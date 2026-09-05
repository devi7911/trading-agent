"""The agent loop.

One tick is one pass through eight stages. It is idempotent: every intent
carries a key derived from (run, symbol, direction), so a crashed tick that is
retried cannot place the same order twice.

The loop proposes. The gate disposes. Nothing here can place an order the gate
has not sized, and no exception in one symbol is allowed to abandon the rest.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import build_context, collect_shared, load_series
from app.core.logging import correlation_id, get_logger
from app.execution import service as execution
from app.execution.port import OrderRequest
from app.models import (
    Account,
    AgentDecision,
    AgentRun,
    Bar,
    Instrument,
    Policy,
    Position,
    RunStatus,
    RunTrigger,
    Side,
    User,
    Watchlist,
    WatchlistItem,
)
from app.risk import gate
from app.risk.types import Intent, Verdict
from app.strategy.signals import Direction
from app.strategy.strategies import consensus, evaluate_all

log = get_logger(__name__)

# Conviction below this is not worth a trade after costs.
MIN_CONVICTION = 0.25

# Conviction tier multipliers on the position cap, from the watchlist.
CONVICTION_TIER_WEIGHT = {1: 0.5, 2: 0.75, 3: 1.0}


class TickError(Exception):
    pass


def _intent_key(run_id: uuid.UUID, symbol: str, direction: Direction) -> str:
    """Idempotency: the same run cannot act twice on the same symbol and side."""
    return f"{run_id}:{symbol}:{direction}"


def _target_quantity(
    equity: Decimal, price: Decimal, max_position_pct: Decimal,
    conviction: float, tier_weight: float,
) -> int:
    """Size from conviction, then let the gate cap it.

    Sizing here is a proposal, never an entitlement - the gate shrinks it to fit
    the position cap, the sector cap and the cash floor.
    """
    if price <= 0:
        return 0
    budget = equity * max_position_pct / 100
    scaled = budget * Decimal(str(conviction)) * Decimal(str(tier_weight))
    return int(scaled / price)


async def _exit_intent(
    session: AsyncSession, account: Account, policy: Policy,
    instrument: Instrument, position: Position, as_of: datetime,
) -> Intent | None:
    """Stop loss and take profit, evaluated before any new entry is considered.

    Protecting an open position always outranks opening another.
    """
    bar = (
        await session.execute(
            select(Bar)
            .where(
                Bar.instrument_id == instrument.id,
                Bar.timeframe == "1d",
                Bar.ts <= as_of,
            )
            .order_by(Bar.ts.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if bar is None or position.avg_cost <= 0:
        return None

    change = (bar.close / position.avg_cost - 1) * 100
    if change <= -policy.stop_loss_pct:
        return Intent(
            symbol=instrument.symbol, direction=Direction.SELL,
            quantity=position.quantity, conviction=1.0,
            rationale=f"Stop loss: down {abs(change):.1f}% against an average cost of "
                      f"{position.avg_cost:.2f}, limit {policy.stop_loss_pct}%.",
            strategy="risk_exit",
        )
    if change >= policy.take_profit_pct:
        return Intent(
            symbol=instrument.symbol, direction=Direction.SELL,
            quantity=position.quantity, conviction=0.9,
            rationale=f"Take profit: up {change:.1f}% against an average cost of "
                      f"{position.avg_cost:.2f}, target {policy.take_profit_pct}%.",
            strategy="risk_exit",
        )
    return None


async def run_tick(
    session: AsyncSession,
    user: User,
    *,
    trigger: RunTrigger = RunTrigger.SCHEDULED,
    global_halt: bool = False,
    now: datetime | None = None,
    dry_run: bool = False,
) -> AgentRun:
    """One pass of the loop. Always returns a persisted AgentRun, even on failure."""
    now = now or datetime.now(UTC)
    started = time.perf_counter()
    cid = correlation_id.get() or str(uuid.uuid4())

    account = (
        await session.execute(select(Account).where(Account.user_id == user.id).limit(1))
    ).scalar_one_or_none()
    policy = (
        await session.execute(
            select(Policy)
            .where(Policy.user_id == user.id, Policy.is_active.is_(True))
            .order_by(Policy.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    run = AgentRun(
        user_id=user.id,
        account_id=account.id if account else None,
        policy_id=policy.id if policy else None,
        trigger=trigger,
        status=RunStatus.RUNNING,
        correlation_id=cid,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    if account is None or policy is None:
        run.status = RunStatus.SKIPPED
        run.error = "The account has no active policy."
        run.finished_at = datetime.now(UTC)
        return run

    try:
        # --- 1. perceive: the watchlist plus everything already held ---------
        symbols = await _universe(session, user, account)
        run.symbols_examined = len(symbols)

        # --- 3. recall: the parts of the world shared across every symbol ----
        exposure, trades_today, symbol_trades, day_start = await collect_shared(
            session, account, now
        )
        seen_keys: set[str] = set()

        for instrument, tier in symbols:
            try:
                decision = await _consider(
                    session, run, account, policy, instrument, tier,
                    now=now, global_halt=global_halt, sector_exposure=exposure,
                    trades_today=trades_today, symbol_trades=symbol_trades,
                    seen_keys=frozenset(seen_keys), dry_run=dry_run,
                    day_start_equity=day_start,
                )
            except Exception as exc:
                # One bad symbol must not abandon the rest of the tick.
                log.exception("symbol_failed", symbol=instrument.symbol, error=str(exc))
                continue

            if decision is None:
                continue
            session.add(decision)
            await session.flush()

            if decision.approved:
                run.orders_placed += 1
                trades_today += 1
                symbol_trades[instrument.id] = symbol_trades.get(instrument.id, 0) + 1
                seen_keys.add(_intent_key(run.id, decision.symbol, decision.direction))
            elif decision.denial:
                run.denials += 1
            if decision.direction != str(Direction.HOLD):
                run.intents_formed += 1

        # --- 7. observe -----------------------------------------------------
        await execution._mark_to_market(session, account, as_of=now)

        run.status = RunStatus.COMPLETED
        run.summary = {
            "equity": str(account.equity),
            "cash": str(account.cash),
            "dry_run": dry_run,
            "autonomy": str(policy.autonomy_level),
        }
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:4000]
        log.exception("tick_failed", error=str(exc))

    run.finished_at = datetime.now(UTC)
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    await session.flush()
    log.info(
        "tick_complete",
        status=str(run.status),
        symbols=run.symbols_examined,
        intents=run.intents_formed,
        orders=run.orders_placed,
        denials=run.denials,
        ms=run.duration_ms,
    )
    return run


async def _universe(
    session: AsyncSession, user: User, account: Account
) -> list[tuple[Instrument, int]]:
    """The watchlist, plus anything held that has fallen off it.

    A position that is no longer on the watchlist still needs managing - it
    cannot be orphaned just because it was removed from a list.
    """
    stmt = (
        select(Instrument, WatchlistItem.conviction)
        .join(WatchlistItem, WatchlistItem.instrument_id == Instrument.id)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user.id, Instrument.is_tradable.is_(True))
    )
    rows = {i.id: (i, tier) for i, tier in (await session.execute(stmt)).all()}

    held = (
        select(Instrument)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(Position.account_id == account.id, Position.quantity != 0)
    )
    for instrument in (await session.execute(held)).scalars():
        rows.setdefault(instrument.id, (instrument, 2))

    return sorted(rows.values(), key=lambda pair: pair[0].symbol)


async def _consider(
    session: AsyncSession,
    run: AgentRun,
    account: Account,
    policy: Policy,
    instrument: Instrument,
    tier: int,
    *,
    now: datetime,
    global_halt: bool,
    sector_exposure: dict,
    trades_today: int,
    symbol_trades: dict,
    seen_keys: frozenset[str],
    dry_run: bool,
    day_start_equity: Decimal,
) -> AgentDecision | None:
    """Stages 2 through 6 for a single symbol."""
    # --- 2. enrich ---
    series = await load_series(session, instrument.id, as_of=now)
    if series is None:
        return None
    series = type(series)(
        symbol=instrument.symbol, close=series.close, high=series.high,
        low=series.low, volume=series.volume,
    )

    position = (
        await session.execute(
            select(Position).where(
                Position.account_id == account.id, Position.instrument_id == instrument.id
            )
        )
    ).scalar_one_or_none()

    # --- 4. reason ---
    signals = evaluate_all(series)
    combined = consensus(signals)

    intent: Intent | None = None
    if position is not None and position.quantity > 0:
        intent = await _exit_intent(session, account, policy, instrument, position, now)

    if intent is None:
        if combined.direction is Direction.HOLD or combined.strength < MIN_CONVICTION:
            return AgentDecision(
                run_id=run.id, account_id=account.id, instrument_id=instrument.id,
                symbol=instrument.symbol, direction=str(Direction.HOLD),
                requested_quantity=0, approved_quantity=0,
                conviction=round(combined.strength, 4), approved=False, denial=None,
                rationale=combined.reason,
                signals={"signals": [
                    {"strategy": s.strategy, "direction": str(s.direction),
                     "strength": round(s.strength, 4), "reason": s.reason,
                     "indicators": s.indicators}
                    for s in signals
                ]},
            )
        quantity = _target_quantity(
            account.equity, Decimal(str(series.last)),
            policy.max_position_pct, combined.strength,
            CONVICTION_TIER_WEIGHT.get(tier, 0.75),
        )
        if quantity <= 0:
            return None
        intent = Intent(
            symbol=instrument.symbol, direction=combined.direction, quantity=quantity,
            conviction=round(combined.strength, 4), rationale=combined.reason,
            strategy="consensus",
        )

    intent = Intent(
        symbol=intent.symbol, direction=intent.direction, quantity=intent.quantity,
        conviction=intent.conviction, rationale=intent.rationale,
        strategy=intent.strategy,
        idempotency_key=_intent_key(run.id, intent.symbol, intent.direction),
    )

    # --- 5. gate ---
    ctx = await build_context(
        session, account, policy, instrument, now=now,
        as_of_day=now.date(), global_halt=global_halt,
        sector_exposure=sector_exposure, trades_today=trades_today,
        symbol_trades=symbol_trades, seen_keys=seen_keys,
        day_start_equity=day_start_equity,
    )
    verdict: Verdict = gate.evaluate(intent, ctx)

    decision = AgentDecision(
        run_id=run.id, account_id=account.id, instrument_id=instrument.id,
        symbol=instrument.symbol, direction=str(intent.direction),
        requested_quantity=intent.quantity, approved_quantity=verdict.quantity,
        conviction=intent.conviction, approved=False,
        denial=str(verdict.denial) if verdict.denial else None,
        rationale=intent.rationale,
        signals={"signals": [
            {"strategy": s.strategy, "direction": str(s.direction),
             "strength": round(s.strength, 4), "reason": s.reason}
            for s in signals
        ], "strategy": intent.strategy},
        risk_trace={"verdict": verdict.message, "checks": verdict.trace()},
        context_snapshot={
            "price": str(ctx.price), "equity": str(ctx.equity), "cash": str(ctx.cash),
            "held": ctx.held_quantity, "sector": ctx.sector,
            "sector_exposure": str(ctx.sector_exposure),
            "trades_today": ctx.trades_today, "autonomy": ctx.autonomy_level,
        },
    )

    if not verdict.approved:
        return decision

    # --- 6. execute ---
    if dry_run:
        decision.approved = False
        decision.denial = "dry_run"
        return decision

    order = await execution.place_order(
        session, account,
        OrderRequest(
            symbol=intent.symbol,
            side=Side.BUY if intent.direction is Direction.BUY else Side.SELL,
            quantity=verdict.quantity,
            client_order_id=intent.idempotency_key,
            note=intent.rationale[:255],
        ),
        allow_shorting=policy.allow_shorting,
        actor="agent",
        as_of=now,
    )
    decision.order_id = order.id
    decision.approved = order.filled_quantity > 0
    if order.filled_quantity == 0:
        decision.denial = str(order.reject_reason) if order.reject_reason else "not_filled"
    return decision


__all__ = ["MIN_CONVICTION", "TickError", "run_tick"]
