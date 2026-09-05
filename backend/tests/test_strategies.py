"""Strategies, on series built to make the right answer obvious."""

import numpy as np
import pytest

from app.strategy.signals import Direction
from app.strategy.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    PriceSeries,
    TrendFollowingStrategy,
    consensus,
    evaluate_all,
)


def series(close: np.ndarray, symbol: str = "TEST") -> PriceSeries:
    return PriceSeries(
        symbol=symbol,
        close=close,
        high=close * 1.01,
        low=close * 0.99,
        volume=np.full(len(close), 1_000_000, dtype=np.int64),
    )


def rising(n: int = 300, rate: float = 0.004) -> np.ndarray:
    return 100 * np.cumprod(np.full(n, 1 + rate))


def falling(n: int = 300, rate: float = 0.004) -> np.ndarray:
    return 100 * np.cumprod(np.full(n, 1 - rate))


def flat(n: int = 300) -> np.ndarray:
    rng = np.random.default_rng(4)
    return 100 + rng.normal(0, 0.35, n)


# --- every strategy always answers -------------------------------------------

@pytest.mark.parametrize(
    "strategy", [MomentumStrategy(), MeanReversionStrategy(), TrendFollowingStrategy()]
)
def test_a_strategy_always_returns_a_signal_with_a_reason(strategy):
    signal = strategy.evaluate(series(flat()))
    assert signal.reason, "a hold still has to say why"
    assert signal.symbol == "TEST"
    assert 0.0 <= signal.strength <= 1.0


@pytest.mark.parametrize(
    "strategy", [MomentumStrategy(), MeanReversionStrategy(), TrendFollowingStrategy()]
)
def test_short_history_produces_a_hold_not_a_guess(strategy):
    signal = strategy.evaluate(series(rising(15)))
    assert signal.direction is Direction.HOLD
    assert "history" in signal.reason


# --- momentum ----------------------------------------------------------------

def test_momentum_buys_a_strong_uptrend():
    signal = MomentumStrategy().evaluate(series(rising()))
    assert signal.direction is Direction.BUY
    assert signal.strength > 0


def test_momentum_sells_a_sustained_downtrend():
    signal = MomentumStrategy().evaluate(series(falling()))
    assert signal.direction is Direction.SELL


def test_momentum_holds_in_a_flat_market():
    assert MomentumStrategy().evaluate(series(flat())).direction is Direction.HOLD


# --- mean reversion ----------------------------------------------------------

def test_mean_reversion_buys_after_a_sharp_selloff():
    prices = np.concatenate([np.full(60, 100.0), 100 * np.cumprod(np.full(25, 0.97))])
    signal = MeanReversionStrategy().evaluate(series(prices))
    assert signal.direction is Direction.BUY
    assert signal.indicators["rsi"] < 30
    assert "oversold" in signal.reason


def test_mean_reversion_sells_after_a_sharp_rally():
    prices = np.concatenate([np.full(60, 100.0), 100 * np.cumprod(np.full(25, 1.03))])
    signal = MeanReversionStrategy().evaluate(series(prices))
    assert signal.direction is Direction.SELL
    assert signal.indicators["rsi"] > 70
    assert "overbought" in signal.reason


def test_mean_reversion_and_momentum_disagree_on_a_selloff():
    """They are meant to. Running only one is running a one-regime strategy."""
    prices = np.concatenate([np.full(200, 100.0), 100 * np.cumprod(np.full(60, 0.985))])
    p = series(prices)
    assert MeanReversionStrategy().evaluate(p).direction is Direction.BUY
    assert MomentumStrategy().evaluate(p).direction is Direction.SELL


# --- trend following ---------------------------------------------------------

def test_trend_following_buys_when_the_fast_average_leads():
    signal = TrendFollowingStrategy().evaluate(series(rising(400)))
    assert signal.direction is Direction.BUY


def test_trend_following_sells_when_the_fast_average_lags():
    signal = TrendFollowingStrategy().evaluate(series(falling(400)))
    assert signal.direction is Direction.SELL


# --- consensus ---------------------------------------------------------------

def test_consensus_agrees_with_a_unanimous_uptrend():
    signals = evaluate_all(series(rising(400)))
    combined = consensus(signals)
    assert combined.direction is Direction.BUY
    assert combined.strategy == "consensus"


def test_consensus_holds_when_strategies_contradict_each_other():
    prices = np.concatenate([np.full(250, 100.0), 100 * np.cumprod(np.full(60, 0.985))])
    combined = consensus(evaluate_all(series(prices)))
    assert combined.direction is Direction.HOLD
    assert "disagree" in combined.reason


def test_consensus_records_who_voted_which_way():
    combined = consensus(evaluate_all(series(rising(400))))
    assert "voters" in combined.indicators
    assert len(combined.indicators["voters"]) == 3


def test_consensus_needs_at_least_one_signal():
    with pytest.raises(ValueError, match="no signals"):
        consensus([])


def test_signal_strength_outside_the_unit_interval_is_rejected():
    from app.strategy.signals import Signal

    with pytest.raises(ValueError, match="within"):
        Signal("TEST", Direction.BUY, 1.4, "s", "r")
