"""Liveness and readiness. Compose and Prometheus both watch these."""

from fastapi import APIRouter
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
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
