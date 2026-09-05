"""The matching engine.

Deliberately unkind: spreads widen with volatility, big orders walk the book and
pay for it, depth runs out, and the venue rejects things for the same reasons a
real one does. Every decision is seeded from the order's own identity, so a
replay of the same order against the same bar produces the same fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.execution.book import Book, _jitter, build_book, walk
from app.execution.port import ExecutionResult, FillEvent, OrderRequest
from app.models.order import OrderType, RejectReason, Side

# US equities are commission-free at the retail venues this simulates. The hook
# stays so a different fee model can be dropped in without touching callers.
COMMISSION_PER_SHARE = Decimal("0.00")
COMMISSION_MINIMUM = Decimal("0.00")

# Acknowledgement latency, in milliseconds. Real, and occasionally expensive.
LATENCY_MS_MIN = 40
LATENCY_MS_MAX = 260

# Chance that a marketable order gets split across two prints rather than one.
PARTIAL_FILL_PROBABILITY = 0.28


@dataclass(frozen=True)
class MarketContext:
    """Everything the engine needs to know about one symbol, right now."""

    symbol: str
    reference_price: Decimal
    daily_vol: float = 0.02
    avg_volume: int = 1_000_000
    is_open: bool = True
    at_open: bool = False
    is_halted: bool = False
    is_tradable: bool = True


def commission_for(quantity: int) -> Decimal:
    if COMMISSION_PER_SHARE == 0:
        return Decimal("0.00")
    return max(COMMISSION_MINIMUM, (COMMISSION_PER_SHARE * quantity)).quantize(Decimal("0.0001"))


def latency_for(seed: str) -> timedelta:
    span = LATENCY_MS_MAX - LATENCY_MS_MIN
    ms = LATENCY_MS_MIN + int(span * (_jitter(f"latency:{seed}", 0.5) - 0.5 + 0.5))
    return timedelta(milliseconds=min(LATENCY_MS_MAX, max(LATENCY_MS_MIN, ms)))


def _slippage_bps(reference: Decimal, fill_price: Decimal, side: Side) -> Decimal:
    """Positive means the fill was worse than the reference price."""
    if reference <= 0:
        return Decimal(0)
    raw = (fill_price - reference) / reference * 10_000
    if side == Side.SELL:
        raw = -raw
    return raw.quantize(Decimal("0.01"))


def _split(quantity: int, seed: str) -> list[int]:
    """Sometimes an order prints in two pieces instead of one."""
    if quantity < 2 or _jitter(f"split:{seed}", 0.5) > (0.5 + PARTIAL_FILL_PROBABILITY):
        return [quantity]
    first = max(1, int(quantity * (0.3 + 0.4 * _jitter(f"ratio:{seed}", 0.5))))
    first = min(first, quantity - 1)
    return [first, quantity - first]


def _triggered(request: OrderRequest, book: Book) -> bool:
    """Has a stop been hit? Buy stops trigger above, sell stops below."""
    if request.stop_price is None:
        return True
    if request.side == Side.BUY:
        return book.best_ask >= request.stop_price
    return book.best_bid <= request.stop_price


def execute(
    request: OrderRequest,
    context: MarketContext,
    *,
    as_of: datetime,
    seed: str,
) -> ExecutionResult:
    """Decide what the venue does with this order. Pure - no I/O, no database."""

    # --- venue-level rejections, in the order a real venue applies them ---
    if request.quantity <= 0:
        return ExecutionResult(False, reject_reason=RejectReason.INVALID_QUANTITY,
                               message="Quantity must be a positive whole number.")
    if not context.is_tradable:
        return ExecutionResult(False, reject_reason=RejectReason.SYMBOL_NOT_TRADABLE,
                               message=f"{context.symbol} is not tradable.")
    if context.is_halted:
        return ExecutionResult(False, reject_reason=RejectReason.SYMBOL_HALTED,
                               message=f"Trading in {context.symbol} is halted.")
    if not context.is_open:
        return ExecutionResult(False, reject_reason=RejectReason.MARKET_CLOSED,
                               message="The market is closed.")
    if context.reference_price <= 0:
        return ExecutionResult(False, reject_reason=RejectReason.NO_MARKET_DATA,
                               message=f"No price available for {context.symbol}.")

    needs_limit = request.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT)
    if needs_limit and (request.limit_price is None or request.limit_price <= 0):
        return ExecutionResult(False, reject_reason=RejectReason.INVALID_PRICE,
                               message="A limit price is required and must be positive.")
    needs_stop = request.order_type in (OrderType.STOP, OrderType.STOP_LIMIT)
    if needs_stop and (request.stop_price is None or request.stop_price <= 0):
        return ExecutionResult(False, reject_reason=RejectReason.INVALID_PRICE,
                               message="A stop price is required and must be positive.")

    book = build_book(
        context.symbol,
        context.reference_price,
        daily_vol=context.daily_vol,
        avg_volume=context.avg_volume,
        at_open=context.at_open,
        seed=seed,
    )

    # --- a stop that has not been hit simply rests ---
    if needs_stop and not _triggered(request, book):
        return ExecutionResult(True, resting=True,
                               message="Stop order accepted and resting.")

    is_buy = request.side == Side.BUY
    levels = book.asks if is_buy else book.bids

    # A triggered stop becomes a market order; a triggered stop-limit keeps its limit.
    limit = request.limit_price if needs_limit else None

    filled, avg_price = walk(levels, request.quantity, limit, is_buy=is_buy)

    if filled == 0:
        # A limit that is not marketable rests; anything else found no liquidity.
        if request.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            return ExecutionResult(True, resting=True,
                                   message="Limit order accepted and resting.")
        return ExecutionResult(False, reject_reason=RejectReason.NO_MARKET_DATA,
                               message="No liquidity available.")

    ack_at = as_of + latency_for(seed)
    fills: list[FillEvent] = []
    for i, chunk in enumerate(_split(filled, seed), start=1):
        fills.append(
            FillEvent(
                sequence=i,
                quantity=chunk,
                price=avg_price,
                commission=commission_for(chunk),
                slippage_bps=_slippage_bps(context.reference_price, avg_price, request.side),
                filled_at=ack_at + timedelta(milliseconds=12 * (i - 1)),
            )
        )

    return ExecutionResult(
        accepted=True,
        fills=fills,
        resting=filled < request.quantity,
        message=(
            None if filled == request.quantity
            else f"Partially filled {filled} of {request.quantity}; book depth exhausted."
        ),
    )


__all__ = ["MarketContext", "commission_for", "execute", "latency_for"]
