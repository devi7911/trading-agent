"""The risk gate.

This is the component that decides whether the system can be left running
unattended, so it gets the heaviest testing in the repository: worked examples
for every denial, and property tests that throw generated states at it to prove
no input can talk it past a cap.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.risk.gate import evaluate
from app.risk.types import Denial, Intent, RiskContext
from app.strategy.signals import Direction

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)


def ctx(**kwargs) -> RiskContext:
    base = dict(
        now=NOW,
        market_open=True,
        minutes_from_open=120.0,
        minutes_to_close=120.0,
        price=Decimal("100.00"),
        sessions_stale=0,
        symbol_known=True,
        sector="Technology",
        cash=Decimal("50000.00"),
        equity=Decimal("100000.00"),
        starting_equity=Decimal("100000.00"),
        peak_equity=Decimal("100000.00"),
        day_start_equity=Decimal("100000.00"),
        held_quantity=0,
        sector_exposure=Decimal("0"),
        trades_today=0,
        symbol_trades_today=0,
        seen_idempotency_keys=frozenset(),
        account_halted=False,
        global_halt=False,
        autonomy_level="full_auto",
        max_position_pct=Decimal("10"),
        max_sector_pct=Decimal("30"),
        cash_floor_pct=Decimal("10"),
        max_daily_loss_pct=Decimal("3"),
        max_drawdown_pct=Decimal("15"),
        max_trades_per_day=10,
        max_trades_per_symbol_per_day=2,
    )
    base.update(kwargs)
    return RiskContext(**base)


def buy(quantity: int = 50, **kwargs) -> Intent:
    return Intent(symbol="TEST", direction=Direction.BUY, quantity=quantity,
                  conviction=0.7, rationale="test", **kwargs)


def sell(quantity: int = 50, **kwargs) -> Intent:
    return Intent(symbol="TEST", direction=Direction.SELL, quantity=quantity,
                  conviction=0.7, rationale="test", **kwargs)


# --- the happy path ----------------------------------------------------------

def test_a_reasonable_buy_is_approved():
    verdict = evaluate(buy(50), ctx())
    assert verdict.approved
    assert verdict.quantity == 50
    assert verdict.denial is None


def test_every_verdict_carries_a_full_trace():
    trace = evaluate(buy(50), ctx()).trace()
    assert len(trace) >= 6
    assert all("check" in row and "passed" in row for row in trace)


# --- denials -----------------------------------------------------------------

@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"global_halt": True}, Denial.GLOBAL_HALT),
        ({"account_halted": True}, Denial.ACCOUNT_HALTED),
        ({"autonomy_level": "observe"}, Denial.OBSERVE_ONLY),
        ({"market_open": False}, Denial.MARKET_CLOSED),
        ({"minutes_from_open": 1.0}, Denial.NEAR_SESSION_EDGE),
        ({"minutes_to_close": 2.0}, Denial.NEAR_SESSION_EDGE),
        ({"sessions_stale": 9}, Denial.STALE_DATA),
        ({"price": Decimal(0)}, Denial.STALE_DATA),
        ({"symbol_known": False}, Denial.UNKNOWN_SYMBOL),
        ({"trades_today": 10}, Denial.TRADE_LIMIT_REACHED),
        ({"symbol_trades_today": 2}, Denial.SYMBOL_TRADE_LIMIT_REACHED),
        ({"equity": Decimal("96000")}, Denial.DAILY_LOSS_LIMIT),
        ({"equity": Decimal("84000"), "day_start_equity": Decimal("84000")},
         Denial.DRAWDOWN_LIMIT),
    ],
)
def test_each_condition_denies_with_its_own_code(kwargs, expected):
    verdict = evaluate(buy(10), ctx(**kwargs))
    assert not verdict.approved
    assert verdict.denial is expected
    assert verdict.quantity == 0
    assert verdict.message


def test_a_hold_is_not_an_order():
    intent = Intent("TEST", Direction.HOLD, 10, 0.5, "nothing to do")
    assert evaluate(intent, ctx()).denial is Denial.MALFORMED_INTENT


def test_zero_and_negative_quantities_are_refused():
    for quantity in (0, -5):
        intent = Intent("TEST", Direction.BUY, quantity, 0.5, "x")
        assert evaluate(intent, ctx()).denial is Denial.ZERO_QUANTITY


def test_conviction_outside_the_unit_interval_is_refused():
    intent = Intent("TEST", Direction.BUY, 10, 1.6, "overconfident")
    assert evaluate(intent, ctx()).denial is Denial.MALFORMED_INTENT


def test_a_repeated_idempotency_key_is_refused():
    verdict = evaluate(
        buy(10, idempotency_key="abc"), ctx(seen_idempotency_keys=frozenset({"abc"}))
    )
    assert verdict.denial is Denial.DUPLICATE_INTENT


# --- shrinking rather than denying -------------------------------------------

def test_the_position_cap_shrinks_an_oversized_order():
    """10% of 100k at 100 a share is 100 shares, however many were asked for."""
    verdict = evaluate(buy(500), ctx())
    assert verdict.approved
    assert verdict.quantity == 100
    assert verdict.was_reduced


def test_an_existing_position_reduces_the_remaining_room():
    verdict = evaluate(buy(500), ctx(held_quantity=60))
    assert verdict.quantity == 40


def test_a_position_already_at_its_cap_is_denied():
    verdict = evaluate(buy(10), ctx(held_quantity=100))
    assert verdict.denial is Denial.POSITION_CAP


def test_sector_concentration_shrinks_the_order():
    # 30% of 100k is 30k; 28k already held leaves room for 20 shares at 100.
    verdict = evaluate(buy(500), ctx(sector_exposure=Decimal("28000")))
    assert verdict.approved
    assert verdict.quantity == 20


def test_a_sector_already_at_its_cap_is_denied():
    verdict = evaluate(buy(10), ctx(sector_exposure=Decimal("30000")))
    assert verdict.denial is Denial.SECTOR_CONCENTRATION


def test_the_cash_floor_shrinks_the_order():
    # 12k cash, a 10k floor: only 2k is spendable, so 20 shares at 100.
    verdict = evaluate(buy(500), ctx(cash=Decimal("12000")))
    assert verdict.approved
    assert verdict.quantity == 20


def test_cash_at_the_floor_is_denied():
    verdict = evaluate(buy(10), ctx(cash=Decimal("10000")))
    assert verdict.denial is Denial.CASH_FLOOR_BREACHED


# --- sells -------------------------------------------------------------------

def test_selling_more_than_is_held_is_trimmed_to_the_holding():
    verdict = evaluate(sell(500), ctx(held_quantity=40))
    assert verdict.approved
    assert verdict.quantity == 40


def test_selling_nothing_is_denied():
    assert evaluate(sell(10), ctx(held_quantity=0)).denial is Denial.NOTHING_TO_SELL


def test_a_sell_is_not_blocked_by_the_cash_floor():
    """Selling raises cash. Blocking it would trap the agent in a drawdown."""
    verdict = evaluate(sell(10), ctx(held_quantity=50, cash=Decimal("0")))
    assert verdict.approved


# --- system ceilings ---------------------------------------------------------

def test_a_user_cannot_raise_a_limit_above_the_system_ceiling():
    """A policy asking for 90% in one name is clamped to the 25% ceiling."""
    verdict = evaluate(buy(5000), ctx(max_position_pct=Decimal("90")))
    assert verdict.quantity == 250   # 25% of 100k at 100 a share


def test_a_user_may_be_stricter_than_the_ceiling():
    verdict = evaluate(buy(5000), ctx(max_position_pct=Decimal("2")))
    assert verdict.quantity == 20


# --- properties --------------------------------------------------------------

money = st.decimals(min_value=0, max_value=10_000_000, places=2)
positive_price = st.decimals(min_value="0.5", max_value=5000, places=2)


@settings(max_examples=400, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=10_000_000),
    price=positive_price,
    cash=money,
    equity=st.decimals(min_value="1", max_value=10_000_000, places=2),
    held=st.integers(min_value=0, max_value=100_000),
    sector_exposure=money,
    position_pct=st.decimals(min_value="0.1", max_value=100, places=1),
    cash_floor_pct=st.decimals(min_value=0, max_value=90, places=1),
)
def test_an_approved_buy_never_breaches_its_caps(
    quantity, price, cash, equity, held, sector_exposure, position_pct, cash_floor_pct
):
    """The property that matters: no combination of inputs gets more than the
    caps allow. A single counterexample here is a system that can be talked into
    an oversized position."""
    context = ctx(
        price=price, cash=cash, equity=equity, held_quantity=held,
        sector_exposure=sector_exposure, max_position_pct=position_pct,
        cash_floor_pct=cash_floor_pct,
    )
    verdict = evaluate(buy(quantity), context)
    if not verdict.approved:
        return

    assert verdict.quantity > 0
    assert verdict.quantity <= quantity, "the gate expanded an order"

    from app.risk.gate import clamp_policy

    effective_pct = clamp_policy(position_pct, "max_position_pct")
    resulting_value = (held + verdict.quantity) * price
    allowance = equity * effective_pct / 100 + price   # one share of rounding
    assert resulting_value <= allowance, "position cap breached"

    spend = verdict.quantity * price
    floor = equity * cash_floor_pct / 100
    assert spend <= cash - floor + price, "cash floor breached"


@settings(max_examples=300, deadline=None)
@given(
    quantity=st.integers(min_value=1, max_value=1_000_000),
    held=st.integers(min_value=0, max_value=1_000_000),
)
def test_an_approved_sell_never_exceeds_the_holding(quantity, held):
    verdict = evaluate(sell(quantity), ctx(held_quantity=held))
    if verdict.approved:
        assert 0 < verdict.quantity <= held
        assert verdict.quantity <= quantity


@settings(max_examples=300, deadline=None)
@given(
    halted=st.booleans(),
    global_halt=st.booleans(),
    autonomy=st.sampled_from(["observe", "approve", "auto_capped", "full_auto"]),
    market_open=st.booleans(),
)
def test_halts_and_observe_mode_can_never_be_overridden(
    halted, global_halt, autonomy, market_open
):
    verdict = evaluate(buy(1), ctx(account_halted=halted, global_halt=global_halt,
                                   autonomy_level=autonomy, market_open=market_open))
    if halted or global_halt or autonomy == "observe" or not market_open:
        assert not verdict.approved, "a halt was overridden"
        assert verdict.quantity == 0


@settings(max_examples=200, deadline=None)
@given(
    conviction=st.floats(min_value=-100, max_value=100, allow_nan=False),
    quantity=st.integers(min_value=-1000, max_value=1000),
)
def test_malformed_intents_never_produce_an_approval(conviction, quantity):
    assume(quantity <= 0 or not 0.0 <= conviction <= 1.0)
    intent = Intent("TEST", Direction.BUY, quantity, conviction, "fuzz")
    verdict = evaluate(intent, ctx())
    assert not verdict.approved
    assert verdict.quantity == 0
