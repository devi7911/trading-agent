"""Analytics maths, on a small hand-built panel so the answers are checkable.

Includes a regression test for the tearsheet window bug: the stats table showed
trailing-252-day figures beside charts drawn over the full history, so a -50%
drawdown was reported as -29.6%.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.market.analytics import (
    INDEX_BASE,
    Panel,
    compute_snapshots,
    correlation_matrix,
    instrument_stats,
    movers,
    sector_performance,
)


def _panel(close: np.ndarray, *, sectors=None, shares=None) -> Panel:
    n_days, n = close.shape
    start = datetime(2024, 1, 2, tzinfo=UTC)
    return Panel(
        days=[start + timedelta(days=i) for i in range(n_days)],
        symbols=[f"S{i}" for i in range(n)],
        ids=[None] * n,
        sectors=sectors or ["Technology"] * n,
        shares=shares if shares is not None else np.ones(n) * 1_000,
        close=close,
        volume=np.full((n_days, n), 1_000, dtype=np.int64),
    )


# --- index and breadth -------------------------------------------------------

def test_index_starts_at_the_base_value():
    close = np.array([[10.0, 20.0], [11.0, 21.0], [12.0, 19.0]])
    rows = compute_snapshots(_panel(close))
    assert rows[0]["index_value"] == pytest.approx(INDEX_BASE)


def test_index_is_cap_weighted_not_price_weighted():
    """A big move in a tiny company must not swing the index like a mega cap."""
    close = np.array([[100.0, 10.0], [100.0, 20.0]])   # small name doubles
    shares = np.array([1_000_000.0, 10.0])             # and is minuscule
    rows = compute_snapshots(_panel(close, shares=shares))
    assert rows[1]["index_return"] < 0.001


def test_breadth_counts_advancers_and_decliners():
    close = np.array([[10.0, 10.0, 10.0], [11.0, 9.0, 10.0]])
    rows = compute_snapshots(_panel(close))
    assert rows[1]["advancers"] == 1
    assert rows[1]["decliners"] == 1
    assert rows[1]["unchanged"] == 1


def test_every_day_gets_exactly_one_snapshot():
    close = np.cumprod(1 + np.zeros((40, 3)) + 0.001, axis=0) * 50
    rows = compute_snapshots(_panel(close))
    assert len(rows) == 40


# --- instrument stats --------------------------------------------------------

def test_max_drawdown_finds_the_real_trough():
    close = np.array([[100.0], [200.0], [100.0], [150.0]])
    s = instrument_stats(_panel(close), "S0", lookback=0)
    assert s["max_drawdown_pct"] == pytest.approx(-50.0)


def test_lookback_zero_means_the_entire_history():
    """The tearsheet bug: a short window hid the deepest drawdown."""
    close = np.vstack([
        np.array([[100.0], [200.0], [100.0]]),      # -50% early on
        np.full((300, 1), 150.0),                   # then flat for a year
    ])
    panel = _panel(close)
    windowed = instrument_stats(panel, "S0", lookback=252)
    full = instrument_stats(panel, "S0", lookback=0)
    assert windowed["max_drawdown_pct"] > full["max_drawdown_pct"]
    assert full["max_drawdown_pct"] == pytest.approx(-50.0)
    assert full["lookback_days"] == close.shape[0]


def test_period_return_is_first_to_last():
    close = np.array([[100.0], [120.0], [150.0]])
    s = instrument_stats(_panel(close), "S0", lookback=0)
    assert s["period_return_pct"] == pytest.approx(50.0)


def test_flat_series_has_no_volatility_and_no_sharpe():
    close = np.full((30, 1), 42.0)
    s = instrument_stats(_panel(close), "S0", lookback=0)
    assert s["annualised_vol_pct"] == pytest.approx(0.0)
    assert s["sharpe"] is None


# --- sectors and movers ------------------------------------------------------

def test_sector_performance_groups_and_ranks():
    close = np.array([[100.0, 100.0, 100.0], [110.0, 90.0, 105.0]])
    panel = _panel(close, sectors=["Technology", "Utilities", "Technology"])
    rows = sector_performance(panel, "1d")
    assert [r["sector"] for r in rows] == ["Technology", "Utilities"]
    assert rows[1]["return_pct"] == pytest.approx(-10.0)


def test_movers_orders_gainers_and_losers_correctly():
    close = np.array([[100.0, 100.0, 100.0], [130.0, 80.0, 101.0]])
    m = movers(_panel(close), "1d", limit=3)
    assert m["gainers"][0]["symbol"] == "S0"
    assert m["losers"][0]["symbol"] == "S1"
    assert m["gainers"][0]["change_pct"] == pytest.approx(30.0)


# --- correlation -------------------------------------------------------------

def test_a_series_correlates_perfectly_with_itself():
    rng = np.random.default_rng(7)
    base = 100 * np.cumprod(1 + rng.normal(0, 0.01, 200))
    close = np.column_stack([base, base])
    result = correlation_matrix(_panel(close), ["S0", "S1"], lookback=100)
    assert result["matrix"][0][1] == pytest.approx(1.0, abs=1e-6)


def test_inverse_series_correlate_negatively():
    rng = np.random.default_rng(11)
    rets = rng.normal(0, 0.01, 200)
    a = 100 * np.cumprod(1 + rets)
    b = 100 * np.cumprod(1 - rets)
    result = correlation_matrix(_panel(np.column_stack([a, b])), ["S0", "S1"], lookback=150)
    assert result["matrix"][0][1] < -0.9
