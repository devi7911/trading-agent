"""Performance metrics for an equity curve.

Deliberately includes the unflattering ones. A strategy is not interesting
because it made money; it is interesting if it made money the benchmark did not,
without a drawdown that would have made you turn it off.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

TRADING_DAYS = 252


@dataclass
class Performance:
    days: int
    starting_equity: float
    ending_equity: float
    total_return_pct: float
    annualised_return_pct: float
    annualised_vol_pct: float
    sharpe: float | None
    sortino: float | None
    max_drawdown_pct: float
    longest_drawdown_days: int
    win_rate_pct: float | None
    profit_factor: float | None
    trades: int
    best_day_pct: float
    worst_day_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def _drawdown_series(equity: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(equity)
    return equity / peak - 1.0


def longest_drawdown(equity: np.ndarray) -> int:
    """The longest stretch spent below a previous peak - the number that decides
    whether a human would actually have kept the thing switched on."""
    dd = _drawdown_series(equity)
    longest = current = 0
    for value in dd:
        current = current + 1 if value < -1e-9 else 0
        longest = max(longest, current)
    return longest


def evaluate(
    equity: np.ndarray, *, trade_returns: list[float] | None = None, trades: int = 0
) -> Performance:
    equity = np.asarray(equity, dtype=float)
    if len(equity) < 2:
        raise ValueError("need at least two equity points")

    returns = np.diff(equity) / equity[:-1]
    years = len(equity) / TRADING_DAYS

    total = equity[-1] / equity[0] - 1
    annualised = (equity[-1] / equity[0]) ** (1 / years) - 1 if years > 0 else 0.0
    vol = float(returns.std() * np.sqrt(TRADING_DAYS))

    downside = returns[returns < 0]
    downside_vol = float(downside.std() * np.sqrt(TRADING_DAYS)) if len(downside) else 0.0

    dd = _drawdown_series(equity)

    win_rate = profit_factor = None
    if trade_returns:
        wins = [r for r in trade_returns if r > 0]
        losses = [r for r in trade_returns if r < 0]
        win_rate = len(wins) / len(trade_returns) * 100
        gross_loss = abs(sum(losses))
        profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else None

    return Performance(
        days=len(equity),
        starting_equity=round(float(equity[0]), 2),
        ending_equity=round(float(equity[-1]), 2),
        total_return_pct=round(float(total) * 100, 2),
        annualised_return_pct=round(float(annualised) * 100, 2),
        annualised_vol_pct=round(vol * 100, 2),
        sharpe=round(float(annualised) / vol, 2) if vol > 1e-9 else None,
        sortino=round(float(annualised) / downside_vol, 2) if downside_vol > 1e-9 else None,
        max_drawdown_pct=round(float(dd.min()) * 100, 2),
        longest_drawdown_days=longest_drawdown(equity),
        win_rate_pct=round(win_rate, 1) if win_rate is not None else None,
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        trades=trades,
        best_day_pct=round(float(returns.max()) * 100, 2),
        worst_day_pct=round(float(returns.min()) * 100, 2),
    )


def block_bootstrap(
    equity: np.ndarray, *, samples: int = 500, block: int = 10, seed: int = 20260905
) -> dict:
    """Resample the return series in blocks to see how much of the result was luck.

    Blocks rather than individual days, so volatility clustering survives the
    resampling. A strategy whose 5th-percentile outcome is a deep loss is a
    strategy that got lucky once, whatever its headline number says.
    """
    equity = np.asarray(equity, dtype=float)
    returns = np.diff(equity) / equity[:-1]
    if len(returns) < block * 2:
        return {"samples": 0, "note": "not enough history to bootstrap"}

    rng = np.random.default_rng(seed)
    outcomes = np.empty(samples)
    blocks_needed = int(np.ceil(len(returns) / block))

    for i in range(samples):
        starts = rng.integers(0, len(returns) - block, size=blocks_needed)
        drawn = np.concatenate([returns[s : s + block] for s in starts])[: len(returns)]
        outcomes[i] = float(np.prod(1 + drawn) - 1)

    return {
        "samples": samples,
        "block_days": block,
        "median_return_pct": round(float(np.median(outcomes)) * 100, 2),
        "p05_return_pct": round(float(np.percentile(outcomes, 5)) * 100, 2),
        "p95_return_pct": round(float(np.percentile(outcomes, 95)) * 100, 2),
        "probability_of_loss_pct": round(float((outcomes < 0).mean()) * 100, 1),
    }


__all__ = ["Performance", "block_bootstrap", "evaluate", "longest_drawdown"]
