"""Notification routing.

The feature is not "send messages", it is "send the right messages". An agent
that pages you five times about the same stop loss trains you to ignore it, and
one that stays silent when a circuit breaker trips is worse than none.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import DeliveryStatus, Notification, Severity, User
from app.notify.service import (
    SEVERITY_BY_EVENT,
    flush_digest,
    link_token,
    notify,
)
from app.notify.telegram import MAX_MESSAGE_CHARS, SendResult, TelegramClient


class FakeTelegram(TelegramClient):
    """Records what would have been sent."""

    def __init__(self, ok: bool = True):
        super().__init__(token="fake-token")
        self.sent: list[tuple[str, str]] = []
        self._ok = ok

    async def send(self, chat_id: str, text: str, *, buttons=None) -> SendResult:
        self.sent.append((chat_id, text))
        return SendResult(ok=self._ok, message_id=1,
                          error=None if self._ok else "boom")


# --- severity routing (pure) -------------------------------------------------

def test_the_events_that_should_page_you_do():
    for event in ("circuit_breaker", "stop.triggered", "agent.error",
                  "approval.requested", "reconciliation.failed"):
        assert SEVERITY_BY_EVENT[event] is Severity.IMMEDIATE, event


def test_routine_noise_is_batched_or_silent():
    assert SEVERITY_BY_EVENT["order.rejected"] is Severity.DIGEST
    assert SEVERITY_BY_EVENT["agent.tick"] is Severity.SILENT


def test_an_unknown_event_defaults_to_the_digest_not_a_page():
    assert SEVERITY_BY_EVENT.get("something.new", Severity.DIGEST) is Severity.DIGEST


def test_link_tokens_are_unique_and_short_enough_to_type():
    tokens = {link_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(8 <= len(t) <= 32 for t in tokens)


# --- the client without a token ---------------------------------------------

async def test_an_unconfigured_client_is_inert_rather_than_broken():
    client = TelegramClient(token="")
    assert client.configured is False
    result = await client.send("123", "hello")
    assert result.ok is False
    assert "token" in (result.error or "")
    assert await client.get_updates() == []


def test_the_message_cap_is_the_telegram_limit():
    assert MAX_MESSAGE_CHARS == 4096


# --- delivery ---------------------------------------------------------------

@pytest.fixture
async def linked_user():
    async with SessionLocal() as session:
        user = User(
            email=f"notify-{uuid.uuid4().hex[:10]}@example.com",
            password_hash="x", is_active=True, telegram_chat_id="424242",
        )
        session.add(user)
        await session.flush()
        yield session, user
        await session.rollback()


@pytest.mark.integration
async def test_an_immediate_event_is_delivered(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    n = await notify(session, user, event="circuit_breaker",
                     title="Halted", body="Daily loss limit hit", client=client)
    assert n.status is DeliveryStatus.SENT
    assert client.sent, "nothing was sent"
    assert "Halted" in client.sent[0][1]


@pytest.mark.integration
async def test_a_silent_event_is_recorded_but_never_sent(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    n = await notify(session, user, event="agent.tick", title="Tick", body="ran",
                     client=client)
    assert n.status is DeliveryStatus.SUPPRESSED
    assert client.sent == []


@pytest.mark.integration
async def test_a_digest_event_waits_rather_than_paging(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    n = await notify(session, user, event="order.rejected", title="Rejected",
                     body="no cash", client=client)
    assert n.status is DeliveryStatus.PENDING
    assert client.sent == []


@pytest.mark.integration
async def test_duplicates_inside_the_window_are_suppressed(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    first = await notify(session, user, event="stop.triggered", title="Stop",
                         body="x", dedupe_key="VBPZ:sell", client=client)
    await session.flush()
    second = await notify(session, user, event="stop.triggered", title="Stop",
                          body="x", dedupe_key="VBPZ:sell", client=client)
    assert first.status is DeliveryStatus.SENT
    assert second.status is DeliveryStatus.SUPPRESSED
    assert len(client.sent) == 1


@pytest.mark.integration
async def test_a_different_symbol_is_not_deduplicated(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    await notify(session, user, event="stop.triggered", title="Stop A", body="x",
                 dedupe_key="AAA:sell", client=client)
    await session.flush()
    await notify(session, user, event="stop.triggered", title="Stop B", body="x",
                 dedupe_key="BBB:sell", client=client)
    assert len(client.sent) == 2


@pytest.mark.integration
async def test_an_old_duplicate_is_allowed_through_again(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    stale = datetime.now(UTC) - timedelta(hours=6)
    session.add(Notification(
        user_id=user.id, event="stop.triggered", severity=Severity.IMMEDIATE,
        channel="telegram", status=DeliveryStatus.SENT, title="old", body="old",
        dedupe_key="VBPZ:sell", created_at=stale, sent_at=stale,
    ))
    await session.flush()
    fresh = await notify(session, user, event="stop.triggered", title="Stop",
                         body="x", dedupe_key="VBPZ:sell", client=client)
    assert fresh.status is DeliveryStatus.SENT


@pytest.mark.integration
async def test_a_failed_send_is_recorded_with_its_error(linked_user):
    session, user = linked_user
    n = await notify(session, user, event="circuit_breaker", title="Halted",
                     body="x", client=FakeTelegram(ok=False))
    assert n.status is DeliveryStatus.FAILED
    assert n.error == "boom"


@pytest.mark.integration
async def test_an_unlinked_user_still_gets_a_record(linked_user):
    """Notifications are the audit trail too - "why didn't I hear about this?"
    must always have an answer."""
    session, user = linked_user
    user.telegram_chat_id = None
    n = await notify(session, user, event="circuit_breaker", title="Halted", body="x",
                     client=FakeTelegram())
    assert n.status is DeliveryStatus.PENDING
    assert n.channel == "in_app"


@pytest.mark.integration
async def test_the_digest_batches_everything_pending_into_one_message(linked_user):
    session, user = linked_user
    client = FakeTelegram()
    for i in range(4):
        await notify(session, user, event="order.rejected", title=f"Rejected {i}",
                     body="x", client=client)
    await session.flush()

    count = await flush_digest(session, user, "Market close summary", client=client)
    assert count == 4
    assert len(client.sent) == 1, "the digest sent more than one message"
    assert "Rejected 0" in client.sent[0][1]

    remaining = list(
        (
            await session.execute(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.status == DeliveryStatus.PENDING,
                )
            )
        ).scalars()
    )
    assert not remaining
