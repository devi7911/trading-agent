"""Telegram Bot API client.

Free, instant, two-way, and it works on every device without an app store. The
surface used here is four endpoints, so it is written against the HTTP API
directly.

Without a bot token the client is inert: every send is a no-op that reports why.
The agent must not care whether notifications are configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 20.0
MAX_MESSAGE_CHARS = 4096


@dataclass
class SendResult:
    ok: bool
    message_id: int | None = None
    error: str | None = None


def _escape(text: str) -> str:
    """Telegram's MarkdownV2 is unforgiving, so plain text is sent instead and
    only the characters that would break parsing are neutralised."""
    return text


class TelegramClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = (token if token is not None else settings.telegram_bot_token) or ""

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _url(self, method: str) -> str:
        return f"{API}/bot{self.token}/{method}"

    async def _post(self, method: str, payload: dict[str, Any]) -> dict | None:
        if not self.configured:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(self._url(method), json=payload)
                body = response.json()
        except Exception as exc:
            log.info("telegram_request_failed", method=method, error=type(exc).__name__)
            return {"ok": False, "description": f"{type(exc).__name__}: {exc}"}
        return body

    async def send(
        self, chat_id: str, text: str, *, buttons: list[list[dict]] | None = None
    ) -> SendResult:
        if not self.configured:
            return SendResult(ok=False, error="no bot token configured")

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": _escape(text)[:MAX_MESSAGE_CHARS],
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}

        body = await self._post("sendMessage", payload)
        if body is None:
            return SendResult(ok=False, error="client not configured")
        if not body.get("ok"):
            return SendResult(ok=False, error=str(body.get("description"))[:300])
        return SendResult(ok=True, message_id=body.get("result", {}).get("message_id"))

    async def get_updates(
        self, offset: int | None = None, poll_seconds: int = 25
    ) -> list[dict]:
        """Long-poll for incoming messages. Empty list on any failure."""
        if not self.configured:
            return []
        # `timeout` here is Telegram's long-poll window, not a cancellation
        # deadline - the HTTP client is given longer than the server will wait.
        payload: dict[str, Any] = {"timeout": poll_seconds}
        if offset is not None:
            payload["offset"] = offset
        try:
            async with httpx.AsyncClient(timeout=poll_seconds + 10) as client:
                response = await client.post(self._url("getUpdates"), json=payload)
                body = response.json()
        except Exception as exc:
            log.info("telegram_poll_failed", error=type(exc).__name__)
            return []
        return body.get("result", []) if body.get("ok") else []

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self._post("answerCallbackQuery",
                         {"callback_query_id": callback_id, "text": text[:200]})

    async def me(self) -> dict | None:
        body = await self._post("getMe", {})
        return body.get("result") if body and body.get("ok") else None


__all__ = ["MAX_MESSAGE_CHARS", "SendResult", "TelegramClient"]
