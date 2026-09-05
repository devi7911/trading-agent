"""Agent runs, decisions, and the kill switch."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select

from app.agent.clock import market_clock
from app.agent.loop import run_tick
from app.agent.worker import HALT_KEY
from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import AgentDecision, AgentRun, RunTrigger

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/runs")
async def list_runs(
    session: SessionDep, user: CurrentUser, limit: int = Query(default=25, ge=1, le=200)
) -> list[dict]:
    rows = list(
        (
            await session.execute(
                select(AgentRun)
                .where(AgentRun.user_id == user.id)
                .order_by(AgentRun.started_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [
        {
            "id": r.id, "trigger": r.trigger, "status": r.status,
            "started_at": r.started_at, "duration_ms": r.duration_ms,
            "symbols_examined": r.symbols_examined, "intents_formed": r.intents_formed,
            "orders_placed": r.orders_placed, "denials": r.denials,
            "error": r.error, "summary": r.summary,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}/decisions")
async def run_decisions(run_id: str, session: SessionDep, user: CurrentUser) -> list[dict]:
    run = (
        await session.execute(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="No such run.")

    rows = list(
        (
            await session.execute(
                select(AgentDecision)
                .where(AgentDecision.run_id == run.id)
                .order_by(AgentDecision.symbol)
            )
        ).scalars()
    )
    return [
        {
            "symbol": d.symbol, "direction": d.direction,
            "requested_quantity": d.requested_quantity,
            "approved_quantity": d.approved_quantity,
            "conviction": d.conviction, "approved": d.approved, "denial": d.denial,
            "rationale": d.rationale, "order_id": d.order_id,
            "risk_trace": d.risk_trace, "context": d.context_snapshot,
            "signals": d.signals,
        }
        for d in rows
    ]


@router.get("/decisions")
async def recent_decisions(
    session: SessionDep,
    user: CurrentUser,
    symbol: str | None = None,
    approved_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict]:
    """The decision log: every choice the agent made, with its reason."""
    stmt = (
        select(AgentDecision)
        .join(AgentRun, AgentRun.id == AgentDecision.run_id)
        .where(AgentRun.user_id == user.id)
    )
    if symbol:
        stmt = stmt.where(AgentDecision.symbol == symbol.upper())
    if approved_only:
        stmt = stmt.where(AgentDecision.approved.is_(True))
    stmt = stmt.order_by(AgentDecision.created_at.desc()).limit(limit)

    return [
        {
            "at": d.created_at, "symbol": d.symbol, "direction": d.direction,
            "approved": d.approved, "quantity": d.approved_quantity,
            "conviction": d.conviction, "denial": d.denial, "rationale": d.rationale,
        }
        for d in (await session.execute(stmt)).scalars()
    ]


@router.post("/tick")
async def manual_tick(
    session: SessionDep, user: CurrentUser, dry_run: bool = False
) -> dict:
    """Run one tick now. `dry_run` evaluates everything and places nothing."""
    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        halted = bool(await redis.exists(HALT_KEY))
    finally:
        await redis.aclose()

    clock = (
        await market_clock(session) if settings.broker == "sim" else datetime.now(UTC)
    )
    run = await run_tick(
        session, user, trigger=RunTrigger.MANUAL, global_halt=halted,
        now=clock, dry_run=dry_run,
    )
    return {
        "run_id": run.id, "status": run.status, "duration_ms": run.duration_ms,
        "symbols_examined": run.symbols_examined, "intents_formed": run.intents_formed,
        "orders_placed": run.orders_placed, "denials": run.denials,
        "dry_run": dry_run, "error": run.error,
    }


@router.get("/halt")
async def halt_status(_user: CurrentUser) -> dict:
    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        return {"halted": bool(await redis.exists(HALT_KEY))}
    finally:
        await redis.aclose()


@router.post("/halt")
async def set_halt(_user: CurrentUser, reason: str = "manual") -> dict:
    """The kill switch. Lives in Redis, outside the agent, so it works even when
    the loop is wedged."""
    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        await redis.set(HALT_KEY, reason)
        return {"halted": True, "reason": reason}
    finally:
        await redis.aclose()


@router.delete("/halt")
async def clear_halt(_user: CurrentUser) -> dict:
    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        await redis.delete(HALT_KEY)
        return {"halted": False}
    finally:
        await redis.aclose()
