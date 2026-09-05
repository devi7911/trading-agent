"""FastAPI application entrypoint."""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.logging import configure_logging, correlation_id, get_logger

configure_logging(settings.log_level, json_output=settings.app_env != "local")
log = get_logger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    log.info(
        "startup",
        env=settings.app_env,
        broker=settings.broker,
        live_trading_allowed=settings.allow_live_trading,
    )
    if settings.allow_live_trading:
        # There is no live adapter in this repo. If this is ever true, something is wrong.
        log.error("live_trading_flag_set", note="no live adapter exists; refusing to assume intent")
    yield
    await engine.dispose()
    log.info("shutdown")


app = FastAPI(
    title="Agentic Trading Desk API",
    version="0.1.0",
    description="Autonomous trading agent. Simulated execution only.",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_and_timing(request: Request, call_next):
    cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    token = correlation_id.set(cid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(token)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Correlation-ID"] = cid
    response.headers["X-Response-Time-ms"] = str(elapsed_ms)
    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=elapsed_ms,
        correlation_id=cid,
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception", error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": "agentic-trading-desk", "docs": "/docs", "health": "/api/v1/health/ready"}
