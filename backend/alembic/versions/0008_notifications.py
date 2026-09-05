"""notifications: what was sent, when, and why not

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("dedupe_key", sa.String(120)),
        sa.Column("sent_at", TS),
        sa.Column("error", sa.Text),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    for col in ("user_id", "event", "severity", "status", "dedupe_key"):
        op.create_index(f"ix_notifications_{col}", "notifications", [col])

    # The token a user pastes to /start in Telegram to link their chat.
    op.add_column("users", sa.Column("telegram_link_token", sa.String(64)))
    op.create_index("ix_users_telegram_link_token", "users", ["telegram_link_token"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_link_token", table_name="users")
    op.drop_column("users", "telegram_link_token")
    op.drop_table("notifications")
