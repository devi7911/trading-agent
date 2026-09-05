"""The generated market has to be reproducible and statistically plausible.

If a seed does not reproduce a market exactly, no bug in the agent is ever
reproducible either - so determinism is tested first and hardest.
"""

from datetime import date

import numpy as np
import pytest

from app.market.calendar import trading_days
from app.market.synthetic.news import generate_news
from app.market.synthetic.prices import simulate
from app.market.synthetic.provider import SyntheticProvider
from app.market.synthetic.universe import SECTOR_BY_NAME, generate_universe

SEED = 20260905
START = date(2020, 1, 2)
END = date(2024, 12, 31)


@pytest.fixture(scope="module")
def days():
    return trading_days(START, END)


@pytest.fixture(scope="module")
def companies():
    return generate_universe(count=40, master_seed=SEED, listing_start=START)


@pytest.fixture(scope="module")
def panel(companies, days):
    return simulate(companies, days, master_seed=SEED)


# --- determinism -------------------------------------------------------------

def test_same_seed_reproduces_identical_companies():
    a = generate_universe(count=40, master_seed=SEED)
    b = generate_universe(count=40, master_seed=SEED)
    assert [c.symbol for c in a] == [c.symbol for c in b]
    assert [c.name for c in a] == [c.name for c in b]
    assert [c.beta for c in a] == [c.beta for c in b]


def test_different_seed_produces_a_different_market():
    a = generate_universe(count=40, master_seed=SEED)
    b = generate_universe(count=40, master_seed=SEED + 1)
    assert [c.symbol for c in a] != [c.symbol for c in b]


def test_same_seed_reproduces_identical_prices(companies, days, panel):
    again = simulate(companies, days, master_seed=SEED)
    assert np.array_equal(panel.close, again.close)
    assert np.array_equal(panel.volume, again.volume)


def test_instrument_seed_is_stable_across_universe_size():
    """Adding companies must not shift the seed of existing ones, or every
    regenerated market would invalidate previous results."""
    small = {c.symbol: c.seed for c in generate_universe(count=20, master_seed=SEED)}
    large = {c.symbol: c.seed for c in generate_universe(count=80, master_seed=SEED)}
    shared = set(small) & set(large)
    assert shared, "expected overlapping symbols"
    for sym in shared:
        assert small[sym] == large[sym]


# --- universe sanity ---------------------------------------------------------

def test_symbols_and_names_are_unique(companies):
    assert len({c.symbol for c in companies}) == len(companies)
    assert len({c.name for c in companies}) == len(companies)


def test_company_parameters_sit_inside_their_sector_profile(companies):
    for c in companies:
        profile = SECTOR_BY_NAME[c.sector]
        assert profile.beta[0] <= c.beta <= profile.beta[1]
        assert profile.vol[0] <= c.annual_vol <= profile.vol[1]


def test_market_caps_span_several_orders_of_magnitude(companies):
    caps = sorted(c.market_cap for c in companies)
    assert caps[-1] / caps[0] > 100, "universe should hold both small and mega caps"


# --- OHLC invariants ---------------------------------------------------------

def test_ohlc_ordering_holds_everywhere(panel):
    assert np.all(panel.high >= panel.open - 1e-6)
    assert np.all(panel.high >= panel.close - 1e-6)
    assert np.all(panel.low <= panel.open + 1e-6)
    assert np.all(panel.low <= panel.close + 1e-6)
    assert np.all(panel.high >= panel.low)


def test_prices_and_volumes_stay_positive(panel):
    assert np.all(panel.close > 0)
    assert np.all(panel.open > 0)
    assert np.all(panel.low > 0)
    assert np.all(panel.volume > 0)


def test_panel_shape_matches_inputs(panel, companies, days):
    assert panel.close.shape == (len(days), len(companies))


# --- statistical plausibility ------------------------------------------------

def test_realised_volatility_is_in_a_believable_band(panel):
    rets = np.diff(np.log(panel.close), axis=0)
    annualised = rets.std(axis=0) * np.sqrt(252)
    assert 0.10 < float(np.median(annualised)) < 0.90
    assert float(annualised.min()) > 0.05


def test_returns_are_fat_tailed(panel):
    """Volatility clustering plus earnings jumps should push kurtosis above
    the 3.0 of a normal distribution. Flat random walks fail this."""
    rets = np.diff(np.log(panel.close), axis=0)
    z = (rets - rets.mean(axis=0)) / rets.std(axis=0)
    kurtosis = (z**4).mean(axis=0)
    assert float(np.median(kurtosis)) > 3.5


def test_stocks_are_correlated_through_the_market_factor(panel):
    rets = np.diff(np.log(panel.close), axis=0)
    corr = np.corrcoef(rets, rowvar=False)
    off_diagonal = corr[~np.eye(corr.shape[0], dtype=bool)]
    mean_corr = float(off_diagonal.mean())
    assert 0.05 < mean_corr < 0.85, f"mean pairwise correlation was {mean_corr:.3f}"


def test_same_sector_names_correlate_more_than_cross_sector(companies, panel):
    rets = np.diff(np.log(panel.close), axis=0)
    corr = np.corrcoef(rets, rowvar=False)
    same, cross = [], []
    for i in range(len(companies)):
        for j in range(i + 1, len(companies)):
            (same if companies[i].sector == companies[j].sector else cross).append(corr[i, j])
    assert same and cross
    assert np.mean(same) > np.mean(cross)


def test_regimes_persist_rather_than_flickering(panel):
    """A regime that changed most days would make trend-following meaningless."""
    switches = int(np.sum(np.diff(panel.regimes) != 0))
    assert switches < len(panel.days) * 0.10
    assert switches > 0, "expected at least one regime change over five years"


def test_every_company_reports_roughly_quarterly(panel, days):
    years = len(days) / 252
    for symbol, reports in panel.earnings.items():
        expected = 4 * years
        assert 0.7 * expected <= len(reports) <= 1.3 * expected, symbol


# --- news --------------------------------------------------------------------

def test_news_carries_ground_truth_labels(companies, panel):
    news = generate_news(companies, panel, master_seed=SEED)
    assert news
    relations = {n.relation for n in news}
    assert relations <= {"leading", "lagging", "noise"}
    assert relations == {"leading", "lagging", "noise"}


def test_leading_news_is_the_minority(companies, panel):
    news = generate_news(companies, panel, master_seed=SEED)
    leading = sum(1 for n in news if n.relation == "leading")
    assert 0 < leading < len(news) * 0.5


def test_earnings_headlines_agree_with_the_numbers(companies, panel):
    news = generate_news(companies, panel, master_seed=SEED)
    earnings = [n for n in news if n.category == "earnings"]
    assert earnings
    for item in earnings:
        if "beats" in item.headline:
            assert item.sentiment >= 0
        elif "misses" in item.headline:
            assert item.sentiment <= 0


# --- provider ----------------------------------------------------------------

def test_provider_emits_one_bar_per_company_per_trading_day():
    provider = SyntheticProvider(
        count=5, seed=SEED, start=date(2024, 1, 2), end=date(2024, 3, 28)
    )
    bars = provider.bars(date(2024, 1, 2), date(2024, 3, 28))
    assert len(bars) == len(provider.days) * 5
    assert {b.timeframe for b in bars} == {"1d"}


def test_provider_rejects_unsupported_timeframes():
    provider = SyntheticProvider(count=2, seed=SEED, start=date(2024, 1, 2), end=date(2024, 2, 1))
    with pytest.raises(ValueError, match="daily bars only"):
        provider.bars(date(2024, 1, 2), date(2024, 2, 1), timeframe="1m")


def test_provider_bars_carry_the_session_close_timestamp():
    provider = SyntheticProvider(count=2, seed=SEED, start=date(2024, 6, 3), end=date(2024, 6, 7))
    bars = provider.bars(date(2024, 6, 3), date(2024, 6, 7))
    # June is daylight saving, so a 16:00 Eastern close is 20:00 UTC.
    assert {b.ts.hour for b in bars} == {20}


def test_provider_produces_earnings_and_dividend_events():
    provider = SyntheticProvider(
        count=10, seed=SEED, start=date(2022, 1, 3), end=date(2024, 12, 31)
    )
    events = provider.corporate_events(date(2022, 1, 3), date(2024, 12, 31))
    kinds = {e.event_type for e in events}
    assert "earnings" in kinds
    assert "dividend" in kinds
    for e in events:
        if e.event_type == "earnings":
            assert e.eps_estimate is not None and e.eps_actual is not None
