import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.market.live import CHANNEL, CLOCK_KEY
from app.market.service import QUOTE_KEY
from app.models import Bar, CorporateEvent, Instrument, NewsItem
from app.schemas.market import (
    BarOut,
    CorporateEventOut,
    InstrumentOut,
    NewsOut,
    QuoteOut,
)

router = APIRouter(prefix="/market", tags=["market"])


async def _instrument_or_404(session: SessionDep, symbol: str) -> Instrument:
    result = await session.execute(
        select(Instrument).where(Instrument.symbol == symbol.upper())
    )
    instrument = result.scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No instrument with symbol {symbol.upper()}.",
        )
    return instrument


@router.get("/instruments", response_model=list[InstrumentOut])
async def list_instruments(
    session: SessionDep,
    _user: CurrentUser,
    sector: str | None = None,
    search: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Instrument]:
    stmt = select(Instrument).where(Instrument.is_tradable.is_(True))
    if sector:
        stmt = stmt.where(Instrument.sector == sector)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            Instrument.symbol.ilike(pattern) | Instrument.name.ilike(pattern)
        )
    stmt = stmt.order_by(Instrument.symbol).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


@router.get("/instruments/{symbol}", response_model=InstrumentOut)
async def get_instrument(session: SessionDep, _user: CurrentUser, symbol: str) -> Instrument:
    return await _instrument_or_404(session, symbol)


@router.get("/instruments/{symbol}/bars", response_model=list[BarOut])
async def get_bars(
    session: SessionDep,
    _user: CurrentUser,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
    timeframe: str = Query(default="1d", pattern="^(1d|1h|1m)$"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[Bar]:
    instrument = await _instrument_or_404(session, symbol)
    stmt = select(Bar).where(
        Bar.instrument_id == instrument.id, Bar.timeframe == timeframe
    )
    if start:
        stmt = stmt.where(Bar.ts >= datetime.combine(start, datetime.min.time()))
    if end:
        stmt = stmt.where(Bar.ts <= datetime.combine(end, datetime.max.time()))

    # Newest first for the limit, then flipped so callers get chronological order.
    stmt = stmt.order_by(Bar.ts.desc()).limit(limit)
    rows = list((await session.execute(stmt)).scalars())
    return list(reversed(rows))


@router.get("/instruments/{symbol}/news", response_model=list[NewsOut])
async def get_news(
    session: SessionDep,
    _user: CurrentUser,
    symbol: str,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[NewsItem]:
    instrument = await _instrument_or_404(session, symbol)
    stmt = (
        select(NewsItem)
        .where(NewsItem.instrument_id == instrument.id)
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


@router.get("/instruments/{symbol}/events", response_model=list[CorporateEventOut])
async def get_events(
    session: SessionDep,
    _user: CurrentUser,
    symbol: str,
    limit: int = Query(default=25, ge=1, le=200),
) -> list[CorporateEvent]:
    instrument = await _instrument_or_404(session, symbol)
    stmt = (
        select(CorporateEvent)
        .where(CorporateEvent.instrument_id == instrument.id)
        .order_by(CorporateEvent.occurs_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


@router.get("/quotes/{symbol}", response_model=QuoteOut)
async def get_quote(session: SessionDep, _user: CurrentUser, symbol: str) -> QuoteOut:
    """The hot quote from Redis, falling back to the last stored close."""
    symbol = symbol.upper()
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        cached = await redis.hgetall(QUOTE_KEY.format(symbol=symbol))
    finally:
        await redis.aclose()

    if cached and "last" in cached:
        return QuoteOut(
            symbol=symbol,
            last=cached["last"],
            ts=datetime.fromisoformat(cached["ts"]),
        )

    instrument = await _instrument_or_404(session, symbol)
    stmt = (
        select(Bar)
        .where(Bar.instrument_id == instrument.id, Bar.timeframe == "1d")
        .order_by(Bar.ts.desc())
        .limit(1)
    )
    bar = (await session.execute(stmt)).scalar_one_or_none()
    if bar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No price data loaded for {symbol}. Run the market seed first.",
        )
    return QuoteOut(symbol=symbol, last=bar.close, ts=bar.ts)


@router.get("/sectors", response_model=list[str])
async def list_sectors(session: SessionDep, _user: CurrentUser) -> list[str]:
    stmt = (
        select(Instrument.sector)
        .where(Instrument.sector.is_not(None))
        .distinct()
        .order_by(Instrument.sector)
    )
    return [s for s in (await session.execute(stmt)).scalars() if s]


# --- the live stream --------------------------------------------------------
#
# Deliberately UNAUTHENTICATED, and deliberately carrying market prices only.
#
# EventSource cannot send an Authorization header, and the alternative - putting
# a bearer token in the query string - writes a credential into browser history,
# proxy logs and the server access log. Since this endpoint exposes nothing but
# quotes for a fictional market, the safe answer is to carry no account data at
# all: positions and equity are fetched over the authenticated API and revalued
# in the browser from these prices.

HEARTBEAT_SECONDS = 20.0


@router.get("/clock")
async def market_clock_state() -> dict:
    """Where the simulated session has got to."""
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis.get(CLOCK_KEY)
    finally:
        await redis.aclose()
    if not raw:
        return {"running": False, "note": "The market ticker is not running."}
    state = json.loads(raw)
    state["running"] = True
    return state


async def _quote_events() -> AsyncGenerator[str, None]:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    try:
        yield ": connected\n\n"
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
            )
            if message is None:
                # Comment frames keep proxies from closing an idle connection.
                yield ": keep-alive\n\n"
                continue
            yield f"data: {message['data']}\n\n"
    except asyncio.CancelledError:  # the client went away
        raise
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await redis.aclose()


@router.get("/stream")
async def stream_quotes() -> StreamingResponse:
    """Server-sent events carrying live quotes for the simulated market."""
    return StreamingResponse(
        _quote_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
