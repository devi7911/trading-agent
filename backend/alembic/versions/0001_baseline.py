"""baseline: users, accounts, instruments, watchlists, policies, audit log

Revision ID: 0001
Revises:
Create Date: 2026-09-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("telegram_chat_id", sa.String(64)),
        *_timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"])

    op.create_table(
        "accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broker", sa.String(32), nullable=False, server_default="sim"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("starting_cash", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash", sa.Numeric(18, 4), nullable=False),
        sa.Column("equity", sa.Numeric(18, 4), nullable=False),
        sa.Column("is_halted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("halt_reason", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_accounts_user_id", "accounts", ["user_id"])

    op.create_table(
        "instruments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False, server_default="SIM"),
        sa.Column("sector", sa.String(64)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("is_synthetic", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_tradable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("generator_seed", sa.Integer),
        sa.Column("initial_price", sa.Numeric(18, 4)),
        *_timestamps(),
    )
    op.create_index("ix_instruments_symbol", "instruments", ["symbol"], unique=True)
    op.create_index("ix_instruments_sector", "instruments", ["sector"])

    op.create_table(
        "watchlists",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default="My list"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index("ix_watchlists_user_id", "watchlists", ["user_id"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("watchlist_id", UUID, sa.ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_favourite", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("conviction", sa.Integer, nullable=False, server_default="2"),
        sa.Column("notes", sa.String(500)),
        *_timestamps(),
        sa.UniqueConstraint("watchlist_id", "instrument_id", name="uq_watchlist_items_instrument"),
    )
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])
    op.create_index("ix_watchlist_items_instrument_id", "watchlist_items", ["instrument_id"])

    op.create_table(
        "policies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("risk_profile", sa.String(16), nullable=False, server_default="balanced"),
        sa.Column("autonomy_level", sa.String(16), nullable=False, server_default="observe"),
        sa.Column("max_position_pct", sa.Numeric(5, 2), nullable=False, server_default="10.00"),
        sa.Column("max_sector_pct", sa.Numeric(5, 2), nullable=False, server_default="30.00"),
        sa.Column("cash_floor_pct", sa.Numeric(5, 2), nullable=False, server_default="10.00"),
        sa.Column("stop_loss_pct", sa.Numeric(5, 2), nullable=False, server_default="8.00"),
        sa.Column("take_profit_pct", sa.Numeric(5, 2), nullable=False, server_default="20.00"),
        sa.Column("max_daily_loss_pct", sa.Numeric(5, 2), nullable=False, server_default="3.00"),
        sa.Column("max_drawdown_pct", sa.Numeric(5, 2), nullable=False, server_default="15.00"),
        sa.Column("max_trades_per_day", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_trades_per_symbol_per_day", sa.Integer, nullable=False, server_default="2"),
        sa.Column("auto_approve_below", sa.Numeric(18, 4), nullable=False, server_default="500.0000"),
        sa.Column("avoid_earnings", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("allow_shorting", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamps(),
    )
    op.create_index("ix_policies_user_id", "policies", ["user_id"])
    op.create_index("ix_policies_is_active", "policies", ["is_active"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", UUID),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(48)),
        sa.Column("entity_id", UUID),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        *_timestamps(),
    )
    for col in ("actor_id", "action", "entity_type", "entity_id", "correlation_id"):
        op.create_index(f"ix_audit_log_{col}", "audit_log", [col])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("policies")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("instruments")
    op.drop_table("accounts")
    op.drop_table("users")
