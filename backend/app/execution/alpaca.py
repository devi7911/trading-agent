"""Alpaca paper-trading adapter.

The second implementation of BrokerPort. Its whole purpose is to prove the port
is real: switching `BROKER=alpaca_paper` changes which venue fills the orders
and nothing else. If this adapter needed the agent, the gate or the ledger to
change, the abstraction was decorative.

Paper only. The base URL is pinned to the paper host and a live URL is rejected
outright - there is no code path in this repository that can reach a live venue,
and adding one is not a configuration change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.execution.port import ExecutionResult, FillEvent, OrderRequest
from app.models.order import OrderType, RejectReason, Side

log = get_logger(__name__)

PAPER_HOST = "paper-api.alpaca.markets"
TIMEOUT = 20.0

# Alpaca's rejection vocabulary, mapped onto ours.
REJECT_MAP = {
    "insufficient buying power": RejectReason.INSUFFICIENT_BUYING_POWER,
    "insufficient qty": RejectReason.INSUFFICIENT_POSITION,
    "account is not authorized": RejectReason.ACCOUNT_HALTED,
    "asset is not tradable": RejectReason.SYMBOL_NOT_TRADABLE,
    "market is closed": RejectReason.MARKET_CLOSED,
    "halted": RejectReason.SYMBOL_HALTED,
}


class LiveTradingRefused(RuntimeError):
    """Raised if anything tries to point this adapter at a live venue."""


class AlpacaPaperBroker:
    name = "alpaca_paper"
    supports_live_trading = False

    def __init__(
        self, key: str | None = None, secret: str | None = None, base_url: str | None = None
    ) -> None:
        self.key = key or settings.alpaca_api_key
        self.secret = secret or settings.alpaca_api_secret
        self.base_url = (base_url or settings.alpaca_base_url).rstrip("/")

        if PAPER_HOST not in self.base_url:
            raise LiveTradingRefused(
                f"{self.base_url} is not the Alpaca paper host. This repository "
                f"has no live trading path, by design."
            )

    @property
    def configured(self) -> bool:
        return bool(self.key and self.secret)

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
            "Content-Type": "application/json",
        }

    def _map_rejection(self, message: str) -> RejectReason:
        lowered = (message or "").lower()
        for needle, reason in REJECT_MAP.items():
            if needle in lowered:
                return reason
        return RejectReason.NO_MARKET_DATA

    async def account(self) -> dict | None:
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(
                    f"{self.base_url}/v2/account", headers=self._headers()
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            log.info("alpaca_account_failed", error=type(exc).__name__)
            return None

    async def submit(self, request: OrderRequest, *, as_of: datetime) -> ExecutionResult:
        if not self.configured:
            return ExecutionResult(
                False, reject_reason=RejectReason.ACCOUNT_HALTED,
                message="Alpaca keys are not configured.",
            )

        payload: dict = {
            "symbol": request.symbol.upper(),
            "qty": str(request.quantity),
            "side": "buy" if request.side == Side.BUY else "sell",
            "type": {
                OrderType.MARKET: "market", OrderType.LIMIT: "limit",
                OrderType.STOP: "stop", OrderType.STOP_LIMIT: "stop_limit",
            }[request.order_type],
            "time_in_force": str(request.time_in_force),
            "client_order_id": request.client_order_id,
        }
        if request.limit_price is not None:
            payload["limit_price"] = str(request.limit_price)
        if request.stop_price is not None:
            payload["stop_price"] = str(request.stop_price)

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{self.base_url}/v2/orders", headers=self._headers(), json=payload
                )
                body = response.json()
        except Exception as exc:
            return ExecutionResult(
                False, reject_reason=RejectReason.NO_MARKET_DATA,
                message=f"Could not reach Alpaca: {type(exc).__name__}",
            )

        if response.status_code >= 400:
            message = str(body.get("message", body))[:300]
            return ExecutionResult(
                False, reject_reason=self._map_rejection(message), message=message
            )

        filled_qty = int(float(body.get("filled_qty") or 0))
        if filled_qty == 0:
            return ExecutionResult(True, resting=True,
                                   message=f"Accepted, status {body.get('status')}.")

        price = Decimal(str(body.get("filled_avg_price") or 0))
        return ExecutionResult(
            accepted=True,
            fills=[
                FillEvent(
                    sequence=1, quantity=filled_qty, price=price,
                    commission=Decimal("0.00"), slippage_bps=Decimal("0.00"),
                    filled_at=datetime.now(UTC),
                )
            ],
            resting=filled_qty < request.quantity,
        )

    async def cancel(self, client_order_id: str) -> bool:
        if not self.configured:
            return False
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                found = await client.get(
                    f"{self.base_url}/v2/orders:by_client_order_id",
                    headers=self._headers(),
                    params={"client_order_id": client_order_id},
                )
                if found.status_code >= 400:
                    return False
                order_id = found.json().get("id")
                cancelled = await client.delete(
                    f"{self.base_url}/v2/orders/{order_id}", headers=self._headers()
                )
                return cancelled.status_code < 400
        except Exception as exc:
            log.info("alpaca_cancel_failed", error=type(exc).__name__)
            return False


__all__ = ["PAPER_HOST", "AlpacaPaperBroker", "LiveTradingRefused"]
