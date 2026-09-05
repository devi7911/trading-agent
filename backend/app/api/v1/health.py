"""Liveness and readiness. Compose and Prometheus both watch these."""

from fastapi import APIRouter, Response
from redis.asyncio import Redis
from sqlalchemy import func, select, text

from app.core import metrics
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.schemas.common import HealthStatus

router = APIRouter(prefix="/health", tags=["health"])

VERSION = "0.1.0"


@router.get("/live", response_model=HealthStatus)
async def live() -> HealthStatus:
    """Is the process up? No dependencies touched."""
    return HealthStatus(status="ok", version=VERSION)


@router.get("/ready", response_model=HealthStatus)
async def ready() -> HealthStatus:
    """Can we actually serve? Checks every downstream dependency."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    redis: Redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    finally:
        await redis.aclose()

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return HealthStatus(status=status, version=VERSION, checks=checks)


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus scrape target.

    The gauge that matters is agent staleness: every other signal can look
    healthy while the loop has quietly stopped, and that is the failure you
    discover a week later.
    """
    from datetime import UTC, datetime

    from app.models import AgentRun, Order, Position

    async with SessionLocal() as session:
        last_run = await session.scalar(select(func.max(AgentRun.started_at)))
        staleness = (
            (datetime.now(UTC) - last_run).total_seconds() if last_run else -1.0
        )
        metrics.gauge("agent_seconds_since_last_tick", staleness)
        metrics.gauge(
            "agent_runs_total", float(await session.scalar(select(func.count(AgentRun.id))) or 0)
        )
        metrics.gauge(
            "trading_orders_total", float(await session.scalar(select(func.count(Order.id))) or 0)
        )
        metrics.gauge(
            "trading_open_positions",
            float(
                await session.scalar(
                    select(func.count(Position.id)).where(Position.quantity != 0)
                ) or 0
            ),
        )

    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")
