"""The ticker worker: keeps the simulated market moving.

Runs as its own container. Advances the session clock, publishes quotes, and
when a session finishes writes it as a daily bar and opens the next one.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging, get_logger
from app.market.live import (
    MINUTES_PER_SECOND,
    TICK_SECONDS,
    advance,
    close_session,
    latest_closes,
    next_session_day,
    publish,
    start_session,
)
from app.models import Bar

log = get_logger("market.ticker")

LOCK_KEY = "market:ticker:lock"
LOCK_TTL = 60
PAUSE_KEY = "market:ticker:paused"


@contextlib.asynccontextmanager
async def ticker_lock(redis: Redis):
    """One ticker only. Two would generate conflicting prices for the same market."""
    token = str(uuid.uuid4())
    acquired = await redis.set(LOCK_KEY, token, nx=True, ex=LOCK_TTL)
    try:
        yield bool(acquired)
    finally:
        if acquired:
            current = await redis.get(LOCK_KEY)
            if current and current.decode() == token:
                await redis.delete(LOCK_KEY)


async def run() -> None:
    redis: Redis = Redis.from_url(settings.redis_url)
    rng = np.random.default_rng()

    async with ticker_lock(redis) as acquired:
        if not acquired:
            log.info("ticker_skipped", reason="another ticker holds the lock")
            await redis.aclose()
            return

        async with SessionLocal() as session:
            newest, universe = await latest_closes(session)
            if newest is None or not universe:
                log.warning("ticker_idle", reason="no market data; run seed-market first")
                await redis.aclose()
                return

        day = next_session_day(newest)
        state = start_session(day, universe, seed=int(datetime.now(UTC).timestamp()))
        log.info("session_open", day=str(day.date()), symbols=len(universe))

        while True:
            # Refresh the lock so a long-lived ticker keeps its claim.
            await redis.expire(LOCK_KEY, LOCK_TTL)

            if await redis.exists(PAUSE_KEY):
                await asyncio.sleep(TICK_SECONDS)
                continue

            quotes = advance(state, universe, TICK_SECONDS * MINUTES_PER_SECOND, rng)
            await publish(redis, quotes, state)

            if state.finished:
                async with SessionLocal() as session:
                    await close_session(session, state, universe)
                    await session.commit()
                day = next_session_day(day)
                state = start_session(
                    day, universe, seed=int(datetime.now(UTC).timestamp())
                )
                log.info("session_open", day=str(day.date()))

            await asyncio.sleep(TICK_SECONDS)


async def main() -> None:
    configure_logging(settings.log_level, json_output=settings.app_env != "local")
    log.info(
        "ticker_starting",
        compression=f"1s = {MINUTES_PER_SECOND}min",
        tick_seconds=TICK_SECONDS,
    )
    try:
        while True:
            try:
                await run()
            except Exception as exc:
                log.exception("ticker_failed", error=str(exc))
            await asyncio.sleep(10)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    _ = (Bar, select, timedelta)  # keep the imports honest for future use
    asyncio.run(main())
