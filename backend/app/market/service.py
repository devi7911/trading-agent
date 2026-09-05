"""Ingestion: pull from a provider, normalise, persist.

Bars land in Timescale, the latest quote per symbol lands in Redis. Writes are
idempotent - re-running an ingest updates rather than duplicates - so a crashed
seed can simply be run again.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.market.provider import MarketDataProvider
from app.models import Bar, CorporateEvent, Instrument, NewsItem

log = get_logger(__name__)

# Postgres caps a single statement at 32767 bind parameters, so the row count
# per insert depends on how wide the row is.
#
# Counting the dict keys alone is NOT enough: SQLAlchemy also binds any
# client-side default the model declares - `id` from UUIDMixin, for instance -
# so the real parameter count per row is higher than the caller can see. The
# headroom below covers those invisible columns, and the ceiling leaves room
# on top of that.
PG_MAX_BIND_PARAMS = 32_767
MAX_BIND_PARAMS = 24_000
IMPLICIT_COLUMN_HEADROOM = 4
MAX_ROWS_PER_STATEMENT = 5_000
QUOTE_KEY = "quote:{symbol}"


def _as_utc(d: date, *, end_of_day: bool = False) -> datetime:
    t = time(23, 59, 59) if end_of_day else time(0, 0)
    return datetime.combine(d, t, tzinfo=UTC)


def _chunks(rows: list[dict[str, Any]]):
    """Yield batches small enough to stay under the bind-parameter limit."""
    if not rows:
        return
    columns = max(1, len(rows[0])) + IMPLICIT_COLUMN_HEADROOM
    size = max(1, min(MAX_ROWS_PER_STATEMENT, MAX_BIND_PARAMS // columns))
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


async def sync_instruments(session: AsyncSession, provider: MarketDataProvider) -> dict[str, Any]:
    """Upsert the tradable universe. Returns symbol -> id."""
    specs = provider.instruments()
    if not specs:
        return {}

    rows = [
        {
            "symbol": s.symbol,
            "name": s.name,
            "sector": s.sector,
            "exchange": s.exchange,
            "is_synthetic": s.is_synthetic,
            "is_tradable": True,
            "initial_price": Decimal(str(s.initial_price)) if s.initial_price else None,
            "shares_outstanding": s.shares_outstanding,
            "beta": s.beta,
            "annual_vol": s.annual_vol,
            "listed_on": s.listed_on,
            "generator_seed": s.generator_seed,
            "sim_params": s.sim_params or {},
        }
        for s in specs
    ]

    stmt = insert(Instrument).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Instrument.symbol],
        set_={
            c: stmt.excluded[c]
            for c in (
                "name", "sector", "exchange", "is_synthetic", "initial_price",
                "shares_outstanding", "beta", "annual_vol", "listed_on",
                "generator_seed", "sim_params",
            )
        },
    )
    await session.execute(stmt)
    await session.flush()

    result = await session.execute(select(Instrument.symbol, Instrument.id))
    ids = {symbol: iid for symbol, iid in result.all()}
    log.info("instruments_synced", count=len(rows))
    return ids


async def ingest_bars(
    session: AsyncSession,
    provider: MarketDataProvider,
    ids: dict[str, Any],
    start: date,
    end: date,
    timeframe: str = "1d",
) -> int:
    specs = provider.bars(start, end, timeframe)
    rows = [
        {
            "instrument_id": ids[b.symbol],
            "ts": b.ts,
            "timeframe": b.timeframe,
            "open": Decimal(str(b.open)),
            "high": Decimal(str(b.high)),
            "low": Decimal(str(b.low)),
            "close": Decimal(str(b.close)),
            "volume": b.volume,
        }
        for b in specs
        if b.symbol in ids
    ]

    written = 0
    for chunk in _chunks(rows):
        stmt = insert(Bar).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Bar.instrument_id, Bar.ts, Bar.timeframe],
            set_={c: stmt.excluded[c] for c in ("open", "high", "low", "close", "volume")},
        )
        await session.execute(stmt)
        written += len(chunk)
        log.info("bars_chunk_written", written=written, total=len(rows))
    return written


async def ingest_news(
    session: AsyncSession,
    provider: MarketDataProvider,
    ids: dict[str, Any],
    start: date,
    end: date,
) -> int:
    # News has no natural key, so a re-run clears the window first rather than
    # duplicating it. This is what makes seed_market safe to run twice.
    await session.execute(
        delete(NewsItem).where(NewsItem.published_at >= _as_utc(start),
                               NewsItem.published_at <= _as_utc(end, end_of_day=True))
    )
    specs = provider.news(start, end)
    rows = [
        {
            "instrument_id": ids.get(n.symbol) if n.symbol else None,
            "published_at": n.published_at,
            "headline": n.headline[:300],
            "body": n.body,
            "source": n.source,
            "category": n.category,
            "sentiment": n.sentiment,
            "relation": n.relation,
        }
        for n in specs
    ]
    for chunk in _chunks(rows):
        await session.execute(insert(NewsItem).values(chunk))
    return len(rows)


async def ingest_events(
    session: AsyncSession,
    provider: MarketDataProvider,
    ids: dict[str, Any],
    start: date,
    end: date,
) -> int:
    await session.execute(
        delete(CorporateEvent).where(CorporateEvent.occurs_at >= _as_utc(start),
                                     CorporateEvent.occurs_at <= _as_utc(end, end_of_day=True))
    )
    specs = provider.corporate_events(start, end)
    rows = [
        {
            "instrument_id": ids[e.symbol],
            "event_type": e.event_type,
            "occurs_at": e.occurs_at,
            "eps_estimate": Decimal(str(e.eps_estimate)) if e.eps_estimate is not None else None,
            "eps_actual": Decimal(str(e.eps_actual)) if e.eps_actual is not None else None,
            "ratio": Decimal(str(e.ratio)) if e.ratio is not None else None,
            "amount": Decimal(str(e.amount)) if e.amount is not None else None,
            "note": e.note,
        }
        for e in specs
        if e.symbol in ids
    ]
    for chunk in _chunks(rows):
        await session.execute(insert(CorporateEvent).values(chunk))
    return len(rows)


async def publish_latest_quotes(session: AsyncSession, timeframe: str = "1d") -> int:
    """Push the most recent close per symbol into Redis as the hot quote.

    Phase 02 replaces this with the simulated exchange's live book; until then
    the last close is the quote.
    """
    # DISTINCT ON is the Postgres way to take the newest row per group. The
    # correlated-subquery version of this auto-correlated its FROM clause away.
    sql = (
        select(Instrument.symbol, Bar.close, Bar.ts)
        .join(Bar, Bar.instrument_id == Instrument.id)
        .where(Bar.timeframe == timeframe)
        .distinct(Instrument.symbol)
        .order_by(Instrument.symbol, Bar.ts.desc())
    )
    rows = (await session.execute(sql)).all()

    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        pipe = redis.pipeline()
        for symbol, close, ts in rows:
            pipe.hset(
                QUOTE_KEY.format(symbol=symbol),
                mapping={"last": str(close), "ts": ts.isoformat()},
            )
        await pipe.execute()
    finally:
        await redis.aclose()
    log.info("quotes_published", count=len(rows))
    return len(rows)


async def seed_market(
    session: AsyncSession,
    provider: MarketDataProvider,
    start: date,
    end: date,
) -> dict[str, int]:
    """Full ingest. Safe to re-run."""
    ids = await sync_instruments(session, provider)
    bars = await ingest_bars(session, provider, ids, start, end)
    news = await ingest_news(session, provider, ids, start, end)
    events = await ingest_events(session, provider, ids, start, end)
    await session.flush()
    quotes = await publish_latest_quotes(session)
    return {
        "instruments": len(ids),
        "bars": bars,
        "news": news,
        "events": events,
        "quotes": quotes,
    }


__all__ = [
    "QUOTE_KEY",
    "ingest_bars",
    "ingest_events",
    "ingest_news",
    "publish_latest_quotes",
    "seed_market",
    "sync_instruments",
]
