"""The matching engine, tested without a database.

The engine's whole purpose is to make size and volatility cost something. If
these tests pass while the engine fills everything at the reference price, the
tests are wrong, not the engine.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.execution.book import build_book, spread_bps, walk
from app.execution.engine import MarketContext, execute
from app.execution.port import OrderRequest
from app.models.order import OrderType, RejectReason, Side

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=UTC)
PRICE = Decimal("100.00")


def ctx(**kwargs) -> MarketContext:
    base = {
        "symbol": "TEST",
        "reference_price": PRICE,
        "daily_vol": 0.02,
        "avg_volume": 1_000_000,
        "is_open": True,
    }
    base.update(kwargs)
    return MarketContext(**base)


def buy(qty: int = 100, **kwargs) -> OrderRequest:
    return OrderRequest(symbol="TEST", side=Side.BUY, quantity=qty, **kwargs)


# --- the book ----------------------------------------------------------------

def test_spread_widens_with_volatility():
    calm = spread_bps(0.01)
    wild = spread_bps(0.08)
    assert wild > calm * 2


def test_spread_widens_at_the_open():
    assert spread_bps(0.02, at_open=True) > spread_bps(0.02, at_open=False)


def test_book_brackets_the_reference_price():
    book = build_book("TEST", PRICE, daily_vol=0.02, avg_volume=1_000_000)
    assert book.best_bid < PRICE < book.best_ask


def test_depth_decays_away_from_the_touch():
    book = build_book("TEST", PRICE, avg_volume=5_000_000)
    sizes = [level.size for level in book.asks]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes[-1] < sizes[0]


def test_a_large_order_pays_a_worse_average_than_a_small_one():
    """The single most important property here. Without it, a backtest learns
    that position size is free."""
    book = build_book("TEST", PRICE, avg_volume=1_000_000)
    _, small = walk(book.asks, 100, None, is_buy=True)
    _, large = walk(book.asks, 40_000, None, is_buy=True)
    assert large > small


def test_walking_stops_at_the_limit_price():
    book = build_book("TEST", PRICE, avg_volume=1_000_000)
    cap = book.asks[2].price
    filled, avg = walk(book.asks, 1_000_000, cap, is_buy=True)
    assert avg <= cap
    assert filled < 1_000_000


def test_depth_runs_out_on_an_enormous_order():
    book = build_book("TEST", PRICE, avg_volume=100_000)
    filled, _ = walk(book.asks, 10_000_000, None, is_buy=True)
    assert 0 < filled < 10_000_000


# --- rejections --------------------------------------------------------------

@pytest.mark.parametrize(
    ("context_kwargs", "expected"),
    [
        ({"is_open": False}, RejectReason.MARKET_CLOSED),
        ({"is_halted": True}, RejectReason.SYMBOL_HALTED),
        ({"is_tradable": False}, RejectReason.SYMBOL_NOT_TRADABLE),
        ({"reference_price": Decimal(0)}, RejectReason.NO_MARKET_DATA),
    ],
)
def test_venue_rejections(context_kwargs, expected):
    result = execute(buy(), ctx(**context_kwargs), as_of=NOW, seed="s")
    assert not result.accepted
    assert result.reject_reason is expected


def test_zero_quantity_is_rejected():
    request = OrderRequest(symbol="TEST", side=Side.BUY, quantity=0)
    result = execute(request, ctx(), as_of=NOW, seed="s")
    assert result.reject_reason is RejectReason.INVALID_QUANTITY


def test_limit_order_without_a_limit_price_is_rejected():
    result = execute(buy(order_type=OrderType.LIMIT), ctx(), as_of=NOW, seed="s")
    assert result.reject_reason is RejectReason.INVALID_PRICE


def test_stop_order_without_a_stop_price_is_rejected():
    result = execute(buy(order_type=OrderType.STOP), ctx(), as_of=NOW, seed="s")
    assert result.reject_reason is RejectReason.INVALID_PRICE


def test_rejections_produce_no_fills():
    result = execute(buy(), ctx(is_open=False), as_of=NOW, seed="s")
    assert result.fills == []
    assert result.filled_quantity == 0


# --- fills -------------------------------------------------------------------

def test_a_market_buy_fills_at_or_above_the_reference_price():
    result = execute(buy(100), ctx(), as_of=NOW, seed="s")
    assert result.accepted
    assert result.filled_quantity == 100
    assert result.average_price >= PRICE


def test_a_market_sell_fills_at_or_below_the_reference_price():
    request = OrderRequest(symbol="TEST", side=Side.SELL, quantity=100)
    result = execute(request, ctx(), as_of=NOW, seed="s")
    assert result.average_price <= PRICE


def test_slippage_is_recorded_as_a_cost_on_both_sides():
    bought = execute(buy(100), ctx(), as_of=NOW, seed="s")
    sold = execute(
        OrderRequest(symbol="TEST", side=Side.SELL, quantity=100), ctx(), as_of=NOW, seed="s"
    )
    assert bought.fills[0].slippage_bps > 0
    assert sold.fills[0].slippage_bps > 0


def test_fills_are_timestamped_after_the_request():
    result = execute(buy(), ctx(), as_of=NOW, seed="s")
    assert result.fills[0].filled_at > NOW


def test_an_unmarketable_limit_rests_instead_of_filling():
    result = execute(
        buy(order_type=OrderType.LIMIT, limit_price=Decimal("50.00")), ctx(), as_of=NOW, seed="s"
    )
    assert result.accepted
    assert result.resting
    assert result.filled_quantity == 0


def test_a_marketable_limit_fills():
    result = execute(
        buy(order_type=OrderType.LIMIT, limit_price=Decimal("200.00")), ctx(), as_of=NOW, seed="s"
    )
    assert result.filled_quantity == 100


def test_an_untriggered_stop_rests():
    result = execute(
        buy(order_type=OrderType.STOP, stop_price=Decimal("150.00")), ctx(), as_of=NOW, seed="s"
    )
    assert result.accepted
    assert result.resting
    assert result.filled_quantity == 0


def test_a_triggered_buy_stop_executes():
    result = execute(
        buy(order_type=OrderType.STOP, stop_price=Decimal("90.00")), ctx(), as_of=NOW, seed="s"
    )
    assert result.filled_quantity == 100


def test_an_order_larger_than_the_book_fills_partially():
    result = execute(buy(5_000_000), ctx(avg_volume=200_000), as_of=NOW, seed="s")
    assert result.accepted
    assert 0 < result.filled_quantity < 5_000_000
    assert "Partially filled" in (result.message or "")


# --- determinism -------------------------------------------------------------

def test_the_same_seed_reproduces_the_same_fill():
    a = execute(buy(500), ctx(), as_of=NOW, seed="order-abc")
    b = execute(buy(500), ctx(), as_of=NOW, seed="order-abc")
    assert a.average_price == b.average_price
    assert [f.quantity for f in a.fills] == [f.quantity for f in b.fills]


def test_different_orders_get_different_treatment():
    prices = {
        execute(buy(500), ctx(), as_of=NOW, seed=f"order-{i}").average_price for i in range(12)
    }
    assert len(prices) > 1, "every order priced identically - the seeding is not working"


def test_volatile_names_cost_more_to_cross():
    calm = execute(buy(100), ctx(daily_vol=0.008), as_of=NOW, seed="s")
    wild = execute(buy(100), ctx(daily_vol=0.09), as_of=NOW, seed="s")
    assert wild.average_price > calm.average_price
