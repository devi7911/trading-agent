"""Price path engine.

A three-factor model rather than independent random walks, because independent
walks make diversification look free and momentum look easy. Here:

  return = drift + beta x market + load x sector + idiosyncratic

The market factor regime-switches (bull / chop / bear) through a Markov chain,
idiosyncratic volatility clusters GARCH-style, and earnings inject jumps. The
result is a market where correlations rise in drawdowns and a strategy tuned on
one regime does not automatically survive the next one - which is the whole
point of simulating instead of using a flat random walk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from app.market.synthetic.universe import SECTORS, Company

TRADING_DAYS = 252

# --- market regimes ---------------------------------------------------------
# annualised drift and volatility of the market factor in each state
REGIMES = (
    ("bull", 0.16, 0.11),
    ("chop", 0.02, 0.17),
    ("bear", -0.28, 0.33),
)

# rows: from-state, cols: to-state. Deliberately sticky - regimes persist for
# months, which is what makes trend-following viable and mean-reversion risky.
TRANSITIONS = np.array(
    [
        [0.9850, 0.0120, 0.0030],
        [0.0220, 0.9670, 0.0110],
        [0.0100, 0.0450, 0.9450],
    ]
)

# GARCH(1,1) on idiosyncratic returns
GARCH_OMEGA_SCALE = 0.05
GARCH_ALPHA = 0.09
GARCH_BETA = 0.88

SECTOR_LOAD = 0.45          # how much of a sector factor a stock absorbs
SECTOR_MARKET_LOAD = 0.30   # how much of the market factor is inside a sector factor


@dataclass
class PricePanel:
    """Everything the generator produced, aligned on `days`."""

    days: list[date]
    symbols: list[str]
    open: np.ndarray          # (n_days, n_stocks)
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    regimes: np.ndarray       # (n_days,) index into REGIMES
    earnings: dict[str, list[tuple[date, float, float]]]  # symbol -> (day, estimate, actual)

    def series(self, symbol: str) -> dict[str, np.ndarray]:
        i = self.symbols.index(symbol)
        return {
            "open": self.open[:, i],
            "high": self.high[:, i],
            "low": self.low[:, i],
            "close": self.close[:, i],
            "volume": self.volume[:, i],
        }


def _simulate_regimes(rng: np.random.Generator, n_days: int) -> np.ndarray:
    states = np.empty(n_days, dtype=np.int8)
    state = 1  # start in chop; nobody knows what comes next
    for t in range(n_days):
        states[t] = state
        state = int(rng.choice(3, p=TRANSITIONS[state]))
    return states


def _earnings_days(days: list[date], company: Company) -> list[int]:
    """One report per quarter, in the company's assigned month of that quarter,
    on a stable day near the middle of the month."""
    out: list[int] = []
    seen: set[tuple[int, int]] = set()
    target_months = {1 + company.earnings_month_offset + 3 * q for q in range(4)}
    for i, d in enumerate(days):
        if d.month in target_months and (d.year, d.month) not in seen and d.day >= 12:
            seen.add((d.year, d.month))
            out.append(i)
    return out


def simulate(
    companies: list[Company],
    days: list[date],
    *,
    master_seed: int = 20260905,
) -> PricePanel:
    """Generate the full OHLCV panel. Deterministic in (companies, days, seed)."""
    n_days, n = len(days), len(companies)
    if n_days == 0 or n == 0:
        raise ValueError("need at least one company and one trading day")

    rng = np.random.default_rng(master_seed ^ 0x5EED)
    sqrt_t = np.sqrt(TRADING_DAYS)

    # --- market factor ---
    regimes = _simulate_regimes(rng, n_days)
    mu = np.array([r[1] for r in REGIMES])[regimes] / TRADING_DAYS
    sd = np.array([r[2] for r in REGIMES])[regimes] / sqrt_t
    market = mu + sd * rng.standard_normal(n_days)

    # --- sector factors ---
    sector_names = [s.name for s in SECTORS]
    sector_index = {name: k for k, name in enumerate(sector_names)}
    sector_extra = 0.13 / sqrt_t * rng.standard_normal((n_days, len(sector_names)))
    sector = SECTOR_MARKET_LOAD * market[:, None] + sector_extra

    # --- per-stock parameters ---
    betas = np.array([c.beta for c in companies])
    vols = np.array([c.annual_vol for c in companies]) / sqrt_t
    drifts = np.array([c.sim_params.get("drift", 0.03) for c in companies]) / TRADING_DAYS
    sec_col = np.array([sector_index[c.sector] for c in companies])

    # --- idiosyncratic returns with volatility clustering ---
    idio = np.empty((n_days, n))
    long_run = vols**2
    omega = long_run * (1.0 - GARCH_ALPHA - GARCH_BETA)
    sigma2 = long_run.copy()
    shocks = rng.standard_normal((n_days, n))
    for t in range(n_days):
        eps = np.sqrt(sigma2) * shocks[t]
        idio[t] = eps
        sigma2 = omega + GARCH_ALPHA * eps**2 + GARCH_BETA * sigma2

    log_returns = (
        drifts
        + betas * market[:, None]
        + SECTOR_LOAD * sector[:, sec_col]
        + idio
    )

    # --- earnings jumps ---
    earnings: dict[str, list[tuple[date, float, float]]] = {}
    earnings_mask = np.zeros((n_days, n), dtype=bool)
    for i, company in enumerate(companies):
        crng = np.random.default_rng(company.seed)
        reports: list[tuple[date, float, float]] = []
        for t in _earnings_days(days, company):
            estimate = float(abs(crng.normal(1.2, 0.6)) + 0.05)
            # Better companies beat more often, but nobody beats every quarter.
            bias = (company.quality - 0.5) * 0.10
            surprise = float(crng.normal(bias, 0.09))
            actual = round(estimate * (1.0 + surprise), 4)

            # Reaction is nonlinear: small beats barely move, big misses gap hard.
            reaction = np.tanh(surprise * 7.0) * float(abs(crng.normal(0.045, 0.025)))
            log_returns[t, i] += reaction
            earnings_mask[t, i] = True
            reports.append((days[t], round(estimate, 4), actual))
        earnings[company.symbol] = reports

    # --- close prices ---
    p0 = np.array([c.initial_price for c in companies])
    close = p0 * np.exp(np.cumsum(log_returns, axis=0))
    close = np.maximum(close, 0.35)  # a floor; delisting is phase 02's problem

    # --- open, high, low ---
    prev_close = np.vstack([p0[None, :], close[:-1]])
    # About a third of the move happens overnight, plus a little gap noise.
    gap = 0.33 * log_returns + 0.35 * vols * rng.standard_normal((n_days, n))
    open_ = np.maximum(prev_close * np.exp(gap), 0.30)

    hi_body = np.maximum(open_, close)
    lo_body = np.minimum(open_, close)
    wick_scale = 0.8 * vols
    high = hi_body * np.exp(np.abs(rng.standard_normal((n_days, n))) * wick_scale)
    low = lo_body * np.exp(-np.abs(rng.standard_normal((n_days, n))) * wick_scale)
    low = np.minimum(low, lo_body)
    high = np.maximum(high, hi_body)

    # --- volume: heavier on big moves and on earnings days ---
    base = np.array([c.shares_outstanding for c in companies]) * 0.0035
    move = np.abs(log_returns) / np.maximum(vols, 1e-9)
    noise = np.exp(rng.normal(0.0, 0.35, size=(n_days, n)))
    volume = base * noise * (0.55 + 0.75 * np.clip(move, 0, 6))
    volume *= np.where(earnings_mask, 2.6, 1.0)
    volume = np.maximum(volume, 1000).astype(np.int64)

    return PricePanel(
        days=days,
        symbols=[c.symbol for c in companies],
        open=np.round(open_, 4),
        high=np.round(high, 4),
        low=np.round(low, 4),
        close=np.round(close, 4),
        volume=volume,
        regimes=regimes,
        earnings=earnings,
    )


__all__ = ["REGIMES", "TRADING_DAYS", "PricePanel", "simulate"]
