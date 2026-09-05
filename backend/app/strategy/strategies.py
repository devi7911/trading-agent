"""Rule-based strategies. No AI anywhere in this file, deliberately.

Phase 08 adds a language model on top of these, but the system has to behave
sensibly without one. If these produce nonsense, a model will produce
better-argued nonsense.

Each strategy is a pure function of a price series and returns exactly one
signal, always - a HOLD with a reason rather than silence, so the decision trace
records why nothing happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.strategy import indicators as ind
from app.strategy.signals import Direction, Signal, hold


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray

    def __len__(self) -> int:
        return len(self.close)

    @property
    def last(self) -> float:
        return float(self.close[-1])


class Strategy(Protocol):
    name: str
    min_bars: int

    def evaluate(self, series: PriceSeries) -> Signal: ...


def _clamp(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


class MomentumStrategy:
    """Buy strength, sell weakness.

    Works in trending regimes and gets repeatedly stopped out in choppy ones,
    which is exactly why the simulator switches regimes.
    """

    name = "momentum"
    min_bars = 120

    def __init__(self, lookback: int = 60, threshold: float = 0.06,
                 confirm_period: int = 50) -> None:
        self.lookback = lookback
        self.threshold = threshold
        self.confirm_period = confirm_period

    def evaluate(self, series: PriceSeries) -> Signal:
        if len(series) < self.min_bars:
            return hold(series.symbol, self.name, "not enough history yet")

        momentum = ind.roc(series.close, self.lookback)[-1]
        trend = ind.sma(series.close, self.confirm_period)[-1]
        price = series.last
        details = {"roc": round(float(momentum), 4), "sma": round(float(trend), 4)}

        if np.isnan(momentum) or np.isnan(trend):
            return hold(series.symbol, self.name, "indicators still warming up", **details)

        above_trend = price > trend
        if momentum > self.threshold and above_trend:
            strength = _clamp((momentum - self.threshold) / (self.threshold * 3))
            return Signal(series.symbol, Direction.BUY, strength, self.name,
                          f"{momentum:.1%} over {self.lookback} sessions, above its "
                          f"{self.confirm_period}-day average", details)
        if momentum < -self.threshold and not above_trend:
            strength = _clamp((abs(momentum) - self.threshold) / (self.threshold * 3))
            return Signal(series.symbol, Direction.SELL, strength, self.name,
                          f"{momentum:.1%} over {self.lookback} sessions, below its "
                          f"{self.confirm_period}-day average", details)
        return hold(series.symbol, self.name,
                    f"momentum {momentum:+.1%} inside the +/-{self.threshold:.0%} band",
                    **details)


class MeanReversionStrategy:
    """Fade extremes: buy oversold names inside their band, sell overbought ones.

    The mirror image of momentum, and it loses in exactly the regimes momentum
    wins. Running both is how the agent avoids being a one-regime strategy.
    """

    name = "mean_reversion"
    min_bars = 60

    def __init__(self, rsi_period: int = 14, oversold: float = 30.0,
                 overbought: float = 70.0, band_period: int = 20) -> None:
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.band_period = band_period

    def evaluate(self, series: PriceSeries) -> Signal:
        if len(series) < self.min_bars:
            return hold(series.symbol, self.name, "not enough history yet")

        strength_index = ind.rsi(series.close, self.rsi_period)[-1]
        upper, _middle, lower = ind.bollinger(series.close, self.band_period)
        price = series.last
        details = {
            "rsi": round(float(strength_index), 2),
            "lower_band": round(float(lower[-1]), 4),
            "upper_band": round(float(upper[-1]), 4),
        }

        if np.isnan(strength_index) or np.isnan(lower[-1]):
            return hold(series.symbol, self.name, "indicators still warming up", **details)

        at_lower = price <= lower[-1]
        at_upper = price >= upper[-1]

        if strength_index < self.oversold:
            conviction = _clamp((self.oversold - strength_index) / self.oversold)
            if at_lower:
                conviction = _clamp(conviction * 1.3)
            return Signal(
                series.symbol, Direction.BUY, conviction, self.name,
                f"RSI {strength_index:.0f} is oversold"
                + (", and price is at the lower band" if at_lower
                   else " (price still inside the bands)"),
                details,
            )
        if strength_index > self.overbought:
            conviction = _clamp((strength_index - self.overbought) / (100 - self.overbought))
            if at_upper:
                conviction = _clamp(conviction * 1.3)
            return Signal(
                series.symbol, Direction.SELL, conviction, self.name,
                f"RSI {strength_index:.0f} is overbought"
                + (", and price is at the upper band" if at_upper
                   else " (price still inside the bands)"),
                details,
            )
        return hold(series.symbol, self.name,
                    f"RSI {strength_index:.0f} is between {self.oversold:.0f} "
                    f"and {self.overbought:.0f}", **details)


class TrendFollowingStrategy:
    """Moving-average crossover confirmed by MACD.

    Slow, late to every turn, and the most robust of the three.
    """

    name = "trend_following"
    min_bars = 220

    def __init__(self, fast: int = 50, slow: int = 200) -> None:
        self.fast = fast
        self.slow = slow

    def evaluate(self, series: PriceSeries) -> Signal:
        if len(series) < self.min_bars:
            return hold(series.symbol, self.name, "not enough history yet")

        fast_ma = ind.ema(series.close, self.fast)
        slow_ma = ind.ema(series.close, self.slow)
        _, _, histogram = ind.macd(series.close)
        details = {
            "fast_ema": round(float(fast_ma[-1]), 4),
            "slow_ema": round(float(slow_ma[-1]), 4),
            "macd_hist": round(float(histogram[-1]), 4),
        }

        if np.isnan(fast_ma[-1]) or np.isnan(slow_ma[-1]) or np.isnan(histogram[-1]):
            return hold(series.symbol, self.name, "indicators still warming up", **details)

        separation = abs(fast_ma[-1] - slow_ma[-1]) / slow_ma[-1]
        conviction = _clamp(separation / 0.10)

        if separation < 0.002:
            return hold(series.symbol, self.name,
                        "the moving averages are effectively on top of each other",
                        **details)

        bullish = fast_ma[-1] > slow_ma[-1]
        # MACD confirms or contradicts. Only a contradiction with real magnitude
        # blocks: on a smooth trend the histogram converges towards zero, and its
        # noise there must not veto an obvious crossover.
        meaningful = abs(histogram[-1]) > 0.001 * series.last
        contradicts = meaningful and ((histogram[-1] < 0) if bullish else (histogram[-1] > 0))
        if contradicts:
            return hold(series.symbol, self.name,
                        f"the {self.fast}/{self.slow} cross is "
                        f"{'bullish' if bullish else 'bearish'} but MACD contradicts it",
                        **details)

        confirms = meaningful
        if confirms:
            conviction = _clamp(conviction * 1.25)
        confirmation = "confirmed by MACD" if confirms else "MACD neutral"

        direction = Direction.BUY if bullish else Direction.SELL
        return Signal(
            series.symbol, direction, conviction, self.name,
            f"{self.fast}-day {'above' if bullish else 'below'} the {self.slow}-day, "
            f"{confirmation}",
            details,
        )


DEFAULT_STRATEGIES: tuple[Strategy, ...] = (
    MomentumStrategy(),
    MeanReversionStrategy(),
    TrendFollowingStrategy(),
)


def evaluate_all(series: PriceSeries,
                 strategies: tuple[Strategy, ...] = DEFAULT_STRATEGIES) -> list[Signal]:
    return [s.evaluate(series) for s in strategies]


def consensus(signals: list[Signal]) -> Signal:
    """Combine several strategies into one view.

    Deliberately conservative: strategies that disagree cancel out, and the
    result is a HOLD. A tie is not a reason to trade.
    """
    if not signals:
        raise ValueError("no signals to combine")

    symbol = signals[0].symbol
    buy = sum(s.strength for s in signals if s.direction is Direction.BUY)
    sell = sum(s.strength for s in signals if s.direction is Direction.SELL)
    voters = [f"{s.strategy}={s.direction}" for s in signals]
    details = {"buy_score": round(buy, 3), "sell_score": round(sell, 3), "voters": voters}

    net = buy - sell
    if abs(net) < 0.15:
        return hold(symbol, "consensus",
                    "strategies disagree or conviction is too low", **details)

    direction = Direction.BUY if net > 0 else Direction.SELL
    agreeing = [s for s in signals if s.direction is direction]
    reason = "; ".join(f"{s.strategy}: {s.reason}" for s in agreeing)
    return Signal(symbol, direction, _clamp(abs(net) / len(signals)), "consensus",
                  reason, details)


__all__ = [
    "DEFAULT_STRATEGIES",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "PriceSeries",
    "Strategy",
    "TrendFollowingStrategy",
    "consensus",
    "evaluate_all",
]
