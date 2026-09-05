"""Execution against the real database: positions, cash and the ledger.

The phase gate for the exchange is that a long run of random orders leaves
stored state agreeing with the fill history to the cent. Everything else in the
exchange can be plausible; if the ledger drifts, none of it is usable.

Runs inside compose:  docker compose exec api pytest -m integration
"""

import random
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.execution import service as execution
from app.execution.port import OrderRequest
from app.models import Account, Instrument, Order, OrderStatus, Position, Side
from app.services.users import create_user

pytestmark = pytest.mark.integration

CENT = Decimal("0.01")


@pytest.fixture
async def ledger():
    """A fresh funded account plus a handful of liquid symbols."""
    async with SessionLocal() as session:
        user = await create_user(
            session,
            email=f"ledger-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()
        account = (
            await session.execute(select(Account).where(Account.user_id == user.id))
        ).scalar_one()

        symbols = list(
            (
                await session.execute(
                    select(Instrument.symbol)
                    .where(Instrument.is_tradable.is_(True))
                    .order_by(Instrument.symbol)
                    .limit(8)
                )
            ).scalars()
        )
        if not symbols:
            pytest.skip("no instruments loaded - run the market seed first")

        yield session, account, symbols
        await session.rollback()


async def _place(session, account, symbol, side, quantity):
    return await execution.place_order(
        session,
        account,
        OrderRequest(symbol=symbol, side=side, quantity=quantity),
        actor="test",
    )


# --- basic mechanics ---------------------------------------------------------

async def test_a_buy_creates_a_position_and_spends_cash(ledger):
    session, account, symbols = ledger
    before = account.cash

    order = await _place(session, account, symbols[0], Side.BUY, 10)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 10

    position = (
        await session.execute(
            select(Position).where(Position.account_id == account.id)
        )
    ).scalar_one()
    assert position.quantity == 10
    assert account.cash < before


async def test_selling_realises_profit_and_loss(ledger):
    session, account, symbols = ledger
    await _place(session, account, symbols[0], Side.BUY, 20)
    await _place(session, account, symbols[0], Side.SELL, 20)

    position = (
        await session.execute(select(Position).where(Position.account_id == account.id))
    ).scalar_one()
    assert position.quantity == 0
    assert position.avg_cost == 0
    # Crossing the spread twice with no price move must lose money.
    assert position.realised_pnl < 0


async def test_average_cost_is_weighted_across_buys(ledger):
    session, account, symbols = ledger
    first = await _place(session, account, symbols[0], Side.BUY, 10)
    second = await _place(session, account, symbols[0], Side.BUY, 30)

    position = (
        await session.execute(select(Position).where(Position.account_id == account.id))
    ).scalar_one()
    expected = (first.avg_fill_price * 10 + second.avg_fill_price * 30) / 40
    assert abs(position.avg_cost - expected) < Decimal("0.01")
    assert position.quantity == 40


# --- guards ------------------------------------------------------------------

async def test_cannot_sell_what_the_account_does_not_hold(ledger):
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.SELL, 5)
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == "insufficient_position"


async def test_cannot_spend_more_cash_than_the_account_holds(ledger):
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.BUY, 900_000)
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == "insufficient_buying_power"


async def test_a_halted_account_cannot_trade(ledger):
    session, account, symbols = ledger
    account.is_halted = True
    account.halt_reason = "circuit breaker"
    order = await _place(session, account, symbols[0], Side.BUY, 1)
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason == "account_halted"


async def test_unknown_symbols_are_refused(ledger):
    session, account, _ = ledger
    with pytest.raises(execution.OrderRejected):
        await _place(session, account, "NOSUCH", Side.BUY, 1)


async def test_a_rejected_order_is_still_recorded(ledger):
    """Rejections are audit trail, not exceptions to swallow."""
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.SELL, 5)
    stored = await session.get(Order, order.id)
    assert stored is not None
    assert stored.status == OrderStatus.REJECTED
    assert stored.closed_at is not None


# --- idempotency and the state machine ---------------------------------------

async def test_a_repeated_client_order_id_does_not_place_twice(ledger):
    session, account, symbols = ledger
    key = f"retry-{uuid.uuid4().hex[:8]}"
    request = OrderRequest(
        symbol=symbols[0], side=Side.BUY, quantity=7, client_order_id=key
    )
    first = await execution.place_order(session, account, request, actor="test")
    second = await execution.place_order(session, account, request, actor="test")

    assert first.id == second.id
    position = (
        await session.execute(select(Position).where(Position.account_id == account.id))
    ).scalar_one()
    assert position.quantity == 7, "the retry placed a second order"


async def test_a_filled_order_cannot_be_cancelled(ledger):
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.BUY, 5)
    with pytest.raises(execution.IllegalTransition):
        await execution.cancel_order(session, account, order)


async def test_illegal_transitions_are_refused(ledger):
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.BUY, 5)
    assert order.status == OrderStatus.FILLED
    with pytest.raises(execution.IllegalTransition):
        execution.transition(order, OrderStatus.SUBMITTED)


# --- the gate ----------------------------------------------------------------

@pytest.mark.slow
async def test_the_ledger_reconciles_after_hundreds_of_random_orders(ledger):
    """Phase 02's acceptance gate.

    Random buys and sells across several symbols, then rebuild cash and every
    position from the fill history alone and compare. Any drift is a bug in how
    fills are applied, and it compounds silently once an agent is trading.
    """
    session, account, symbols = ledger
    rng = random.Random(20260905)
    held: dict[str, int] = dict.fromkeys(symbols, 0)

    placed = 0
    for _ in range(400):
        symbol = rng.choice(symbols)
        can_sell = held[symbol] > 0
        side = Side.SELL if (can_sell and rng.random() < 0.45) else Side.BUY
        quantity = (
            rng.randint(1, held[symbol]) if side == Side.SELL else rng.randint(1, 25)
        )

        order = await _place(session, account, symbol, side, quantity)
        placed += 1
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            delta = order.filled_quantity
            held[symbol] += delta if side == Side.BUY else -delta

    assert placed == 400

    expected_cash = await execution.cash_from_fills(session, account)
    assert abs(account.cash - expected_cash) < CENT, (
        f"cash drifted: stored {account.cash}, fills imply {expected_cash}"
    )

    rebuilt = await execution.rebuild_positions_from_fills(session, account)
    stored = list(
        (
            await session.execute(select(Position).where(Position.account_id == account.id))
        ).scalars()
    )
    assert stored, "expected at least one position"

    for position in stored:
        expected = rebuilt[position.instrument_id]
        assert position.quantity == expected["quantity"]
        assert abs(position.realised_pnl - expected["realised_pnl"]) < CENT
        assert abs(position.avg_cost - expected["avg_cost"]) < Decimal("0.0001")


@pytest.mark.slow
async def test_no_position_ever_goes_negative_without_shorting(ledger):
    session, account, symbols = ledger
    rng = random.Random(7)
    for _ in range(120):
        symbol = rng.choice(symbols[:3])
        side = Side.BUY if rng.random() < 0.5 else Side.SELL
        await _place(session, account, symbol, side, rng.randint(1, 30))

    positions = list(
        (
            await session.execute(select(Position).where(Position.account_id == account.id))
        ).scalars()
    )
    for position in positions:
        assert position.quantity >= 0, "shorting is disabled but a position went short"


@pytest.mark.slow
async def test_cash_never_goes_negative(ledger):
    session, account, symbols = ledger
    rng = random.Random(99)
    for _ in range(150):
        await _place(session, account, rng.choice(symbols), Side.BUY, rng.randint(1, 60))
        assert account.cash >= 0, "the account spent money it did not have"


async def test_enum_columns_survive_a_round_trip_through_the_database(ledger):
    """Regression: `side` is a String column, so a StrEnum comes back as a plain
    str after a reload. `is` comparison then silently fails and every buy is
    accounted for as a sell - which drifted cash by 850k on the first run of the
    ledger gate."""
    session, account, symbols = ledger
    order = await _place(session, account, symbols[0], Side.BUY, 3)
    order_id = order.id

    await session.flush()
    session.expire_all()

    # Expired attributes reload lazily, which is IO - it has to be awaited
    # explicitly under asyncio rather than triggered by attribute access.
    reloaded = await session.get(Order, order_id)
    await session.refresh(account)

    assert reloaded.side == Side.BUY
    assert reloaded.status == OrderStatus.FILLED
    # Recomputing cash from fills must agree whichever way the enum came back.
    expected = await execution.cash_from_fills(session, account)
    assert abs(account.cash - expected) < CENT


@pytest.mark.slow
async def test_the_ledger_has_a_total_order_independent_of_timestamps():
    """Regression: fills were replayed in `filled_at` order, but simulated
    acknowledgement latency jitters by up to ~200ms, so two orders placed in the
    same instant can have their fills timestamped out of sequence. Replaying a
    sell before the buy that funded it drove a position negative and then
    divided by zero. `ledger_seq` is assigned by the database in commit order.
    """
    from app.models import Fill

    async with SessionLocal() as session:
        user = await create_user(
            session,
            email=f"seq-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()
        account = (
            await session.execute(select(Account).where(Account.user_id == user.id))
        ).scalar_one()
        symbols = list(
            (
                await session.execute(
                    select(Instrument.symbol).where(Instrument.is_tradable.is_(True)).limit(3)
                )
            ).scalars()
        )
        if not symbols:
            pytest.skip("no instruments loaded")

        for _ in range(12):
            await _place(session, account, symbols[0], Side.BUY, 5)
            await _place(session, account, symbols[0], Side.SELL, 3)
        await session.flush()

        fills = list(
            (
                await session.execute(
                    select(Fill).where(Fill.account_id == account.id).order_by(Fill.ledger_seq)
                )
            ).scalars()
        )
        assert len(fills) >= 24

        sequences = [f.ledger_seq for f in fills]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences), "ledger sequence is not unique"

        # Replaying in ledger order must never take the position negative.
        running = 0
        for fill in fills:
            order = await session.get(Order, fill.order_id)
            running += fill.quantity if order.side == Side.BUY else -fill.quantity
            assert running >= 0, "ledger replay drove the position negative"

        await session.rollback()
