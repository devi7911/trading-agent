"""The Telegram bot worker: two-way commands.

Long-polls for messages so no public webhook endpoint is needed - the whole
thing runs behind a home router with nothing exposed.

Commands are read-only or safety-increasing by design. `/halt` stops the agent;
there is deliberately no command that raises a limit, increases autonomy, or
places a trade. Anyone who gets hold of the chat can make the system safer, not
bolder.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select

from app.agent.worker import HALT_KEY
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging, get_logger
from app.models import Account, AgentDecision, AgentRun, Bar, Instrument, Position, User
from app.notify.telegram import TelegramClient

log = get_logger("notify.bot")

POLL_TIMEOUT = 25

HELP = """Commands

/status      how the agent and the account are doing
/positions   what is currently held
/pnl         realised and unrealised profit and loss
/explain SYM why the agent last did what it did with a symbol
/halt        stop all new entries
/resume      lift the halt
/help        this message

There is no command that raises a limit, increases autonomy, or places a trade."""


async def _account_for(session, user: User) -> Account | None:
    return (
        await session.execute(select(Account).where(Account.user_id == user.id).limit(1))
    ).scalar_one_or_none()


async def _last_price(session, instrument_id) -> Decimal | None:
    return await session.scalar(
        select(Bar.close)
        .where(Bar.instrument_id == instrument_id, Bar.timeframe == "1d")
        .order_by(Bar.ts.desc())
        .limit(1)
    )


async def cmd_status(session, user: User, redis: Redis) -> str:
    account = await _account_for(session, user)
    if account is None:
        return "No trading account on this login."
    run = (
        await session.execute(
            select(AgentRun).where(AgentRun.user_id == user.id)
            .order_by(AgentRun.started_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    halted = bool(await redis.exists(HALT_KEY))

    change = (
        (account.equity / account.starting_cash - 1) * 100 if account.starting_cash else 0
    )
    lines = [
        f"Equity {account.equity:,.2f} ({change:+.2f}% since inception)",
        f"Cash   {account.cash:,.2f}",
        f"Agent  {'HALTED' if halted or account.is_halted else 'running'}",
    ]
    if run:
        lines.append(
            f"Last tick {run.started_at:%d %b %H:%M} - {run.orders_placed} orders, "
            f"{run.denials} declined"
        )
    return "\n".join(lines)


async def cmd_positions(session, user: User) -> str:
    account = await _account_for(session, user)
    if account is None:
        return "No trading account on this login."
    rows = list(
        (
            await session.execute(
                select(Position, Instrument.symbol)
                .join(Instrument, Instrument.id == Position.instrument_id)
                .where(Position.account_id == account.id, Position.quantity != 0)
            )
        ).all()
    )
    if not rows:
        return "No open positions."

    lines = []
    for position, symbol in rows:
        last = await _last_price(session, position.instrument_id)
        value = (last or Decimal(0)) * position.quantity
        change = ((last / position.avg_cost - 1) * 100) if last and position.avg_cost else 0
        lines.append(f"{symbol:<6} {position.quantity:>5} @ {position.avg_cost:>9,.2f}  "
                     f"{value:>11,.2f}  {change:+.1f}%")
    return "Open positions\n\n" + "\n".join(lines)


async def cmd_pnl(session, user: User) -> str:
    account = await _account_for(session, user)
    if account is None:
        return "No trading account on this login."
    positions = list(
        (
            await session.execute(
                select(Position).where(Position.account_id == account.id)
            )
        ).scalars()
    )
    realised = sum((p.realised_pnl for p in positions), Decimal(0))
    unrealised = Decimal(0)
    for position in positions:
        if position.quantity:
            last = await _last_price(session, position.instrument_id)
            if last:
                unrealised += (last - position.avg_cost) * position.quantity
    commission = sum((p.total_commission for p in positions), Decimal(0))
    return (
        f"Realised    {realised:>12,.2f}\n"
        f"Unrealised  {unrealised:>12,.2f}\n"
        f"Commission  {commission:>12,.2f}\n"
        f"Equity      {account.equity:>12,.2f}"
    )


async def cmd_explain(session, user: User, symbol: str) -> str:
    decision = (
        await session.execute(
            select(AgentDecision)
            .join(AgentRun, AgentRun.id == AgentDecision.run_id)
            .where(AgentRun.user_id == user.id, AgentDecision.symbol == symbol.upper())
            .order_by(AgentDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if decision is None:
        return f"The agent has not considered {symbol.upper()}."

    verdict = (
        f"{decision.direction} {decision.approved_quantity}"
        if decision.approved else f"declined ({decision.denial or 'held'})"
    )
    return (
        f"{decision.symbol} - {verdict}\n"
        f"Conviction {decision.conviction:.2f}\n\n"
        f"{decision.rationale}"
    )


async def handle(text: str, session, user: User, redis: Redis) -> str:
    command, _, argument = text.strip().partition(" ")
    command = command.lower().lstrip("/").split("@")[0]

    if command in ("status", "s"):
        return await cmd_status(session, user, redis)
    if command in ("positions", "pos"):
        return await cmd_positions(session, user)
    if command == "pnl":
        return await cmd_pnl(session, user)
    if command == "explain":
        if not argument.strip():
            return "Which symbol? For example: /explain VBPZ"
        return await cmd_explain(session, user, argument.strip())
    if command in ("halt", "pause", "stop"):
        await redis.set(HALT_KEY, f"telegram:{user.email}")
        return "Halted. No new entries will be placed. Send /resume to lift it."
    if command == "resume":
        await redis.delete(HALT_KEY)
        return "Resumed. The agent will act on its next tick."
    return HELP


async def _link(session, token: str, chat_id: str) -> str:
    user = (
        await session.execute(select(User).where(User.telegram_link_token == token))
    ).scalar_one_or_none()
    if user is None:
        return "That link code is not valid. Generate a new one in the app."
    user.telegram_chat_id = str(chat_id)
    user.telegram_link_token = None
    await session.commit()
    return f"Linked to {user.email}. Send /help to see what I can do."


async def poll_once(client: TelegramClient, redis: Redis, offset: int | None) -> int | None:
    updates = await client.get_updates(offset=offset)
    for update in updates:
        offset = update["update_id"] + 1
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat_id = str((message.get("chat") or {}).get("id", ""))
        if not text or not chat_id:
            continue

        async with SessionLocal() as session:
            if text.lower().startswith("/start"):
                token = text.partition(" ")[2].strip()
                reply = (
                    await _link(session, token, chat_id) if token
                    else "Send /start followed by the link code from the app."
                )
            else:
                user = (
                    await session.execute(
                        select(User).where(User.telegram_chat_id == chat_id)
                    )
                ).scalar_one_or_none()
                if user is None:
                    reply = ("This chat is not linked to an account. Send /start "
                             "followed by the code from the app.")
                else:
                    reply = await handle(text, session, user, redis)
                    await session.commit()
        await client.send(chat_id, reply)
    return offset


async def main() -> None:
    configure_logging(settings.log_level, json_output=settings.app_env != "local")
    client = TelegramClient()
    if not client.configured:
        log.info("telegram_bot_idle", reason="no TELEGRAM_BOT_TOKEN set")
        # Stay alive so compose does not restart-loop a container that exits.
        # Notifications are still recorded in the database and visible in the app;
        # only the push half is missing. An Event that is never set blocks
        # forever without a polling loop.
        await asyncio.Event().wait()
        return

    identity = await client.me()
    log.info("telegram_bot_starting", username=(identity or {}).get("username"))

    redis: Redis = Redis.from_url(settings.redis_url)
    offset: int | None = None
    try:
        while True:
            try:
                offset = await poll_once(client, redis, offset)
            except Exception as exc:
                log.exception("telegram_poll_cycle_failed", error=str(exc))
                await asyncio.sleep(5)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    _ = datetime.now(UTC)
    asyncio.run(main())
