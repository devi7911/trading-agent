"""Operator commands.

    docker compose exec api python -m app.cli seed-market --years 6
    docker compose exec api python -m app.cli market-stats
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import typer

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.logging import configure_logging

app = typer.Typer(add_completion=False, help="Agentic Trading Desk operator commands.")


@app.command("seed-market")
def seed_market_cmd(
    count: int = typer.Option(60, help="How many synthetic companies to create."),
    years: float = typer.Option(6.0, help="How much history to generate."),
    seed: int = typer.Option(20260905, help="Master seed. Same seed, same market."),
    end: str = typer.Option("", help="End date YYYY-MM-DD. Defaults to today."),
) -> None:
    """Generate a synthetic market and load it into the database."""
    configure_logging(settings.log_level, json_output=False)
    end_date = date.fromisoformat(end) if end else date.today()
    start_date = end_date - timedelta(days=int(years * 365.25))

    async def run() -> None:
        from app.market.service import seed_market
        from app.market.synthetic.provider import SyntheticProvider

        provider = SyntheticProvider(count=count, seed=seed, start=start_date, end=end_date)
        typer.echo(
            f"Generating {count} companies over {len(provider.days)} trading days "
            f"({start_date} to {end_date}), seed {seed}..."
        )
        async with SessionLocal() as session:
            stats = await seed_market(session, provider, start_date, end_date)
            typer.echo("Building analytics...")
            from app.market.analytics import rebuild_snapshots

            stats["snapshots"] = await rebuild_snapshots(session)
            await session.commit()
        for k, v in stats.items():
            typer.echo(f"  {k:<14} {v:>9,}")
        await engine.dispose()

    asyncio.run(run())
    typer.echo("Done.")


@app.command("market-stats")
def market_stats_cmd() -> None:
    """Summarise what is currently loaded."""
    configure_logging(settings.log_level, json_output=False)

    async def run() -> None:
        from sqlalchemy import func, select

        from app.models import Bar, CorporateEvent, Instrument, NewsItem

        async with SessionLocal() as session:
            for label, model in (
                ("instruments", Instrument),
                ("bars", Bar),
                ("news items", NewsItem),
                ("events", CorporateEvent),
            ):
                n = await session.scalar(select(func.count()).select_from(model))
                typer.echo(f"  {label:<14} {n:>9,}")

            span = await session.execute(select(func.min(Bar.ts), func.max(Bar.ts)))
            lo, hi = span.one()
            if lo:
                typer.echo(f"  span           {lo.date()} to {hi.date()}")
        await engine.dispose()

    asyncio.run(run())


@app.command("rebuild-analytics")
def rebuild_analytics_cmd() -> None:
    """Recompute the market index and breadth from the stored bars."""
    configure_logging(settings.log_level, json_output=False)

    async def run() -> None:
        from app.market.analytics import rebuild_snapshots

        async with SessionLocal() as session:
            n = await rebuild_snapshots(session)
            await session.commit()
        typer.echo(f"  snapshots      {n:>9,}")
        await engine.dispose()

    asyncio.run(run())


@app.command("digest")
def digest_cmd() -> None:
    """Print today's market digest - the text phase 07 will send to Telegram."""
    configure_logging("WARNING", json_output=False)

    async def run() -> None:
        from sqlalchemy import select

        from app.market.analytics import load_panel
        from app.market.reporting import build_digest
        from app.models import MarketSnapshot

        async with SessionLocal() as session:
            latest = await session.scalar(
                select(MarketSnapshot).order_by(MarketSnapshot.ts.desc()).limit(1)
            )
            if latest is None:
                typer.echo("No analytics built yet. Run rebuild-analytics first.")
                return
            panel = await load_panel(session)
            d = build_digest(panel, {
                "index_value": latest.index_value,
                "index_return": latest.index_return,
                "regime": latest.regime,
                "advancers": latest.advancers,
                "decliners": latest.decliners,
            })
            typer.echo("")
            typer.echo(d.to_text())
            typer.echo("")
        await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    app()
