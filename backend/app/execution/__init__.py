"""Execution: the broker port and its adapters."""

from app.core.config import settings
from app.execution.port import BrokerPort


def active_broker_name() -> str:
    return settings.broker


def describe_broker() -> dict:
    """What the system is trading against, and whether it could ever be real.

    ALLOW_LIVE_TRADING exists so this can be asserted rather than assumed. No
    adapter in this repository reports supports_live_trading = True.
    """
    from app.execution.alpaca import AlpacaPaperBroker

    name = settings.broker
    live_capable = False
    configured = True

    if name == "alpaca_paper":
        try:
            adapter = AlpacaPaperBroker()
            live_capable = adapter.supports_live_trading
            configured = adapter.configured
        except Exception:
            configured = False

    return {
        "broker": name,
        "live_trading_possible": live_capable,
        "allow_live_trading_flag": settings.allow_live_trading,
        "configured": configured,
    }


__all__ = ["BrokerPort", "active_broker_name", "describe_broker"]
