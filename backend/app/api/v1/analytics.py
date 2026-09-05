"""Market-wide analytics, reports and exports."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.market import analytics as an
from app.market import reporting as rep
from app.models import Instrument, MarketSnapshot, NewsItem

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _panel(session: SessionDep) -> an.Panel:
    panel = await an.load_panel(session)
    if panel is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No market data loaded. Run: python -m app.cli seed-market",
        )
    return panel


@router.get("/index")
async def index_history(
    session: SessionDep,
    _user: CurrentUser,
    limit: int = Query(default=1000, ge=1, le=5000),
) -> list[dict]:
    """Cap-weighted index level and breadth, oldest first."""
    stmt = select(MarketSnapshot).order_by(MarketSnapshot.ts.desc()).limit(limit)
    rows = list((await session.execute(stmt)).scalars())
    return [
        {
            "ts": r.ts,
            "index_value": float(r.index_value),
            "index_return_pct": float(r.index_return) * 100,
            "advancers": r.advancers,
            "decliners": r.decliners,
            "new_highs": r.new_highs,
            "new_lows": r.new_lows,
            "pct_above_50dma": float(r.pct_above_50dma),
            "total_volume": r.total_volume,
            "regime": r.regime,
        }
        for r in reversed(rows)
    ]


@router.get("/overview")
async def overview(session: SessionDep, _user: CurrentUser) -> dict:
    """Everything the market dashboard needs, in one call."""
    latest = await session.scalar(
        select(MarketSnapshot).order_by(MarketSnapshot.ts.desc()).limit(1)
    )
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No analytics built yet. Run: python -m app.cli rebuild-analytics",
        )
    panel = await _panel(session)
    m = an.movers(panel, "1d", limit=8)
    return {
        "as_of": latest.ts,
        "index": {
            "value": float(latest.index_value),
            "change_pct": float(latest.index_return) * 100,
            "regime": latest.regime,
        },
        "breadth": {
            "advancers": latest.advancers,
            "decliners": latest.decliners,
            "unchanged": latest.unchanged,
            "new_highs": latest.new_highs,
            "new_lows": latest.new_lows,
            "pct_above_50dma": float(latest.pct_above_50dma),
        },
        "total_volume": latest.total_volume,
        "sectors": an.sector_performance(panel, "1d"),
        "gainers": m["gainers"],
        "losers": m["losers"],
        "most_active": m["most_active"],
    }


@router.get("/sectors")
async def sectors(
    session: SessionDep,
    _user: CurrentUser,
    window: str = Query(default="1d", pattern="^(1d|1w|1m|3m|ytd|1y)$"),
) -> list[dict]:
    return an.sector_performance(await _panel(session), window)


@router.get("/movers")
async def market_movers(
    session: SessionDep,
    _user: CurrentUser,
    window: str = Query(default="1d", pattern="^(1d|1w|1m|3m|ytd|1y)$"),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict:
    return an.movers(await _panel(session), window, limit)


@router.get("/stats/{symbol}")
async def stats(
    session: SessionDep,
    _user: CurrentUser,
    symbol: str,
    lookback: int = Query(default=252, ge=20, le=5000),
) -> dict:
    panel = await _panel(session)
    if symbol.upper() not in panel.symbols:
        raise HTTPException(status_code=404, detail=f"No data for {symbol.upper()}.")
    return an.instrument_stats(panel, symbol.upper(), lookback)


@router.get("/correlation")
async def correlation(
    session: SessionDep,
    _user: CurrentUser,
    symbols: str = Query(description="Comma-separated symbols, 2 to 20."),
    lookback: int = Query(default=252, ge=20, le=5000),
) -> dict:
    panel = await _panel(session)
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not 2 <= len(wanted) <= 20:
        raise HTTPException(status_code=400, detail="Provide between 2 and 20 symbols.")
    unknown = [s for s in wanted if s not in panel.symbols]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown symbols: {', '.join(unknown)}.")
    return an.correlation_matrix(panel, wanted, lookback)


@router.get("/digest")
async def digest(session: SessionDep, _user: CurrentUser) -> dict:
    """The daily market summary. Phase 07 sends this text over Telegram."""
    latest = await session.scalar(
        select(MarketSnapshot).order_by(MarketSnapshot.ts.desc()).limit(1)
    )
    if latest is None:
        raise HTTPException(status_code=409, detail="No analytics built yet.")
    panel = await _panel(session)
    d = rep.build_digest(panel, {
        "index_value": latest.index_value,
        "index_return": latest.index_return,
        "regime": latest.regime,
        "advancers": latest.advancers,
        "decliners": latest.decliners,
    })
    return {"as_of": d.as_of, "text": d.to_text(), "data": d.__dict__}


# --- exports ----------------------------------------------------------------

@router.get("/export/universe.csv")
async def export_universe_csv(session: SessionDep, _user: CurrentUser) -> Response:
    body = rep.universe_csv(await _panel(session))
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="universe.csv"'},
    )


@router.get("/export/{symbol}/bars.csv")
async def export_bars_csv(session: SessionDep, _user: CurrentUser, symbol: str) -> Response:
    panel = await _panel(session)
    symbol = symbol.upper()
    if symbol not in panel.symbols:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}.")
    return Response(
        content=rep.bars_csv(panel, symbol),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{symbol}_bars.csv"'},
    )


@router.get("/export/market.xlsx")
async def export_workbook(session: SessionDep, _user: CurrentUser) -> Response:
    body = rep.market_workbook(await _panel(session))
    stamp = datetime.now().strftime("%Y%m%d")
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="market_{stamp}.xlsx"'},
    )


@router.get("/export/{symbol}/tearsheet.pdf")
async def export_tearsheet(session: SessionDep, _user: CurrentUser, symbol: str) -> Response:
    panel = await _panel(session)
    symbol = symbol.upper()
    if symbol not in panel.symbols:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}.")

    instrument = await session.scalar(select(Instrument).where(Instrument.symbol == symbol))
    news_rows = list(
        (
            await session.execute(
                select(NewsItem)
                .where(NewsItem.instrument_id == instrument.id)
                .order_by(NewsItem.published_at.desc())
                .limit(6)
            )
        ).scalars()
    )
    news = [
        {"published_at": n.published_at.isoformat(), "headline": n.headline,
         "sentiment": n.sentiment}
        for n in news_rows
    ]

    body = rep.tearsheet_pdf(
        panel, symbol, name=instrument.name, sector=instrument.sector, news=news
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{symbol}_tearsheet.pdf"'},
    )
