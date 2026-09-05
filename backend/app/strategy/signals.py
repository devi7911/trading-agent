"""Signals are what strategies emit. They are opinions, not orders.

A signal never reaches the broker. It is one input to the agent's reasoning,
and everything downstream of it can still shrink it or throw it away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Direction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: Direction
    strength: float                 # 0.0 to 1.0 - conviction, not size
    strategy: str
    reason: str
    indicators: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be within [0, 1], got {self.strength}")

    @property
    def is_actionable(self) -> bool:
        return self.direction is not Direction.HOLD and self.strength > 0


def hold(symbol: str, strategy: str, reason: str, **indicators: Any) -> Signal:
    """Holding is a decision with a reason, not the absence of one."""
    return Signal(
        symbol=symbol,
        direction=Direction.HOLD,
        strength=0.0,
        strategy=strategy,
        reason=reason,
        indicators=indicators,
    )


__all__ = ["Direction", "Signal", "hold"]
