"""Order lifecycle, positions and cash.

The rules this module exists to enforce:

* Fills are the only thing that move cash or position. Positions are derived,
  never edited, so the ledger can always be rebuilt from the fill history.
* Status changes go through `transition`, which refuses any move the state
  machine does not allow rather than corrupting the order silently.
* A repeated client_order_id returns the original order. Retries are safe.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id, get_logger
from app.execution.engine import MarketContext, execute
from app.execution.port import ExecutionResult, OrderRequest
from app.models import (
    ALLOWED_TRANSITIONS,
    Account,
    AuditLog,
    Bar,
    Fill,
    Instrument,
    Order,
    OrderStatus,
    Position,
    RejectReason,
    Side,
)

log = get_logger(__name__)

CENT = Decimal("0.01")


class IllegalTransition(Exception):
    """Attempted a status change the state machine forbids."""


class OrderRejected(Exception):
    def __init__(self, reason: RejectReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def transition(order: Order, new_status: OrderStatus) -> None:
    allowed = ALLOWED_TRANSITIONS[order.status]
    if new_status not in allowed:
        raise IllegalTransition(
            f"{order.status} -> {new_status} is not a legal transition "
            f"(allowed: {sorted(allowed) or 'none, terminal'})"
        )
    order.status = new_status


# --- market context ---------------------------------------------------------


async def _latest_bar(
    session: AsyncSession, instrument_id: uuid.UUID, as_of: datetime | None = None
) -> Bar | None:
    """The most recent bar AT OR BEFORE `as_of`.

    `as_of` is what makes a backtest honest: without it, a replay of 2023 would
    price its decisions using 2026 data and every result would be fiction.
    """
    stmt = select(Bar).where(Bar.instrument_id == instrument_id, Bar.timeframe == "1d")
    if as_of is not None:
        stmt = stmt.where(Bar.ts <= as_of)
    stmt = stmt.order_by(Bar.ts.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def market_context(
    session: AsyncSession,
    instrument: Instrument,
    *,
    market_open: bool = True,
    as_of: datetime | None = None,
) -> MarketContext:
    bar = await _latest_bar(session, instrument.id, as_of)
    reference = bar.close if bar else Decimal(0)

    # Daily volatility from the annualised figure the generator assigned.
    daily_vol = float(instrument.annual_vol or 0.30) / (252**0.5)

    avg_volume = 1_000_000
    if bar:
        volume_stmt = select(Bar.volume).where(
            Bar.instrument_id == instrument.id, Bar.timeframe == "1d"
        )
        if as_of is not None:
            volume_stmt = volume_stmt.where(Bar.ts <= as_of)
        recent = volume_stmt.order_by(Bar.ts.desc()).limit(21).subquery()
        avg = await session.scalar(select(func.avg(recent.c.volume)))
        if avg:
            avg_volume = int(avg)

    return MarketContext(
        symbol=instrument.symbol,
        reference_price=reference,
        daily_vol=daily_vol,
        avg_volume=avg_volume,
        is_open=market_open,
        is_tradable=instrument.is_tradable,
    )


# --- pre-trade checks -------------------------------------------------------


async def _position_for(
    session: AsyncSession, account_id: uuid.UUID, instrument_id: uuid.UUID
) -> Position | None:
    stmt = select(Position).where(
        Position.account_id == account_id, Position.instrument_id == instrument_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _pre_trade_checks(
    session: AsyncSession,
    account: Account,
    instrument: Instrument,
    request: OrderRequest,
    context: MarketContext,
    *,
    allow_shorting: bool,
) -> None:
    """Raises OrderRejected. These are account-level rules; the venue applies
    its own separately inside the engine."""
    if account.is_halted:
        raise OrderRejected(
            RejectReason.ACCOUNT_HALTED,
            account.halt_reason or "Trading on this account is halted.",
        )

    if request.side == Side.BUY:
        # Price the worst case: a limit order can cost its limit, a market order
        # is estimated from the reference plus a generous allowance for spread.
        unit = request.limit_price or (context.reference_price * Decimal("1.01"))
        needed = (unit * request.quantity).quantize(CENT)
        if needed > account.cash:
            raise OrderRejected(
                RejectReason.INSUFFICIENT_BUYING_POWER,
                f"Order needs {needed} but the account holds {account.cash}.",
            )
    else:
        position = await _position_for(session, account.id, instrument.id)
        held = position.quantity if position else 0
        if request.quantity > held and not allow_shorting:
            raise OrderRejected(
                RejectReason.INSUFFICIENT_POSITION,
                f"Cannot sell {request.quantity}; the account holds {held} "
                f"and shorting is disabled.",
            )


# --- applying fills ---------------------------------------------------------


async def _apply_fill(
    session: AsyncSession,
    account: Account,
    instrument: Instrument,
    order: Order,
    *,
    sequence: int,
    quantity: int,
    price: Decimal,
    commission: Decimal,
    slippage_bps: Decimal,
    filled_at: datetime,
) -> Fill:
    """The only place cash and position change."""
    fill = Fill(
        order_id=order.id,
        account_id=account.id,
        instrument_id=instrument.id,
        sequence=sequence,
        quantity=quantity,
        price=price,
        commission=commission,
        slippage_bps=slippage_bps,
        filled_at=filled_at,
    )
    session.add(fill)

    gross = (price * quantity).quantize(CENT)
    position = await _position_for(session, account.id, instrument.id)
    if position is None:
        position = Position(
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=0,
            avg_cost=Decimal(0),
            realised_pnl=Decimal(0),
            total_commission=Decimal(0),
            opened_at=filled_at,
        )
        session.add(position)
        await session.flush()

    if order.side == Side.BUY:
        account.cash = (account.cash - gross - commission).quantize(CENT)
        new_quantity = position.quantity + quantity
        # Weighted average cost. Commission is expensed, not capitalised, so the
        # cost basis stays comparable with the quoted price.
        total_cost = position.avg_cost * position.quantity + price * quantity
        position.avg_cost = (total_cost / new_quantity).quantize(Decimal("0.000001"))
        position.quantity = new_quantity
        if position.opened_at is None:
            position.opened_at = filled_at
        position.closed_at = None
    else:
        account.cash = (account.cash + gross - commission).quantize(CENT)
        realised = ((price - position.avg_cost) * quantity).quantize(CENT)
        position.realised_pnl = (position.realised_pnl + realised).quantize(CENT)
        position.quantity -= quantity
        if position.quantity == 0:
            position.avg_cost = Decimal(0)
            position.closed_at = filled_at

    position.total_commission = (position.total_commission + commission).quantize(CENT)

    # Roll the average forward arithmetically. Summing `order.fills` here would
    # lazy-load the relationship and raise MissingGreenlet inside async code -
    # and it costs a query per fill for a number we already know.
    previous_quantity = order.filled_quantity
    previous_notional = (order.avg_fill_price or Decimal(0)) * previous_quantity

    order.filled_quantity = previous_quantity + quantity
    order.commission = (order.commission + commission).quantize(CENT)
    order.avg_fill_price = (
        (previous_notional + price * quantity) / order.filled_quantity
    ).quantize(Decimal("0.0001"))
    return fill


# --- public API -------------------------------------------------------------


async def place_order(
    session: AsyncSession,
    account: Account,
    request: OrderRequest,
    *,
    market_open: bool = True,
    allow_shorting: bool = False,
    actor: str = "user",
    as_of: datetime | None = None,
) -> Order:
    """Submit an order. Always returns an Order - a rejection is a persisted
    order in REJECTED state, not an exception, because a rejected order is part
    of the audit trail and the agent needs to see why."""
    as_of = as_of or datetime.now(UTC)
    client_order_id = request.client_order_id or str(uuid.uuid4())

    # Idempotency: a repeat of the same key returns the original order.
    existing = (
        await session.execute(
            select(Order).where(
                Order.account_id == account.id, Order.client_order_id == client_order_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        log.info("order_idempotent_hit", client_order_id=client_order_id)
        return existing

    instrument = (
        await session.execute(
            select(Instrument).where(Instrument.symbol == request.symbol.upper())
        )
    ).scalar_one_or_none()
    if instrument is None:
        raise OrderRejected(
            RejectReason.SYMBOL_NOT_TRADABLE, f"Unknown symbol {request.symbol.upper()}."
        )

    order = Order(
        account_id=account.id,
        instrument_id=instrument.id,
        client_order_id=client_order_id,
        side=request.side,
        order_type=request.order_type,
        time_in_force=request.time_in_force,
        quantity=request.quantity,
        limit_price=request.limit_price,
        stop_price=request.stop_price,
        note=request.note,
        status=OrderStatus.NEW,
    )
    session.add(order)
    await session.flush()

    context = await market_context(
        session, instrument, market_open=market_open, as_of=as_of
    )

    try:
        await _pre_trade_checks(
            session, account, instrument, request, context, allow_shorting=allow_shorting
        )
    except OrderRejected as exc:
        transition(order, OrderStatus.REJECTED)
        order.reject_reason = exc.reason
        order.note = exc.message[:255]
        order.closed_at = as_of
        await _audit(session, account, order, "order.rejected", actor, {"reason": exc.reason})
        log.info("order_rejected", reason=exc.reason, symbol=instrument.symbol)
        return order

    transition(order, OrderStatus.SUBMITTED)
    order.submitted_at = as_of

    result: ExecutionResult = execute(request, context, as_of=as_of, seed=client_order_id)

    if not result.accepted:
        transition(order, OrderStatus.REJECTED)
        order.reject_reason = result.reject_reason
        order.note = (result.message or "")[:255]
        order.closed_at = as_of
        await _audit(session, account, order, "order.rejected", actor,
                     {"reason": result.reject_reason})
        log.info("order_rejected_by_venue", reason=result.reject_reason)
        return order

    for event in result.fills:
        await _apply_fill(
            session, account, instrument, order,
            sequence=event.sequence,
            quantity=event.quantity,
            price=event.price,
            commission=event.commission,
            slippage_bps=event.slippage_bps,
            filled_at=event.filled_at,
        )
        await session.flush()

    if order.filled_quantity == order.quantity:
        transition(order, OrderStatus.FILLED)
        order.closed_at = as_of
    elif order.filled_quantity > 0:
        transition(order, OrderStatus.PARTIALLY_FILLED)

    await _mark_to_market(session, account, as_of=as_of)
    await _audit(session, account, order, "order.placed", actor, {
        "symbol": instrument.symbol,
        "side": str(order.side),
        "quantity": order.quantity,
        "filled": order.filled_quantity,
        "avg_price": str(order.avg_fill_price) if order.avg_fill_price else None,
        "status": str(order.status),
    })
    await session.flush()
    log.info(
        "order_executed",
        symbol=instrument.symbol,
        side=str(order.side),
        quantity=order.quantity,
        filled=order.filled_quantity,
        status=str(order.status),
    )
    return order


async def cancel_order(
    session: AsyncSession, account: Account, order: Order, *, actor: str = "user"
) -> Order:
    if not order.is_open:
        raise IllegalTransition(f"Order is already {order.status} and cannot be cancelled.")
    transition(order, OrderStatus.CANCELLED)
    order.closed_at = datetime.now(UTC)
    await _audit(session, account, order, "order.cancelled", actor, {})
    return order


async def _mark_to_market(
    session: AsyncSession, account: Account, *, as_of: datetime | None = None
) -> Decimal:
    """Equity = cash + the market value of every open position."""
    stmt = select(Position).where(
        Position.account_id == account.id, Position.quantity != 0
    )
    positions = list((await session.execute(stmt)).scalars())

    market_value = Decimal(0)
    for position in positions:
        bar = await _latest_bar(session, position.instrument_id, as_of)
        if bar:
            market_value += bar.close * position.quantity

    account.equity = (account.cash + market_value).quantize(CENT)
    return account.equity


async def _audit(
    session: AsyncSession,
    account: Account,
    order: Order,
    action: str,
    actor: str,
    payload: dict,
) -> None:
    session.add(
        AuditLog(
            actor_type=actor,
            actor_id=account.user_id,
            action=action,
            entity_type="order",
            entity_id=order.id,
            correlation_id=correlation_id.get(),
            payload=payload,
        )
    )


# --- reconciliation ---------------------------------------------------------


async def rebuild_positions_from_fills(
    session: AsyncSession, account: Account
) -> dict[uuid.UUID, dict]:
    """Recompute every position from the fill history.

    This is the reconciliation job: if the stored positions disagree with what
    the fills imply, the fills win and the difference is a bug worth halting on.
    """
    stmt = (
        select(Fill)
        .where(Fill.account_id == account.id)
        .order_by(Fill.ledger_seq)
    )
    fills = list((await session.execute(stmt)).scalars())

    state: dict[uuid.UUID, dict] = {}
    for fill in fills:
        order = await session.get(Order, fill.order_id)
        entry = state.setdefault(
            fill.instrument_id,
            {"quantity": 0, "avg_cost": Decimal(0), "realised_pnl": Decimal(0),
             "commission": Decimal(0)},
        )
        if order.side == Side.BUY:
            new_quantity = entry["quantity"] + fill.quantity
            total = entry["avg_cost"] * entry["quantity"] + fill.price * fill.quantity
            entry["avg_cost"] = (total / new_quantity).quantize(Decimal("0.000001"))
            entry["quantity"] = new_quantity
        else:
            realised = ((fill.price - entry["avg_cost"]) * fill.quantity).quantize(CENT)
            entry["realised_pnl"] = (entry["realised_pnl"] + realised).quantize(CENT)
            entry["quantity"] -= fill.quantity
            if entry["quantity"] == 0:
                entry["avg_cost"] = Decimal(0)
        entry["commission"] = (entry["commission"] + fill.commission).quantize(CENT)

    return state


async def cash_from_fills(session: AsyncSession, account: Account) -> Decimal:
    """What cash should be, given the starting balance and every fill since."""
    stmt = select(Fill).where(Fill.account_id == account.id).order_by(Fill.ledger_seq)
    fills = list((await session.execute(stmt)).scalars())

    # Replay exactly as _apply_fill does, including the per-fill rounding to
    # the cent. Summing at full precision and rounding once at the end drifts
    # from the stored balance by up to half a cent per fill, which would make
    # this audit report a leak where there is none.
    cash = account.starting_cash
    for fill in fills:
        order = await session.get(Order, fill.order_id)
        gross = (fill.price * fill.quantity).quantize(CENT)
        if order.side == Side.BUY:
            cash = (cash - gross - fill.commission).quantize(CENT)
        else:
            cash = (cash + gross - fill.commission).quantize(CENT)
    return cash


__all__ = [
    "IllegalTransition",
    "OrderRejected",
    "cancel_order",
    "cash_from_fills",
    "market_context",
    "place_order",
    "rebuild_positions_from_fills",
    "transition",
]
