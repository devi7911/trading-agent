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


@app.command("setup-agent")
def setup_agent_cmd(
    email: str = typer.Option(..., help="Which user to set up."),
    symbols: str = typer.Option("", help="Comma-separated symbols. Blank picks a spread."),
    count: int = typer.Option(12, help="How many symbols to pick when none are named."),
    autonomy: str = typer.Option("full_auto", help="observe | approve | auto_capped | full_auto"),
) -> None:
    """Fill a user's watchlist and set their autonomy level, so the agent has
    something to work with."""
    configure_logging("WARNING", json_output=False)

    async def run() -> None:
        from sqlalchemy import select

        from app.models import AutonomyLevel, Instrument, Policy, User, Watchlist, WatchlistItem

        async with SessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.email == email.lower()))
            ).scalar_one_or_none()
            if user is None:
                typer.echo(f"No user with email {email}.")
                return

            watchlist = (
                await session.execute(
                    select(Watchlist).where(Watchlist.user_id == user.id).limit(1)
                )
            ).scalar_one_or_none()
            if watchlist is None:
                watchlist = Watchlist(user_id=user.id, name="My list", is_default=True)
                session.add(watchlist)
                await session.flush()

            if symbols.strip():
                wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
                stmt = select(Instrument).where(Instrument.symbol.in_(wanted))
            else:
                # A spread across sectors rather than the first N alphabetically,
                # so concentration limits actually get exercised.
                stmt = (
                    select(Instrument)
                    .where(Instrument.is_tradable.is_(True))
                    .order_by(Instrument.sector, Instrument.symbol)
                    .limit(count)
                )
            instruments = list((await session.execute(stmt)).scalars())

            existing = {
                i for i in (
                    await session.execute(
                        select(WatchlistItem.instrument_id).where(
                            WatchlistItem.watchlist_id == watchlist.id
                        )
                    )
                ).scalars()
            }
            added = 0
            for i, instrument in enumerate(instruments):
                if instrument.id in existing:
                    continue
                session.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        instrument_id=instrument.id,
                        conviction=(i % 3) + 1,
                        is_favourite=i % 4 == 0,
                    )
                )
                added += 1

            policy = (
                await session.execute(
                    select(Policy)
                    .where(Policy.user_id == user.id, Policy.is_active.is_(True))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if policy is not None:
                policy.autonomy_level = AutonomyLevel(autonomy)

            await session.commit()
            typer.echo(f"  watchlist      {added} added, {len(instruments)} total considered")
            typer.echo(f"  autonomy       {autonomy}")
            typer.echo("  symbols        " + ", ".join(i.symbol for i in instruments))
        await engine.dispose()

    asyncio.run(run())


@app.command("tick")
def tick_cmd(
    email: str = typer.Option(..., help="Which user's agent to run."),
    dry_run: bool = typer.Option(False, help="Evaluate everything, place nothing."),
) -> None:
    """Run one pass of the agent loop and print what it decided."""
    configure_logging(settings.log_level, json_output=False)

    async def run() -> None:
        from sqlalchemy import select

        from app.agent.clock import market_clock
        from app.agent.loop import run_tick
        from app.models import AgentDecision, RunTrigger, User

        async with SessionLocal() as session:
            user = (
                await session.execute(select(User).where(User.email == email.lower()))
            ).scalar_one_or_none()
            if user is None:
                typer.echo(f"No user with email {email}.")
                return

            clock = await market_clock(session)
            run_row = await run_tick(
                session, user, trigger=RunTrigger.MANUAL, dry_run=dry_run, now=clock
            )
            typer.echo(f"  market clock   {clock:%Y-%m-%d %H:%M} UTC")
            await session.commit()

            typer.echo("")
            typer.echo(f"  status         {run_row.status}")
            typer.echo(f"  symbols        {run_row.symbols_examined}")
            typer.echo(f"  intents        {run_row.intents_formed}")
            typer.echo(f"  orders placed  {run_row.orders_placed}")
            typer.echo(f"  denials        {run_row.denials}")
            typer.echo(f"  duration       {run_row.duration_ms} ms")
            if run_row.error:
                typer.echo(f"  error          {run_row.error}")

            decisions = list(
                (
                    await session.execute(
                        select(AgentDecision)
                        .where(AgentDecision.run_id == run_row.id)
                        .order_by(AgentDecision.approved.desc(), AgentDecision.symbol)
                        .limit(20)
                    )
                ).scalars()
            )
            if decisions:
                typer.echo("")
                for d in decisions:
                    mark = "OK " if d.approved else "-- "
                    detail = d.denial or d.rationale[:64]
                    typer.echo(
                        f"  {mark}{d.symbol:<6} {d.direction:<5} "
                        f"{d.approved_quantity:>5}  {detail}"
                    )
        await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    app()
