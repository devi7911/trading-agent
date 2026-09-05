"""The agent worker.

Runs as its own container so it survives an API restart and is not tied to any
HTTP request. Holds a Redis lock so exactly one instance ticks at a time, even
if two workers are started by accident.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select

from app.agent.clock import market_clock
from app.agent.loop import run_tick
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging, correlation_id, get_logger
from app.models import Policy, RunTrigger, User

log = get_logger("agent.worker")

LOCK_KEY = "agent:tick:lock"
LOCK_TTL_SECONDS = 300
HALT_KEY = "agent:halt"
TICK_INTERVAL_SECONDS = 900  # every 15 minutes


@contextlib.asynccontextmanager
async def singleton_lock(redis: Redis, key: str = LOCK_KEY):
    """Only one worker ticks at a time. The TTL means a crashed holder releases
    the lock on its own rather than wedging the agent forever."""
    token = str(uuid.uuid4())
    acquired = await redis.set(key, token, nx=True, ex=LOCK_TTL_SECONDS)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            # Only release a lock we still own - a slow tick may have let it expire
            # and another worker may already hold it.
            current = await redis.get(key)
            if current and current.decode() == token:
                await redis.delete(key)


async def is_halted(redis: Redis) -> bool:
    """The kill switch lives outside the agent, so it works when the loop is wedged."""
    return bool(await redis.exists(HALT_KEY))


async def tick_all_users(*, trigger: RunTrigger = RunTrigger.SCHEDULED) -> int:
    """One pass across every user with an active policy."""
    redis: Redis = Redis.from_url(settings.redis_url)
    ticked = 0
    try:
        async with singleton_lock(redis) as acquired:
            if not acquired:
                log.info("tick_skipped", reason="another worker holds the lock")
                return 0

            halted = await is_halted(redis)
            async with SessionLocal() as session:
                # In simulation the market clock is authoritative: the agent runs
                # mid-session on the day of the most recent bar.
                clock = (
                    await market_clock(session)
                    if settings.broker == "sim"
                    else datetime.now(UTC)
                )
                users = list(
                    (
                        await session.execute(
                            select(User)
                            .join(Policy, Policy.user_id == User.id)
                            .where(User.is_active.is_(True), Policy.is_active.is_(True))
                            .distinct()
                        )
                    ).scalars()
                )
                for user in users:
                    correlation_id.set(str(uuid.uuid4()))
                    await run_tick(
                        session, user, trigger=trigger, global_halt=halted, now=clock
                    )
                    ticked += 1
                await session.commit()
    finally:
        await redis.aclose()
    return ticked


async def main() -> None:
    configure_logging(settings.log_level, json_output=settings.app_env != "local")
    log.info("agent_worker_starting", interval_seconds=TICK_INTERVAL_SECONDS)
    try:
        while True:
            try:
                count = await tick_all_users()
                log.info("tick_cycle_done", users=count)
            except Exception as exc:
                # A failed cycle must not kill the worker; the next one retries.
                log.exception("tick_cycle_failed", error=str(exc))
            await asyncio.sleep(TICK_INTERVAL_SECONDS)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
