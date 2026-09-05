"""Notification history and the Telegram linking flow."""

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.models import Notification
from app.notify.service import link_token
from app.notify.telegram import TelegramClient

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    session: SessionDep,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    rows = list(
        (
            await session.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [
        {
            "at": n.created_at, "event": n.event, "severity": n.severity,
            "channel": n.channel, "status": n.status, "title": n.title,
            "body": n.body, "error": n.error,
        }
        for n in rows
    ]


@router.get("/telegram")
async def telegram_status(user: CurrentUser) -> dict:
    client = TelegramClient()
    identity = await client.me() if client.configured else None
    return {
        "bot_configured": client.configured,
        "bot_username": (identity or {}).get("username"),
        "linked": bool(user.telegram_chat_id),
    }


@router.post("/telegram/link")
async def start_link(session: SessionDep, user: CurrentUser) -> dict:
    """Issue a one-time code to send to the bot as `/start <code>`."""
    token = link_token()
    user.telegram_link_token = token
    await session.flush()

    client = TelegramClient()
    identity = await client.me() if client.configured else None
    username = (identity or {}).get("username")
    return {
        "code": token,
        "bot_username": username,
        "instructions": (
            f"Open Telegram, message @{username}, and send:  /start {token}"
            if username else
            "Set TELEGRAM_BOT_TOKEN in .env and restart, then request a code again."
        ),
        "configured": bool(settings.telegram_bot_token),
    }


@router.delete("/telegram/link")
async def unlink(session: SessionDep, user: CurrentUser) -> dict:
    user.telegram_chat_id = None
    user.telegram_link_token = None
    await session.flush()
    return {"linked": False}
