"""A synthetic order book derived from a daily bar.

There is no real depth in daily OHLCV, so the book is reconstructed: a spread
that widens with volatility, and levels whose size decays away from the touch.
This exists so that a large order pays for its size. An engine that fills every
order at the close teaches a strategy that size is free, which is the single
most expensive lie a backtest can tell you.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

# Spread model, in basis points of mid.
BASE_SPREAD_BPS = 3.0
VOL_SPREAD_COEFFICIENT = 220.0    # bps per unit of daily volatility
MIN_SPREAD_BPS = 1.0
MAX_SPREAD_BPS = 320.0
OPEN_SPREAD_MULTIPLIER = 2.4      # the first minutes of a session are wide

# Depth model.
DEPTH_LEVELS = 12
LEVEL_STEP_BPS = 6.0              # price gap between consecutive levels
LEVEL_DECAY = 0.72                # each level holds this fraction of the one before
TOP_OF_BOOK_FRACTION = 0.0009     # share of average daily volume resting at the touch
MIN_TOP_OF_BOOK = 100


@dataclass(frozen=True)
class Level:
    price: Decimal
    size: int


@dataclass(frozen=True)
class Book:
    """A two-sided book around a reference price."""

    symbol: str
    mid: Decimal
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

    @property
    def best_bid(self) -> Decimal:
        return self.bids[0].price

    @property
    def best_ask(self) -> Decimal:
        return self.asks[0].price

    @property
    def spread_bps(self) -> float:
        return float((self.best_ask - self.best_bid) / self.mid) * 10_000

    @property
    def total_ask_size(self) -> int:
        return sum(level.size for level in self.asks)

    @property
    def total_bid_size(self) -> int:
        return sum(level.size for level in self.bids)


def _jitter(seed_material: str, spread: float = 0.25) -> float:
    """Deterministic per-order noise in [1 - spread, 1 + spread].

    Derived from a hash rather than a random generator so that replaying the
    same order against the same bar always produces the same fill.
    """
    digest = hashlib.sha256(seed_material.encode()).digest()
    unit = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return 1.0 - spread + 2 * spread * unit


def spread_bps(daily_vol: float, *, at_open: bool = False, seed: str = "") -> float:
    """Wider for volatile names, wider still at the open."""
    raw = BASE_SPREAD_BPS + VOL_SPREAD_COEFFICIENT * max(0.0, daily_vol)
    if at_open:
        raw *= OPEN_SPREAD_MULTIPLIER
    if seed:
        raw *= _jitter(f"spread:{seed}", 0.2)
    return min(MAX_SPREAD_BPS, max(MIN_SPREAD_BPS, raw))


def build_book(
    symbol: str,
    reference_price: Decimal,
    *,
    daily_vol: float = 0.02,
    avg_volume: int = 1_000_000,
    at_open: bool = False,
    seed: str = "",
) -> Book:
    """Reconstruct a plausible book around `reference_price`."""
    if reference_price <= 0:
        raise ValueError("reference price must be positive")

    half = Decimal(str(spread_bps(daily_vol, at_open=at_open, seed=seed) / 2 / 10_000))
    mid = reference_price
    best_bid = mid * (Decimal(1) - half)
    best_ask = mid * (Decimal(1) + half)

    top_size = max(MIN_TOP_OF_BOOK, int(avg_volume * TOP_OF_BOOK_FRACTION))
    if seed:
        top_size = max(MIN_TOP_OF_BOOK, int(top_size * _jitter(f"size:{seed}", 0.35)))

    step = Decimal(str(LEVEL_STEP_BPS / 10_000))
    bids: list[Level] = []
    asks: list[Level] = []
    for i in range(DEPTH_LEVELS):
        size = max(1, int(top_size * (LEVEL_DECAY**i)))
        bids.append(Level(price=(best_bid * (Decimal(1) - step * i)).quantize(Decimal("0.0001")),
                          size=size))
        asks.append(Level(price=(best_ask * (Decimal(1) + step * i)).quantize(Decimal("0.0001")),
                          size=size))

    return Book(symbol=symbol, mid=mid, bids=tuple(bids), asks=tuple(asks))


def walk(levels: tuple[Level, ...], quantity: int, limit: Decimal | None = None,
         *, is_buy: bool) -> tuple[int, Decimal]:
    """Consume `quantity` against `levels`, respecting an optional limit price.

    Returns (filled_quantity, average_price). A partial fill means the book ran
    out of depth, or the limit stopped being marketable partway down.
    """
    remaining = quantity
    notional = Decimal(0)
    filled = 0

    for level in levels:
        if remaining <= 0:
            break
        if limit is not None:
            if is_buy and level.price > limit:
                break
            if not is_buy and level.price < limit:
                break
        take = min(remaining, level.size)
        notional += level.price * take
        filled += take
        remaining -= take

    if filled == 0:
        return 0, Decimal(0)
    return filled, (notional / filled).quantize(Decimal("0.0001"))


__all__ = ["Book", "Level", "build_book", "spread_bps", "walk"]
