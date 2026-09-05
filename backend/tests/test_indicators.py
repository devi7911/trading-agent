"""Indicators, checked against values computed by hand.

The warm-up region must be NaN, not a fabricated number - a strategy must never
be able to trade on an indicator that has not seen enough history.
"""

import numpy as np
import pytest

from app.strategy import indicators as ind


def test_sma_matches_the_arithmetic_mean():
    values = np.array([1, 2, 3, 4, 5], dtype=float)
    result = ind.sma(values, 3)
    assert np.isnan(result[:2]).all()
    assert result[2] == pytest.approx(2.0)
    assert result[4] == pytest.approx(4.0)


def test_sma_of_a_flat_series_is_the_value_itself():
    result = ind.sma(np.full(20, 7.0), 5)
    assert result[-1] == pytest.approx(7.0)


def test_indicators_return_all_nan_when_history_is_too_short():
    short = np.array([1.0, 2.0])
    for series in (ind.sma(short, 10), ind.ema(short, 10), ind.rsi(short, 10),
                   ind.roc(short, 10)):
        assert np.isnan(series).all()


def test_ema_leads_sma_on_a_compounding_uptrend():
    """On a steady trend the EMA sits closer to the latest price than the SMA.

    Two shapes where this is NOT true, both found the hard way: after a step
    change the SMA of the last n bars is exactly the new level while the EMA is
    still catching up, and on a straight linear ramp the two lag identically and
    land on the same number. Compounding growth is the honest case."""
    values = 100 * np.cumprod(np.full(80, 1.01))
    assert ind.ema(values, 10)[-1] > ind.sma(values, 10)[-1]


def test_rsi_is_bounded_and_saturates_on_a_one_way_series():
    rising = np.arange(1, 60, dtype=float)
    falling = rising[::-1].copy()
    up = ind.rsi(rising, 14)
    down = ind.rsi(falling, 14)
    assert up[-1] == pytest.approx(100.0)
    assert down[-1] == pytest.approx(0.0, abs=1e-6)


def test_rsi_stays_within_zero_and_one_hundred_on_noise():
    rng = np.random.default_rng(3)
    series = 100 * np.cumprod(1 + rng.normal(0, 0.02, 500))
    values = ind.rsi(series, 14)
    valid = values[~np.isnan(values)]
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_bollinger_bands_bracket_the_middle_and_contain_most_of_the_series():
    rng = np.random.default_rng(5)
    series = 100 * np.cumprod(1 + rng.normal(0, 0.01, 400))
    upper, middle, lower = ind.bollinger(series, 20, 2.0)  # middle used below
    valid = ~np.isnan(middle)
    assert (upper[valid] >= middle[valid]).all()
    assert (lower[valid] <= middle[valid]).all()
    inside = ((series[valid] <= upper[valid]) & (series[valid] >= lower[valid])).mean()
    assert inside > 0.85, f"only {inside:.0%} of points fell inside two deviations"


def test_bollinger_bands_collapse_onto_a_flat_series():
    upper, _middle, lower = ind.bollinger(np.full(50, 42.0), 20)
    assert upper[-1] == pytest.approx(42.0)
    assert lower[-1] == pytest.approx(42.0)


def test_atr_is_positive_and_rises_with_range():
    calm_high = np.full(60, 101.0)
    calm_low = np.full(60, 99.0)
    close = np.full(60, 100.0)
    wild_high = np.full(60, 115.0)
    wild_low = np.full(60, 85.0)

    calm = ind.atr(calm_high, calm_low, close, 14)[-1]
    wild = ind.atr(wild_high, wild_low, close, 14)[-1]
    assert calm > 0
    assert wild > calm


def test_true_range_accounts_for_overnight_gaps():
    high = np.array([100.0, 120.0])
    low = np.array([99.0, 119.0])
    close = np.array([99.5, 119.5])
    # The gap from 99.5 to 119 dwarfs the 1-point intraday range.
    assert ind.true_range(high, low, close)[1] == pytest.approx(20.5)


def test_roc_measures_the_change_over_the_period():
    values = np.array([100.0] * 10 + [110.0])
    assert ind.roc(values, 10)[-1] == pytest.approx(0.10)


def test_drawdown_is_zero_at_a_new_high_and_negative_below():
    values = np.array([100.0, 120.0, 90.0, 130.0])
    dd = ind.drawdown(values)
    assert dd[1] == pytest.approx(0.0)
    assert dd[2] == pytest.approx(-0.25)
    assert dd[3] == pytest.approx(0.0)


def test_realised_volatility_rises_with_noise():
    rng = np.random.default_rng(11)
    calm = 100 * np.cumprod(1 + rng.normal(0, 0.002, 300))
    wild = 100 * np.cumprod(1 + rng.normal(0, 0.04, 300))
    assert ind.realised_volatility(wild, 20)[-1] > ind.realised_volatility(calm, 20)[-1]


def test_macd_histogram_is_the_difference_of_the_two_lines():
    rng = np.random.default_rng(13)
    series = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 300))
    line, signal, histogram = ind.macd(series)
    valid = ~np.isnan(histogram)
    assert np.allclose(histogram[valid], (line - signal)[valid])


def test_a_zero_period_is_rejected():
    with pytest.raises(ValueError, match="period"):
        ind.sma(np.arange(10, dtype=float), 0)


def test_a_two_dimensional_input_is_rejected():
    with pytest.raises(ValueError, match="one-dimensional"):
        ind.sma(np.zeros((5, 5)), 3)
