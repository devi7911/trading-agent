from fastapi import APIRouter

from app.api.v1 import analytics, auth, health, market, trading

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(market.router)
api_router.include_router(analytics.router)
api_router.include_router(trading.router)
