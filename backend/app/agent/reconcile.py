"""The reconciliation job.

Rebuilds cash and every position from the fill history and compares them with
stored state. A mismatch means the ledger and reality have diverged, and the
only safe response is to stop trading: an agent acting on a wrong balance
compounds the error with every order.

This is the check that turns "the numbers are probably fine" into a fact the
system verifies on a schedule.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
from app.core.logging import get_logger
from app.execution import service as execution
from app.models import Account, Instrument, Position, User
from app.notify.service import notify

log = get_logger(__name__)

TOLERANCE = Decimal("0.01")


async def reconcile_account(session: AsyncSession, account: Account) -> dict:
    expected_cash = await execution.cash_from_fills(session, account)
    rebuilt = await execution.rebuild_positions_from_fills(session, account)

    stored = list(
        (
            await session.execute(select(Position).where(Position.account_id == account.id))
        ).scalars()
    )
    mismatches: list[dict] = []
    for position in stored:
        expected = rebuilt.get(position.instrument_id, {"quantity": 0})
        if position.quantity != expected["quantity"]:
            symbol = await session.scalar(
                select(Instrument.symbol).where(Instrument.id == position.instrument_id)
            )
            mismatches.append({
                "symbol": symbol,
                "stored": position.quantity,
                "expected": expected["quantity"],
            })

    difference = (account.cash - expected_cash).quantize(TOLERANCE)
    ok = not mismatches and abs(difference) < TOLERANCE

    metrics.gauge("trading_reconciliation_ok", 1.0 if ok else 0.0,
                  account=str(account.id)[:8])
    metrics.gauge("trading_cash_drift", float(abs(difference)), account=str(account.id)[:8])

    return {
        "reconciled": ok,
        "cash_stored": str(account.cash),
        "cash_from_fills": str(expected_cash),
        "cash_difference": str(difference),
        "position_mismatches": mismatches,
    }


async def reconcile_and_halt(session: AsyncSession, user: User, account: Account) -> dict:
    """Reconcile, and halt the account if it does not add up."""
    report = await reconcile_account(session, account)
    if report["reconciled"]:
        return report

    account.is_halted = True
    account.halt_reason = (
        f"Reconciliation failed: cash differs by {report['cash_difference']}, "
        f"{len(report['position_mismatches'])} position mismatch(es)."
    )[:255]
    log.error("reconciliation_failed", account=str(account.id), report=report)

    try:
        await notify(
            session, user,
            event="reconciliation.failed",
            title="Trading halted: the ledger does not reconcile",
            body=(f"Stored cash {report['cash_stored']} against "
                  f"{report['cash_from_fills']} implied by the fills.\n\n"
                  f"The account is halted until this is resolved."),
            dedupe_key="reconciliation",
            payload=report,
        )
    except Exception as exc:
        # The halt is what matters and it is already applied; a failed
        # notification must not undo it or hide it.
        log.warning("reconciliation_notify_failed", error=type(exc).__name__)
    return report


async def reconcile_all(session: AsyncSession) -> dict:
    """Sweep every account. Returns a summary for the metrics endpoint."""
    rows = list(
        (
            await session.execute(
                select(User, Account).join(Account, Account.user_id == User.id)
            )
        ).all()
    )
    checked = failed = 0
    for user, account in rows:
        report = await reconcile_and_halt(session, user, account)
        checked += 1
        if not report["reconciled"]:
            failed += 1

    metrics.gauge("trading_accounts_checked", checked)
    metrics.gauge("trading_accounts_failing_reconciliation", failed)
    log.info("reconciliation_sweep", checked=checked, failed=failed)
    return {"checked": checked, "failed": failed}


__all__ = ["TOLERANCE", "reconcile_account", "reconcile_all", "reconcile_and_halt"]
