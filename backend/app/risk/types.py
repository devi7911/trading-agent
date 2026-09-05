"""What goes into the risk gate and what comes out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.strategy.signals import Direction


class Denial(StrEnum):
    """Why the gate said no. Every rejection carries one of these, always."""

    MALFORMED_INTENT = "malformed_intent"
    UNKNOWN_SYMBOL = "unknown_symbol"
    STALE_DATA = "stale_data"
    MARKET_CLOSED = "market_closed"
    NEAR_SESSION_EDGE = "near_session_edge"
    INSUFFICIENT_CASH = "insufficient_cash"
    CASH_FLOOR_BREACHED = "cash_floor_breached"
    POSITION_CAP = "position_cap"
    SECTOR_CONCENTRATION = "sector_concentration"
    TRADE_LIMIT_REACHED = "trade_limit_reached"
    SYMBOL_TRADE_LIMIT_REACHED = "symbol_trade_limit_reached"
    DUPLICATE_INTENT = "duplicate_intent"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    ACCOUNT_HALTED = "account_halted"
    GLOBAL_HALT = "global_halt"
    NOTHING_TO_SELL = "nothing_to_sell"
    OBSERVE_ONLY = "observe_only"
    ZERO_QUANTITY = "zero_quantity"


@dataclass(frozen=True)
class Intent:
    """What the reasoning layer wants to do. Never reaches a broker unchanged."""

    symbol: str
    direction: Direction
    quantity: int
    conviction: float
    rationale: str
    strategy: str = "unspecified"
    idempotency_key: str | None = None


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    denial: Denial | None = None
    adjusted_quantity: int | None = None


@dataclass
class Verdict:
    """The gate's answer. `quantity` is authoritative - it may be smaller than
    the intent asked for, and it is never larger."""

    approved: bool
    quantity: int
    denial: Denial | None = None
    message: str = ""
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def was_reduced(self) -> bool:
        return self.approved and any(c.adjusted_quantity is not None for c in self.checks)

    def trace(self) -> list[dict]:
        """Persisted with the decision so any verdict can be explained later."""
        return [
            {
                "check": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "denial": str(c.denial) if c.denial else None,
                "adjusted_quantity": c.adjusted_quantity,
            }
            for c in self.checks
        ]


@dataclass(frozen=True)
class RiskContext:
    """Everything the gate needs, gathered before it runs.

    The gate is a pure function of this - no database, no clock, no network -
    which is what makes it exhaustively testable.
    """

    now: datetime
    market_open: bool
    minutes_from_open: float
    minutes_to_close: float

    price: Decimal
    price_age_seconds: float
    symbol_known: bool
    sector: str | None

    cash: Decimal
    equity: Decimal
    starting_equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal

    held_quantity: int
    sector_exposure: Decimal          # market value already held in this sector
    trades_today: int
    symbol_trades_today: int
    seen_idempotency_keys: frozenset[str]

    account_halted: bool
    global_halt: bool
    autonomy_level: str

    # Policy limits, already clamped against the system ceilings.
    max_position_pct: Decimal
    max_sector_pct: Decimal
    cash_floor_pct: Decimal
    max_daily_loss_pct: Decimal
    max_drawdown_pct: Decimal
    max_trades_per_day: int
    max_trades_per_symbol_per_day: int

    max_price_age_seconds: float = 90_000.0   # daily bars: a bit over a day
    session_edge_minutes: float = 5.0


__all__ = ["CheckResult", "Denial", "Intent", "RiskContext", "Verdict"]
