"""Phase 10: the properties that make this safe to leave running.

Chaos-flavoured: what happens when the broker lies, the ledger drifts, or a
dependency disappears. A system is only as trustworthy as its behaviour when
something is already wrong.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core import metrics
from app.core.config import settings
from app.execution import describe_broker
from app.execution.alpaca import PAPER_HOST, AlpacaPaperBroker, LiveTradingRefused
from app.execution.port import BrokerPort, OrderRequest
from app.models.order import OrderType, Side

# --- the port is real --------------------------------------------------------

def test_the_alpaca_adapter_satisfies_the_broker_port():
    """If a second adapter did not fit the port, the abstraction was decorative."""
    adapter = AlpacaPaperBroker(key="k", secret="s")
    assert isinstance(adapter, BrokerPort)
    assert hasattr(adapter, "submit")
    assert hasattr(adapter, "cancel")


def test_no_adapter_in_this_repository_can_trade_live():
    assert AlpacaPaperBroker(key="k", secret="s").supports_live_trading is False


def test_pointing_the_adapter_at_a_live_venue_is_refused():
    """Reaching a live venue is not a configuration change."""
    with pytest.raises(LiveTradingRefused, match="paper host"):
        AlpacaPaperBroker(key="k", secret="s", base_url="https://api.alpaca.markets")


def test_the_paper_host_is_pinned():
    adapter = AlpacaPaperBroker(key="k", secret="s")
    assert PAPER_HOST in adapter.base_url


def test_an_unconfigured_adapter_reports_itself_rather_than_failing_late():
    assert AlpacaPaperBroker(key="", secret="").configured is False


async def test_an_unconfigured_adapter_refuses_orders_cleanly():
    adapter = AlpacaPaperBroker(key="", secret="")
    result = await adapter.submit(
        OrderRequest(symbol="AAPL", side=Side.BUY, quantity=1, order_type=OrderType.MARKET),
        as_of=datetime.now(UTC),
    )
    assert result.accepted is False
    assert "not configured" in (result.message or "")


def test_live_trading_stays_off_by_default():
    assert settings.allow_live_trading is False


def test_the_broker_description_reports_no_live_path():
    described = describe_broker()
    assert described["live_trading_possible"] is False
    assert described["broker"] in ("sim", "alpaca_paper")


def test_alpaca_rejection_vocabulary_maps_onto_ours():
    from app.models.order import RejectReason

    adapter = AlpacaPaperBroker(key="k", secret="s")
    assert adapter._map_rejection("insufficient buying power available") is (
        RejectReason.INSUFFICIENT_BUYING_POWER
    )
    assert adapter._map_rejection("the market is closed") is RejectReason.MARKET_CLOSED
    assert adapter._map_rejection("something nobody predicted") is (
        RejectReason.NO_MARKET_DATA
    )


# --- metrics -----------------------------------------------------------------

def test_metrics_render_in_prometheus_format():
    metrics.reset()
    metrics.counter("orders_total", 3, side="buy")
    metrics.gauge("agent_seconds_since_last_tick", 42.0)
    output = metrics.render()
    assert 'orders_total{side="buy"} 3' in output
    assert "agent_seconds_since_last_tick 42.0" in output
    assert "process_uptime_seconds" in output


def test_counters_accumulate_and_gauges_replace():
    metrics.reset()
    metrics.counter("c", 1)
    metrics.counter("c", 2)
    metrics.gauge("g", 1)
    metrics.gauge("g", 9)
    output = metrics.render()
    assert "c 3.0" in output
    assert "g 9" in output


# --- reconciliation ----------------------------------------------------------

@pytest.mark.integration
async def test_a_clean_account_reconciles():
    from app.agent.reconcile import reconcile_account
    from app.core.db import SessionLocal
    from app.models import Account
    from app.services.users import create_user

    async with SessionLocal() as session:
        user = await create_user(
            session, email=f"rec-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()
        account = (
            await session.execute(select(Account).where(Account.user_id == user.id))
        ).scalar_one()

        report = await reconcile_account(session, account)
        assert report["reconciled"] is True
        assert report["position_mismatches"] == []
        await session.rollback()


@pytest.mark.integration
async def test_tampered_cash_is_detected_and_halts_the_account():
    """The chaos case: something wrote to the balance behind the ledger's back."""
    from app.agent.reconcile import reconcile_and_halt
    from app.core.db import SessionLocal
    from app.models import Account
    from app.services.users import create_user

    async with SessionLocal() as session:
        user = await create_user(
            session, email=f"tamper-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()
        account = (
            await session.execute(select(Account).where(Account.user_id == user.id))
        ).scalar_one()

        account.cash = account.cash + Decimal("5000.00")   # money from nowhere
        await session.flush()

        report = await reconcile_and_halt(session, user, account)
        assert report["reconciled"] is False
        assert account.is_halted is True
        assert "Reconciliation failed" in (account.halt_reason or "")
        await session.rollback()


@pytest.mark.integration
async def test_a_halted_account_cannot_be_traded_after_reconciliation_fails():
    """Halting must actually stop trading, not just set a flag nobody reads."""
    from app.agent.reconcile import reconcile_and_halt
    from app.core.db import SessionLocal
    from app.execution import service as execution
    from app.models import Account, Instrument, OrderStatus
    from app.services.users import create_user

    async with SessionLocal() as session:
        user = await create_user(
            session, email=f"halted-{uuid.uuid4().hex[:10]}@example.com",
            password="a-sufficiently-long-password",
        )
        await session.flush()
        account = (
            await session.execute(select(Account).where(Account.user_id == user.id))
        ).scalar_one()
        symbol = await session.scalar(
            select(Instrument.symbol).where(Instrument.is_tradable.is_(True)).limit(1)
        )
        if symbol is None:
            pytest.skip("no instruments loaded")

        account.cash = account.cash - Decimal("1234.00")
        await session.flush()
        await reconcile_and_halt(session, user, account)

        order = await execution.place_order(
            session, account,
            OrderRequest(symbol=symbol, side=Side.BUY, quantity=1),
            actor="test",
        )
        assert order.status == OrderStatus.REJECTED
        assert order.reject_reason == "account_halted"
        await session.rollback()
