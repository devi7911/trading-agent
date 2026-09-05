"""The risk gate.

This is the component that decides whether the system can be left running
unattended. Everything it does is deterministic, has no dependencies it cannot
see, and can only ever shrink an intent - never expand one.

Rules it enforces on itself:

* No language model is involved, imported, or consulted.
* It is a pure function of (Intent, RiskContext). No database, no clock, no
  network - so the property tests can throw millions of states at it.
* Position caps SHRINK an order to fit. Everything else denies outright.
* Every outcome carries a Denial code and a human-readable reason.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.models.policy import SYSTEM_CEILINGS
from app.risk.types import CheckResult, Denial, Intent, RiskContext, Verdict
from app.strategy.signals import Direction


def clamp_policy(value: Decimal, key: str) -> Decimal:
    """A user policy may be stricter than the system ceiling, never looser."""
    ceiling = SYSTEM_CEILINGS.get(key)
    if ceiling is None:
        return value
    return min(value, Decimal(str(ceiling)))


def _deny(checks: list[CheckResult], name: str, denial: Denial, detail: str) -> Verdict:
    checks.append(CheckResult(name=name, passed=False, detail=detail, denial=denial))
    return Verdict(approved=False, quantity=0, denial=denial, message=detail, checks=checks)


def _pass(checks: list[CheckResult], name: str, detail: str,
          adjusted: int | None = None) -> None:
    checks.append(
        CheckResult(name=name, passed=True, detail=detail, adjusted_quantity=adjusted)
    )


def evaluate(intent: Intent, ctx: RiskContext) -> Verdict:
    """Run every check, in order. The first failure stops everything."""
    checks: list[CheckResult] = []

    # --- 1. the intent itself ------------------------------------------------
    if intent.direction is Direction.HOLD:
        return _deny(checks, "schema", Denial.MALFORMED_INTENT,
                     "A hold is not an order.")
    if intent.quantity <= 0:
        return _deny(checks, "schema", Denial.ZERO_QUANTITY,
                     f"Quantity must be positive, got {intent.quantity}.")
    if not 0.0 <= intent.conviction <= 1.0:
        return _deny(checks, "schema", Denial.MALFORMED_INTENT,
                     f"Conviction {intent.conviction} is outside [0, 1].")
    if not ctx.symbol_known:
        return _deny(checks, "schema", Denial.UNKNOWN_SYMBOL,
                     f"{intent.symbol} is not in the tradable universe.")
    _pass(checks, "schema", "Intent is well formed.")

    # --- 2. halts, before anything else is considered ------------------------
    if ctx.global_halt:
        return _deny(checks, "global_halt", Denial.GLOBAL_HALT,
                     "Trading is halted system-wide.")
    if ctx.account_halted:
        return _deny(checks, "account_halt", Denial.ACCOUNT_HALTED,
                     "This account is halted.")
    _pass(checks, "halts", "No halt in force.")

    # --- 3. autonomy ---------------------------------------------------------
    if ctx.autonomy_level == "observe":
        return _deny(checks, "autonomy", Denial.OBSERVE_ONLY,
                     "Autonomy is set to observe: the intent is logged, not placed.")
    _pass(checks, "autonomy", f"Autonomy level is {ctx.autonomy_level}.")

    # --- 4. data freshness ---------------------------------------------------
    if ctx.price <= 0:
        return _deny(checks, "freshness", Denial.STALE_DATA,
                     f"No usable price for {intent.symbol}.")
    if ctx.sessions_stale > ctx.max_sessions_stale:
        return _deny(checks, "freshness", Denial.STALE_DATA,
                     f"The last bar is {ctx.sessions_stale} sessions old; the limit "
                     f"is {ctx.max_sessions_stale}.")
    _pass(checks, "freshness",
          f"Price {ctx.price} is from {ctx.sessions_stale} session(s) ago.")

    # --- 5. session ----------------------------------------------------------
    if not ctx.market_open:
        return _deny(checks, "session", Denial.MARKET_CLOSED, "The market is closed.")
    if ctx.minutes_from_open < ctx.session_edge_minutes:
        return _deny(checks, "session", Denial.NEAR_SESSION_EDGE,
                     f"Only {ctx.minutes_from_open:.1f} minutes into the session; "
                     f"the open is too disorderly to trade.")
    if ctx.minutes_to_close < ctx.session_edge_minutes:
        return _deny(checks, "session", Denial.NEAR_SESSION_EDGE,
                     f"Only {ctx.minutes_to_close:.1f} minutes to the close.")
    _pass(checks, "session", "Inside the orderly part of the session.")

    # --- 6. duplicate --------------------------------------------------------
    if intent.idempotency_key and intent.idempotency_key in ctx.seen_idempotency_keys:
        return _deny(checks, "duplicate", Denial.DUPLICATE_INTENT,
                     f"Intent {intent.idempotency_key} has already been acted on.")
    _pass(checks, "duplicate", "Not a repeat of a recent intent.")

    # --- 7. loss limits ------------------------------------------------------
    if ctx.day_start_equity > 0:
        day_change = (ctx.equity / ctx.day_start_equity - 1) * 100
        if day_change <= -clamp_policy(ctx.max_daily_loss_pct, "max_daily_loss_pct"):
            return _deny(checks, "daily_loss", Denial.DAILY_LOSS_LIMIT,
                         f"Down {abs(day_change):.2f}% today; the limit is "
                         f"{ctx.max_daily_loss_pct}%. Halting new entries.")
        _pass(checks, "daily_loss", f"Day change {day_change:+.2f}% is within limits.")

    if ctx.peak_equity > 0:
        drawdown = (ctx.equity / ctx.peak_equity - 1) * 100
        if drawdown <= -clamp_policy(ctx.max_drawdown_pct, "max_drawdown_pct"):
            return _deny(checks, "drawdown", Denial.DRAWDOWN_LIMIT,
                         f"Drawdown {abs(drawdown):.2f}% from peak; the limit is "
                         f"{ctx.max_drawdown_pct}%.")
        _pass(checks, "drawdown", f"Drawdown {drawdown:+.2f}% is within limits.")

    # --- 8. frequency --------------------------------------------------------
    trade_ceiling = min(ctx.max_trades_per_day, int(SYSTEM_CEILINGS["max_trades_per_day"]))
    if ctx.trades_today >= trade_ceiling:
        return _deny(checks, "frequency", Denial.TRADE_LIMIT_REACHED,
                     f"Already placed {ctx.trades_today} trades today; the limit is "
                     f"{trade_ceiling}.")
    if ctx.symbol_trades_today >= ctx.max_trades_per_symbol_per_day:
        return _deny(checks, "frequency", Denial.SYMBOL_TRADE_LIMIT_REACHED,
                     f"Already traded {intent.symbol} {ctx.symbol_trades_today} times "
                     f"today; the limit is {ctx.max_trades_per_symbol_per_day}.")
    _pass(checks, "frequency",
          f"{ctx.trades_today}/{trade_ceiling} trades used today.")

    # --- 9. sells: you can only sell what you hold ---------------------------
    if intent.direction is Direction.SELL:
        if ctx.held_quantity <= 0:
            return _deny(checks, "position", Denial.NOTHING_TO_SELL,
                         f"No position in {intent.symbol} to sell.")
        quantity = min(intent.quantity, ctx.held_quantity)
        adjusted = quantity if quantity != intent.quantity else None
        _pass(checks, "position",
              f"Selling {quantity} of {ctx.held_quantity} held.", adjusted)
        return Verdict(approved=True, quantity=quantity, checks=checks,
                       message=f"Approved: sell {quantity} {intent.symbol}.")

    # --- 10. buys: sizing, caps, concentration, cash -------------------------
    quantity = intent.quantity

    # Position cap. Shrinks rather than denies - a smaller position is still a
    # valid expression of the same idea.
    max_position_pct = clamp_policy(ctx.max_position_pct, "max_position_pct")
    max_position_value = ctx.equity * max_position_pct / 100
    current_value = ctx.held_quantity * ctx.price
    room = max_position_value - current_value
    if room <= 0:
        return _deny(checks, "position_cap", Denial.POSITION_CAP,
                     f"{intent.symbol} is already at its {max_position_pct}% cap.")
    allowed = int((room / ctx.price).to_integral_value(rounding=ROUND_DOWN))
    if allowed <= 0:
        return _deny(checks, "position_cap", Denial.POSITION_CAP,
                     f"The {max_position_pct}% cap leaves room for less than one share.")
    if allowed < quantity:
        _pass(checks, "position_cap",
              f"Reduced {quantity} to {allowed} to stay inside the "
              f"{max_position_pct}% position cap.", allowed)
        quantity = allowed
    else:
        _pass(checks, "position_cap", f"Within the {max_position_pct}% position cap.")

    # Sector concentration.
    max_sector_pct = clamp_policy(ctx.max_sector_pct, "max_sector_pct")
    sector_room = ctx.equity * max_sector_pct / 100 - ctx.sector_exposure
    if sector_room <= 0:
        return _deny(checks, "concentration", Denial.SECTOR_CONCENTRATION,
                     f"{ctx.sector or 'This sector'} is already at its "
                     f"{max_sector_pct}% cap.")
    sector_allowed = int((sector_room / ctx.price).to_integral_value(rounding=ROUND_DOWN))
    if sector_allowed <= 0:
        return _deny(checks, "concentration", Denial.SECTOR_CONCENTRATION,
                     f"The {max_sector_pct}% sector cap leaves room for less than "
                     f"one share.")
    if sector_allowed < quantity:
        _pass(checks, "concentration",
              f"Reduced {quantity} to {sector_allowed} to stay inside the "
              f"{max_sector_pct}% sector cap.", sector_allowed)
        quantity = sector_allowed
    else:
        _pass(checks, "concentration",
              f"{ctx.sector or 'Sector'} exposure is within {max_sector_pct}%.")

    # Cash floor: the agent is never allowed to be fully invested.
    floor = ctx.equity * ctx.cash_floor_pct / 100
    spendable = ctx.cash - floor
    if spendable <= 0:
        return _deny(checks, "cash_floor", Denial.CASH_FLOOR_BREACHED,
                     f"Cash {ctx.cash} is at or below the {ctx.cash_floor_pct}% floor "
                     f"of {floor.quantize(Decimal('0.01'))}.")
    affordable = int((spendable / ctx.price).to_integral_value(rounding=ROUND_DOWN))
    if affordable <= 0:
        return _deny(checks, "buying_power", Denial.INSUFFICIENT_CASH,
                     f"{spendable.quantize(Decimal('0.01'))} spendable will not buy "
                     f"one share at {ctx.price}.")
    if affordable < quantity:
        _pass(checks, "buying_power",
              f"Reduced {quantity} to {affordable} to keep the "
              f"{ctx.cash_floor_pct}% cash floor intact.", affordable)
        quantity = affordable
    else:
        _pass(checks, "buying_power", "Sufficient cash above the floor.")

    if quantity <= 0:
        return _deny(checks, "sizing", Denial.ZERO_QUANTITY,
                     "Every cap combined leaves nothing to buy.")

    return Verdict(approved=True, quantity=quantity, checks=checks,
                   message=f"Approved: buy {quantity} {intent.symbol}.")


__all__ = ["clamp_policy", "evaluate"]
